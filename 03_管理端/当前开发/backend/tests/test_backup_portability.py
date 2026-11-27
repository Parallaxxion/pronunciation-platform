"""Backup portability and file-handle regression tests without an HTTP client."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maintenance
from store import Store


def test_backup_portable_paths_and_sync_state(tmp_path):
    source = Store(tmp_path / 'source')
    audio = b'synthetic original audio fixture'
    digest = source.put_audio(audio, standard=False)['sha256']
    with source.db(write=True) as db:
        db.execute('INSERT INTO sync_sources VALUES(?,?,?)',
                   ('student', 'cursor-1', '2026-11-27T00:00:00Z'))
        db.execute('INSERT INTO sync_events VALUES(?,?,?)',
                   ('student', 'event-1', 'fingerprint-1'))
        db.execute('INSERT INTO sync_batches VALUES(?,?,?,?)',
                   ('student', 'batch-1', 'fingerprint-1', '{"ok":true}'))
    saved, restored = tmp_path / 'saved', tmp_path / 'restored'
    manifest = maintenance.backup(source.root, saved)
    assert set(manifest['files']) == {'management.sqlite3', 'audio/' + digest}
    assert all('\\' not in name for name in manifest['files'])
    assert maintenance.check_backup(saved) == manifest
    maintenance.restore(saved, restored)
    assert (restored / 'audio' / digest).read_bytes() == audio
    with Store(restored).db() as db:
        assert db.execute('SELECT cursor FROM sync_sources').fetchone()[0] == 'cursor-1'
        assert db.execute('SELECT event_id FROM sync_events').fetchone()[0] == 'event-1'
        assert db.execute('SELECT receipt FROM sync_batches').fetchone()[0] == '{"ok":true}'
    manifest['files']['audio\\' + digest] = manifest['files'].pop('audio/' + digest)
    (saved / 'backup.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='非法路径'):
        maintenance.check_backup(saved)


@pytest.mark.parametrize('reject_backup', [False, True])
def test_backup_closes_connections_and_cleans_failed_copy(tmp_path, monkeypatch, reject_backup):
    source = Store(tmp_path / 'source')
    original_connect = sqlite3.connect
    opened = []

    def track_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(maintenance.sqlite3, 'connect', track_connect)
    saved = tmp_path / 'saved'
    if reject_backup:
        def reject(_folder):
            raise ValueError('verification rejected')
        monkeypatch.setattr(maintenance, 'check_backup', reject)
        with pytest.raises(ValueError, match='verification rejected'):
            maintenance.backup(source.root, saved)
        assert not saved.exists()
    else:
        maintenance.backup(source.root, saved)
        database = saved / 'management.sqlite3'
        moved = saved / 'renamed.sqlite3'
        database.rename(moved)
        moved.rename(database)
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            connection.execute('SELECT 1')
