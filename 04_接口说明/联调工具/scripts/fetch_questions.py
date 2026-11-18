"""Read the proposition API and normalize; never publishes questions or alters counts."""
import argparse,json,sys,urllib.request,urllib.parse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integration.adapters import question_list
p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--level',type=int,default=1);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
u=urllib.parse.urlsplit(a.base)
if u.scheme not in ('http','https') or u.username or u.password or u.query or u.fragment:p.error('base仅允许无凭证的HTTP(S)基础地址')
url=a.base.rstrip('/')+'/api/questions?'+urllib.parse.urlencode({'level':a.level,'status':'published'})
with urllib.request.urlopen(url,timeout=15) as r:data=json.load(r)
items=question_list(data)
if any(q['status']!='published' for q in items):raise ValueError('上游返回了未发布题目')
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'items':items},ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(f'已读取 {len(items)} 道已发布题目；{a.output}')
