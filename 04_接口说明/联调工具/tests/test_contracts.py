import copy,json,unittest,hashlib,wave,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from integration.adapters import *
ROOT=Path(__file__).resolve().parents[3]
Q=json.loads((ROOT/'04_接口说明/示例/question-source.json').read_text(encoding='utf-8'))
D=json.loads((ROOT/'04_接口说明/示例/diagnosis-source.json').read_text(encoding='utf-8'))
class AdapterTests(unittest.TestCase):
 def test_tone_styles(self):
  for a,b in [('wǒ','wo3'),('WO3','wo3'),('nǚ','nv3'),('nu:3','nv3'),('lüè','lve4'),('ma0','ma5'),('men','men5'),('ḿ','m2')]:
   with self.subTest(a=a):self.assertEqual(pinyin_numbered(a),b)
 def test_bad_pinyin(self):
  for a in ('','wo3 men5','wǒ2','wo6','xi-huan'):
   with self.subTest(a=a),self.assertRaises(ContractError):pinyin_numbered(a)
 def test_items_wrapper(self):self.assertEqual(question_list({'items':[Q]})[0]['question_id'],Q['id'])
 def test_legacy_wrapper(self):self.assertEqual(question_list({'questions':[Q]}),question_list([Q]))
 def test_invalid_wrapper(self):
  with self.assertRaises(ContractError):question_list({'total':0})
 def test_punctuation_offsets(self):self.assertEqual([t['display_start'] for t in normalize_question(Q)['tokens']],[0,2,3,4])
 def test_unicode_codepoints(self):
  q=copy.deepcopy(Q);q['text']='😀'+q['text'];self.assertEqual(normalize_question(q)['tokens'][0]['display_start'],1)
 def test_missing_character(self):
  q=copy.deepcopy(Q);q['tokens'].pop(1)
  with self.assertRaises(ContractError):normalize_question(q)
 def test_no_guessed_version(self):self.assertIsNone(normalize_question(Q)['question_version'])
 def test_revision_changes(self):
  q=copy.deepcopy(Q);q['tokens'][0]['py']='wo2';self.assertNotEqual(normalize_question(Q)['content_revision'],normalize_question(q)['content_revision'])
 def test_legacy_admin_pinyin(self):
  q=copy.deepcopy(Q);q['pinyin']=[t['py'] for t in q.pop('tokens')];self.assertEqual(normalize_question(Q)['content_revision'],normalize_question(q)['content_revision'])
 def test_do_not_split_sentence(self):
  q=copy.deepcopy(Q);q.pop('tokens');q['pinyin']='wo xue hanyu'
  with self.assertRaises(ContractError):normalize_question(q)
 def test_four_error_types_and_boundaries(self):
  d=normalize_diagnosis(D,normalize_question(Q));self.assertEqual(d['status'],'completed');self.assertEqual({e['type'] for e in d['errors']},{'tone','substitution','omission','insertion'});self.assertEqual([e['boundary_index'] for e in d['errors'] if e['type']=='insertion'],[0,4])
 def test_pending_failed_are_not_success(self):
  for s in ('pending','processing','failed'):
   self.assertEqual(normalize_diagnosis(dict(recording_id='r',status=s),normalize_question(Q))['status'],s)
 def test_no_missing_result_as_zero_error(self):
  with self.assertRaises(ContractError):normalize_diagnosis(dict(recording_id='r',status='done'),normalize_question(Q))
 def test_unknown_error(self):
  d=copy.deepcopy(D);d['tokens'][0]['err']['t']='unknown'
  with self.assertRaises(ContractError):normalize_diagnosis(d,normalize_question(Q))
 def test_out_of_range(self):
  d=copy.deepcopy(D);d['gap_errors']['5']={'t':'ins','py':'a5'}
  with self.assertRaises(ContractError):normalize_diagnosis(d,normalize_question(Q))
 def test_multiple_errors_preserved(self):
  d={'recording_id':'r','status':'completed','errors':[{'type':'tone','char_index':0,'actual':'wo2'},{'type':'substitution','char_index':0,'actual':'bo3'}]};self.assertEqual(len(normalize_diagnosis(d,normalize_question(Q))['errors']),2)
 def test_counts_retry_retake_delete(self):
  q=normalize_question(Q);r={'recording_id':'r1','question_id':Q['id'],'speaker_id':'s','upload_status':'uploaded'};r2={**r,'recording_id':'r2'};deleted={**r,'recording_id':'r3','deleted':True};pending={**r,'recording_id':'r4','upload_status':'pending'}
  c=coverage([q],[r,r,r2,deleted,pending])['items'][0];self.assertEqual(c['recording_count'],2);self.assertEqual(c['unique_speaker_count'],1);self.assertIsNone(c['gap']);self.assertEqual(coverage([q],[r],{Q['id']:3})['items'][0]['gap'],2)
 def test_conflicting_retry(self):
  q=normalize_question(Q);r={'recording_id':'r','question_id':Q['id'],'speaker_id':'s','upload_status':'uploaded'}
  with self.assertRaises(ContractError):coverage([q],[r,{**r,'deleted':True}])
 def test_unknown_question(self):
  with self.assertRaises(ContractError):coverage([normalize_question(Q)],[{'recording_id':'r','question_id':'wrong','speaker_id':'s'}])
 def test_ui_baseline_bytes(self):
  for name,digest in json.loads((ROOT/'05_相关材料/统一前端/baseline.sha256.json').read_text(encoding='utf-8')).items():self.assertEqual(hashlib.sha256((ROOT/'05_相关材料/统一前端/baseline'/name).read_bytes()).hexdigest(),digest)
 def test_wav_manifest(self):
  for line in (ROOT/'05_相关材料/算法交接样例/manifest.jsonl').read_text(encoding='utf-8').splitlines():
   r=json.loads(line);p=ROOT/'05_相关材料/算法交接样例'/r['audio_path'];self.assertIsNone(r['gold_errors']);self.assertEqual(r['dataset_role'],'format_integration_only');self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),r['sha256'])
   with wave.open(str(p),'rb') as w:self.assertEqual((w.getframerate(),w.getnchannels(),w.getsampwidth()),(16000,1,2));self.assertGreater(w.getnframes(),0)
if __name__=='__main__':unittest.main()
