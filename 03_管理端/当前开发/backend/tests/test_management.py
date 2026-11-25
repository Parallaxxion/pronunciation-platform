import copy
import hashlib
import io
import json
import sys
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, load_accounts

TOKEN = 'fixture-admin-token-' + 'x' * 32
READER = 'fixture-reader-token-' + 'y' * 32
AUTH = {'Authorization': 'Bearer '+TOKEN}
VIEWER = {'Authorization': 'Bearer '+READER}
PREFIX = '/api/v1/admin'
Q = {'question_id': 'L1-001', 'display_text': '我，你。', 'level': 1,
     'tokens': [{'c':'我','py':'wo3'}, {'c':'你','py':'ni3'}], 'status':'published'}
S = {'speaker_id':'S-001','nationality':'样例','language':'样例语','level':1, 'source':'synthetic_fixture'}


def wav_bytes(rate=16000, channels=1):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as stream:
        stream.setnchannels(channels)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(b'\0\0' * rate * channels)
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path):
    accounts = [{'actor':'闫晓奕-自动化测试','role':'admin','token_sha256':hashlib.sha256(TOKEN.encode()).hexdigest()},
                {'actor':'只读测试','role':'viewer','token_sha256':hashlib.sha256(READER.encode()).hexdigest()}]
    with TestClient(create_app(tmp_path, accounts)) as client:
        yield client


def write(client, path, body=None, method='POST', key=None, auth=AUTH):
    return client.request(method, PREFIX+path, json=body,
                          headers={**auth,'Idempotency-Key':key or str(uuid.uuid4())})


def seed(client):
    assert write(client,'/speakers',S).status_code == 200
    assert write(client,'/questions',Q).status_code == 200
    audio = client.post(PREFIX+'/audio',headers=AUTH,content=wav_bytes()).json()['sha256']
    recording = {'recording_id':'R-001','speaker_id':'S-001','question_id':'L1-001',
                 'practice_session_id':'session-1','take_no':1,'recorded_at':'2026-11-23T12:00:00+08:00',
                 'question_snapshot':Q, 'wav_sha256':audio,'original_sha256':audio,'data_source':'synthetic_fixture'}
    result=write(client,'/recordings',recording)
    assert result.status_code == 200, result.text
    return recording, result.json()


@pytest.mark.parametrize('path',['/speakers','/questions','/recordings','/actions','/coverage','/recordings/R-001/audio'])
def test_read_requires_identity(client,path):
    assert client.get(PREFIX+path).status_code == 401


def test_viewer_can_read_but_cannot_write(client):
    seed(client)
    assert client.get(PREFIX+'/recordings',headers=VIEWER).status_code == 200
    assert write(client,'/recordings/R-001',{'expected_version':1,'note':'x'},'PUT',auth=VIEWER).status_code == 403
    assert client.post(PREFIX+'/audio',headers=VIEWER,content=wav_bytes()).status_code == 403
    assert write(client,'/coverage/snapshots',{},auth=VIEWER).status_code == 403


def test_fail_closed_startup(monkeypatch):
    monkeypatch.delenv('ADMIN_TOKEN',raising=False)
    monkeypatch.delenv('ADMIN_AUTH_FILE',raising=False)
    with pytest.raises(RuntimeError): load_accounts()


def test_session_origin_and_logout(client):
    r=client.post('/api/session',headers=AUTH)
    assert r.status_code==200 and 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=strict' in r.headers['set-cookie']
    assert client.get(PREFIX+'/speakers').status_code==200
    assert write(client,'/speakers',S,auth={}).status_code==403
    assert write(client,'/speakers',S,auth={'Origin':'https://evil.example'}).status_code==403
    assert write(client,'/speakers',S,auth={'Origin':'http://testserver'}).status_code==200
    assert client.delete('/api/session',headers={'Origin':'http://testserver'}).status_code==200
    assert client.get(PREFIX+'/speakers').status_code==401


