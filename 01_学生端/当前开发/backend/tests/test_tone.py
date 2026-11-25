import os
import unittest
from unittest.mock import patch

from app.services.tone import classify
from app.services.tone_diagnosis import map_target_spans, strict_tone_errors, tone_evidence


def feat(**kw):
    base = dict(frames=12, duration_ms=300, contour_st=[0, 0, 0, 0, 0],
                start_st=0, end_st=0, peak_st=0, trough_st=0,
                peak_pos=0.5, trough_pos=0.5, rise_st=0, drop_st=0)
    base.update(kw)
    return base


class ClassifyTests(unittest.TestCase):
    def test_falling_is_fourth(self):
        tone, conf, _ = classify(feat(start_st=4, end_st=-3, peak_st=4, trough_st=-3,
                                      peak_pos=0.05, trough_pos=0.95, drop_st=7, rise_st=-7))
        self.assertEqual(tone, "4")
        self.assertGreater(conf, 0.8)

    def test_flat_is_first(self):
        tone, _, _ = classify(feat(start_st=0.2, end_st=0.1, rise_st=-0.1, drop_st=0.3))
        self.assertEqual(tone, "1")

    def test_rising_is_second(self):
        tone, _, _ = classify(feat(start_st=-2, end_st=2, rise_st=4, trough_pos=0.0, drop_st=0.2))
        self.assertEqual(tone, "2")

    def test_dip_rise_is_third(self):
        tone, _, _ = classify(feat(start_st=1, end_st=1.5, trough_st=-1.5, trough_pos=0.5,
                                   rise_st=0.5, drop_st=2.5))
        self.assertEqual(tone, "3")

    def test_empty(self):
        self.assertEqual(classify(None)[0], None)


class SpanTests(unittest.TestCase):
    def test_words_split_evenly(self):
        words = [{"text": "我想", "start": 0.0, "end": 1.0},
                 {"text": "喝水", "start": 1.0, "end": 2.0}]
        spans = map_target_spans(list("我想喝水"), "我想喝水", words)
        self.assertEqual(len(spans), 4)
        self.assertAlmostEqual(spans[2][0], 1000.0)
        self.assertAlmostEqual(spans[2][1], 1500.0)

    def test_mismatch_returns_empty(self):
        words = [{"text": "再见", "start": 0.0, "end": 1.0}]
        self.assertEqual(map_target_spans(list("你好"), "再见", words), {})


class EvidenceTests(unittest.TestCase):
    def test_evidence_uses_patched_prosody(self):
        tokens = [{"c": "水", "py": "shui3"}, {"c": "好", "py": "hao3"}]
        words = [{"text": "水", "start": 0.0, "end": 0.3},
                 {"text": "好", "start": 0.3, "end": 0.6}]
        fake = feat(drop_st=6, peak_pos=0.1, start_st=4, end_st=-2, contour_st=[4, 3, 1, 0, -2])
        with patch("app.services.tone_diagnosis.prosody.analyze", return_value=[fake, None]):
            out = tone_evidence("x.wav", tokens, "水好", words)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["char_index"], 0)
        self.assertEqual(out[0]["detected"], "4")

    def test_strict_off_by_default(self):
        os.environ.pop("TONE_REPORT", None)
        ev = [{"char_index": 0, "expected": "hao4", "detected": "1",
               "confidence": 0.95, "contour_st": [4, 2, 0, -2, -3],
               "start_ms": 0, "end_ms": 300}]
        self.assertEqual(strict_tone_errors(ev, [{"c": "好", "py": "hao4"}]), [])

    def test_strict_reports_clear_case(self):
        os.environ["TONE_REPORT"] = "strict"
        try:
            ev = [{"char_index": 0, "expected": "hao4", "detected": "1",
                   "confidence": 0.95, "contour_st": [4, 3, 1, 0, -3],
                   "start_ms": 0, "end_ms": 300}]
            out = strict_tone_errors(ev, [{"c": "好", "py": "hao4"}])
            self.assertEqual(out[0]["actual"], "hao1")
        finally:
            os.environ.pop("TONE_REPORT", None)

    def test_strict_excludes_third_tone(self):
        os.environ["TONE_REPORT"] = "strict"
        try:
            ev = [{"char_index": 0, "expected": "shui3", "detected": "4",
                   "confidence": 0.95, "contour_st": [4, 3, 1, 0, -3],
                   "start_ms": 0, "end_ms": 300}]
            self.assertEqual(strict_tone_errors(ev, [{"c": "水", "py": "shui3"}]), [])
        finally:
            os.environ.pop("TONE_REPORT", None)


class DiagnosisIntegrationTests(unittest.TestCase):
    def _wav(self):
        import tempfile, wave
        from pathlib import Path
        d = tempfile.mkdtemp()
        path = Path(d) / "a.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\0\0" * 8000)
        return path

    def test_hypothesis_path_has_no_tone_evidence(self):
        from app.services.diagnosis import diagnose
        r = diagnose("", "你好", hypothesis="你好")
        self.assertEqual(r["tone_evidence"], [])
        self.assertNotIn("tone_evidence", r["tokens"][0])

    def test_strict_mode_adds_one_tone_error(self):
        from app.services.diagnosis import diagnose
        words = [{"text": "妈", "start": 0.0, "end": 0.3}]
        falling = feat(start_st=4, end_st=-2, peak_st=4, trough_st=-2,
                       peak_pos=0.05, trough_pos=0.95, drop_st=6, rise_st=-6,
                       contour_st=[4, 3, 1, 0, -2])
        os.environ["TONE_REPORT"] = "strict"
        try:
            with patch("app.services.diagnosis.transcribe_with_words",
                       return_value=("妈", words)), \
                 patch("app.services.tone_diagnosis.prosody.analyze",
                       return_value=[falling]):
                r = diagnose(str(self._wav()), "妈")
        finally:
            os.environ.pop("TONE_REPORT", None)
        self.assertEqual(len(r["tone_evidence"]), 1)
        self.assertIn("tone_evidence", r["tokens"][0])
        self.assertTrue(any(e["type"] == "tone" and e["actual"] == "ma4"
                            for e in r["errors"]))

