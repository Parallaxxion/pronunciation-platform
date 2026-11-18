"""Verify imported snapshot completeness and public handoff integrity."""
import hashlib,json,re,subprocess,zipfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'evidence/导入文件清单.json').read_text(encoding='utf-8'))
for e in manifest:
 p=root/e['path']
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=e['sha256']:raise ValueError('导入快照发生变化，请更新来源说明和清单: '+e['path'])
for row in (root/'packages/SHA256SUMS').read_text().splitlines():
 digest,name=row.split('  ',1);p=root/'packages'/name
 if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('交接包校验不一致')
 with zipfile.ZipFile(p) as z:
  if z.testzip() is not None:raise ValueError('ZIP损坏')
for p in [root/'README.md',root/'CONTRIBUTING.md',*list((root/'docs').glob('*.md'))]:
 for link in re.findall(r'\]\(([^)]+)\)',p.read_text(encoding='utf-8')):
  if '://' in link or link.startswith('#'):continue
  if not (p.parent/link.split('#')[0]).exists():raise ValueError('文档链接不存在: '+link)
print(f'PASS {len(manifest)}个源文件完整，交接包哈希与公共导航有效')
