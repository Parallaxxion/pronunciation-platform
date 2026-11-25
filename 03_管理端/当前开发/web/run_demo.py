"""Start an isolated three-service workspace. Never uses upstream production databases."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import wave

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BACKEND=HERE.parent/'backend'

def copy_source(source,target):
    if not source.is_dir():raise SystemExit(f'源码目录不存在：{source}')
    ignored={'.git','.venv','node_modules','__pycache__','original','wav'}
    manifest={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(source.rglob('*')) if p.is_file() and not (set(p.relative_to(source).parts)&ignored)
              and p.suffix not in {'.db','.sqlite3','.pyc'} and p.name!='.env'}
    marker=target/'.source-manifest.json'
    if target.exists():
        if marker.exists():
            if json.loads(marker.read_text())!=manifest:raise SystemExit('上游源码版本改变，请使用新的 --data-dir；不覆盖已有测试数据')
        elif any(not (target/name).is_file() or hashlib.sha256((target/name).read_bytes()).hexdigest()!=digest for name,digest in manifest.items()):
            raise SystemExit('已有运行目录与源码不一致，请使用新的 --data-dir')
    else:
        shutil.copytree(source,target,ignore=shutil.ignore_patterns('.git','.venv','node_modules','__pycache__','*.db','*.sqlite3','.env','original','wav'))
    marker.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')

def run(args,cwd,env,log):
    subprocess.run([sys.executable,*args],cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)

def seed(root,token):
    sys.path.insert(0,str(BACKEND))
    from app import create_app
    from fastapi.testclient import TestClient
    app=create_app(root,accounts=[{'actor':'本机演示管理员','role':'admin','token_sha256':hashlib.sha256(token.encode()).hexdigest()}])
    headers={'Authorization':'Bearer '+token}
    with TestClient(app) as c:
        if c.get('/api/v1/admin/recordings',headers=headers).json()['total']:return
        def write(path,data):
            r=c.post('/api/v1/admin/'+path,headers={**headers,'Idempotency-Key':secrets.token_urlsafe(20)},json=data)
            r.raise_for_status();return r.json()
        s={'speaker_id':'DEMO-S001','nationality':'演示背景','language':'演示语言','level':1,'source':'synthetic_fixture'}
        if not c.get('/api/v1/admin/speakers/DEMO-S001',headers=headers).is_success:write('speakers',s)
        q={'question_id':'DEMO-Q001','level':1,'display_text':'我喜欢学习中文。','tokens':[{'c':ch,'py':py} for ch,py in zip('我喜欢学习中文',['wo3','xi3','huan1','xue2','xi2','zhong1','wen2'])],'status':'published','source':'synthetic_fixture','target_recordings':6,'question_version':'demo-v1'}
        if not c.get('/api/v1/admin/questions/DEMO-Q001',headers=headers).is_success:write('questions',q)
        stream=io.BytesIO()
        with wave.open(stream,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0\0'*32000)
        digest=c.post('/api/v1/admin/audio',headers=headers,content=stream.getvalue()).json()['sha256']
        for i,status in enumerate(['completed','pending','processing','failed']):
            d={'status':status,'errors':[],'model_version':'constructed-ui-fixture'}
            if status=='completed':d['errors']=[{'type':'tone','char_index':1,'actual':'xi1'},{'type':'substitution','char_index':3,'actual':'shue2'},{'type':'omission','char_index':5},{'type':'insertion','boundary_index':7,'actual':'a5'}]
            write('recordings',{'recording_id':f'DEMO-R00{i+1}','speaker_id':s['speaker_id'],'question_id':q['question_id'],'practice_session_id':'DEMO-P001','take_no':i+1,'recorded_at':'2026-11-25T10:00:00+08:00','question_snapshot':q,'wav_sha256':digest,'original_sha256':digest,'data_source':'synthetic_fixture','diagnosis':d,'note':'界面测试：合成静音，人工构造偏误，不代表算法效果'})

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port',type=int,default=8791)
    ap.add_argument('--proposition-source',type=Path,default=ROOT/'02_命题端/2026.11.23-2026.11.29第3周/成果快照')
    ap.add_argument('--student-source',type=Path,default=ROOT/'01_学生端/当前开发')
    ap.add_argument('--data-dir',type=Path,default=HERE.parent/'local-data/portal-demo')
    args=ap.parse_args();root=args.data_dir.resolve();root.mkdir(parents=True,exist_ok=True)
    marker=root/'DEMO_ONLY'
    if not marker.exists() and any(root.iterdir()):raise SystemExit('拒绝使用已有的非演示目录，请指定新的空目录')
    marker.write_text('Only synthetic fixtures and explicitly submitted local test data.\n')
    for port in [args.port,args.port+1,args.port+2]:
        with socket.socket() as sock:
            try:sock.bind(('127.0.0.1',port))
            except OSError as error:raise SystemExit(f'端口 {port} 无法监听：{error}')
    token_file=root/'access-token.txt'
    if token_file.exists():token=token_file.read_text().strip()
    else:
        token=secrets.token_urlsafe(40);token_file.write_text(token);token_file.chmod(0o600)
    env={**os.environ,'ADMIN_TOKEN':token,'ADMIN_ACTOR':'本机演示管理员','ADMIN_DATA_DIR':str(root/'management'),'PORTAL_DEMO':'1','ADMIN_PUBLIC_ORIGIN':f'http://127.0.0.1:{args.port}','STUDENT_BASE_URL':f'http://127.0.0.1:{args.port+1}','PROPOSITION_BASE_URL':f'http://127.0.0.1:{args.port+2}'}
    # A demo must not inherit production identities, SMTP or secure-cookie configuration.
    for key in ['ADMIN_AUTH_FILE','ADMIN_COOKIE_SECURE','PROPOSITION_SERVICE_TOKEN','SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM']:env.pop(key,None)
    os.environ.update({k:env[k] for k in ['ADMIN_TOKEN','ADMIN_ACTOR','ADMIN_DATA_DIR','PORTAL_DEMO','ADMIN_PUBLIC_ORIGIN','STUDENT_BASE_URL','PROPOSITION_BASE_URL']})
    os.environ.pop('ADMIN_AUTH_FILE',None)
    seed(root/'management',token)
    student=root/'student';prop=root/'proposition'
    copy_source(args.student_source.resolve(),student);copy_source(args.proposition_source.resolve(),prop)
    log=(root/'services.log').open('a')
    student_env={**env,'APP_ENV':'development','PUBLIC_BASE_URL':f'http://127.0.0.1:{args.port}','PRIVACY_VERSION':'local-demo-only'}
    for module in ['app.init_db','app.import_questions','app.build_pinyin']:
        run(['-m',module],student/'backend',student_env,log)
    prop_env={**env,'BANK_DB':str(root/'question-bank.db')}
    run(['backend/init_db.py'],prop,prop_env,log)
    for level in range(1,8):
        if (prop/f'banks/level{level}/final.json').exists():run(['backend/import_bank.py','--level',str(level)],prop,prop_env,log)
    processes=[]
    try:
        for cwd,module,port,service_env in [(student/'backend','app.main:app',args.port+1,student_env),(prop,'backend.main:app',args.port+2,prop_env),(BACKEND,'app:create_app',args.port,env)]:
            cmd=[sys.executable,'-m','uvicorn',module,'--host','127.0.0.1','--port',str(port)]
            if cwd==BACKEND:cmd.append('--factory')
            processes.append(subprocess.Popen(cmd,cwd=cwd,env=service_env,stdout=log,stderr=subprocess.STDOUT))
        import httpx
        deadline=time.monotonic()+60
        while True:
            if any(p.poll() is not None for p in processes):raise SystemExit('服务启动失败，请检查 services.log')
            try:
                with httpx.Client(timeout=1,trust_env=False) as client:
                    for port,path in [(args.port,'/api/health'),(args.port+1,'/api/health'),(args.port+2,'/api/levels')]:
                        client.get(f'http://127.0.0.1:{port}{path}').raise_for_status()
                break
            except httpx.HTTPError:
                if time.monotonic()>deadline:raise SystemExit('服务启动超时，请检查 services.log')
                time.sleep(.2)
        print(f'Web: http://127.0.0.1:{args.port}',flush=True)
        print(f'管理访问令牌保存在本机文件：{token_file}',flush=True)
        print('Ctrl+C 停止三个服务。此环境不代表真实跨端同步和算法效果验收。',flush=True)
        while all(p.poll() is None for p in processes):time.sleep(1)
        raise SystemExit('某个服务退出，请检查 services.log')
    except KeyboardInterrupt:pass
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill()
        log.close()

if __name__=='__main__':main()
