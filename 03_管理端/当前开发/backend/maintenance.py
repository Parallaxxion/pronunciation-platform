"""Private, consistent backup/restore. Responsibility: 王阳; assisted implementation."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from store import Store, encoded, now


def digest_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_backup(folder):
    folder = Path(folder)
    manifest = json.loads((folder/'backup.json').read_text())
    if manifest['schema'] != 'management-backup-v1':
        raise ValueError('备份版本不支持')
    expected = manifest['files']
    if not isinstance(expected, dict) or 'management.sqlite3' not in expected:
        raise ValueError('备份清单不完整')
    for name, digest in expected.items():
        if name != 'management.sqlite3' and not (name.startswith('audio/') and len(name) == 70 and
                                                 all(c in '0123456789abcdef' for c in name[6:])):
            raise ValueError('备份清单含非法路径')
        if digest_file(folder/name) != digest:
            raise ValueError('备份校验失败：'+name)
    with sqlite3.connect(f'{(folder/"management.sqlite3").resolve().as_uri()}?mode=ro', uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('数据库完整性校验失败')
        for digest, size in db.execute('SELECT sha256,size FROM blobs'):
            path = folder/'audio'/digest
            if expected.get('audio/'+digest) != digest or path.stat().st_size != size:
                raise ValueError('数据库与音频清单不符')
    return manifest


def backup(data_dir, destination):
    root, destination = Path(data_dir).resolve(), Path(destination).resolve()
    if not (root/'management.sqlite3').is_file():
        raise ValueError('源数据库不存在')
    if destination == root or root in destination.parents:
        raise ValueError('备份目录必须在数据目录外')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        (destination/'audio').mkdir(mode=0o700)
        store = Store(root)
        with store.db() as db:
            blobs = db.execute('SELECT sha256 FROM blobs').fetchall()
            with sqlite3.connect(destination/'management.sqlite3') as output:
                db.backup(output)
            for row in blobs:
                shutil.copyfile(store.audio/row['sha256'], destination/'audio'/row['sha256'])
        files = {str(path.relative_to(destination)):digest_file(path)
                 for path in destination.rglob('*') if path.is_file()}
        for name in files: os.chmod(destination/name, 0o600)
        (destination/'backup.json').write_text(encoded({'schema':'management-backup-v1',
                                                       'created_at':now(), 'files':files}), encoding='utf-8')
        os.chmod(destination/'backup.json', 0o600)
        return check_backup(destination)
    except BaseException:
        shutil.rmtree(destination)
        raise


def restore(source, destination):
    manifest = check_backup(source)
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        (destination/'audio').mkdir(mode=0o700)
        for name in manifest['files']:
            shutil.copyfile(Path(source)/name, destination/name)
            os.chmod(destination/name, 0o600)
        return {'restored':True, 'files':len(manifest['files'])}
    except BaseException:
        shutil.rmtree(destination)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='管理数据备份/校验/恢复；不包含认证文件或访问令牌')
    parser.add_argument('operation',choices=['backup','verify','restore'])
    parser.add_argument('source')
    parser.add_argument('destination',nargs='?')
    args = parser.parse_args()
    if args.operation != 'verify' and not args.destination:
        parser.error('需要一个尚不存在的目标目录')
    try:
        result = check_backup(args.source) if args.operation == 'verify' else (
            backup(args.source,args.destination) if args.operation == 'backup' else restore(args.source,args.destination))
        print(json.dumps({'ok':True,'operation':args.operation,'file_count':len(result.get('files',{})) if isinstance(result.get('files',{}),dict) else result['files']},ensure_ascii=False))
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1,f'操作失败：{error}\n')
