"""Read ZIP in place; never extract untrusted paths. Responsibility: 王阳."""
import argparse
import csv
import hashlib
import io
import json
import wave
import zipfile
from pathlib import PurePosixPath

from contracts import normalize_diagnosis


def verify(path):
    if not __debug__:
        raise ValueError('请勿使用 python -O 运行校验工具')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)), '重复 ZIP 路径'
        assert all(not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts and '\\' not in n for n in names), '非法 ZIP 路径'
        assert sum(i.file_size for i in archive.infolist()) <= 2*1024**3, '校验工具单包上限 2 GiB'
        checksums = json.loads(archive.read('checksums.json'))
        assert set(names) == set(checksums) | {'checksums.json'}, '文件清单不一致'
        for name, expected in checksums.items():
            digest = hashlib.sha256()
            with archive.open(name) as stream:
                while chunk := stream.read(1024*1024): digest.update(chunk)
            assert digest.hexdigest() == expected, f'哈希错误：{name}'
        metadata = json.loads(archive.read('export.json'))
        assert metadata['schema_version'] == 'management-export-v1'
        rows = [json.loads(line) for line in archive.read('manifest.jsonl').decode().splitlines()]
        annotations = [json.loads(line) for line in archive.read('annotations.jsonl').decode().splitlines()]
        speakers = json.loads(archive.read('speakers.json'))
        ids = [r['recording_id'] for r in rows]
        assert len(ids) == len(set(ids)) == metadata['recording_count'], '录音数或唯一性不一致'
        assert len(annotations) == len(rows) and {a['recording_id'] for a in annotations} == set(ids), '标注关联错误'
        assert {r['speaker_id'] for r in rows} == {s['speaker_id'] for s in speakers}, '说话人关联错误'
        csv_rows = list(csv.DictReader(io.StringIO(archive.read('manifest.csv').decode('utf-8-sig'))))
        assert [r['recording_id'] for r in csv_rows] == ids, 'CSV 关联错误'
        stats = json.loads(archive.read('statistics.json'))
        assert stats['snapshot_version'] == metadata['snapshot_version'] and stats['recording_count'] == len(rows), '统计快照不一致'
        annotation_map = {a['recording_id']:a for a in annotations}
        for row in rows:
            assert not row['deleted'] and row['upload_status'] == 'uploaded', '范围不符'
            assert row['question_id'] == row['question_snapshot']['question_id'], '题目快照不符'
            for variant in ('wav','original'):
                assert checksums[row[variant+'_path']] == row[variant+'_sha256'], '音频引用不符'
            with wave.open(io.BytesIO(archive.read(row['wav_path'])), 'rb') as wav:
                assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth(),wav.getcomptype()) == (16000,1,2,'NONE'), 'WAV 格式错误'
                assert wav.getnframes() > 0 and len(wav.readframes(wav.getnframes())) == wav.getnframes()*2, 'WAV 截断'
            ann = annotation_map[row['recording_id']]
            assert ann['diagnosis'] == row['diagnosis'] and ann['available'] == row['diagnosis_available'], '诊断版本不符'
            normalize_diagnosis(row['diagnosis'], row['question_snapshot'])
        return {'ok':True, 'recording_count':len(rows), 'file_count':len(names),
                'snapshot_version':metadata['snapshot_version']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='校验管理端导出包（2 GiB 以内）')
    parser.add_argument('zip')
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.zip), ensure_ascii=False, indent=2))
    except (AssertionError, ValueError, KeyError, OSError, zipfile.BadZipFile, wave.Error) as error:
        parser.exit(1, f'校验失败：{error}\n')
