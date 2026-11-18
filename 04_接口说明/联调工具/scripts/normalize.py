"""Normalize a locally obtained authorized JSON response. No network or credentials."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integration.adapters import question_list, normalize_question, normalize_diagnosis
p=argparse.ArgumentParser()
p.add_argument('kind',choices=['questions','diagnosis'])
p.add_argument('input',type=Path)
p.add_argument('--question',type=Path)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
data=json.loads(a.input.read_text(encoding='utf-8'))
if a.kind=='questions': result={'items':question_list(data)}
else:
 if a.question is None: p.error('diagnosis需要--question')
 q=normalize_question(json.loads(a.question.read_text(encoding='utf-8')))
 result=normalize_diagnosis(data,q)
a.output.parent.mkdir(parents=True,exist_ok=True)
a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(a.output)
