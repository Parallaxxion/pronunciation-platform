"""音节级 F0 测量（声调证据）。

只在需要时导入 parselmouth；未安装或音频不可读时由调用方降级，不影响文本诊断。
"""
import math


def _load(wav):
    import parselmouth

    return parselmouth.Sound(str(wav))


def _pitch(snd):
    p = snd.to_pitch_ac(
        time_step=0.01,
        pitch_floor=75,
        pitch_ceiling=400,
        voicing_threshold=0.45,
        octave_cost=0.05,
        octave_jump_cost=2.5,
        voiced_unvoiced_cost=0.2,
    )
    return list(p.xs()), list(p.selected_array["frequency"])


def _median(values):
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _resample(values, points=5):
    if len(values) == points:
        return list(values)
    idx = [i * (len(values) - 1) / (points - 1) for i in range(points)]
    out = []
    for x in idx:
        lo = int(math.floor(x))
        hi = min(lo + 1, len(values) - 1)
        frac = x - lo
        out.append(values[lo] * (1 - frac) + values[hi] * frac)
    return out


def analyze(wav, spans, points=5):
    """spans 为 [(start_ms, end_ms), ...]，返回等长的特征列表（不可测的位置为 None）。

    特征以“说话人本段录音的浊音中位 F0”为零点，单位为半音，避免不同人音高差异。
    """
    snd = _load(wav)
    times, f0 = _pitch(snd)
    voiced = [v for v in f0 if v > 0]
    if not voiced:
        return [None] * len(spans)
    ref = _median(voiced)
    st = lambda hz: 12.0 * math.log2(max(hz, 1e-6) / ref)

    out = []
    for start_ms, end_ms in spans:
        seg = [v for t, v in zip(times, f0) if start_ms / 1000.0 <= t <= end_ms / 1000.0 and v > 0]
        if len(seg) < 6:
            out.append(None)
            continue
        contour = _resample(seg, points)
        contour_st = [st(v) for v in contour]
        k = max(1, len(seg) // 3)
        start_hz = _median(seg[:k])
        end_hz = _median(seg[-k:])
        peak_hz, trough_hz = max(seg), min(seg)
        peak_pos = seg.index(peak_hz) / max(len(seg) - 1, 1)
        trough_pos = seg.index(trough_hz) / max(len(seg) - 1, 1)
        out.append(
            {
                "frames": len(seg),
                "duration_ms": int(end_ms - start_ms),
                "contour_st": [round(v, 2) for v in contour_st],
                "start_st": round(st(start_hz), 2),
                "end_st": round(st(end_hz), 2),
                "peak_st": round(st(peak_hz), 2),
                "trough_st": round(st(trough_hz), 2),
                "peak_pos": round(peak_pos, 2),
                "trough_pos": round(trough_pos, 2),
                "rise_st": round(st(end_hz) - st(start_hz), 2),
                "drop_st": round(st(peak_hz) - st(end_hz), 2),
            }
        )
    return out
