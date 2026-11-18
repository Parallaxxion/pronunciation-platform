"""Verify immutable imports, handoff archives, and maintained public navigation."""
import hashlib,json,re,zipfile
from pathlib import Path
from urllib.parse import unquote
root=Path(__file__).resolve().parents[3]
evidence=root/'05_相关材料/来源与核验'
manifest=json.loads((evidence/'导入文件清单.json').read_text(encoding='utf-8'))
for entry in manifest:
 path=root/entry['path']
 if not path.is_file() or path.stat().st_size!=entry['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
  raise ValueError('固定来源归档发生变化: '+entry['path'])
packages=root/'05_相关材料/交接压缩包'
for row in (packages/'SHA256SUMS').read_text().splitlines():
 digest,name=row.split('  ',1);path=packages/name
 if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('交接包校验不一致: '+name)
 with zipfile.ZipFile(path) as archive:
  if archive.testzip() is not None:raise ValueError('ZIP损坏: '+name)
# Imported READMEs retain historical claims/paths; check newly maintained navigation.
checked=0
for path in root.rglob('*.md'):
 relative=path.relative_to(root)
 if '.git' in relative.parts or '成果快照' in relative.parts or 'local-data' in relative.parts:continue
 if '当前开发' in relative.parts and relative.as_posix()!='03_管理端/当前开发/README.md':continue
 for link in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
  if '://' in link or link.startswith(('#','mailto:')):continue
  target=unquote(link.split('#')[0])
  if not (path.parent/target).exists():raise ValueError(f'文档链接不存在: {relative} -> {link}')
 checked+=1
print(f'PASS {len(manifest)}个原始归档文件完整，交接包哈希与{checked}份维护文档导航有效；当前开发可正常迭代')
