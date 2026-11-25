import copy
import json
import sqlite3
import hashlib
import gzip
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from test_management import client, write, AUTH, VIEWER, PREFIX, Q, S, wav_bytes
from integration_cli import Service
from sync_worker import coverage_once, pull_student, journal
from maintenance import backup, restore
from store import Store


def event(kind, entity_id, data=None, version=1, operation='upsert'):
    return {'event_id': f'{kind}-{entity_id}-{version}-{operation}', 'kind': kind,
            'entity_id': entity_id, 'source_version': version, 'operation': operation, 'data': data}


def batch(events, cursor=None, next_cursor='cursor-1', batch_id='batch-1', source='student-test'):
    return {'schema_version': 1, 'source_id': source, 'batch_id': batch_id,
            'cursor': cursor, 'next_cursor': next_cursor, 'events': events}


def receive(client, data, auth=AUTH):
    return write(client, '/integration/batches', data, auth=auth)


def initial(client):
    audio = client.post(PREFIX+'/audio', headers=AUTH, content=wav_bytes()).json()['sha256']
    recording = {'recording_id':'R-SYNC', 'speaker_id':S['speaker_id'], 'question_id':Q['question_id'],
        'practice_session_id':'sync-session', 'take_no':1, 'recorded_at':'2026-11-25T12:00:00+08:00',
        'question_snapshot':Q, 'wav_sha256':audio, 'original_sha256':audio, 'data_source':'synthetic_fixture'}
    payload = batch([event('speakers', S['speaker_id'], S), event('questions', Q['question_id'], Q),
                     event('recordings', 'R-SYNC', recording)])
    return recording, payload


def test_batch_replay_conflict_and_reader_permission(client):
    _, payload = initial(client)
    assert receive(client, payload, VIEWER).status_code == 403
    assert client.get(PREFIX+'/integration/sources/student-test', headers=VIEWER).status_code == 403
    assert receive(client, payload).status_code == 200
    again = receive(client, payload)
    assert again.json()['batch_replayed'] is True
    payload['next_cursor'] = 'different'
    assert receive(client, payload).status_code == 409
    assert client.get(PREFIX+'/statistics', headers=AUTH).json()['recording_count'] == 1


def test_atomic_failure_does_not_advance_cursor_or_leave_parents(client):
    _, payload = initial(client)
    payload['events'][-1]['data']['wav_sha256'] = 'f'*64
    assert receive(client, payload).status_code == 409
    assert client.get(PREFIX+'/speakers', headers=AUTH).json()['total'] == 0
    assert client.get(PREFIX+'/integration/sources/student-test', headers=AUTH).json()['cursor'] is None
    _, valid = initial(client)
    assert receive(client, valid).status_code == 200


def test_diagnosis_updates_keep_review_note_and_frozen_question(client):
    recording, payload = initial(client)
    assert receive(client, payload).status_code == 200
    assert write(client, '/recordings/R-SYNC', {'expected_version':1, 'note':'人工核查保留'}, 'PUT').status_code == 200
    recording['diagnosis'] = {'status':'completed', 'errors':[{'type':'tone','char_index':0,'actual':'wo2'}]}
    updated = batch([event('recordings','R-SYNC',recording,2)], 'cursor-1','cursor-2','batch-2')
    assert receive(client, updated).status_code == 200
    row = client.get(PREFIX+'/recordings/R-SYNC', headers=AUTH).json()
    assert row['note'] == '人工核查保留' and row['diagnosis']['status'] == 'completed'
    recording['question_snapshot'] = {**Q, 'display_text':'你，我。', 'tokens':[{'c':'你','py':'ni3'},{'c':'我','py':'wo3'}]}
    invalid = batch([event('recordings','R-SYNC',recording,3)], 'cursor-2','cursor-3','batch-3')
    assert receive(client, invalid).status_code == 409
    assert client.get(PREFIX+'/recordings/R-SYNC', headers=AUTH).json()['question_snapshot']['display_text'] == Q['display_text']


def test_manual_diagnosis_is_not_overwritten(client):
    recording, payload = initial(client)
    receive(client,payload)
    assert write(client,'/recordings/R-SYNC/diagnosis',{'expected_version':1,'diagnosis':{'status':'failed'}},'PUT').status_code==200
    recording['diagnosis'] = {'status':'completed','errors':[]}
    assert receive(client,batch([event('recordings','R-SYNC',recording,2)],'cursor-1','c2','b2')).status_code==409


