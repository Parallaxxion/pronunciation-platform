"""统计与交付包。维护责任：王阳；2026-11-23 自动化协助补齐，待本人复核。"""
import csv
import hashlib
import io
import json
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from store import Conflict, encoded, now


def capture(store, level=None):
    """One SQLite read transaction fixes metadata; blobs are immutable by hash."""
    with store.db() as db:
        sequence = db.execute('SELECT coalesce(max(id),0) FROM actions').fetchone()[0]
        instance = db.execute("SELECT value FROM settings WHERE key='instance'").fetchone()[0]
        speakers = store.list(db, 'speakers')
        all_speakers = speakers + store.list(db, 'speakers', True)
        questions = store.list(db, 'questions') + store.list(db, 'questions', True)
        recordings = [r for r in store.list(db, 'recordings') if r['upload_status'] == 'uploaded']
        coverage = store.coverage(db)['items']
    if level is not None:
        recordings = [r for r in recordings if r['question_snapshot']['level'] == level]
    return {'snapshot_version': f'{instance}:{sequence:012d}', 'generated_at': now(),
            'filter': {'level': level}, 'speakers': speakers, 'all_speakers': all_speakers,
            'questions': questions, 'recordings': recordings, 'coverage': coverage}


def statistics(snapshot):
    records = snapshot['recordings']
    selected_level = snapshot['filter']['level']
    questions = [q for q in snapshot['questions'] if not q['deleted'] and
                 (selected_level is None or q['level'] == selected_level)]
    backgrounds = {s['speaker_id']: s for s in snapshot['all_speakers']}
    counts = Counter(r['question_id'] for r in records)
    target_unknown = sum(q['target_recordings'] is None for q in questions)
    by_level = []
    for level in range(1, 10):
        if selected_level is not None and selected_level != level:
            continue
        rows = [r for r in records if r['question_snapshot']['level'] == level]
        level_questions = [q for q in questions if q['level'] == level]
        by_level.append({'level': level, 'recording_count': len(rows),
                         'unique_speaker_count': len({r['speaker_id'] for r in rows}),
                         'active_question_count': len(level_questions)})
    def background_counts(field):
        counts = Counter(backgrounds[r['speaker_id']][field] or '未填写' for r in records)
        return [{'value': key, 'recording_count': value} for key, value in sorted(counts.items())]
    covered = {r['question_id'] for r in records}
    coverage = [{'question_id':q['question_id'], 'recording_count':counts[q['question_id']],
                 'unique_speaker_count':len({r['speaker_id'] for r in records if r['question_id']==q['question_id']}),
                 'target_recordings':q['target_recordings'],
                 'gap':None if q['target_recordings'] is None else max(0,q['target_recordings']-counts[q['question_id']])}
                for q in questions]
    return {'snapshot_version': snapshot['snapshot_version'], 'generated_at': snapshot['generated_at'],
            'filter': snapshot['filter'], 'counting_policy': 'uploaded_not_deleted_distinct_recording_id',
            'known_active_speakers': len(snapshot['speakers']),
            'registered_user_total': None,
            'registered_user_total_note': '学生注册总数尚未接通；known_active_speakers 仅为管理端已导入的活动说话人',
            'recording_count': len(records), 'unique_speaker_count': len({r['speaker_id'] for r in records}),
            'active_question_count': len(questions),
            'covered_active_question_count': sum(q['question_id'] in covered for q in questions),
            'known_target_gap': sum(max(0, q['target_recordings']-counts[q['question_id']])
                                    for q in questions if q['target_recordings'] is not None),
            'target_unknown_question_count': target_unknown,
            'total_gap': None if target_unknown else sum(max(0, q['target_recordings']-counts[q['question_id']]) for q in questions),
            'coverage':{'items':coverage},
            'known_speakers_by_level':dict(sorted(Counter(s['level'] for s in snapshot['speakers']).items())),
            'by_level': by_level, 'by_nationality': background_counts('nationality'),
            'by_language': background_counts('language'),
            'by_diagnosis': dict(sorted(Counter(r['diagnosis']['status'] if r['diagnosis_available'] else 'unavailable' for r in records).items())),
            'by_data_source': dict(sorted(Counter(r['data_source'] for r in records).items()))}


def csv_bytes(rows):
    fields = ['recording_id','speaker_id','question_id','practice_session_id','take_no','recorded_at',
              'level','display_text','diagnosis_status','diagnosis_available','data_source','note',
              'wav_path','original_path','wav_sha256','original_sha256']
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        flat = {key: row.get(key, '') for key in fields}
        flat.update(level=row['question_snapshot']['level'], display_text=row['question_snapshot']['display_text'],
                    diagnosis_status=row['diagnosis']['status'])
        # Spreadsheet formula protection. JSONL remains exact and is the canonical machine input.
        flat = {key: "'"+value if isinstance(value, str) and value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
                for key, value in flat.items()}
        writer.writerow(flat)
    return ('\ufeff'+stream.getvalue()).encode('utf-8')


def export_bundle(store, level=None):
    snapshot = capture(store, level)
    rows = []
    expected = {}
    for record in snapshot['recordings']:
        row = dict(record)
        for variant in ('wav', 'original'):
            digest = row[variant+'_sha256']
            path = f'{variant}/{digest}' + ('.wav' if variant == 'wav' else '.bin')
            row[variant+'_path'] = path
            expected[path] = digest
        rows.append(row)
    fd, filename = tempfile.mkstemp(prefix='management-export-', suffix='.zip', dir=store.root)
    import os
    os.close(fd)
    os.chmod(filename, 0o600)
    checksums = {}
    try:
        with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path, digest in sorted(expected.items()):
                source = store.audio / digest
                if not source.is_file():
                    raise Conflict('导出中止：存在缺失音频，请修复后重试')
                hasher = hashlib.sha256()
                with source.open('rb') as incoming, archive.open(path, 'w') as outgoing:
                    while chunk := incoming.read(1024*1024):
                        hasher.update(chunk)
                        outgoing.write(chunk)
                if hasher.hexdigest() != digest:
                    raise Conflict('导出中止：音频校验失败，请恢复授权原文件')
                checksums[path] = digest
            related = {r['speaker_id'] for r in rows}
            payloads = {
                'manifest.jsonl': ''.join(encoded(r)+'\n' for r in rows).encode(),
                'manifest.csv': csv_bytes(rows),
                'speakers.json': encoded([s for s in snapshot['all_speakers'] if s['speaker_id'] in related]).encode(),
                'annotations.jsonl': ''.join(encoded({'recording_id':r['recording_id'], 'available':r['diagnosis_available'],
                                                       'diagnosis':r['diagnosis']})+'\n' for r in rows).encode(),
                'statistics.json': encoded(statistics(snapshot)).encode(),
                'export.json': encoded({'schema_version':'management-export-v1', 'snapshot_version':snapshot['snapshot_version'],
                                         'generated_at':snapshot['generated_at'], 'filter':snapshot['filter'],
                                         'recording_count':len(rows), 'scope':'uploaded_not_deleted',
                                         'csv_note':'CSV 对公式前缀加单引号；机器处理请读取保留原值的 manifest.jsonl',
                                         'audio_note':'相同内容按 SHA256 复用文件；录音次数仍按 recording_id 独立统计'}).encode()}
            for name, data in payloads.items():
                archive.writestr(name, data)
                checksums[name] = hashlib.sha256(data).hexdigest()
            archive.writestr('checksums.json', encoded(checksums))
        return Path(filename)
    except BaseException:
        Path(filename).unlink(missing_ok=True)
        raise
