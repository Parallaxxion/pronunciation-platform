"""声调判定：从 F0 特征给出绝对调类与置信度。

这是**声学证据**，不是经充分验证的判调器。实测（25 条人工真值）：
- 整体判对约 28%（全猜四声 48%），句末三声常读成半三声，声学上是降调，与四声重叠；
- 因此默认只把结果写入 tone_evidence，不自动报错；只有 TONE_REPORT=strict 才参与报错。
"""
TONE_NAMES = {"1": "一声", "2": "二声", "3": "三声", "4": "四声", "5": "轻声"}


def classify(feat):
    """返回 (tone|None, confidence, reason)，tone 为 '1'/'2'/'3'/'4'。"""
    if not feat:
        return None, 0.0, "无有效 F0"
    rise, drop = feat["rise_st"], feat["drop_st"]
    start, end = feat["start_st"], feat["end_st"]
    peak_pos, trough_pos, trough = feat["peak_pos"], feat["trough_pos"], feat["trough_st"]

    # 三声（214）：中间低谷，之后回升
    if 0.15 <= trough_pos <= 0.85 and (end - trough) >= 1.0 and (start - trough) >= 0.5:
        return "3", _conf(min(end - trough, start - trough), 0.5, 4.0), "先降后升"

    # 二声（35）：起点低、单调上升
    if rise >= 1.5 and trough_pos <= 0.25:
        return "2", _conf(rise, 1.5, 4.0), f"上升 {rise:+.1f} 半音"

    # 四声（51）：峰在开头，随后下降
    if peak_pos <= 0.45 and drop >= 2.5:
        return "4", _conf(drop, 2.5, 6.0), f"高峰后降 {drop:.1f} 半音"

    # 一声（55）：平
    if abs(rise) < 1.5 and drop < 2.5 and start > -2.0:
        return "1", _conf(2.5 - abs(rise), 1.0, 2.5), f"平（起伏 {rise:+.1f}）"

    return None, 0.0, "无法判定"


def _conf(value, lo, hi):
    span = max(hi - lo, 1e-6)
    return round(min(0.95, 0.55 + 0.4 * (value - lo) / span), 2)