def test_old_revision_same_revision_conflict_and_source_ownership(client):
    recording, payload = initial(client)
    receive(client,payload)
    recording['diagnosis']={'status':'processing'}
    assert receive(client,batch([event('recordings','R-SYNC',recording,3)],'cursor-1','c3','b3')).status_code==200
    for revision in (1,2,3):
        wrong=copy.deepcopy(recording);wrong['diagnosis']={'status':'completed','errors':[]}
        e=event('recordings','R-SYNC',wrong,revision);e['event_id']+='-new'
        assert receive(client,batch([e],'c3','c4','b4')).status_code==409
    assert receive(client,batch([event('recordings','R-SYNC',recording,4)],source='other')).status_code==409
    assert receive(client,batch([event('recordings','R-SYNC',recording,4)],'old-cursor','c4','b4')).status_code==409


def test_delete_restore_counts_and_replay_do_not_resurrect(client):
    _, payload=initial(client);receive(client,payload)
    deleted=batch([event('recordings','R-SYNC',version=2,operation='delete')],'cursor-1','c2','b2')
    assert receive(client,deleted).status_code==200
    assert client.get(PREFIX+'/statistics',headers=AUTH).json()['recording_count']==0
    assert receive(client,payload).status_code==200
    assert client.get(PREFIX+'/statistics',headers=AUTH).json()['recording_count']==0
    restored=batch([event('recordings','R-SYNC',version=3,operation='restore')],'c2','c3','b3')
    assert receive(client,restored).status_code==200
    assert client.get(PREFIX+'/coverage',headers=AUTH).json()['items'][0]['recording_count']==1


def test_local_changes_and_existing_unowned_entities_conflict(client):
    assert write(client,'/speakers',S).status_code==200
    assert receive(client,batch([event('speakers',S['speaker_id'],S)])).status_code==409
    q=batch([event('questions',Q['question_id'],Q)])
    assert receive(client,q).status_code==200
    assert write(client,'/questions/'+Q['question_id'],{'expected_version':1,'question':{**Q,'target_recordings':9}},'PUT').status_code==200
    assert receive(client,batch([event('questions',Q['question_id'],{**Q,'target_recordings':3},2)],'cursor-1','c2','b2')).status_code==409


def test_sync_cursor_and_dedup_survive_backup_restore(client,tmp_path):
    _,payload=initial(client);receive(client,payload)
    saved=tmp_path.parent/(tmp_path.name+'-saved');restored=tmp_path.parent/(tmp_path.name+'-restored')
    backup(client.app.state.store.root,saved);restore(saved,restored)
    with Store(restored).db() as db:
        assert db.execute('SELECT cursor FROM sync_sources').fetchone()[0]=='cursor-1'
        assert db.execute('SELECT count(*) FROM sync_events').fetchone()[0]==3


def test_transport_retry_preserves_idempotency_key_and_no_credential_redirect():
    seen=[]
    def handle(request):
        seen.append(request.headers['idempotency-key'])
        if len(seen)==1:raise httpx.ReadTimeout('lost acknowledgement')
        return httpx.Response(200,json={'ok':True})
    service=Service('http://testserver',transport=httpx.MockTransport(handle),sleep=lambda _:None)
    assert service.request('POST','/accepted',json={}).json()['ok']
    assert len(seen)==2 and len(set(seen))==1
    for path in ['https://other.example/token','//other.example/path','/\\other/path']:
        with pytest.raises(ValueError):service.request('GET',path)
    service.close()


def test_response_size_limit_and_permanent_failure_do_not_retry():
    calls=[]
    def handle(request):calls.append(1);return httpx.Response(401,text='secret')
    service=Service('http://testserver',transport=httpx.MockTransport(handle),sleep=lambda _:None)
    with pytest.raises(RuntimeError,match='401'):service.request('GET','/feed')
    assert len(calls)==1
    service.close()
    service=Service('http://testserver',transport=httpx.MockTransport(lambda r:httpx.Response(200,content=b'x'*100)))
    with pytest.raises(RuntimeError,match='大小'):service.request('GET','/audio',max_bytes=10)
    service.close()


