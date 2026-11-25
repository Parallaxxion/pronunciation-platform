"""SQLite data ownership, optimistic writes, immutable history and audit trail."""
import hashlib
import io
import json
import os
import sqlite3
import uuid
import wave
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from contracts import ContractError

KINDS = ('speakers', 'questions', 'recordings')
KEYS = {'speakers': 'speaker_id', 'questions': 'question_id', 'recordings': 'recording_id'}


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class Conflict(Exception):
    pass


class Missing(Exception):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.audio = self.root / 'audio'
        self.audio.mkdir(exist_ok=True, mode=0o700)
        self.path = self.root / 'management.sqlite3'
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS speakers(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
              deleted INTEGER NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS questions(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
              deleted INTEGER NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recordings(id TEXT PRIMARY KEY, version INTEGER NOT NULL,
              deleted INTEGER NOT NULL, body TEXT NOT NULL,
              speaker_id TEXT NOT NULL REFERENCES speakers(id),
              question_id TEXT NOT NULL REFERENCES questions(id),
              practice_session_id TEXT NOT NULL, take_no INTEGER NOT NULL,
              UNIQUE(practice_session_id,take_no));
            CREATE TABLE IF NOT EXISTS history(kind TEXT, entity_id TEXT, version INTEGER,
              body TEXT NOT NULL, deleted INTEGER NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(kind,entity_id,version));
            CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT,
              actor TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
              operation TEXT NOT NULL, before_json TEXT, after_json TEXT NOT NULL,
              created_at TEXT NOT NULL, undo_of INTEGER UNIQUE REFERENCES actions(id),
              undone INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS requests(actor TEXT, request_key TEXT,
              fingerprint TEXT NOT NULL, response TEXT NOT NULL,
              PRIMARY KEY(actor,request_key));
            CREATE TABLE IF NOT EXISTS blobs(sha256 TEXT PRIMARY KEY, size INTEGER NOT NULL,
              is_standard_wav INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS coverage_snapshots(version TEXT PRIMARY KEY,
              payload TEXT NOT NULL, action_id INTEGER NOT NULL);
            ''')
            db.execute('INSERT OR IGNORE INTO settings VALUES(?,?)', ('instance', uuid.uuid4().hex))
            from synchronization import SCHEMA
            db.executescript(SCHEMA)

    @contextmanager
    def db(self, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def get(self, db, kind, entity_id):
        assert kind in KINDS
        row = db.execute(f'SELECT * FROM {kind} WHERE id=?', (entity_id,)).fetchone()
        if not row:
            raise Missing('记录不存在')
        return {**json.loads(row['body']), 'version': row['version'], 'deleted': bool(row['deleted'])}

    def list(self, db, kind, deleted=False):
        assert kind in KINDS
        rows = db.execute(f'SELECT id FROM {kind} WHERE deleted=? ORDER BY id', (int(deleted),))
        return [self.get(db, kind, row['id']) for row in rows]

    def require_version(self, current, version):
        if current['version'] != version:
            raise Conflict(f'数据已有变更，当前版本为 {current["version"]}，请刷新后重试')

    def references(self, db, kind, value):
        if kind != 'recordings':
            return
        for parent, key in [('speakers', 'speaker_id'), ('questions', 'question_id')]:
            if self.get(db, parent, value[key])['deleted']:
                raise Conflict('关联的说话人或题目已删除，请先恢复')
        # A practice session always belongs to the same speaker and question.
        session = db.execute('SELECT speaker_id,question_id FROM recordings WHERE practice_session_id=? LIMIT 1',
                             (value['practice_session_id'],)).fetchone()
        if session and (session['speaker_id'] != value['speaker_id'] or session['question_id'] != value['question_id']):
            raise Conflict('同一次练习不能关联不同说话人或题目')
        for key in ('wav_sha256', 'original_sha256'):
            blob = db.execute('SELECT * FROM blobs WHERE sha256=?', (value[key],)).fetchone()
            if not blob or not (self.audio / value[key]).is_file():
                raise Conflict('音频尚未上传或文件缺失')
            if key == 'wav_sha256' and not blob['is_standard_wav']:
                raise ContractError('标准音频必须是 16kHz、单声道、16bit PCM WAV')

    def persist(self, db, kind, value, actor, operation, before=None, undo_of=None):
        entity_id = value[KEYS[kind]]
        version = (before['version'] + 1) if before else 1
        deleted = bool(value.pop('deleted', False))
        body = {k: v for k, v in value.items() if k != 'version'}
        if before:
            db.execute(f'UPDATE {kind} SET version=?,deleted=?,body=? WHERE id=?',
                       (version, int(deleted), encoded(body), entity_id))
        elif kind == 'recordings':
            db.execute('INSERT INTO recordings VALUES(?,?,?,?,?,?,?,?)',
                       (entity_id, version, int(deleted), encoded(body), body['speaker_id'], body['question_id'],
                        body['practice_session_id'], body['take_no']))
        else:
            db.execute(f'INSERT INTO {kind} VALUES(?,?,?,?)', (entity_id, version, int(deleted), encoded(body)))
        result = {**body, 'version': version, 'deleted': deleted}
        timestamp = now()
        db.execute('INSERT INTO history VALUES(?,?,?,?,?,?)',
                   (kind, entity_id, version, encoded(body), int(deleted), timestamp))
        action_id = db.execute('INSERT INTO actions(actor,kind,entity_id,operation,before_json,after_json,created_at,undo_of) VALUES(?,?,?,?,?,?,?,?)',
                              (actor, kind, entity_id, operation, encoded(before) if before else None,
                               encoded(result), timestamp, undo_of)).lastrowid
        return {'item': result, 'action_id': action_id, 'duplicate': False}

    def create(self, db, kind, value, actor):
        entity_id = value[KEYS[kind]]
        old = db.execute(f'SELECT id FROM {kind} WHERE id=?', (entity_id,)).fetchone()
        if old:
            # Compare against the original import. Replays never undo later review or deletion.
            initial = json.loads(db.execute('SELECT body FROM history WHERE kind=? AND entity_id=? AND version=1',
                                           (kind, entity_id)).fetchone()[0])
            if initial != value:
                raise Conflict('编号已存在且内容不同；更新需提供当前版本')
            return {'item': self.get(db, kind, entity_id), 'duplicate': True, 'action_id': None}
        self.references(db, kind, value)
        return self.persist(db, kind, value, actor, 'create')

    def update(self, db, kind, entity_id, version, fields, actor, operation='update'):
        old = self.get(db, kind, entity_id)
        self.require_version(old, version)
        if old['deleted']:
            raise Conflict('请先恢复已删除的记录')
        return self.persist(db, kind, {**old, **fields}, actor, operation, old)

    def set_deleted(self, db, kind, entity_id, version, deleted, actor):
        old = self.get(db, kind, entity_id)
        self.require_version(old, version)
        if old['deleted'] == deleted:
            raise Conflict('记录已处于该状态')
        if not deleted:
            self.references(db, kind, old)
        return self.persist(db, kind, {**old, 'deleted': deleted}, actor, 'delete' if deleted else 'restore', old)

    def undo(self, db, action_id, actor):
        action = db.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone()
        if not action:
            raise Missing('操作不存在')
        if action['undone'] or action['undo_of'] is not None:
            raise Conflict('该操作已撤销，或本身是撤销操作')
        kind, entity_id = action['kind'], action['entity_id']
        current = self.get(db, kind, entity_id)
        self.require_version(current, json.loads(action['after_json'])['version'])
        before = json.loads(action['before_json']) if action['before_json'] else None
        if before is None and kind in ('speakers', 'questions'):
            column = 'speaker_id' if kind == 'speakers' else 'question_id'
            if db.execute(f'SELECT 1 FROM recordings WHERE {column}=? LIMIT 1', (entity_id,)).fetchone():
                raise Conflict('新增记录已被录音引用，不能撤销创建；可选择软删除并保留历史')
        target = before if before is not None else {**current, 'deleted': True}
        if not target['deleted']:
            self.references(db, kind, target)
        result = self.persist(db, kind, dict(target), actor, 'undo', current, action_id)
        db.execute('UPDATE actions SET undone=1 WHERE id=?', (action_id,))
        return result

    def write(self, actor, key, fingerprint, operation):
        with self.db(write=True) as db:
            old = db.execute('SELECT fingerprint,response FROM requests WHERE actor=? AND request_key=?',
                             (actor, key)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise Conflict('Idempotency-Key 已用于不同请求')
                return {**json.loads(old['response']), 'replayed': True}
            result = operation(db)
            db.execute('INSERT INTO requests VALUES(?,?,?,?)', (actor, key, fingerprint, encoded(result)))
            return {**result, 'replayed': False}

    def put_audio(self, data, standard):
        is_wav = False
        try:
            with wave.open(io.BytesIO(data), 'rb') as wav:
                is_wav = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) == (1, 2, 16000, 'NONE')
                expected = wav.getnframes() * wav.getsampwidth() * wav.getnchannels()
                is_wav = is_wav and expected > 0 and len(wav.readframes(wav.getnframes())) == expected
        except (wave.Error, EOFError):
            pass
        if standard and not is_wav:
            raise ContractError('标准音频必须是完整的 16kHz、单声道、16bit PCM WAV')
        digest = hashlib.sha256(data).hexdigest()
        # A crash can leave an unreferenced blob; content-addressed retries are safe.
        with self.db(write=True) as db:
            path = self.audio / digest
            if not path.exists():
                temp = self.audio / ('.upload-' + uuid.uuid4().hex)
                try:
                    with temp.open('xb') as stream:
                        os.chmod(temp, 0o600)
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                    temp.replace(path)
                finally:
                    temp.unlink(missing_ok=True)
            db.execute('INSERT OR IGNORE INTO blobs VALUES(?,?,?)', (digest, len(data), int(is_wav)))
        return {'sha256': digest, 'size': len(data), 'is_standard_wav': is_wav}

    def coverage(self, db):
        recordings = self.list(db, 'recordings')
        items = []
        # Deleted questions remain in the snapshot so the receiver can clear old counts.
        questions = self.list(db, 'questions') + self.list(db, 'questions', True)
        for question in sorted(questions, key=lambda q: q['question_id']):
            rows = [r for r in recordings if r['question_id'] == question['question_id'] and r['upload_status'] == 'uploaded']
            target = question['target_recordings']
            items.append({'question_id': question['question_id'], 'recording_count': len(rows),
                          'unique_speaker_count': len({r['speaker_id'] for r in rows}),
                          'target_recordings': target, 'gap': None if target is None else max(0, target-len(rows))})
        return {'counting_policy': 'uploaded_not_deleted_distinct_recording_id', 'items': items}

    def snapshot(self, db):
        action_id = db.execute('SELECT coalesce(max(id),0) FROM actions').fetchone()[0]
        instance = db.execute("SELECT value FROM settings WHERE key='instance'").fetchone()[0]
        version = f'{instance}:{action_id:012d}'
        old = db.execute('SELECT payload FROM coverage_snapshots WHERE version=?', (version,)).fetchone()
        if old:
            return json.loads(old[0])
        items = [{k: row[k] for k in ('question_id','recording_count','unique_speaker_count')} for row in self.coverage(db)['items']]
        payload = {'snapshot_version': version, 'generated_at': now(), 'items': items}
        db.execute('INSERT INTO coverage_snapshots VALUES(?,?,?)', (version, encoded(payload), action_id))
        return payload
