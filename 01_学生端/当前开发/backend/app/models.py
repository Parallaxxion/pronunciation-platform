
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    UniqueConstraint
)

from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


# 获取当前 UTC 时间
def utc_now():
    return datetime.now(timezone.utc)


# ====================================
# 第一张表：学生信息
# ====================================

class User(Base):

    __tablename__ = "users"

    # 数据库内部编号
    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # 学生匿名编号
    anonymous_id: Mapped[str] = mapped_column(
        String(50),
        unique=True
    )

    # 邮箱
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True
    )

    # 密码哈希，不存储明文密码
    password_hash: Mapped[str] = mapped_column(
        String(255)
    )

    # 国籍
    nationality: Mapped[str] = mapped_column(
        String(100)
    )

    # 母语
    native_language: Mapped[str] = mapped_column(
        String(100)
    )

    # 汉语等级
    chinese_level: Mapped[int] = mapped_column(
        Integer
    )

    # 是否完成邮箱验证
    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    # 隐私协议版本
    privacy_policy_version: Mapped[str] = mapped_column(
        String(30)
    )

    # 同意隐私协议的时间
    consent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    # 注册时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now
    )


# ====================================
# 第二张表：题目信息
# ====================================

class Question(Base):

    __tablename__ = "questions"

    # 题目编号，例如 L1-002
    id: Mapped[str] = mapped_column(
        String(50),
        primary_key=True
    )

    # 题目等级
    level: Mapped[int] = mapped_column(
        Integer,
        index=True
    )

    # 题目汉字文本
    text: Mapped[str] = mapped_column(
        Text
    )

    # 原始拼音字符串
    pinyin: Mapped[str] = mapped_column(
        Text
    )

    # 逐字拼音结构
    tokens: Mapped[list] = mapped_column(
        JSON,
        default=list
    )

    # 语法点编号
    grammar: Mapped[list] = mapped_column(
        JSON,
        default=list
    )


# ====================================
# 第三张表：练习记录
# ====================================

class PracticeSession(Base):

    __tablename__ = "practice_sessions"

    # 本次练习的 UUID
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True
    )

    # 关联学生
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # 关联题目
    question_id: Mapped[str] = mapped_column(
        ForeignKey("questions.id")
    )

    # 练习开始时间
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now
    )


# ====================================
# 第四张表：录音记录
# ====================================

class Recording(Base):

    __tablename__ = "recordings"

    # 防止同一次练习的录音序号重复
    __table_args__ = (
        UniqueConstraint(
            "practice_session_id",
            "take_no",
            name="uq_session_take"
        ),
    )

    # 服务器上的录音 UUID
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True
    )

    # 浏览器生成的录音 UUID
    client_recording_id: Mapped[str] = mapped_column(
        String(36),
        unique=True
    )

    # 对应哪次练习
    practice_session_id: Mapped[str] = mapped_column(
        ForeignKey("practice_sessions.id")
    )

    # 第几次录音
    take_no: Mapped[int] = mapped_column(
        Integer
    )

    # 录音开始时间
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    # 录音时长，单位毫秒
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    # 原始音频格式
    mime_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    # 设备信息
    device_info: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True
    )

    # 原始录音路径
    original_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # WAV 录音路径
    wav_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # 文件校验值
    file_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True
    )

    # 上传状态
    upload_status: Mapped[str] = mapped_column(
        String(30),
        default="pending"
    )

    # 是否是学生最终选用的录音
    is_selected: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    # 服务器接收记录的时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now
    )


# ====================================
# 第五张表：诊断结果
# ====================================

class Diagnosis(Base):

    __tablename__ = "diagnoses"

    # 诊断记录编号
    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # 对应的录音编号
    recording_id: Mapped[str] = mapped_column(
        ForeignKey("recordings.id"),
        unique=True
    )

    # 识别出的文本
    recognized_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # 逐字偏误标注
    tokens: Mapped[list] = mapped_column(
        JSON,
        default=list
    )

    # 字间偏误标注
    gap_errors: Mapped[dict] = mapped_column(
        JSON,
        default=dict
    )

    # 使用的算法版本
    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    # 诊断状态
    status: Mapped[str] = mapped_column(
        String(30),
        default="pending"
    )

    # 失败原因
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # 诊断记录创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now
    )


# ====================================
# 第六张表：邮箱验证凭据
# ====================================

class EmailVerificationToken(Base):

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # 对应哪个学生
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # 验证凭据的哈希值
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True
    )

    # 过期时间（UTC）
    expires_at: Mapped[datetime] = mapped_column(
        DateTime
    )

    # 是否已经使用过
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )


# ====================================
# 第七张表：登录会话
# ====================================

class LoginSession(Base):

    __tablename__ = "login_sessions"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # 对应哪个学生
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # 登录会话凭据的哈希值
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True
    )

    # 会话有效期限（UTC）
    expires_at: Mapped[datetime] = mapped_column(
        DateTime
    )

    # 登录时间（UTC）
    created_at: Mapped[datetime] = mapped_column(
        DateTime
    )