def test_worker_audio_hash_and_cursor_ack(client):
    recording,payload=initial(client)
    pages=[]
    def upstream(request):
        if request.url.path=='/audio':return httpx.Response(200,content=wav_bytes())
        pages.append(request.url.params.get('cursor'))
        return httpx.Response(200,json={'source_id':'student-test','batch':payload,'has_more':False,
            'audio':[{'sha256':recording[k+'_sha256'],'variant':k,'path':'/audio'} for k in ('wav','original')]})
    student=Service('http://testserver',transport=httpx.MockTransport(upstream))
    class Admin:
        def request(self,method,path,**kwargs):
            kwargs['headers']={**AUTH,**kwargs.get('headers',{})}
            if method!='GET':kwargs['headers'].setdefault('Idempotency-Key','test-worker-key-'+path[-8:])
            response=client.request(method,path,**kwargs)
            response.raise_for_status();return response
    assert pull_student(Admin(),student,'student-test','/confirmed-feed')['events']==3
    assert pages==[None]
    student.close()


def test_coverage_durable_retry_uses_frozen_payload_and_checks_receipt(tmp_path):
    snapshot={'snapshot_version':'instance:0001','generated_at':'2026-11-25T00:00:00Z','items':[]}
    class Admin:
        calls=0
        def request(self,*a,**kw):self.calls+=1;return httpx.Response(200,json={'snapshot':snapshot})
    admin=Admin(); sent=[]
    def handle(request):
        data=json.loads(request.content);sent.append(data)
        return httpx.Response(200,json={'ok':True,'applied':True,'snapshot':({**data,'items':[{}]} if len(sent)==1 else data)})
    prop=Service('http://testserver',transport=httpx.MockTransport(handle))
    path=tmp_path/'coverage.db'
    with pytest.raises(RuntimeError):coverage_once(admin,prop,path)
    original=copy.deepcopy(snapshot);snapshot['snapshot_version']='instance:0002'
    assert coverage_once(admin,prop,path)['status']=='received'
    assert sent==[original,original] and admin.calls==1
    assert coverage_once(admin,prop,path)['snapshot_version']=='instance:0002'
    assert coverage_once(admin,prop,path)['status']=='unchanged'
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM delivery WHERE state='received'").fetchone()[0]==2
    prop.close()


def test_journal_refuses_concurrent_workers(tmp_path):
    with journal(tmp_path/'coverage.db'):
        with pytest.raises(sqlite3.OperationalError):
            with journal(tmp_path/'coverage.db'):pass


def test_concurrent_batch_receipts_apply_only_once(client):
    _,payload=initial(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:receive(client,payload),range(2)))
    assert [r.status_code for r in results]==[200,200]
    assert sum(r.json()['batch_replayed'] for r in results)==1
    assert client.get(PREFIX+'/statistics',headers=AUTH).json()['recording_count']==1


def test_bad_audio_hash_never_advances_import(client):
    recording,payload=initial(client)
    def upstream(request):
        if request.url.path=='/audio':return httpx.Response(200,content=b'wrong bytes')
        return httpx.Response(200,json={'source_id':'student-test','batch':payload,'has_more':False,
            'audio':[{'sha256':recording[k+'_sha256'],'variant':k,'path':'/audio'} for k in ('wav','original')]})
    class Admin:
        def request(self,method,path,**kwargs):
            assert method=='GET', '音频校验失败前不得写管理端'
            return httpx.Response(200,json={'cursor':None})
    student=Service('http://testserver',transport=httpx.MockTransport(upstream))
    with pytest.raises(ValueError,match='SHA256'):pull_student(Admin(),student,'student-test','/feed')
    student.close()


def test_compressed_response_is_decoded_once():
    service=Service('http://testserver',transport=httpx.MockTransport(lambda r:httpx.Response(
        200,content=gzip.compress(b'{"ok":true}'),headers={'Content-Encoding':'gzip'})))
    assert service.request('GET','/feed').json()=={'ok':True}
    service.close()


def test_real_recording_requires_authorization_and_question_version(client):
    _,payload=initial(client)
    data=payload['events'][-1]['data'];data['data_source']='authorized_test'
    assert receive(client,payload).status_code==422
    data['consent_reference']='authorized-sample-001'
    assert receive(client,payload).status_code==422
    data['question_snapshot']={**Q,'question_version':'fixed-version-1'}
    assert receive(client,payload).status_code==200
