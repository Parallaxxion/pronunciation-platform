"""Lazy adapters. Never pass reference text or hotwords from the answer to ASR."""
import os,re,threading,wave
from dataclasses import dataclass
DEFAULTS={'whisper':'small','sensevoice':'iic/SenseVoiceSmall','paraformer':'paraformer-zh'}
@dataclass(frozen=True)
class ASRConfig:
    backend:str='whisper'
    model:str='small'
    device:str='cpu'
    compute_type:str='int8'
    revision:str='master'
    @classmethod
    def environment(cls,model=None):
        b=os.getenv('ASR_BACKEND','whisper')
        if b not in DEFAULTS: raise ValueError('Unsupported ASR_BACKEND')
        return cls(b,model or os.getenv('ASR_MODEL') or (os.getenv('WHISPER_MODEL','small') if b=='whisper' else DEFAULTS[b]),os.getenv('ASR_DEVICE','cpu'),os.getenv('ASR_COMPUTE_TYPE','int8'),os.getenv('ASR_REVISION','master'))
class Recognizer:
    def __init__(self,cfg):
        self.config=cfg
        if cfg.backend=='whisper':
            from faster_whisper import WhisperModel
            self.model=WhisperModel(cfg.model,device=cfg.device,compute_type=cfg.compute_type)
        elif cfg.backend in ('sensevoice','paraformer'):
            from funasr import AutoModel
            self.model=AutoModel(model=cfg.model,model_revision=cfg.revision,device=cfg.device,disable_update=True,trust_remote_code=False)
        else: raise ValueError('Unsupported backend')
    def _samples(self,path):
        import numpy as np
        with wave.open(str(path),'rb') as w:
            if (w.getframerate(),w.getnchannels(),w.getsampwidth())!=(16000,1,2):raise ValueError('Expected 16k mono PCM16')
            return np.frombuffer(w.readframes(w.getnframes()),dtype=np.int16).astype(np.float32)/32768.
    def transcribe(self,path):
        if self.config.backend=='whisper':
            seg,_=self.model.transcribe(self._samples(path),language='zh',beam_size=5,temperature=0,condition_on_previous_text=False,vad_filter=False)
            return ''.join(s.text for s in seg).strip()
        kw={'language':'zh','use_itn':False} if self.config.backend=='sensevoice' else {}
        res=self.model.generate(input=self._samples(path),cache={},fs=16000,**kw)
        if not isinstance(res,list) or not res or any('text' not in r for r in res): raise RuntimeError('Invalid ASR response')
        return re.sub(r'<\|[^|]*\|>','',''.join(r['text'] for r in res)).strip()
    def transcribe_with_words(self,path):
        """返回 (text, words)；words 为 [{'text','start','end'}]，不支持的模型返回 None。

        只用于声调证据定位，不改变原有转写结果。
        """
        if self.config.backend!='whisper':
            return self.transcribe(path),None
        seg,_=self.model.transcribe(self._samples(path),language='zh',beam_size=5,temperature=0,condition_on_previous_text=False,vad_filter=False,word_timestamps=True)
        text=[];words=[]
        for s in seg:
            text.append(s.text)
            for w in (s.words or []):words.append({'text':w.word,'start':float(w.start),'end':float(w.end)})
        return ''.join(text).strip(),words
_LOCK=threading.Lock()
_CACHE={}
def _recognizer(config=None):
    cfg=config or ASRConfig.environment()
    with _LOCK:
        if cfg not in _CACHE: _CACHE[cfg]=Recognizer(cfg)
        return _CACHE[cfg]
def transcribe(path,config=None):
    return _recognizer(config).transcribe(path)
def transcribe_with_words(path,config=None):
    return _recognizer(config).transcribe_with_words(path)
