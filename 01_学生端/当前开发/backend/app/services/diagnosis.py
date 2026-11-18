"""基线诊断：ASR → 拼音 → 音节对齐 → 四类偏误。

C 只需要改这个文件里的 transcribe / 对齐规则，路由和数据库不用动。
"""
import os
import wave
from difflib import SequenceMatcher
from pathlib import Path

from pypinyin import Style, lazy_pinyin

INITIALS = [
    "zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l",
    "g", "k", "h", "j", "q", "x", "r", "z", "c", "s", "y", "w",
]

_MODELS = {}


class DiagnosisUnavailable(RuntimeError):
    """ASR 依赖没装好时抛出，后台任务会把它写进 diagnoses.error_message。"""


def split_syllable(syllable: str):
    """pao3 -> ("p", "ao", "3")；轻声记 5。"""
    tone = syllable[-1] if syllable and syllable[-1].isdigit() else "5"
    body = syllable[:-1] if syllable and syllable[-1].isdigit() else syllable
    for initial in INITIALS:
        if body.startswith(initial):
            return initial, body[len(initial):], tone
    return "", body, tone


def to_pinyin(text: str):
    return lazy_pinyin(
        text,
        style=Style.TONE3,
        neutral_tone_with_five=True,
        errors="ignore",
    )


def read_wav_16k(path: str):
    """读 16k / 单声道 / 16bit WAV，转 float32，绕开 PyAV 的兼容问题。"""
    import numpy as np

    with wave.open(path, "rb") as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2):
            raise DiagnosisUnavailable("需要 16k / 单声道 / 16bit 的 WAV")
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def get_model(model_size: str):
    if model_size in _MODELS:
        return _MODELS[model_size]

    # 国内网络默认走镜像；已经设置 HF_ENDPOINT 的话不覆盖。
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise DiagnosisUnavailable(
            "未安装 faster-whisper，请先执行 pip install faster-whisper"
        ) from exc

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    _MODELS[model_size] = model
    return model


def transcribe(wav_path: str, model_size: str = "small") -> str:
    model = get_model(model_size)
    segments, _ = model.transcribe(
        read_wav_16k(wav_path),
        language="zh",
        beam_size=5,
    )
    return "".join(segment.text for segment in segments).strip()


def diagnose(
    wav_path: str,
    text: str,
    tokens: list[dict] | None = None,
    model_size: str | None = None,
    hypothesis: str | None = None,
) -> dict:
    """返回可直接写进 diagnoses 表的结构。"""
    model_size = model_size or os.getenv("WHISPER_MODEL", "small")
    if tokens:
        chars = [token.get("c", "") for token in tokens]
        target = [token.get("py", "") for token in tokens]
        result_tokens = [dict(token) for token in tokens]
    else:
        chars = [c for c in text if "\u4e00" <= c <= "\u9fff"]
        target = to_pinyin(text)
        result_tokens = [
            {"c": c, "py": p} for c, p in zip(chars, target)
        ]

    if len(target) != len(chars):
        raise ValueError("题目 tokens 与文本长度不一致，请先检查题库拼音")

    for token in result_tokens:
        token.pop("err", None)
        token.pop("error", None)

    recognized = hypothesis if hypothesis is not None else transcribe(wav_path, model_size)
    recognized_pinyin = to_pinyin(recognized)
    gap_errors: dict[str, dict] = {}

    matcher = SequenceMatcher(
        a=target,
        b=recognized_pinyin,
        autojunk=False,
    )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        if tag == "replace":
            count = max(i2 - i1, j2 - j1)
            for offset in range(count):
                i, j = i1 + offset, j1 + offset
                if i < i2 and j < j2:
                    ti, tf, tt = split_syllable(target[i])
                    hi, hf, ht = split_syllable(recognized_pinyin[j])
                    if (ti, tf) == (hi, hf) and tt != ht:
                        result_tokens[i]["err"] = {
                            "t": "tone",
                            "py": recognized_pinyin[j],
                        }
                    else:
                        result_tokens[i]["err"] = {
                            "t": "sf",
                            "py": recognized_pinyin[j],
                        }
                elif i < i2:
                    result_tokens[i]["err"] = {"t": "del"}
                else:
                    gap_errors[str(i1)] = {
                        "t": "ins",
                        "py": recognized_pinyin[j],
                    }

        elif tag == "delete":
            for i in range(i1, i2):
                result_tokens[i]["err"] = {"t": "del"}

        elif tag == "insert":
            gap_errors[str(i1)] = {
                "t": "ins",
                "py": recognized_pinyin[j1],
            }

    return {
        "recognized_text": recognized,
        "tokens": result_tokens,
        "gap_errors": gap_errors,
        "model_version": f"faster-whisper-{model_size}+syl-lev-1",
        "status": "done",
    }
