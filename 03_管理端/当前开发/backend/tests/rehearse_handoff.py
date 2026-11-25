"""Real HTTP/TLS rehearsal against an explicitly synthetic student/coverage contract server."""
import argparse
import hashlib
import io
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import wave
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from integration_cli import Service
from sync_worker import pull_student, coverage_once
from maintenance import backup, restore


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def run(output, caddy=None):
    report = {'at': datetime.now(timezone.utc).isoformat(), 'scope':'synthetic_contract_http_rehearsal',
              'checks': [], 'not_proven':['真实学生接口','真实算法准确率','命题实际 rec_count 应用',
                                       '公网证书与部署','Windows实机','手机麦克风']}
    def passed(name):
        report['checks'].append({'check':name,'result':'pass'})
        print('PASS '+name, flush=True)
    with tempfile.TemporaryDirectory(prefix='shengcai-handoff-') as temp:
        root=Path(temp); token=secrets.token_urlsafe(40); upstream_token=secrets.token_urlsafe(40)
        port=free_port(); tls_port=free_port(); origin=f'https://127.0.0.1:{tls_port}'
        audio=io.BytesIO()
        with wave.open(audio,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*16000)
        audio=audio.getvalue(); sha=hashlib.sha256(audio).hexdigest()
        question={'question_id':'QA-Q','level':1,'display_text':'你好。','tokens':[{'c':'你','py':'ni3'},{'c':'好','py':'hao3'}],
                  'question_version':'fixture-v1','status':'published','target_recordings':2,'source':'synthetic_fixture'}
        speaker={'speaker_id':'QA-S','nationality':'合成测试','language':'合成测试','level':1,'source':'synthetic_fixture'}
        recording={'recording_id':'QA-R','question_id':'QA-Q','speaker_id':'QA-S','practice_session_id':'QA-P',
                   'take_no':1,'recorded_at':'2026-11-25T12:00:00+08:00','question_snapshot':question,
                   'wav_sha256':sha,'original_sha256':sha,'data_source':'synthetic_fixture'}
        def event(kind,identity,data=None,version=1,op='upsert'):
            return {'event_id':f'{kind}-{version}-{identity}-{op}','kind':kind,'entity_id':identity,
                    'source_version':version,'operation':op,'data':data}
        changes=[[event('speakers','QA-S',speaker),event('questions','QA-Q',question),event('recordings','QA-R',recording)],
                 [event('recordings','QA-R',{**recording,'diagnosis':{'status':'completed','errors':[{'type':'tone','char_index':0,'actual':'ni2'}]}},2)],
                 [event('recordings','QA-R',version=3,op='delete')],
                 [event('recordings','QA-R',version=4,op='restore')]]
        state={'available':1,'coverage':{},'drop':True,'coverage_requests':[]}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,code,body,media='application/json'):
                content=body if isinstance(body,bytes) else json.dumps(body,ensure_ascii=False).encode()
                self.send_response(code);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(content)))
                self.end_headers();self.wfile.write(content)
            def authorized(self):
                if self.headers.get('Authorization')!='Bearer '+upstream_token:
                    self.respond(401,{});return False
                return True
            def do_GET(self):
                if not self.authorized():return
                url=urlsplit(self.path)
                if url.path=='/audio':return self.respond(200,audio,'audio/wav')
                if url.path!='/agreed-test-feed':return self.respond(404,{})
                cursor=parse_qs(url.query).get('cursor',[None])[0]
                index=int(cursor.split('-')[1]) if cursor else 0
                if index>=state['available']:
                    return self.respond(200,{'source_id':'fixture-student','batch':None,'audio':[],'has_more':False})
                refs=[{'sha256':sha,'variant':v,'path':'/audio'} for v in ('wav','original')] if index<2 else []
                return self.respond(200,{'source_id':'fixture-student','batch':{'schema_version':1,'source_id':'fixture-student',
                    'batch_id':f'batch-{index+1}','cursor':cursor,'next_cursor':f'cursor-{index+1}','events':changes[index]},
                    'audio':refs,'has_more':index+1<state['available']})
            def do_PUT(self):
                if not self.authorized():return
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                key=value['snapshot_version'];duplicate=key in state['coverage']
                if duplicate and state['coverage'][key]!=value:return self.respond(409,{})
                state['coverage'][key]=value;state['coverage_requests'].append(value)
                if state['drop']:
                    state['drop']=False;self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                return self.respond(200,{'ok':True,'applied':not duplicate,'snapshot':value})
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{port}'; upstream_url=f'http://127.0.0.1:{upstream.server_port}'
        env={**os.environ,'ADMIN_TOKEN':token,'ADMIN_ACTOR':'synthetic-rehearsal','ADMIN_DATA_DIR':str(root/'management'),
             'ADMIN_PUBLIC_ORIGIN':origin,'ADMIN_COOKIE_SECURE':'1','PYTHONUTF8':'1'}
        for key in ('ADMIN_AUTH_FILE','PORTAL_DEMO','STUDENT_BASE_URL','PROPOSITION_BASE_URL'):env.pop(key,None)
        processes=[]; log=(root/'services.log').open('w')
        admin=Service(base,token);remote=Service(upstream_url,upstream_token)
        def start(data_dir):
            e={**env,'ADMIN_DATA_DIR':str(data_dir)}
            process=subprocess.Popen([sys.executable,'run.py','--port',str(port)],cwd=BACKEND,env=e,stdout=log,stderr=subprocess.STDOUT)
            processes.append(process)
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('管理服务未启动')
                try:
                    with httpx.Client(timeout=.3,trust_env=False) as client:
                        if client.get(base+'/api/health').status_code==200:return process
                except httpx.HTTPError:pass
                time.sleep(.1)
            raise RuntimeError('管理服务启动超时')
        try:
            process=start(root/'management')
            result=pull_student(admin,remote,'fixture-student','/agreed-test-feed')
            assert result['events']==3 and result['cursor']=='cursor-1'
            assert pull_student(admin,remote,'fixture-student','/agreed-test-feed')['events']==0
            passed('授权变更页、音频SHA256、事务入库、游标续传与空页去重')
            row=admin.request('GET','/api/v1/admin/recordings/QA-R').json()
            admin.request('PUT','/api/v1/admin/recordings/QA-R',json={'expected_version':row['version'],'note':'保留人工核查'})
            state['available']=2;pull_student(admin,remote,'fixture-student','/agreed-test-feed')
            row=admin.request('GET','/api/v1/admin/recordings/QA-R').json()
            assert row['diagnosis']['status']=='completed' and row['note']=='保留人工核查'
            passed('后续诊断更新保留人工核查备注与录音题目快照')
            delivered=coverage_once(admin,remote,root/'outbox.sqlite3')
            assert delivered['status']=='received' and state['coverage_requests'][0]==state['coverage_requests'][1]
            passed('接收端已处理但回执丢失：重试同一快照，不重复生成计数')
            for available,count in [(3,0),(4,1)]:
                state['available']=available;pull_student(admin,remote,'fixture-student','/agreed-test-feed')
                assert admin.request('GET','/api/v1/admin/statistics').json()['recording_count']==count
                coverage_once(admin,remote,root/'outbox.sqlite3')
                assert state['coverage_requests'][-1]['items'][0]['recording_count']==count
            passed('来源删除与恢复后管理统计和发送快照按1→0→1变化')
            archive=admin.request('GET','/api/v1/admin/export',max_bytes=32*1024*1024).content
            with zipfile.ZipFile(io.BytesIO(archive)) as z:
                checksums=json.loads(z.read('checksums.json'))
                assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in checksums.items())
            passed('同步后完整导出与逐文件校验')
            if caddy:
                cert,key=root/'test-cert.pem',root/'test-key.pem'
                conf=root/'openssl.cnf'
                conf.write_text('[req]\ndistinguished_name=dn\nx509_extensions=v3\nprompt=no\n[dn]\nCN=127.0.0.1\n[v3]\nsubjectAltName=IP:127.0.0.1\nbasicConstraints=critical,CA:TRUE\n',encoding='utf-8')
                subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-config',str(conf),
                                '-keyout',str(key),'-out',str(cert)],check=True,stdout=log,stderr=log)
                config=root/'Caddyfile'
                config.write_text('{\n admin off\n auto_https off\n}\n'+origin+' {\n bind 127.0.0.1\n tls "'+str(cert)+'" "'+str(key)+'"\n request_body {\n max_size 23MB\n }\n reverse_proxy 127.0.0.1:'+str(port)+'\n}\n',encoding='utf-8')
                cenv={**os.environ,'XDG_DATA_HOME':str(root/'caddy-data'),'XDG_CONFIG_HOME':str(root/'caddy-config')}
                subprocess.run([str(caddy),'validate','--config',str(config),'--adapter','caddyfile'],check=True,env=cenv,stdout=log,stderr=log)
                cp=subprocess.Popen([str(caddy),'run','--config',str(config),'--adapter','caddyfile'],env=cenv,stdout=log,stderr=log);processes.append(cp)
                context=ssl.create_default_context(cafile=str(cert))
                with httpx.Client(verify=context,trust_env=False,timeout=3,follow_redirects=False) as browser:
                    for _ in range(100):
                        try:
                            if browser.get(origin+'/api/health').status_code==200:break
                        except httpx.HTTPError:time.sleep(.1)
                    assert browser.get(origin+'/api/v1/admin/statistics').status_code==401
                    signed=browser.post(origin+'/api/session',headers={'Authorization':'Bearer '+token,'Origin':origin})
                    assert signed.status_code==200 and 'Secure' in signed.headers['set-cookie'] and 'HttpOnly' in signed.headers['set-cookie']
                    assert browser.get(origin+'/api/v1/admin/statistics').status_code==200
                    assert browser.get(base+'/api/v1/admin/statistics').status_code==401
                    assert browser.get(origin+'/api/v1/admin/recordings/QA-R/audio',headers={'Range':'bytes=0-43'}).status_code==206
                    assert browser.post(origin+'/api/v1/admin/coverage/snapshots',headers={'Origin':'https://untrusted.invalid'},json={}).status_code==403
                passed('Caddy本机TLS、证书校验、Secure会话、禁止HTTP携带会话、Range音频、跨站拒绝')
            backup(root/'management',root/'backup');restore(root/'backup',root/'restored')
            process.terminate();process.wait(timeout=10)
            start(root/'restored')
            assert admin.request('GET','/api/v1/admin/integration/sources/fixture-student').json()['cursor']=='cursor-4'
            assert admin.request('GET','/api/v1/admin/recordings/QA-R').json()['note']=='保留人工核查'
            assert pull_student(admin,remote,'fixture-student','/agreed-test-feed')['events']==0
            passed('在线备份、新目录恢复、服务重新启动后数据与游标保留')
        finally:
            admin.close();remote.close();upstream.shutdown();upstream.server_close()
            for p in processes:
                if p.poll() is None:p.terminate()
            for p in processes:
                try:p.wait(timeout=10)
                except subprocess.TimeoutExpired:p.kill();p.wait()
            log.close()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Report: '+str(output),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--caddy',type=Path)
    args=parser.parse_args();run(args.output,args.caddy)
