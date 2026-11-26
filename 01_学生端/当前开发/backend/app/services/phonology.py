"""音节级音系分析：把“读错了”细化成声母/韵母/声调，并给出具体对立（如 s→sh）。

为什么单独一层：
  原来的四类（tone/substitution/omission/insertion）是编辑操作，不是教学分类。
  “substitution”既可能是声母错、韵母错，也可能是整个音节都错，教学反馈需要分开。
  这一层只做纯文本（拼音）推断，不引入声学证据；声学证据由后续模块提供。

约定：
  * 声调统一用数字调（1–4，轻声 5），与 alignment.numbered 一致。
  * fine_type ∈ {tone, initial, final, syllable, initial+tone, final+tone, syllable+tone,
                 omission, insertion, none}
  * coarse_type 保持原四类，供现有前端/接口兼容。
"""
from .alignment import numbered

_INITIALS = ("zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
             "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w")

_COARSE = {
    "tone": "tone", "initial": "substitution", "final": "substitution",
    "syllable": "substitution", "initial+tone": "tone", "final+tone": "tone",
    "syllable+tone": "substitution", "omission": "omission",
    "insertion": "insertion", "none": "none",
}


def split_syllable(pinyin: str):
    """'shui3' -> ('sh', 'ui', '3')；零声母返回 ('', 'an', '1')。"""
    value = numbered(pinyin)  # 统一 ü/v、补轻声 5，非法音节直接抛错
    tone = value[-1] if value[-1].isdigit() else "5"
    body = value[:-1] if value[-1].isdigit() else value
    for ini in _INITIALS:
        if body.startswith(ini):
            return ini, body[len(ini):], tone
    return "", body, tone


def classify(expected: str, actual):
    """对比标准读音与实际读音，返回 (fine_type, detail, coarse_type)。

    actual=None 表示漏读；detail 是给人看的对立描述，如 's→sh'、'eng→ing'、'3→4'。
    """
    if actual is None:
        return "omission", "", _COARSE["omission"]
    ei, ef, et = split_syllable(expected)
    ai, af, at = split_syllable(actual)
    diffs = []
    if ei != ai:
        diffs.append("initial")
    if ef != af:
        diffs.append("final")
    if et != at:
        diffs.append("tone")
    if not diffs:
        return "none", "", _COARSE["none"]
    if diffs == ["tone"]:
        return "tone", f"{et}→{at}", _COARSE["tone"]
    if diffs == ["initial"]:
        return "initial", f"{ei}→{ai}", _COARSE["initial"]
    if diffs == ["final"]:
        return "final", f"{ef}→{af}", _COARSE["final"]
    if "tone" in diffs and len(diffs) == 2:
        base = "initial" if diffs[0] == "initial" else "final"
        fine = base + "+tone"
        return fine, f"{ei}{ef}→{ai}{af}", _COARSE[fine]
    return "syllable", f"{ei}{ef}→{ai}{af}", _COARSE["syllable"]


def annotate(errors):
    """给 alignment.align() 的输出补 fine_type/detail，原地修改并返回。"""
    for e in errors:
        if e["type"] == "insertion":
            e["fine_type"], e["detail"] = "insertion", e.get("actual") or ""
        elif e["type"] == "omission":
            e["fine_type"], e["detail"] = "omission", ""
        else:
            fine, detail, _ = classify(e["expected"], e["actual"])
            e["fine_type"], e["detail"] = fine, detail
    return errors
