"""Regression checks for Wang Yang's submitted demo and integration refinements."""
import csv
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen
from urllib.error import HTTPError
import server
from validate_data import validate

class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        server.DB_PATH=Path(self.tmp.name)/'demo.sqlite3'
        server.initialize()
    def tearDown(self): self.tmp.cleanup()
    def test_seed_counts(self):
        c=server.stats({})['counts']
        self.assertEqual((c['total'],c['diagnosis_completed'],c['diagnosis_pending'],c['error_occurrences']),(4,3,1,5))
        self.assertEqual(validate(server.DB_PATH),[])
    def test_filter_and_exports_are_consistent(self):
        http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        threading.Thread(target=http.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{http.server_port}'
        try:
            with urlopen(base+'/api/export.json?review_status=passed') as r: j=json.load(r)
            with urlopen(base+'/api/export.csv?review_status=passed') as r: c=list(csv.DictReader(io.StringIO(r.read().decode('utf-8-sig'))))
            self.assertEqual([x['recording_id'] for x in j['items']],[x['recording_id'] for x in c])
            self.assertEqual(len(c),1)
            self.assertEqual(json.loads(c[0]['error_details']),j['items'][0]['error_details'])
            with urlopen(base+'/stats.html') as r: self.assertEqual(r.status,200)
            for path in ('/server.py','/management_demo.sqlite3','/','/api/stats'):
                if path in ('/','/api/stats'):
                    with urlopen(base+path) as r: self.assertEqual(r.status,200)
                else:
                    with self.assertRaises(HTTPError) as ctx: urlopen(base+path)
                    self.assertEqual(ctx.exception.code,404)
        finally: http.shutdown();http.server_close()
    def test_date_upper_bound_is_exclusive(self):
        with server.connect() as c: c.execute("UPDATE recordings SET created_at='2026-11-23T23:59:59+00:00'")
        self.assertEqual(server.stats({'from':'2026-11-23','to':'2026-11-24'})['counts']['total'],4)
        self.assertEqual(server.stats({'to':'2026-11-23'})['counts']['total'],0)
    def test_csv_formula_protection(self):
        self.assertEqual(server.safe_csv(' =1+1'),"' =1+1")
        self.assertEqual(server.safe_csv('正常文本'),'正常文本')
    def test_invalid_position_is_rejected(self):
        with server.connect() as c: c.execute('UPDATE diagnosis_errors SET char_index=999 WHERE error_id=1')
        self.assertTrue(any('越界' in e for e in validate(server.DB_PATH)))
    def test_orphan_and_duplicate_attempt_are_rejected(self):
        with server.connect() as c:
            c.execute("DELETE FROM diagnoses WHERE recording_id='REC-DEMO-001'")
            c.execute("UPDATE recordings SET speaker_id='S-DEMO-01',question_id='L1-Q001',question_version='v1',attempt=1 WHERE recording_id='REC-DEMO-002'")
        errors=validate(server.DB_PATH)
        self.assertTrue(any('重复' in e for e in errors))
        self.assertTrue(any('没有诊断' in e for e in errors))
        self.assertTrue(any('未完成' in e for e in errors))
    def test_empty_filter(self):
        self.assertEqual(server.rows_for({'question_id':'missing'}),[])
        self.assertEqual(server.stats({'question_id':'missing'})['counts']['total'],0)
    def test_failed_status(self):
        with server.connect() as c: c.execute("UPDATE diagnoses SET status='failed' WHERE recording_id='REC-DEMO-003'")
        self.assertEqual(server.stats({})['counts']['diagnosis_failed'],1)

if __name__=='__main__': unittest.main(verbosity=2)
