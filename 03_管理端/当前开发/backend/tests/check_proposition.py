"""Optional real HTTP compatibility probe against a pinned proposition checkout.

All data and processes are temporary. Uses public question data and synthetic silence;
does not access a live deployment, student database, or genuine speech recordings.
"""
import argparse
import hashlib
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integration_cli import Service, sync_questions, question_input, coverage_handoff
from integration.adapters import normalize_question
from verify_export import verify


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_ready(service, path, process):
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError('测试服务提前退出')
        try:
            service.request('GET', path)
            return
        except Exception:
            time.sleep(.1)
    raise RuntimeError('测试服务启动超时')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    backend = Path(__file__).resolve().parents[1]
    results = {'checked_at': datetime.now(timezone.utc).isoformat(), 'source_revision': args.revision,
               'scope':'两个本机真实 HTTP 服务，独立数据库；题目来自上游源码，音频为合成静音，未测试真实学生采集或算法准确率',
               'levels':[], 'checks':{}}
    processes=[]
    with tempfile.TemporaryDirectory(prefix='admin-interop-') as temporary:
        temporary=Path(temporary)
        env={**os.environ,'BANK_DB':str(temporary/'bank.db')}
        try:
            for level,bank in [(1,'banks/level1/final.json'),(2,'banks/level2/final.json'),(3,'banks/final 3.json'),
                               (4,'banks/final4.json'),(5,'banks/final5.json'),(6,'banks/final6.json')]:
                process=subprocess.run([sys.executable,'backend/import_bank.py','--level',str(level),'--bank',bank],
                                       cwd=source,env=env,capture_output=True,text=True)
                if process.returncode:
                    raise RuntimeError(f'第 {level} 级导入失败：'+process.stderr[-1000:])
            prop_port,admin_port=free_port(),free_port()
            token=secrets.token_urlsafe(40)
            processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port',str(prop_port)],
                                               cwd=source,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            admin_env={**os.environ,'ADMIN_TOKEN':token,'ADMIN_ACTOR':'integration-fixture','ADMIN_DATA_DIR':str(temporary/'admin')}
            admin_env.pop('ADMIN_AUTH_FILE',None)
            processes.append(subprocess.Popen([sys.executable,'-m','uvicorn','app:create_app','--factory','--host','127.0.0.1','--port',str(admin_port)],
                                               cwd=backend,env=admin_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            proposition=Service(f'http://127.0.0.1:{prop_port}')
            admin=Service(f'http://127.0.0.1:{admin_port}',token)
            wait_ready(proposition,'/',processes[0]);wait_ready(admin,'/api/health',processes[1])
            for level in range(1,10):
                listing=proposition.request('GET',f'/api/questions?level={level}').json()
                item={'level':level,'questions':listing['total']}
                if listing['total']:
                    validation=proposition.request('POST',f'/api/pipeline/validate?level={level}').json()
                    stats=proposition.request('POST',f'/api/pipeline/stats?level={level}').json()
                    publish=proposition.client.post('/api/pipeline/publish',json={'level':level})
                    item.update(validation=validation['verdict'],statistics=stats['verdict'],
                                char_coverage={k:stats['char'][k] for k in ('total','covered','coverage')},
                                grammar_coverage={k:stats['grammar'][k] for k in ('total','covered','coverage')},
                                publish_http=publish.status_code,
                                publish_result=publish.json())
                    if publish.is_success:
                        first=sync_questions(admin,proposition,level)
                        retry=sync_questions(admin,proposition,level)
                        item['management_import']=first;item['repeat_import']=retry
                results['levels'].append(item)
            published=next((r for r in results['levels'] if r.get('publish_http')==200),None)
            if published is None:
                raise RuntimeError('上游无可发布等级，无法继续真实题目接口测试')
            raw_question=proposition.request('GET',f'/api/questions?level={published["level"]}&status=published').json()['items'][0]
            question=question_input(normalize_question(raw_question))
            qid=question['question_id']
            results['checks']['upstream_revision_preserved_separately']=(
                question['source_content_revision']==raw_question['content_revision'])
            admin.request('POST','/api/v1/admin/speakers',json={'speaker_id':'S-interop','nationality':'合成样例','language':'测试','level':1,'source':'synthetic_fixture'})
            buffer=io.BytesIO()
            with wave.open(buffer,'wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000)
            audio=admin.request('POST','/api/v1/admin/audio',content=buffer.getvalue()).json()['sha256']
            recording={'recording_id':'R-interop','speaker_id':'S-interop','question_id':qid,'practice_session_id':'P-interop',
                       'take_no':1,'recorded_at':datetime.now(timezone.utc).isoformat(),'question_snapshot':question,
                       'wav_sha256':audio,'original_sha256':audio,'data_source':'synthetic_fixture',
                       'diagnosis':{'status':'completed','model_version':'fixture-not-algorithm','errors':[]}}
            created=admin.request('POST','/api/v1/admin/recordings',json=recording).json()
            duplicate=admin.request('POST','/api/v1/admin/recordings',json=recording).json()
            results['checks']['recording_duplicate_not_added']=duplicate['duplicate']
            playback=admin.request('GET','/api/v1/admin/recordings/R-interop/audio').content
            results['checks']['authorized_audio_matches_hash']=hashlib.sha256(playback).hexdigest()==audio
            handoff=coverage_handoff(admin,proposition,temporary/'snapshot.json')
            replay=coverage_handoff(admin,proposition,temporary/'snapshot.json')
            results['checks']['coverage_first_receipt_applied']=handoff['receipt_applied']
            results['checks']['coverage_repeat_receipt_not_applied']=not replay['receipt_applied']
            after=proposition.request('GET',f'/api/questions/{qid}').json()
            results['checks']['upstream_rec_count_after_snapshot']=after['rec_count']
            snapshot=json.loads((temporary/'snapshot.json').read_text())
            changed=json.loads(json.dumps(snapshot));changed['items'][0]['recording_count']+=1
            conflict=proposition.client.put('/api/v1/integration/coverage',json=changed)
            stale={**snapshot,'snapshot_version':'stale-independent-fixture','generated_at':'2020-01-01T00:00:00Z'}
            stale_result=proposition.client.put('/api/v1/integration/coverage',json=stale)
            results['checks']['upstream_same_version_different_body_http']=conflict.status_code
            results['checks']['upstream_stale_snapshot_http']=stale_result.status_code
            deletion=admin.request('DELETE','/api/v1/admin/recordings/R-interop',json={'expected_version':1}).json()
            coverage=admin.request('GET','/api/v1/admin/coverage').json()
            results['checks']['deleted_count']=next(r['recording_count'] for r in coverage['items'] if r['question_id']==qid)
            admin.request('POST',f'/api/v1/admin/actions/{deletion["action_id"]}/undo',json={})
            final=admin.request('GET','/api/v1/admin/recordings/R-interop').json()
            results['checks']['undo_restores_snapshot']=final['question_snapshot']==created['item']['question_snapshot'] and not final['deleted']
            output=Path(args.out)
            output.parent.mkdir(parents=True,exist_ok=True)
            export_path=output.parent/'管理端合成样例导出.zip'
            export_path.write_bytes(admin.request('GET','/api/v1/admin/export').content)
            results['checks']['management_export_verification']=verify(export_path)
            results['checks']['management_statistics']=admin.request('GET','/api/v1/admin/statistics').json()
        finally:
            for process in processes:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait(timeout=5)
            output=Path(args.out)
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
