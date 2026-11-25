"""Run from backend: python -m app.benchmark prepare/run/compare. No UI/DB mutations."""
import argparse,csv,hashlib,json,os,platform,re,sys,time,zipfile
from pathlib import Path
from dataclasses import asdict
from collections import Counter
from importlib.metadata import version,PackageNotFoundError
from .services.asr_backends import ASRConfig,DEFAULTS,Recognizer
from .services.audio import to_wav,wav_duration_ms
from .services.diagnosis import diagnose,hanzi

def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def rows(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8-sig').splitlines() if x.strip()]
def cer_text(s):
    # Explicit policy: NFKC; lowercase; punctuation/spacing removed; numbers/Latin retained.
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKC',s).lower() if c.isalnum())
def distance(a,b):
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1): cur.append(min(cur[-1]+1,prev[j]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]
def event_key(e):
    t=e['type']
    return (t,e.get('boundary_index') if t=='insertion' else e.get('char_index'))
def validate_sample(r):
    if not r.get('sample_id') or not r.get('audio_path'): raise ValueError('Missing sample_id/audio_path')
    if r.get('reference_verified') is not True: raise ValueError('Reference not human verified: '+r['sample_id'])
    if not cer_text(r.get('reference_text','')): raise ValueError('Missing reference_text')
    gold=r.get('gold_errors')
    if gold is not None:
        if not isinstance(gold,list) or r.get('gold_verified') is not True: raise ValueError('Gold requires list + gold_verified=true')
        n=len(hanzi(r.get('target_text','')))
        if not n: raise ValueError('Gold needs target_text')
        keys=[]
        for e in gold:
            if e.get('type') not in ('tone','substitution','omission','insertion'): raise ValueError('Unknown gold error type')
            t,k=event_key(e)
            if type(k) is not int or not 0<=k<(n+1 if t=='insertion' else n): raise ValueError('Gold index out of range')
            keys.append((t,k))
        if len(set(keys))!=len(keys): raise ValueError('Merge same-boundary insertions / duplicate gold events')
def prepare(a):
    import openpyxl
    src=Path(a.source);out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    lookup={};zs=[]
    for p in sorted(src.rglob('*.zip')):
        try: z=zipfile.ZipFile(p)
        except zipfile.BadZipFile: continue
        zs.append(z)
        for n in z.namelist():
            if n.lower().endswith('.wav'): lookup.setdefault(Path(n).name,[]).append((z,n))
    candidates=[];excluded=Counter()
    try:
        for p in sorted((src/'数据标注').glob('*.xlsx')):
            w=openpyxl.load_workbook(p,data_only=True,read_only=True)
            for s in w:
                it=iter(s.values);head=next(it,())
                if 'sample_id' not in head: continue
                for row in it:
                    r=dict(zip(head,row))
                    if not r.get('sample_id'): continue
                    reason=None
                    if r.get('status')!='通过': reason='not_passed'
                    elif r.get('role') not in ('题干朗读','对话','短文材料','提问','判断句','采访对话'): reason='prompt_or_number'
                    elif not 1<=float(r.get('duration_s') or 0)<=30: reason='duration'
                    elif not hanzi(str(r.get('text') or '')): reason='no_chinese'
                    elif r.get('text_review_status') in ('unreliable_placeholder','needs_review'): reason='unreliable_text'
                    if reason: excluded[reason]+=1;continue
                    candidates.append((p,s.title,r))
            w.close()
        seen=set();chosen=[]
        # Round-robin levels for a small balanced candidate set; exclude duplicate sentence text.
        groups={}
        for item in candidates: groups.setdefault(item[2]['level'],[]).append(item)
        while groups and len(chosen)<a.limit:
            for level in list(groups):
                if not groups[level]: del groups[level];continue
                p,s,r=groups[level].pop(0);key=cer_text(r['text'])
                if key in seen: excluded['duplicate_text']+=1;continue
                matches=lookup.get(r['audio_file'],[])
                match=None
                for z,n in matches:
                    b=z.read(n)
                    if hashlib.sha256(b).hexdigest()==r.get('audio_sha256'): match=b;break
                if match is None: excluded['missing_or_hash_mismatch']+=1;continue
                sid=r['sample_id']
                if not re.fullmatch(r'[A-Za-z0-9_-]+',sid): raise ValueError('Unsafe sample ID')
                dest=out/'audio'/f'{sid}.wav';dest.parent.mkdir(exist_ok=True);dest.write_bytes(match)
                chosen.append(dict(sample_id=sid,audio_path='audio/'+dest.name,reference_text=r['text'],
                    reference_verified=False,target_text=r['text'],gold_errors=None,gold_verified=False,
                    group_id=r['exam_key']+':'+str(r['question_no']),level=level,
                    source_workbook=str(p),source_sheet=s,source_status=r.get('status'),
                    source_text_review_status=r.get('text_review_status'),review_note=r.get('review_note'),
                    source_sha256=r['audio_sha256']))
                seen.add(key)
                if len(chosen)>=a.limit: break
        with (out/'candidates.jsonl').open('w',encoding='utf-8') as f:
            for r in chosen:f.write(json.dumps(r,ensure_ascii=False)+'\n')
        dump(out/'preparation.json',dict(selected=len(chosen),excluded=dict(excluded),notice='Candidates only; reference_verified=false; do not invent gold_errors=[]'))
        print('Prepared',len(chosen),'candidates at',out)
    finally:
        for z in zs:z.close()
def run(a):
    manifest=Path(a.manifest).resolve();data=rows(manifest)
    if not data:raise ValueError('Empty manifest')
    ids=[r['sample_id'] for r in data]
    if len(set(ids))!=len(ids):raise ValueError('Duplicate sample IDs')
    for r in data:
        validate_sample(r)
        if not (manifest.parent/r['audio_path']).is_file():raise FileNotFoundError(r['audio_path'])
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    cfg=ASRConfig(a.backend,a.model or DEFAULTS[a.backend],a.device,a.compute_type,a.revision)
    packages={}
    for name in ('faster-whisper','funasr','torch','pypinyin','ctranslate2'):
        try:packages[name]=version(name)
        except PackageNotFoundError:pass
    meta=dict(config=asdict(cfg),python=sys.version,platform=platform.platform(),packages=packages,
              manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
              normalization='NFKC lowercase alphanumeric; no simplified/traditional or numeral conversion',
              algorithm='weighted-dp-v2;text-proxy',time=time.strftime('%Y-%m-%dT%H:%M:%S'),
              audio_sha256={r['sample_id']:hashlib.sha256((manifest.parent/r['audio_path']).read_bytes()).hexdigest() for r in data})
    dump(out/'run_config.json',meta)
    start=time.perf_counter()
    try:model=Recognizer(cfg)
    except Exception as e:
        dump(out/'load_error.json',dict(error=str(e),elapsed_s=time.perf_counter()-start));raise
    meta['load_seconds']=time.perf_counter()-start;dump(out/'run_config.json',meta)
    results=[];total_edits=total_chars=0;gold_rows=0;failed_gold=0;tp=Counter();fp=Counter();fn=Counter();clean=clean_fp=0
    elapsed=duration=0.
    with (out/'predictions.jsonl').open('w',encoding='utf-8') as f:
        for r in data:
            rec=dict(sample_id=r['sample_id'],reference_text=r['reference_text'],status='failed')
            gold=r.get('gold_errors')
            if gold is not None:gold_rows+=1
            try:
                wav=out/'wav16k'/f"{len(results):05d}.wav";wav.parent.mkdir(exist_ok=True)
                to_wav(manifest.parent/r['audio_path'],wav)
                seconds=wav_duration_ms(wav)/1000
                t=time.perf_counter();hyp=model.transcribe(wav);dt=time.perf_counter()-t
                if not cer_text(hyp):raise RuntimeError('Empty transcript')
                ref=cer_text(r['reference_text']);edits=distance(ref,cer_text(hyp))
                total_edits+=edits;total_chars+=len(ref);elapsed+=dt;duration+=seconds
                rec.update(status='ok',recognized_text=hyp,edits=edits,reference_chars=len(ref),asr_seconds=dt,duration_seconds=seconds)
                try:
                    diag=diagnose(wav,r.get('target_text') or r['reference_text'],r.get('tokens'),hypothesis=hyp,config=cfg)
                    diag['evidence_kind']='asr_text_proxy';rec['diagnosis']=diag
                except Exception as e:rec['diagnosis_error']=str(e)
                if gold is not None:
                    if 'diagnosis' not in rec: failed_gold+=1
                    else:
                        predicted=set(map(event_key,rec['diagnosis']['errors']));expected=set(map(event_key,gold))
                        for typ,idx in predicted&expected:tp[typ]+=1
                        for typ,idx in predicted-expected:fp[typ]+=1
                        for typ,idx in expected-predicted:fn[typ]+=1
                        if not gold:clean+=1;clean_fp+=bool(predicted)
            except Exception as e:
                rec['error']=str(e)
                if gold is not None:failed_gold+=1
            results.append(rec);f.write(json.dumps(rec,ensure_ascii=False)+'\n');f.flush()
            print(rec['sample_id'],rec['status'],flush=True)
    types={}
    for typ in ('tone','substitution','omission','insertion'):
        t,p,n=tp[typ],fp[typ],fn[typ]
        types[typ]=dict(tp=t,fp=p,fn=n,precision=t/(t+p) if t+p else None,recall=t/(t+n) if t+n else None,
                       f1=2*t/(2*t+p+n) if 2*t+p+n else None)
    summary=dict(total=len(data),successful=sum(r['status']=='ok' for r in results),failed=sum(r['status']!='ok' for r in results),
                 cer_success_only=total_edits/total_chars if total_chars else None,
                 rtf_success_only=elapsed/duration if duration else None,gold_samples=gold_rows,gold_failed=failed_gold,
                 error_metrics_success_only=types if gold_rows else None,
                 clean_false_alarm_rate=clean_fp/clean if clean else None,
                 warning='Failures reported separately. No gold means NO pronunciation accuracy. Tone is text proxy, not acoustics.')
    dump(out/'summary.json',summary)
    (out/'报告.md').write_text('# 模型评测结果\n\n仅对成功样本计算CER/RTF；必须同时报告失败数。无人工偏误金标，不报告诊断准确率。\n\n'+
        '```json\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    if summary['failed']:raise SystemExit(2)
def compare(a):
    items=[]
    for p in a.runs:
        p=Path(p);cfg=json.loads((p/'run_config.json').read_text());s=json.loads((p/'summary.json').read_text())
        items.append((p,cfg,s))
    if len({x[1]['manifest_sha256'] for x in items})!=1 or any(x[1]['audio_sha256']!=items[0][1]['audio_sha256'] for x in items):raise ValueError('Different manifest/audio; comparison rejected')
    lines=['# 模型对比','', '失败率不同会影响成功样本CER，不据此自动排名。声调指标仅为文本代理。','',
           '| 模型 | 成功/总数 | 失败 | CER（成功样本） | RTF（成功样本） | 人工偏误标注数 |',
           '|---|---:|---:|---:|---:|---:|']
    for p,c,s in items:
        lines.append(f"| {c['config']['backend']} / {c['config']['model']} | {s['successful']}/{s['total']} | {s['failed']} | {s['cer_success_only']} | {s['rtf_success_only']} | {s['gold_samples']} |")
    Path(a.out).write_text('\n'.join(lines)+'\n',encoding='utf-8')
def main():
    p=argparse.ArgumentParser();sp=p.add_subparsers(dest='cmd',required=True)
    q=sp.add_parser('prepare');q.add_argument('--source',required=True);q.add_argument('--out',required=True);q.add_argument('--limit',type=int,default=40);q.set_defaults(fn=prepare)
    q=sp.add_parser('run');q.add_argument('--manifest',required=True);q.add_argument('--out',required=True);q.add_argument('--backend',choices=list(DEFAULTS),required=True);q.add_argument('--model');q.add_argument('--device',default='cpu');q.add_argument('--compute-type',default='int8');q.add_argument('--revision',default='master');q.set_defaults(fn=run)
    q=sp.add_parser('compare');q.add_argument('--runs',nargs='+',required=True);q.add_argument('--out',required=True);q.set_defaults(fn=compare)
    a=p.parse_args();a.fn(a)
if __name__=='__main__': main()
