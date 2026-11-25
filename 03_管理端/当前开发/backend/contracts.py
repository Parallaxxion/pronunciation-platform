"""Management input models and the shared, versioned three-group adapters."""
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '04_接口说明' / '联调工具'))
from integration.adapters import normalize_question, normalize_diagnosis, ContractError

ID = Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')]
Digest = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
Version = Annotated[int, Field(strict=True, ge=1)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Speaker(Input):
    speaker_id: ID
    nationality: str = Field(max_length=100)
    language: str = Field(max_length=100)
    level: int = Field(strict=True, ge=1, le=9)
    source: Literal['manual', 'student', 'synthetic_fixture'] = 'manual'


class Question(Input):
    question_id: ID
    level: int = Field(strict=True, ge=1, le=9)
    display_text: str = Field(min_length=1, max_length=2000)
    tokens: list[dict] = Field(min_length=1, max_length=2000)
    question_version: str | None = Field(default=None, max_length=128)
    source_content_revision: Digest | None = None
    grammar: list[str] = Field(default_factory=list, max_length=200)
    status: Literal['draft', 'validated', 'rejected', 'ready', 'published', 'unknown'] = 'unknown'
    source: Literal['manual', 'proposition', 'student', 'synthetic_fixture'] = 'manual'
    target_recordings: int | None = Field(default=None, strict=True, ge=0)

    def normalized(self):
        result = normalize_question(self.model_dump(), self.source)
        result['target_recordings'] = self.target_recordings
        return result


class Recording(Input):
    recording_id: ID
    speaker_id: ID
    question_id: ID
    practice_session_id: ID
    take_no: int = Field(strict=True, ge=1)
    recorded_at: datetime
    device: dict = Field(default_factory=dict)
    question_snapshot: Question
    wav_sha256: Digest
    original_sha256: Digest
    data_source: Literal['synthetic_fixture', 'authorized_test', 'authorized_collection']
    consent_reference: str | None = Field(default=None, max_length=500)
    diagnosis: dict | None = None
    note: str = Field(default='', max_length=500)

    @field_validator('recorded_at')
    @classmethod
    def timezone_required(cls, value):
        if value.utcoffset() is None:
            raise ValueError('recorded_at 必须带时区')
        return value

    def normalized(self):
        if self.question_id != self.question_snapshot.question_id:
            raise ContractError('题目编号与录音快照不一致')
        if self.data_source != 'synthetic_fixture' and not (self.consent_reference or '').strip():
            raise ContractError('非合成录音必须附授权依据编号；不要在此填写个人资料')
        value = self.model_dump(mode='json')
        value['question_snapshot'] = self.question_snapshot.normalized()
        diagnosis = dict(self.diagnosis) if self.diagnosis is not None else {'status':'pending'}
        if diagnosis.get('recording_id', self.recording_id) != self.recording_id:
            raise ContractError('诊断关联了其他录音')
        diagnosis['recording_id'] = self.recording_id
        value['diagnosis'] = normalize_diagnosis(diagnosis, value['question_snapshot'])
        value['diagnosis_available'] = self.diagnosis is not None
        # Raw algorithm exceptions can contain disk paths or credentials.
        if value['diagnosis']['status'] == 'failed':
            value['diagnosis']['error_message'] = '诊断失败，请凭录音编号向算法组核查'
        else:
            value['diagnosis']['error_message'] = None
        value['upload_status'] = 'uploaded'
        return value


class SpeakerUpdate(Input):
    expected_version: Version
    nationality: str = Field(max_length=100)
    language: str = Field(max_length=100)
    level: int = Field(strict=True, ge=1, le=9)


class QuestionUpdate(Input):
    expected_version: Version
    question: Question


class RecordingUpdate(Input):
    expected_version: Version
    note: str = Field(max_length=500)


class DiagnosisUpdate(Input):
    expected_version: Version
    diagnosis: dict


class ChangeState(Input):
    expected_version: Version


class ImportBatch(Input):
    speakers: list[Speaker] = Field(default_factory=list, max_length=500)
    questions: list[Question] = Field(default_factory=list, max_length=500)
    recordings: list[Recording] = Field(default_factory=list, max_length=500)
