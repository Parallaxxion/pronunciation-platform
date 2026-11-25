"""Text proxy baseline plus optional F0 tone evidence.

Text is still the primary evidence. F0 tone detection is experimental:
- TONE_EVIDENCE=1 attaches per-character tone_evidence (off by default);
- TONE_REPORT=strict additionally reports high-confidence tone errors (off by default).
"""
import os,wave
from pypinyin import Style,lazy_pinyin
from .alignment import align,numbered
from .phonology import annotate
from .asr_backends import ASRConfig,transcribe as run_asr,transcribe_with_words
from .tone_diagnosis import strict_tone_errors,tone_evidence
class DiagnosisUnavailable(RuntimeError): pass
def hanzi(text): return ''.join(c for c in text if '\u3400'<=c<='\u9fff')
def to_pinyin(text): return lazy_pinyin(hanzi(text),style=Style.TONE3,neutral_tone_with_five=True,errors='ignore')
def transcribe(wav_path,model_size=None): return run_asr(wav_path,ASRConfig.environment(model_size))
def _flag(name): return os.getenv(name,'off').strip().lower() not in ('','off','0','false','no')
def diagnose(wav_path,text,tokens=None,model_size=None,hypothesis=None,config=None):
    chars=hanzi(text)
    if not chars: raise ValueError('No Chinese target characters')
    rt=[dict(t) for t in tokens] if tokens else [dict(c=c,py=p) for c,p in zip(chars,to_pinyin(text))]
    if ''.join(t.get('c','') for t in rt)!=chars: raise ValueError('tokens do not match target text')
    target=[numbered(t['py']) for t in rt]
    for t in rt: t.pop('err',None);t.pop('error',None)
    cfg=config or ASRConfig.environment(model_size)
    words=None
    want_tone=_flag('TONE_EVIDENCE') or _flag('TONE_REPORT')
    if hypothesis is None:
        with wave.open(str(wav_path),'rb') as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2) or not w.getnframes(): raise DiagnosisUnavailable('Expected nonempty 16k mono PCM16 WAV')
        if want_tone: recognized,words=transcribe_with_words(wav_path,cfg)
        else: recognized=run_asr(wav_path,cfg)
    else: recognized=hypothesis
    if not hanzi(recognized): raise DiagnosisUnavailable('No Chinese transcript: cannot infer zero errors or all omissions')
    errors=align(target,to_pinyin(recognized));annotate(errors);gaps={}
    for e in errors:
        if e['type']=='insertion': gaps[str(e['boundary_index'])]={'t':'ins','py':e['actual']}
        else: rt[e['char_index']]['err']={'t':{'tone':'tone','substitution':'sf','omission':'del'}[e['type']],'py':e['actual']}
    evidence=tone_evidence(wav_path,rt,recognized,words) if words else []
    for item in evidence: rt[item['char_index']]['tone_evidence']={k:v for k,v in item.items() if k!='char_index'}
    strict=strict_tone_errors(evidence,rt)
    for e in strict:
        if rt[e['char_index']].get('err'): continue
        if any(x.get('type')=='tone' and x.get('char_index')==e['char_index'] for x in errors): continue
        errors.append(e);rt[e['char_index']]['err']={'t':'tone','py':e['actual']}
    version=f'{cfg.backend}:{cfg.model}+weighted-dp-v2;text-proxy'
    if evidence: version+=';f0-evidence'
    if strict: version+=';tone-strict'
    return dict(recognized_text=recognized,tokens=rt,gap_errors=gaps,errors=errors,status='done',
        model_version=version,
        evidence_kind='manual_hypothesis' if hypothesis is not None else 'asr_text_proxy',
        tone_evidence=evidence,
        limitations=['Text proxy can be masked by ASR correction or homophones','F0 tone evidence is experimental (2/15 measurable on the 25-sample dev set); tone errors are not reported unless TONE_REPORT=strict','Repeated syllables may have ambiguous alignment'])
