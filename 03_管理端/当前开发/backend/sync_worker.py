"""Explicit, repeatable handoff jobs. No guessed student endpoints or database access."""
import argparse
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from contracts import ID, Digest, Input
from pydantic import Field
from typing import Literal
from integration_cli import Service
from synchronization import SyncBatch, digest
from store import encoded, now


class AudioReference(Input):
    sha256: Digest
    variant: Literal['wav', 'original']
    path: str = Field(min_length=1, max_length=1000)


class FeedPage(Input):
    source_id: ID
    batch: SyncBatch | None
    audio: list[AudioReference] = Field(default_factory=list, max_length=200)
    has_more: bool = Field(strict=True)


def pull_student(admin, student, source_id, feed_path, max_pages=10):
    """The feed path is supplied by the upstream owner after protocol agreement."""
    pages = events = 0
    for _ in range(max_pages):
        cursor = admin.request('GET', '/api/v1/admin/integration/sources/'+source_id).json()['cursor']
        params = {'limit': 100}
        if cursor is not None:
            params['cursor'] = cursor
        try:
            page = FeedPage.model_validate(student.request('GET', feed_path, params=params).json())
        except ValueError:
            raise ValueError('上游变更页不符合已声明的交接契约') from None
        if page.source_id != source_id:
            raise ValueError('变更页来源不匹配')
        if page.batch is None:
            if page.has_more or page.audio:
                raise ValueError('空页不能包含音频或声称还有下一页')
            break
        batch = page.batch
        if batch.source_id != source_id or batch.cursor != cursor:
            raise ValueError('变更批次来源或游标不匹配')
        required = {(e.data[variant+'_sha256'], variant) for e in batch.events
                    if e.kind == 'recordings' and e.operation == 'upsert' and e.data
                    for variant in ('wav', 'original') if variant+'_sha256' in e.data}
        supplied = {(a.sha256, a.variant) for a in page.audio}
        if supplied != required or len(supplied) != len(page.audio):
            raise ValueError('音频清单必须与录音引用一一匹配')
        for audio in page.audio:
            content = student.request('GET', audio.path, max_bytes=20*1024*1024).content
            if hashlib.sha256(content).hexdigest() != audio.sha256:
                raise ValueError('交接音频 SHA256 不匹配')
            uploaded = admin.request('POST', '/api/v1/admin/audio', params={'variant': audio.variant}, content=content).json()
            if uploaded.get('sha256') != audio.sha256:
                raise ValueError('管理端音频回执不匹配')
        body = batch.model_dump(mode='json')
        receipt = admin.request('POST', '/api/v1/admin/integration/batches', json=body,
                                headers={'Idempotency-Key': 'sync-'+digest(body)}).json()
        if any(receipt.get(k) != v for k, v in {'source_id': source_id, 'batch_id': batch.batch_id,
                'cursor': batch.next_cursor, 'payload_sha256': digest(body)}.items()):
            raise RuntimeError('管理端批次回执不匹配')
        pages += 1
        events += len(batch.events)
        if not page.has_more:
            break
    return {'pages': pages, 'events': events, 'cursor': admin.request(
        'GET', '/api/v1/admin/integration/sources/'+source_id).json()['cursor']}


@contextmanager
def journal(path):
    """Separate SQLite lock survives across commits, and is released by a crashed process."""
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = sqlite3.connect(str(path)+'.lock', timeout=1)
    db = None
    try:
        lock.execute('BEGIN IMMEDIATE')
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.executescript('''CREATE TABLE IF NOT EXISTS delivery(
          version TEXT PRIMARY KEY, target TEXT NOT NULL, payload TEXT NOT NULL,
          state TEXT NOT NULL, attempts INTEGER NOT NULL, receipt TEXT, last_error TEXT, updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS binding(target TEXT PRIMARY KEY);''')
        os.chmod(path, 0o600)
        yield db
    finally:
        if db is not None:
            db.close()
        lock.close()


