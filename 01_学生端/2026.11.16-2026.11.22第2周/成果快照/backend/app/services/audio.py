"""音频落盘、转码与时长读取。"""
import subprocess
import wave
from pathlib import Path


def ffmpeg_exe() -> str:
    """优先用 imageio-ffmpeg 自带的二进制，其次用 PATH 里的 ffmpeg。"""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def to_wav(src: Path, dst: Path) -> None:
    """统一转成 16 kHz / 单声道 / 16 bit PCM WAV。"""
    proc = subprocess.run(
        [
            ffmpeg_exe(),
            "-y",
            "-i",
            str(src),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "ignore")[-800:]
        raise RuntimeError(f"ffmpeg 转码失败：{detail}")
    if not dst.exists():
        raise RuntimeError("ffmpeg 没有生成 WAV 文件")


def wav_duration_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as wav:
        return int(wav.getnframes() / wav.getframerate() * 1000)