def test_no_static_audio_or_data_bypass(client):
    seed(client)
    for path in ['/audio/R-001.wav','/local-data/management.sqlite3','/api/state','/api/export']:
        assert client.get(path).status_code==404


def test_history_snapshot_and_undo(client):
    seed(client)
    changed={**Q,'display_text':'你，我。','tokens':[{'c':'你','py':'ni3'},{'c':'我','py':'wo3'}]}
    r=write(client,'/questions/L1-001',{'expected_version':1,'question':changed},'PUT')
    assert r.status_code==200
    recording=client.get(PREFIX+'/recordings/R-001',headers=AUTH).json()
    assert recording['question_snapshot']['display_text']=='我，你。'
    history=client.get(PREFIX+'/questions/L1-001/history',headers=AUTH).json()['items']
    assert [h['display_text'] for h in history]==['我，你。','你，我。']
    assert write(client,f'/actions/{r.json()["action_id"]}/undo').json()['item']['display_text']=='我，你。'
    assert client.get(PREFIX+'/questions/L1-001',headers=AUTH).json()['version']==3


@pytest.mark.parametrize('kind,id,changes', [('speakers','S-001',{'nationality':'更新','language':'语言','level':2}),
                                          ('recordings','R-001',{'note':'已核查'})])
def test_updates_and_conflicts(client,kind,id,changes):
    seed(client)
    result=write(client,f'/{kind}/{id}',{'expected_version':1,**changes},'PUT')
    assert result.status_code==200
    assert write(client,f'/{kind}/{id}',{'expected_version':1,**changes},'PUT').status_code==409
    action=client.get(PREFIX+'/actions',headers=AUTH).json()['items'][0]
    assert action['actor']=='闫晓奕-自动化测试' and action['before']['version']==1 and action['after']['version']==2
    assert write(client,f'/actions/{result.json()["action_id"]}/undo').status_code==200
    assert write(client,f'/actions/{result.json()["action_id"]}/undo').status_code==409


@pytest.mark.parametrize('kind,id',[('speakers','S-001'),('questions','L1-001'),('recordings','R-001')])
def test_soft_delete_restore(client,kind,id):
    seed(client)
    assert write(client,f'/{kind}/{id}',{'expected_version':1},'DELETE').status_code==200
    assert client.get(PREFIX+f'/{kind}',headers=AUTH).json()['total']==0
    assert client.get(PREFIX+f'/{kind}?deleted=true',headers=AUTH).json()['items'][0]['version']==2
    assert write(client,f'/{kind}/{id}/restore',{'expected_version':2}).status_code==200
    assert client.get(PREFIX+f'/{kind}/{id}',headers=AUTH).json()['version']==3
    assert client.get(PREFIX+'/recordings/R-001',headers=AUTH).json()['question_snapshot']['display_text']=='我，你。'


def test_undo_create_with_references_rejected(client):
    seed(client)
    actions=client.get(PREFIX+'/actions',headers=AUTH).json()['items']
    q_action=next(a for a in actions if a['kind']=='questions')
    assert write(client,f'/actions/{q_action["id"]}/undo').status_code==409


def test_restore_requires_active_parents(client):
    seed(client)
    write(client,'/recordings/R-001',{'expected_version':1},'DELETE')
    write(client,'/speakers/S-001',{'expected_version':1},'DELETE')
    assert write(client,'/recordings/R-001/restore',{'expected_version':2}).status_code==409


def test_undo_rejects_later_change(client):
    seed(client)
    a=write(client,'/recordings/R-001',{'expected_version':1,'note':'first'},'PUT').json()
    write(client,'/recordings/R-001',{'expected_version':2,'note':'second'},'PUT')
    assert write(client,f'/actions/{a["action_id"]}/undo').status_code==409


