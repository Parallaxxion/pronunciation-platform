"""Local research-data admin prototype. Bind to loopback; synthetic fixtures only."""
import csv
import io
import json
import os
import sqlite3
import sys
import threading
import webbrowser
import zipfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).resolve().parent
DB = Path(os.environ.get('ADMIN_DEMO_DB', str(BASE / 'demo.sqlite3')))


def connect():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS speakers(id TEXT PRIMARY KEY, nationality TEXT, language TEXT, level INTEGER);
        CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, level INTEGER, text TEXT, pinyin TEXT, target INTEGER);
        CREATE TABLE IF NOT EXISTS recordings(id TEXT PRIMARY KEY, speaker_id TEXT REFERENCES speakers(id),
        question_id TEXT REFERENCES questions(id), attempt INTEGER, recorded_at TEXT, device TEXT,
        audio TEXT, diagnosis TEXT, note TEXT DEFAULT '', deleted INTEGER DEFAULT 0, version INTEGER DEFAULT 1,
        UNIQUE(speaker_id, question_id, attempt));
        CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT, recording_id TEXT,
        kind TEXT, before_json TEXT, after_version INTEGER, created_at TEXT, undone INTEGER DEFAULT 0);
        ''')
        if db.execute('SELECT count(*) FROM speakers').fetchone()[0]:
            return
        db.executemany('INSERT INTO speakers VALUES(?,?,?,?)', [('S-001','泰国','泰语',1),('S-002','韩国','韩语',1),('S-003','越南','越南语',2),('S-004','日本','日语',2)])
        questions = [('Q-001',1,'我喜欢学习汉语',['wǒ','xǐ','huān','xué','xí','hàn','yǔ'],3),('Q-002',1,'今天我们去学校',['jīn','tiān','wǒ','men','qù','xué','xiào'],3),('Q-003',2,'请问图书馆在哪里',['qǐng','wèn','tú','shū','guǎn','zài','nǎ','lǐ'],3),('Q-004',2,'周末我和朋友去公园',['zhōu','mò','wǒ','hé','péng','you','qù','gōng','yuán'],3)]
        db.executemany('INSERT INTO questions VALUES(?,?,?,?,?)', [(a,b,c,json.dumps(d,ensure_ascii=False),e) for a,b,c,d,e in questions])
        errors=[{'type':'tone','char_index':0,'expected':'wǒ','actual':'wó'}, {'type':'substitution','char_index':5,'expected':'hàn','actual':'kàn'}, {'type':'omission','char_index':4,'expected':'xí','actual':None}, {'type':'insertion','boundary_index':3,'expected':None,'actual':'a'}]
        for n,(speaker,question,attempt) in enumerate([('S-001','Q-001',1),('S-001','Q-001',2),('S-002','Q-002',1),('S-003','Q-003',1),('S-004','Q-003',1)],1):
            diagnosis={'status':'completed','source':'synthetic_fixture','model_version':'fixture-v1','errors':errors if n==1 else []}
            db.execute('INSERT INTO recordings(id,speaker_id,question_id,attempt,recorded_at,device,audio,diagnosis) VALUES(?,?,?,?,?,?,?,?)', (f'R-{n:03}',speaker,question,attempt,f'2026-11-16T0{n}:00:00+00:00','演示设备 / 合成语音',f'{question}.wav',json.dumps(diagnosis,ensure_ascii=False)))


def records(db, include_deleted=False):
    rows = db.execute('''SELECT r.*, q.text, q.pinyin, q.level, s.nationality, s.language
        FROM recordings r JOIN questions q ON r.question_id=q.id JOIN speakers s ON r.speaker_id=s.id
        ''' + ('' if include_deleted else 'WHERE r.deleted=0 ') + 'ORDER BY r.id').fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        item['pinyin']=json.loads(item['pinyin'])
        item['diagnosis']=json.loads(item['diagnosis'])
        result.append(item)
    return result


def export_archive(db):
    rows=records(db)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        manifest=[]
        for r in rows:
            source=BASE/'static'/'audio'/r['audio']
            if not source.is_file():
                raise ValueError(f'音频缺失 {r["id"]}')
            wav=f'audio/{r["id"]}.wav'
            original=f'original/{r["id"]}.wav'
            archive.writestr(wav,source.read_bytes())
            archive.writestr(original,source.read_bytes())
            manifest.append({'recording_id':r['id'],'speaker_id':r['speaker_id'],'question_id':r['question_id'],'attempt':r['attempt'],'recorded_at':r['recorded_at'],'device':r['device'],'level':r['level'],'text':r['text'],'pinyin':r['pinyin'],'audio_path':wav,'original_path':original,'note':r['note'],'data_source':'synthetic_fixture'})
        archive.writestr('manifest.jsonl','\n'.join(json.dumps(r,ensure_ascii=False) for r in manifest)+'\n')
        archive.writestr('annotations.jsonl','\n'.join(json.dumps({'recording_id':r['id'],**r['diagnosis']},ensure_ascii=False) for r in rows)+'\n')
        table=io.StringIO()
        writer=csv.DictWriter(table,fieldnames=['recording_id','speaker_id','question_id','attempt','level','audio_path'])
        writer.writeheader()
        writer.writerows({k:r[k] for k in writer.fieldnames} for r in manifest)
        archive.writestr('manifest.csv','\ufeff'+table.getvalue())
        archive.writestr('README.txt','演示数据。语音由系统合成，偏误为人工构造的展示样例，不代表算法检测结果。\n原始文件与规范文件在本演示中均为同一份WAV。\n字索引从0开始，不含标点。boundary_index=k表示第k个字之前，允许0到字数。\n导出包含未删除记录。匿名背景信息见speakers.json。')
        archive.writestr('speakers.json',json.dumps([dict(r) for r in db.execute('SELECT * FROM speakers')],ensure_ascii=False,indent=2))
        archive.writestr('schema.json',json.dumps({'schema_version':'0.1-draft','created_at':datetime.now(timezone.utc).isoformat(),'recording_count':len(rows),'index_unit':'unicode_code_point_without_punctuation','target_per_question':3,'target_status':'demo_assumption'},indent=2))
    return buffer.getvalue()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(BASE/'static'),**kwargs)

    def send_json(self,data,status=200):
        payload=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path=urlparse(self.path).path
        if not path.startswith('/api/'):
            return super().do_GET()
        with connect() as db:
            if path=='/api/state':
                questions=[dict(r) for r in db.execute('SELECT q.id,q.level,q.text,q.target,count(r.id) AS count FROM questions q LEFT JOIN recordings r ON q.id=r.question_id AND r.deleted=0 GROUP BY q.id ORDER BY q.id')]
                return self.send_json({'recordings':records(db,True),'questions':questions,'speakers':[dict(r) for r in db.execute('SELECT * FROM speakers')], 'actions':[dict(r) for r in db.execute('SELECT id,recording_id,kind,after_version,created_at,undone FROM actions ORDER BY id DESC')]})
            if path=='/api/export':
                try:
                    data=export_archive(db)
                except ValueError as error:
                    return self.send_json({'error':str(error)},409)
                self.send_response(200)
                self.send_header('Content-Type','application/zip')
                self.send_header('Content-Disposition','attachment; filename="admin-demo-export.zip"')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                return self.wfile.write(data)
        self.send_json({'error':'接口不存在'},404)

    def do_POST(self):
        # The demo listens only on localhost. Reject browser cross-origin writes.
        if self.headers.get('Origin') and self.headers['Origin'] != 'http://'+self.headers.get('Host',''):
            return self.send_json({'error':'来源不匹配'},403)
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=10000:
                raise ValueError('请求大小不正确')
            body=json.loads(self.rfile.read(size))
            path=urlparse(self.path).path
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if path=='/api/undo':
                    action=db.execute('SELECT * FROM actions WHERE id=?',(body['action_id'],)).fetchone()
                    if not action:
                        return self.send_json({'error':'操作不存在'},404)
                    current=db.execute('SELECT * FROM recordings WHERE id=?',(action['recording_id'],)).fetchone()
                    if action['undone'] or current['version']!=action['after_version']:
                        return self.send_json({'error':'记录已有后续变更或已撤销，请刷新后处理'},409)
                    before=json.loads(action['before_json'])
                    db.execute('UPDATE recordings SET note=?,deleted=?,version=version+1 WHERE id=?',(before['note'],before['deleted'],action['recording_id']))
                    db.execute('UPDATE actions SET undone=1 WHERE id=?',(action['id'],))
                elif path=='/api/recordings/update':
                    row=db.execute('SELECT * FROM recordings WHERE id=?',(body['id'],)).fetchone()
                    if not row:
                        return self.send_json({'error':'录音不存在'},404)
                    if body['version']!=row['version']:
                        return self.send_json({'error':'数据已变化，请刷新重试'},409)
                    kind=body['kind']
                    if kind not in ('note','delete','restore'):
                        raise ValueError('操作不支持')
                    note=body.get('note',row['note'])
                    if not isinstance(note,str) or len(note)>500:
                        raise ValueError('备注最长500字')
                    deleted=1 if kind=='delete' else (0 if kind=='restore' else row['deleted'])
                    db.execute('UPDATE recordings SET note=?,deleted=?,version=version+1 WHERE id=?',(note,deleted,row['id']))
                    db.execute('INSERT INTO actions(recording_id,kind,before_json,after_version,created_at) VALUES(?,?,?,?,?)',(row['id'],kind,json.dumps(dict(row)),row['version']+1,datetime.now(timezone.utc).isoformat()))
                else:
                    return self.send_json({'error':'接口不存在'},404)
            self.send_json({'ok':True})
        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as error:
            self.send_json({'error':str(error)},400)


if __name__=='__main__':
    initialize()
    port=int(os.environ.get('ADMIN_DEMO_PORT','8765'))
    url=f'http://127.0.0.1:{port}'
    try:
        http=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    except OSError as error:
        print(f'无法启动端口 {port}。若演示已运行，请访问 {url}。错误 {error}',flush=True)
        raise SystemExit(1)
    print(f'管理端原型 {url}  数据为模拟样例',flush=True)
    if '--open-browser' in sys.argv:
        threading.Timer(0.5,lambda: webbrowser.open(url)).start()
    http.serve_forever()
