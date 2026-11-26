"""Export a local review page; import downloaded decisions without changing originals."""
import argparse,json,html
from pathlib import Path
from .benchmark import rows,dump
def main():
    p=argparse.ArgumentParser();p.add_argument('folder');p.add_argument('--decisions');a=p.parse_args()
    folder=Path(a.folder).resolve();data=rows(folder/'candidates.jsonl')
    if a.decisions:
        decisions=json.loads(Path(a.decisions).read_text(encoding='utf-8-sig'))
        mapping={x['sample_id']:x for x in decisions}
        if len(mapping)!=len(decisions) or set(mapping)!=set(r['sample_id'] for r in data):raise ValueError('Review IDs mismatch')
        verified=[]
        for r in data:
            d=mapping[r['sample_id']]
            if d.get('approved') is not True:continue
            if not isinstance(d.get('text'),str) or not d['text'].strip():raise ValueError('Empty approved text')
            r.update(reference_text=d['text'].strip(),reference_verified=True,target_text=d['text'].strip())
            verified.append(r)
        if not verified:raise ValueError('No approved samples')
        path=folder/'verified.jsonl'
        if path.exists():raise FileExistsError('verified.jsonl exists; preserve it before revising')
        path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in verified),encoding='utf-8')
        print('Verified',len(verified),path);return
    payload=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
    page="""<!doctype html><meta charset="utf-8"><title>录音文本复核</title>
<style>body{font:16px sans-serif;max-width:1000px;margin:32px auto;background:#f6f8fa}article{background:white;padding:18px;margin:16px 0;border:1px solid #ddd}textarea{width:95%;height:70px}audio{display:block;margin:12px 0}button{padding:12px}small{display:block;color:#555}</style>
<h1>录音文本复核</h1><p>逐条回听，修正“实际说出的文字”，仅在确认文本与切片一致后勾选。切分残缺、不确定的样本不要勾选。这里不代表发音无偏误。</p>
<p>页面不自动保存；离开前点击“导出复核结果”。保留原始候选表。</p><button id="export">导出复核结果</button><div id="items"></div>
<script>const data=PAYLOAD;const decisions=[];
for(const r of data){const e=document.createElement('article');const h=document.createElement('b');h.textContent=r.sample_id+' / 等级 '+r.level;e.append(h);
const note=document.createElement('small');note.textContent='原审核：'+r.source_status+'；备注：'+(r.review_note||'无');e.append(note);
const audio=document.createElement('audio');audio.controls=true;audio.src=r.audio_path;e.append(audio);
const text=document.createElement('textarea');text.value=r.reference_text;e.append(text);
const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';label.append(check,' 已回听并确认文本');e.append(label);
decisions.push({r,text,check});document.getElementById('items').append(e);}
document.getElementById('export').onclick=()=>{const result=decisions.map(({r,text,check})=>({sample_id:r.sample_id,text:text.value,approved:check.checked}));
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));a.download='review-decisions.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);};</script>"""
    (folder/'复核页面.html').write_text(page.replace('PAYLOAD',payload),encoding='utf-8')
    print(folder/'复核页面.html')
if __name__=='__main__':main()