def test_idempotency_and_duplicate_id(client):
    r,_=seed(client)
    first=write(client,'/recordings/R-001',{'expected_version':1,'note':'checked'},'PUT',key='fixed-key')
    again=write(client,'/recordings/R-001',{'expected_version':1,'note':'checked'},'PUT',key='fixed-key')
    assert again.json()['replayed'] and again.json()['action_id']==first.json()['action_id']
    assert write(client,'/recordings/R-001',{'expected_version':2,'note':'different'},'PUT',key='fixed-key').status_code==409
    duplicate=write(client,'/recordings',r)
    assert duplicate.json()['duplicate'] and duplicate.json()['item']['note']=='checked'
    assert write(client,'/recordings',{**r,'recorded_at':'2026-11-23T12:01:00+08:00'}).status_code==409
    assert client.get(PREFIX+'/recordings',headers=AUTH).json()['total']==1


def test_concurrent_writers_only_one_wins(client):
    seed(client)
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(lambda note:write(client,'/recordings/R-001',{'expected_version':1,'note':note},'PUT').status_code,['a','b']))
    assert sorted(results)==[200,409]


def test_atomic_import_and_session_uniqueness(client):
    r,_=seed(client)
    bad={**r,'recording_id':'R-002'}
    result=write(client,'/import',{'speakers':[{**S,'speaker_id':'S-002'}],'recordings':[bad]})
    assert result.status_code==409
    assert client.get(PREFIX+'/speakers/S-002',headers=AUTH).status_code==404
    assert write(client,'/recordings',{**bad,'practice_session_id':'session-2'}).status_code==200
    assert client.get(PREFIX+'/coverage',headers=AUTH).json()['items'][0]['recording_count']==2


def test_unknown_parent_and_mismatched_snapshot(client):
    r,_=seed(client)
    assert write(client,'/recordings',{**r,'recording_id':'R-002','speaker_id':'missing'}).status_code==404
    assert write(client,'/recordings',{**r,'recording_id':'R-002','question_id':'wrong'}).status_code==422


def test_audio_auth_integrity_and_validation(client):
    r,_=seed(client)
    audio=client.get(PREFIX+'/recordings/R-001/audio',headers=AUTH)
    assert audio.status_code==200 and hashlib.sha256(audio.content).hexdigest()==r['wav_sha256']
    for invalid in [b'not wav',wav_bytes(8000),wav_bytes(channels=2),wav_bytes()[:-100]]:
        assert client.post(PREFIX+'/audio',headers=AUTH,content=invalid).status_code==422
    assert client.get(PREFIX+'/recordings/R-001/audio?variant=other',headers=AUTH).status_code==422


def test_missing_audio_blocks_create_and_playback(client):
    r,_=seed(client)
    client.app.state.store.audio.joinpath(r['wav_sha256']).unlink()
    assert client.get(PREFIX+'/recordings/R-001/audio',headers=AUTH).status_code==409
    assert write(client,'/recordings',{**r,'recording_id':'R-002','take_no':2}).status_code==409


def test_coverage_replays_delete_undo_and_unknown_target(client):
    seed(client)
    c=client.get(PREFIX+'/coverage',headers=AUTH).json()['items'][0]
    assert c['recording_count']==1 and c['unique_speaker_count']==1 and c['gap'] is None
    a=write(client,'/coverage/snapshots',{}).json()['snapshot']
    assert write(client,'/coverage/snapshots',{}).json()['snapshot']==a
    deletion=write(client,'/recordings/R-001',{'expected_version':1},'DELETE').json()
    b=write(client,'/coverage/snapshots',{}).json()['snapshot']
    assert b['snapshot_version']!=a['snapshot_version'] and b['items'][0]['recording_count']==0
    write(client,f'/actions/{deletion["action_id"]}/undo')
    assert write(client,'/coverage/snapshots',{}).json()['snapshot']['items'][0]['recording_count']==1


