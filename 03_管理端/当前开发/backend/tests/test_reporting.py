import io
import json
import zipfile

import pytest

from test_management import client, seed, write, AUTH, VIEWER, PREFIX, S, Q
from reporting import capture, statistics, export_bundle
from verify_export import verify


def stats(client, suffix=''):
    response = client.get(PREFIX+'/statistics'+suffix, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_and_unknown_targets(client):
    assert stats(client)['recording_count'] == 0
    seed(client)
    value = stats(client)
    assert value['recording_count'] == value['unique_speaker_count'] == value['known_active_speakers'] == 1
    assert value['registered_user_total'] is None
    assert value['total_gap'] is None and value['target_unknown_question_count'] == 1
    assert value['by_diagnosis'] == {'unavailable':1}


def test_counts_retake_replay_delete_undo_and_filter(client):
    recording, _ = seed(client)
    assert write(client, '/recordings', recording).json()['duplicate']
    second = {**recording, 'recording_id':'R-002', 'take_no':2}
    assert write(client, '/recordings', second).status_code == 200
    assert stats(client)['recording_count'] == 2 and stats(client)['unique_speaker_count'] == 1
    assert stats(client,'?level=2')['recording_count'] == 0
    action = write(client,'/recordings/R-001', {'expected_version':1}, 'DELETE').json()
    assert stats(client)['recording_count'] == 1
    assert write(client, f'/actions/{action["action_id"]}/undo').status_code == 200
    assert stats(client)['recording_count'] == 2
    assert write(client, '/questions/L1-001', {'expected_version':1,'question':{**Q,'target_recordings':3}}, 'PUT').status_code == 200
    assert stats(client)['total_gap'] == 1
    assert write(client,'/speakers/S-001', {'expected_version':1}, 'DELETE').status_code == 200
    assert stats(client)['known_active_speakers'] == 0 and stats(client)['recording_count'] == 2


def test_snapshot_stays_fixed_after_changes(client):
    seed(client)
    snapshot = capture(client.app.state.store)
    write(client,'/recordings/R-001', {'expected_version':1}, 'DELETE')
    assert statistics(snapshot)['recording_count'] == 1 and stats(client)['recording_count'] == 0


@pytest.mark.parametrize('path', ['/statistics','/export'])
def test_reports_require_auth(client, path):
    assert client.get(PREFIX+path).status_code == 401


def test_viewer_cannot_bulk_export(client):
    assert client.get(PREFIX+'/export',headers=VIEWER).status_code == 403
    assert client.get(PREFIX+'/statistics',headers=VIEWER).status_code == 200


def test_export_exact_metadata_and_formula_safety(client, tmp_path):
    seed(client)
    write(client,'/recordings/R-001',{'expected_version':1,'note':'=HYPERLINK("https://example.invalid")'},'PUT')
    response = client.get(PREFIX+'/export', headers=AUTH)
    assert response.status_code == 200
    path = tmp_path/'result.zip'
    path.write_bytes(response.content)
    assert verify(path)['recording_count'] == 1
    with zipfile.ZipFile(path) as archive:
        row = json.loads(archive.read('manifest.jsonl'))
        assert row['note'].startswith('=HYPERLINK')
        assert "'=HYPERLINK" in archive.read('manifest.csv').decode('utf-8-sig')
        assert row['question_snapshot']['display_text'] == '我，你。'
    assert not list(client.app.state.store.root.glob('management-export-*.zip'))


@pytest.mark.parametrize('damage',['missing','changed'])
def test_export_never_silently_skips_bad_audio(client, damage):
    recording, _ = seed(client)
    path = client.app.state.store.audio/recording['wav_sha256']
    if damage == 'missing': path.unlink()
    else: path.write_bytes(b'broken')
    assert client.get(PREFIX+'/export',headers=AUTH).status_code == 409
    assert not list(client.app.state.store.root.glob('management-export-*.zip'))


def test_empty_filtered_export_and_tamper(client, tmp_path):
    seed(client)
    path = export_bundle(client.app.state.store, 2)
    assert verify(path)['recording_count'] == 0
    tampered = tmp_path/'bad.zip'
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(tampered,'w') as target:
        for name in source.namelist():
            target.writestr(name, b'changed' if name == 'speakers.json' else source.read(name))
    with pytest.raises(AssertionError,match='哈希'): verify(tampered)
    path.unlink()
