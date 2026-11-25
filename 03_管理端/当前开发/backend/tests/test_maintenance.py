import sqlite3
import pytest
from test_management import client, seed
from maintenance import backup, restore, check_backup
from store import Store


def test_backup_restore_rehearsal(client,tmp_path):
    seed(client)
    source = client.app.state.store.root
    saved, restored = tmp_path.parent/(tmp_path.name+'-backup'), tmp_path.parent/(tmp_path.name+'-restored')
    backup(source,saved)
    assert check_backup(saved)['schema'] == 'management-backup-v1'
    restore(saved,restored)
    store=Store(restored)
    with store.db() as db:
        assert store.get(db,'recordings','R-001')['recording_id']=='R-001'
        assert len(store.coverage(db)['items'])==1
    with pytest.raises(FileExistsError): restore(saved,restored)
    (saved/'management.sqlite3').write_bytes(b'broken')
    with pytest.raises(ValueError,match='校验失败'): check_backup(saved)


def test_backup_missing_source_does_not_initialize_it(tmp_path):
    source=tmp_path/'absent'
    with pytest.raises(ValueError): backup(source,tmp_path/'backup')
    assert not source.exists()