def coverage_once(admin, proposition, state_file):
    target = hashlib.sha256(str(proposition.client.base_url).encode()).hexdigest()
    with journal(state_file) as db:
        bound = db.execute('SELECT target FROM binding').fetchone()
        if bound and bound['target'] != target:
            raise ValueError('回传日志已绑定其他服务；更换服务请使用新日志并确认快照顺序')
        db.execute('INSERT OR IGNORE INTO binding VALUES(?)', (target,))
        db.commit()
        pending = db.execute("SELECT * FROM delivery WHERE state='pending' ORDER BY rowid LIMIT 1").fetchone()
        if pending:
            snapshot = json.loads(pending['payload'])
        else:
            snapshot = admin.request('POST', '/api/v1/admin/coverage/snapshots', json={}).json()['snapshot']
            prior = db.execute('SELECT * FROM delivery WHERE version=?', (snapshot['snapshot_version'],)).fetchone()
            if prior:
                if json.loads(prior['payload']) != snapshot:
                    raise ValueError('同一快照版本内容改变')
                return {'status': 'unchanged', 'snapshot_version': snapshot['snapshot_version']}
            db.execute('INSERT INTO delivery VALUES(?,?,?,?,?,?,?,?)',
                (snapshot['snapshot_version'], target, encoded(snapshot), 'pending', 0, None, None, now()))
            db.commit()  # Freeze the payload before any request; a crash cannot skip it.
        version = snapshot['snapshot_version']
        db.execute('UPDATE delivery SET attempts=attempts+1,updated_at=? WHERE version=?', (now(), version))
        db.commit()
        try:
            receipt = proposition.request('PUT', '/api/v1/integration/coverage', json=snapshot,
                                           headers={'Idempotency-Key': 'coverage-'+digest(snapshot)}).json()
            if (receipt.get('ok') is not True or type(receipt.get('applied')) is not bool
                    or receipt.get('snapshot') != snapshot):
                raise RuntimeError('覆盖回执未完整确认原始快照')
        except (RuntimeError, ValueError):
            db.execute('UPDATE delivery SET last_error=?,updated_at=? WHERE version=?',
                       ('传输失败或回执不匹配；保留原快照待重试', now(), version))
            db.commit()
            raise
        # "received" deliberately does not claim the upstream business count changed.
        db.execute("UPDATE delivery SET state='received',receipt=?,last_error=NULL,updated_at=? WHERE version=?",
                   (encoded(receipt), now(), version))
        db.commit()
        return {'status': 'received', 'snapshot_version': version,
                'business_application': '待命题组验证 rec_count 已采用该快照'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin', default='http://127.0.0.1:8766')
    sub = parser.add_subparsers(dest='command', required=True)
    student = sub.add_parser('student')
    student.add_argument('--student', required=True)
    student.add_argument('--source-id', required=True)
    student.add_argument('--feed-path', required=True, help='学生组明确交付的管理员变更接口路径')
    coverage = sub.add_parser('coverage')
    coverage.add_argument('--proposition', required=True)
    coverage.add_argument('--state-file', required=True)
    args = parser.parse_args()
    token = os.environ.get('ADMIN_TOKEN')
    if not token:
        parser.error('请通过环境变量 ADMIN_TOKEN 提供管理服务身份')
    if args.command == 'student' and not os.environ.get('STUDENT_SERVICE_TOKEN'):
        parser.error('学生接口需要明确授权的 STUDENT_SERVICE_TOKEN')
    admin = upstream = None
    try:
        admin = Service(args.admin, token)
        if args.command == 'student':
            # Validate before interpolating the source identifier into a route.
            from pydantic import TypeAdapter
            TypeAdapter(ID).validate_python(args.source_id)
            upstream = Service(args.student, os.environ['STUDENT_SERVICE_TOKEN'])
            result = pull_student(admin, upstream, args.source_id, args.feed_path)
        else:
            upstream = Service(args.proposition, os.environ.get('PROPOSITION_SERVICE_TOKEN', ''))
            result = coverage_once(admin, upstream, args.state_file)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, RuntimeError, sqlite3.Error, OSError):
        # Bodies, tokens, source URLs and filesystem details stay out of shared logs.
        parser.exit(1, '交接未确认成功；检查配置、权限、游标或快照回执，原状态保留供重试。\n')
    finally:
        if admin: admin.close()
        if upstream: upstream.close()


if __name__ == '__main__':
    main()
