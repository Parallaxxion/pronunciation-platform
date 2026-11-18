import hashlib,json,wave
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'samples/algorithm-kit'
rows=[json.loads(l) for l in (root/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
ids=set()
for row in rows:
 if row['recording_id'] in ids:raise ValueError('重复录音ID')
 ids.add(row['recording_id'])
 for key in ('audio_path','original_path'):
  p=(root/row[key]).resolve()
  if root.resolve() not in p.parents or not p.is_file():raise ValueError('路径越界或文件缺失')
 p=root/row['audio_path']
 if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('音频哈希不一致')
 with wave.open(str(p),'rb') as w:
  if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2) or w.getnframes()==0:raise ValueError('音频规格错误')
 if row['gold_errors'] is not None or row['dataset_role']!='format_integration_only':raise ValueError('样例用途标记错误')
print(f'PASS {len(rows)}条合成WAV：ID、路径、哈希、16kHz/mono/16bit和用途一致')
