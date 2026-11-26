"""把 ASR 词时间戳、目标字和 F0 证据拼起来，供诊断流程使用。

设计原则：
- 只对“ASR 认成了同一个字”的位置做声学分析，避免把替换错误当声调错误；
- 默认只产出 tone_evidence（证据），不报错；
- TONE_REPORT=strict 时才报“高置信”声调错，阈值取在实测精确率可接受的位置。
"""
import difflib
import os
import re

from . import prosody, tone

_HAN = re.compile(r"[\u3400-\u9fff]")


def _is_han(ch):
    return bool(_HAN.match(ch))


def _word_char_spans(words):
    """把词级时间戳按汉字数均分，得到逐字 (char, start_ms, end_ms)。"""
    out = []
    for w in words or []:
        chars = [c for c in str(w.get("text", "")) if _is_han(c)]
        if not chars:
            continue
        start, end = float(w["start"]), float(w["end"])
        step = (end - start) / len(chars)
        for k, ch in enumerate(chars):
            out.append((ch, (start + k * step) * 1000.0, (start + (k + 1) * step) * 1000.0))
    return out


def map_target_spans(target_chars, recognized_text, words):
    """目标字下标 -> 识别字时间区间（毫秒）。只映射 ASR 与题目完全相同的字。"""
    rec_chars = [c for c in (recognized_text or "") if _is_han(c)]
    spans = _word_char_spans(words)
    if not rec_chars or len(spans) != len(rec_chars):
        return {}
    matcher = difflib.SequenceMatcher(a=list(target_chars), b=rec_chars, autojunk=False)
    mapping = {}
    for a0, b0, size in matcher.get_matching_blocks():
        for k in range(size):
            ti, ri = a0 + k, b0 + k
            mapping[ti] = (spans[ri][1], spans[ri][2])
    return mapping


def _split_py(py):
    py = (py or "").strip().lower()
    return (py[:-1], py[-1]) if py[-1:] in "12345" else (py, "5")


def tone_evidence(wav_path, tokens, recognized_text, words, points=5):
    """返回逐字声调证据列表；不可用时返回空列表，不抛异常。"""
    if not words:
        return []
    mapping = map_target_spans([t.get("c", "") for t in tokens], recognized_text, words)
    wanted = []
    for i, t in enumerate(tokens):
        base, tone_no = _split_py(t.get("py", ""))
        if i in mapping and tone_no in "1234":
            wanted.append((i, mapping[i], t))
    if not wanted:
        return []
    try:
        feats = prosody.analyze(wav_path, [span for _, span, _ in wanted], points=points)
    except Exception:  # noqa: BLE001 - 声学证据不可用不能拖垮文本诊断
        return []
    out = []
    for (i, (start_ms, end_ms), token), feat in zip(wanted, feats):
        detected, conf, reason = tone.classify(feat)
        out.append(
            {
                "char_index": i,
                "expected": token.get("py"),
                "detected": detected,
                "confidence": conf,
                "reason": reason,
                "start_ms": round(start_ms),
                "end_ms": round(end_ms),
                "contour_st": feat["contour_st"] if feat else None,
            }
        )
    return out


def strict_tone_errors(evidence, tokens):
    """只在 TONE_REPORT=strict 下返回声调错误；条件刻意保守，宁可少报。"""
    if os.getenv("TONE_REPORT", "off").lower() != "strict":
        return []
    errors = []
    for item in evidence:
        target = _split_py(item.get("expected"))[1]
        detected = item.get("detected")
        feat_ok = item.get("contour_st") is not None
        if not feat_ok or not detected or target not in "124" or detected not in "124":
            continue
        if detected == target or item.get("confidence", 0) < 0.9:
            continue
        span = item.get("end_ms", 0) - item.get("start_ms", 0)
        if not 120 <= span <= 600:
            continue
        contour = item["contour_st"]
        strength = max(contour) - min(contour)
        if strength < 5.0:
            continue
        base, _ = _split_py(item["expected"])
        errors.append(
            {
                "type": "tone",
                "char_index": item["char_index"],
                "expected": item["expected"],
                "actual": base + detected,
            }
        )
    return errors
