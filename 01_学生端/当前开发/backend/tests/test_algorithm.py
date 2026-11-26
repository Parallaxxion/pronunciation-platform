import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from app.services.alignment import align,numbered
from app.services.diagnosis import diagnose,DiagnosisUnavailable
from app.benchmark import distance,cer_text,validate_sample,run
from argparse import Namespace
class Tests(unittest.TestCase):
    def test_tone(self): self.assertEqual(align(['ma1'],['ma3'])[0]['type'],'tone')
    def test_substitution(self):self.assertEqual(align(['ma1'],['ba1'])[0]['type'],'substitution')
    def test_deletion(self):self.assertEqual(align(['wo3','hao3'],['wo3'])[0]['char_index'],1)
    def test_continuous_boundary_insertions(self):
        e=align(['wo3'],['a5','ba5','wo3','ne5','ma5'])
        self.assertEqual([(x['boundary_index'],x['actual']) for x in e],[(0,'a5 ba5'),(1,'ne5 ma5')])
    def test_match(self):self.assertEqual(align(['ni3','hao3'],['ni3','hao3']),[])
    def test_normalization(self):
        self.assertEqual(numbered('nǚ'),'nv3');self.assertEqual(numbered('lü4'),'lv4');self.assertEqual(numbered('ma'),'ma5')
    def test_empty_asr(self):
        with self.assertRaises(DiagnosisUnavailable):diagnose('', '你好', hypothesis='')
    def test_bad_tokens(self):
        with self.assertRaises(ValueError):diagnose('', '你好',tokens=[{'c':'你','py':'ni3'}],hypothesis='你好')
    def test_legacy_fields(self):
        r=diagnose('', '我好',hypothesis='啊吧我好呢吗')
        self.assertEqual(r['gap_errors']['0']['py'],'a5 ba5')
        self.assertIn('2',r['gap_errors']);self.assertEqual(r['status'],'done')
    def test_cer(self):self.assertEqual(distance(cer_text('你好。'),cer_text('你号!')),1)
    def test_gold_gate(self):
        r=dict(sample_id='x',audio_path='x.wav',reference_text='你好',reference_verified=True,gold_errors=None)
        validate_sample(r)
        r.update(gold_errors=[],gold_verified=False)
        with self.assertRaises(ValueError):validate_sample(r)
    def test_pipeline_mock_not_asr_evidence(self):
        class Fake:
            def __init__(self,c):pass
            def transcribe(self,p):return '你好'
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'a.wav').write_bytes(b'fixture')
            m=d/'manifest.jsonl';m.write_text(json.dumps(dict(sample_id='x',audio_path='a.wav',reference_text='你好',reference_verified=True,gold_errors=None)),encoding='utf-8')
            a=Namespace(manifest=str(m),out=str(d/'out'),backend='whisper',model='small',device='cpu',compute_type='int8',revision='master')
            with patch('app.benchmark.Recognizer',Fake),patch('app.benchmark.to_wav'),patch('app.benchmark.wav_duration_ms',return_value=1000):run(a)
            s=json.loads((d/'out/summary.json').read_text())
            self.assertEqual(s['cer_success_only'],0);self.assertIsNone(s['error_metrics_success_only'])

class AdapterTests(unittest.TestCase):
    def test_whisper_lazy_generator_consumed(self):
        from app.services.asr_backends import Recognizer,ASRConfig
        import types
        r=object.__new__(Recognizer);r.config=ASRConfig()
        class Model:
            def transcribe(self,*a,**kw):
                assert kw['language']=='zh' and 'initial_prompt' not in kw
                return (types.SimpleNamespace(text=x) for x in ['你','好']),None
        r.model=Model()
        with tempfile.TemporaryDirectory() as d:
            import wave
            path=Path(d)/'a.wav'
            with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*160)
            self.assertEqual(r.transcribe(path),'你好')
    def test_funasr_tags(self):
        from app.services.asr_backends import Recognizer,ASRConfig
        r=object.__new__(Recognizer);r.config=ASRConfig('sensevoice','test')
        class Model:
            def generate(self,**kw):
                assert kw['use_itn'] is False
                return [{'text':'<|zh|><|NEUTRAL|>你好'}]
        r.model=Model()
        with tempfile.TemporaryDirectory() as d:
            import wave
            path=Path(d)/'a.wav'
            with wave.open(str(path),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0\0'*160)
            self.assertEqual(r.transcribe(path),'你好')
    def test_failed_asr_is_counted(self):
        class Fake:
            def __init__(self,c):pass
            def transcribe(self,p):raise RuntimeError('test failure')
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);(d/'a.wav').write_bytes(b'fixture')
            m=d/'m.jsonl';m.write_text(json.dumps(dict(sample_id='x',audio_path='a.wav',reference_text='你好',reference_verified=True,gold_errors=None)),encoding='utf-8')
            a=Namespace(manifest=str(m),out=str(d/'out'),backend='whisper',model='small',device='cpu',compute_type='int8',revision='master')
            with patch('app.benchmark.Recognizer',Fake),patch('app.benchmark.to_wav'),patch('app.benchmark.wav_duration_ms',return_value=1000),self.assertRaises(SystemExit):run(a)
            s=json.loads((d/'out/summary.json').read_text());self.assertEqual(s['failed'],1);self.assertIsNone(s['cer_success_only'])
if __name__=='__main__':unittest.main()


class PhonologyTests(unittest.TestCase):
    def test_split_initial_final_tone(self):
        from app.services.phonology import split_syllable
        self.assertEqual(split_syllable("zhong1"), ("zh", "ong", "1"))
        self.assertEqual(split_syllable("an1"), ("", "an", "1"))
        self.assertEqual(split_syllable("nv3"), ("n", "v", "3"))

    def test_initial_error(self):
        from app.services.phonology import classify
        fine, detail, coarse = classify("san1", "shan1")
        self.assertEqual((fine, detail, coarse), ("initial", "s→sh", "substitution"))

    def test_final_error(self):
        from app.services.phonology import classify
        fine, detail, coarse = classify("leng3", "ling3")
        self.assertEqual((fine, detail, coarse), ("final", "eng→ing", "substitution"))

    def test_tone_error(self):
        from app.services.phonology import classify
        fine, detail, coarse = classify("shui3", "shui4")
        self.assertEqual((fine, detail, coarse), ("tone", "3→4", "tone"))

    def test_syllable_error(self):
        from app.services.phonology import classify
        fine, _, coarse = classify("san1", "dang1")
        self.assertEqual((fine, coarse), ("syllable", "substitution"))

    def test_omission(self):
        from app.services.phonology import classify
        self.assertEqual(classify("xiang3", None)[0], "omission")

    def test_annotate_preserves_coarse_type(self):
        from app.services.phonology import annotate
        errs = [{"type": "substitution", "char_index": 0, "expected": "san1", "actual": "shan1"},
                {"type": "insertion", "boundary_index": 1, "actual": "xiang3"},
                {"type": "omission", "char_index": 2, "expected": "shui3", "actual": None}]
        out = annotate(errs)
        self.assertEqual([e["fine_type"] for e in out], ["initial", "insertion", "omission"])
        self.assertEqual([e["type"] for e in out], ["substitution", "insertion", "omission"])
