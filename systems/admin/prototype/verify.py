"""Exercise normal HTTP entry points against a temporary database."""
import io
import json
import tempfile
import threading
import urllib.request
import urllib.error
import wave
import zipfile
from pathlib import Path
import server

checks=[]
def check(name,condition):
    assert condition,name
    checks.append('通过  '+name)

def request(path,payload=None):
    data=None if payload is None else json.dumps(payload).encode()
    req=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            return response.status,response.read()
    except urllib.error.HTTPError as error:
        return error.code,error.read()

def state():
    return json.loads(request('/api/state')[1])

with tempfile.TemporaryDirectory() as folder:
    server.DB=Path(folder)/'verify.sqlite3'
    server.initialize()
    http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
    base=f'http://127.0.0.1:{http.server_port}'
    thread=threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    try:
        check('首页和脚本可访问',request('/')[0]==200 and request('/app.js')[0]==200)
        s=state()
        check('初始关联数据为4人4题5条录音',len(s['speakers'])==4 and len(s['questions'])==4 and len(s['recordings'])==5)
        check('初始覆盖3题、缺口7条',sum(q['count']>0 for q in s['questions'])==3 and sum(max(0,q['target']-q['count']) for q in s['questions'])==7)
        r=s['recordings'][0]
        check('四类偏误与合法索引齐全',set(e['type'] for e in r['diagnosis']['errors'])=={'tone','substitution','omission','insertion'} and all(0<=e.get('char_index',e.get('boundary_index'))<len(r['pinyin']) for e in r['diagnosis']['errors']))
        code,_=request('/api/recordings/update',{'id':r['id'],'version':1,'kind':'note','note':'核查测试'})
        check('备注通过HTTP保存并重新读取',code==200 and state()['recordings'][0]['note']=='核查测试')
        check('过期版本返回409',request('/api/recordings/update',{'id':r['id'],'version':1,'kind':'note','note':'旧值'})[0]==409)
        check('删除操作成功',request('/api/recordings/update',{'id':r['id'],'version':2,'kind':'delete'})[0]==200)
        check('删除同步影响统计',sum(q['count'] for q in state()['questions'])==4)
        check('撤销已有后续变更的操作返回409',request('/api/undo',{'action_id':1})[0]==409)
        check('删除后导出排除该样本',json.loads(zipfile.ZipFile(io.BytesIO(request('/api/export')[1])).read('schema.json'))['recording_count']==4)
        check('撤销删除恢复数据',request('/api/undo',{'action_id':2})[0]==200 and sum(q['count'] for q in state()['questions'])==5)
        check('重复撤销被拒绝',request('/api/undo',{'action_id':2})[0]==409)
        code,blob=request('/api/export')
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            rows=[json.loads(l) for l in z.read('manifest.jsonl').decode().splitlines()]
            annotations=[json.loads(l) for l in z.read('annotations.jsonl').decode().splitlines()]
            check('ZIP中5条信息与5条标注一一对应',code==200 and len(rows)==5 and {x['recording_id'] for x in rows}=={x['recording_id'] for x in annotations})
            for row in rows:
                for field in ('audio_path','original_path'):
                    with wave.open(io.BytesIO(z.read(row[field]))) as audio:
                        assert audio.getnframes()>0 and audio.getframerate()==16000
            check('全部规范音频和原始文件存在且WAV有效',True)
        output=Path(__file__).resolve().parent.parent/'evidence'
        # Fresh seed export for presentation evidence, independent from mutation checks.
        server.DB=Path(folder)/'fresh.sqlite3'
        server.initialize()
        with server.connect() as db:
            (output/'演示导出包.zip').write_bytes(server.export_archive(db))
        check('未知接口返回404',request('/api/missing')[0]==404)
        report='管理端原型验证记录\n2026年11月16日\n\n'+'\n'.join(checks)+'\n\n合计 '+str(len(checks))+' 项通过。\n验证使用独立临时数据库，通过实际HTTP接口执行。\n浏览器另行验证列表呈现、按S-001筛选为2条、四类标注和播放状态。\n未验证真实三端接口、身份认证、HTTPS部署、并发负载与算法准确率。\n'
        (output/'验证记录.txt').write_text(report)
        print(report)
    finally:
        http.shutdown()
