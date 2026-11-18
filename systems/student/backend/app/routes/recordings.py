"""录音上传：保存原始文件、转 WAV、写录音元数据。"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..database import SessionLocal
from ..models import Diagnosis, PracticeSession, Question, Recording, User
from ..services.audio import to_wav, wav_duration_ms
from ..services.diagnosis import diagnose
from .auth import get_current_user

router = APIRouter(prefix="/api/recordings", tags=["录音"])

BASE_DIR = Path(__file__).resolve().parents[2]
ORIGINAL_DIR = BASE_DIR / "data" / "original"
WAV_DIR = BASE_DIR / "data" / "wav"
ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
WAV_DIR.mkdir(parents=True, exist_ok=True)


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_device(value: str) -> dict:
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {"raw": value}
    except json.JSONDecodeError:
        return {"raw": value}


@router.post("", status_code=201)
async def upload_recording(
    background: BackgroundTasks,
    audio: UploadFile = File(...),
    practice_session_id: str = Form(...),
    client_recording_id: str = Form(...),
    recorded_at: str = Form(...),
    duration_ms: int = Form(0),
    device_info: str = Form("{}"),
    user: User = Depends(get_current_user),
):
    with SessionLocal() as db:
        session = db.get(PracticeSession, practice_session_id)
        if session is None or session.user_id != user.id:
            raise HTTPException(404, "练习记录不存在")

        existed = db.scalar(
            select(Recording).where(
                Recording.client_recording_id == client_recording_id
            )
        )
        if existed is not None:
            return {
                "recording_id": existed.id,
                "take_no": existed.take_no,
                "duration_ms": existed.duration_ms,
                "status": existed.upload_status,
                "duplicate": True,
            }

        max_take = db.scalar(
            select(func.max(Recording.take_no)).where(
                Recording.practice_session_id == practice_session_id
            )
        )
        take_no = (max_take or 0) + 1

    recording_id = str(uuid.uuid4())
    content_type = audio.content_type or ""
    suffix = (
        ".webm" if "webm" in content_type
        else ".mp4" if "mp4" in content_type
        else ".wav" if "wav" in content_type
        else ".bin"
    )
    original_path = ORIGINAL_DIR / f"{recording_id}{suffix}"
    wav_path = WAV_DIR / f"{recording_id}.wav"

    digest = hashlib.sha256()
    with original_path.open("wb") as target:
        while chunk := await audio.read(1024 * 1024):
            digest.update(chunk)
            target.write(chunk)

    try:
        to_wav(original_path, wav_path)
    except RuntimeError as exc:
        original_path.unlink(missing_ok=True)
        raise HTTPException(500, str(exc)) from exc

    actual_duration = wav_duration_ms(wav_path)
    recording = Recording(
        id=recording_id,
        client_recording_id=client_recording_id,
        practice_session_id=practice_session_id,
        take_no=take_no,
        recorded_at=parse_time(recorded_at),
        duration_ms=actual_duration or duration_ms or None,
        mime_type=content_type or None,
        device_info=parse_device(device_info),
        original_path=str(original_path),
        wav_path=str(wav_path),
        file_sha256=digest.hexdigest(),
        upload_status="uploaded",
    )

    try:
        with SessionLocal() as db:
            db.add(recording)
            db.commit()
    except IntegrityError as exc:
        original_path.unlink(missing_ok=True)
        wav_path.unlink(missing_ok=True)
        raise HTTPException(409, "该录音已提交过，请刷新后重试") from exc

    # 上传响应先返回，诊断在后台跑，不阻塞学生
    background.add_task(run_diagnosis, recording_id)

    return {
        "recording_id": recording_id,
        "take_no": take_no,
        "duration_ms": actual_duration,
        "status": "uploaded",
    }


def run_diagnosis(recording_id: str) -> None:
    """后台任务：调 C 的 diagnose()，把结果写进 diagnoses 表。"""
    with SessionLocal() as db:
        recording = db.get(Recording, recording_id)
        if recording is None or not recording.wav_path:
            return

        practice = db.get(PracticeSession, recording.practice_session_id)
        if practice is None:
            return

        question = db.get(Question, practice.question_id)
        if question is None:
            return

        diagnosis = db.scalar(
            select(Diagnosis).where(Diagnosis.recording_id == recording_id)
        )
        if diagnosis is None:
            diagnosis = Diagnosis(recording_id=recording_id, status="pending")
            db.add(diagnosis)
            db.commit()

        try:
            result = diagnose(
                recording.wav_path,
                question.text,
                question.tokens or [],
            )
            diagnosis.recognized_text = result["recognized_text"]
            diagnosis.tokens = result["tokens"]
            diagnosis.gap_errors = result["gap_errors"]
            diagnosis.model_version = result["model_version"]
            diagnosis.status = "done"
            diagnosis.error_message = None
        except Exception as exc:  # noqa: BLE001 - 后台任务要把失败原因写进库
            diagnosis.status = "failed"
            diagnosis.error_message = str(exc)[:2000]

        db.commit()


@router.get("/{recording_id}/diagnosis")
def get_diagnosis(
    recording_id: str,
    user: User = Depends(get_current_user),
):
    with SessionLocal() as db:
        recording = db.get(Recording, recording_id)
        if recording is None:
            raise HTTPException(404, "录音不存在")

        practice = db.get(PracticeSession, recording.practice_session_id)
        if practice is None or practice.user_id != user.id:
            raise HTTPException(404, "录音不存在")

        diagnosis = db.scalar(
            select(Diagnosis).where(Diagnosis.recording_id == recording_id)
        )
        if diagnosis is None:
            return {"recording_id": recording_id, "status": "pending"}

        return {
            "recording_id": recording_id,
            "status": diagnosis.status,
            "recognized_text": diagnosis.recognized_text,
            "tokens": diagnosis.tokens,
            "gap_errors": diagnosis.gap_errors,
            "model_version": diagnosis.model_version,
            "error_message": diagnosis.error_message,
        }