@pytest.mark.parametrize('status',['pending','processing','failed','completed'])
def test_diagnosis_states_and_redaction(client,status):
    seed(client)
    d={'status':status,'errors':[],'error_message':'secret /private/path'}
    result=write(client,'/recordings/R-001/diagnosis',{'expected_version':1,'diagnosis':d},'PUT')
    assert result.status_code==200
    data=client.get(PREFIX+'/recordings/R-001/diagnosis',headers=AUTH).json()
    assert data['status']==status and 'secret' not in json.dumps(data)


def test_four_errors_and_boundary_validation(client):
    seed(client)
    errors=[{'type':'tone','char_index':0,'actual':'wo2'}, {'type':'substitution','char_index':1,'actual':'li3'},
            {'type':'omission','char_index':1}, {'type':'insertion','boundary_index':2,'actual':'a5'}]
    d={'status':'completed','errors':errors}
    assert write(client,'/recordings/R-001/diagnosis',{'expected_version':1,'diagnosis':d},'PUT').status_code==200
    d['errors'][3]['boundary_index']=3
    assert write(client,'/recordings/R-001/diagnosis',{'expected_version':2,'diagnosis':d},'PUT').status_code==422
    assert write(client,'/recordings/R-001/diagnosis',{'expected_version':2,'diagnosis':{'status':'completed'}},'PUT').status_code==422


def test_pagination_and_filters(client):
    r,_=seed(client)
    write(client,'/recordings',{**r,'recording_id':'R-002','take_no':2})
    page=client.get(PREFIX+'/recordings?offset=1&limit=1&level=1&status=pending',headers=AUTH).json()
    assert page['total']==2 and len(page['items'])==1 and page['items'][0]['recording_id']=='R-002'
    assert client.get(PREFIX+'/recordings?limit=101',headers=AUTH).status_code==422


def test_strict_input_and_consent(client):
    r,_=seed(client)
    assert write(client,'/speakers',{**S,'email':'must-not-be-stored@example.com'}).status_code==422
    assert write(client,'/recordings',{**r,'recording_id':'R-002','take_no':2,'data_source':'authorized_test'}).status_code==422
    assert write(client,'/recordings/R-001',{'expected_version':True,'note':'x'},'PUT').status_code==422
    assert write(client,'/recordings',{**r,'recorded_at':'2026-11-23T12:00:00'}).status_code==422


def test_body_identity_does_not_impersonate_actor(client):
    assert write(client,'/speakers',{**S,'actor':'other-person'}).status_code==422
    assert client.post(PREFIX+'/speakers',headers=AUTH,json=S).status_code==400


def test_failed_batch_does_not_reserve_idempotency_key(client):
    result=write(client,'/import',{'speakers':[S,S|{'level':2}]},key='retry-after-failure')
    assert result.status_code==409
    assert client.get(PREFIX+'/speakers',headers=AUTH).json()['total']==0
    assert write(client,'/import',{'speakers':[S]},key='retry-after-failure').status_code==200


@pytest.mark.parametrize('diagnosis',[{'status':[]}, {'status':'completed','errors':[None]},
    {'status':'completed','tokens':[None,None]},
    {'status':'completed','tokens':[{'c':'我','err':'bad'},{'c':'你'}]},
    {'status':'completed','tokens':[{'c':'我'},{'c':'你'}],'gap_errors':{'0':None}}])
def test_malformed_nested_diagnosis_is_422(client,diagnosis):
    seed(client)
    assert write(client,'/recordings/R-001/diagnosis',{'expected_version':1,'diagnosis':diagnosis},'PUT').status_code==422


def test_missing_diagnosis_is_distinct_from_pending(client):
    seed(client)
    assert client.get(PREFIX+'/recordings/R-001/diagnosis',headers=AUTH).json()['available'] is False
    result=write(client,'/recordings/R-001/diagnosis',{'expected_version':1,'diagnosis':{'status':'pending'}},'PUT')
    assert result.status_code==200
    assert client.get(PREFIX+'/recordings/R-001/diagnosis',headers=AUTH).json()['available'] is True
