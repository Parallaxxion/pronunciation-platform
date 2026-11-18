from pathlib import Path
import hashlib,zipfile
root=Path(__file__).resolve().parents[1];out=root/'packages';out.mkdir(exist_ok=True)
configs=[('frontend-handoff-20261118.zip',root/'shared/ui'),('algorithm-format-kit-20261118.zip',root/'samples/algorithm-kit')]
checks=[]
for name,source in configs:
 target=out/name
 with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
  for f in sorted(source.rglob('*')):
   if not f.is_file() or '__pycache__' in f.parts:continue
   info=zipfile.ZipInfo(f.relative_to(source).as_posix(),date_time=(2026,11,18,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,f.read_bytes())
 checks.append(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+name)
 print(name,target.stat().st_size)
(out/'SHA256SUMS').write_text('\n'.join(checks)+'\n',encoding='utf-8')
