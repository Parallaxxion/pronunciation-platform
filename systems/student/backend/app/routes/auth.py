
import os
import uuid
import hashlib
import secrets
import smtplib

from datetime import datetime, timedelta, timezone
from pathlib import Path
from email.message import EmailMessage
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pwdlib import PasswordHash
from pydantic import BaseModel, EmailStr, Field

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Response,
    Depends
)

from fastapi.responses import JSONResponse
from sqlalchemy import select, update

from ..database import SessionLocal
from ..models import (
    User,
    EmailVerificationToken,
    LoginSession
)


# ====================================
# 1. 读取项目配置
# ====================================

ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

APP_ENV = os.getenv("APP_ENV", "development")

PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    "http://127.0.0.1:8000"
).rstrip("/")

PRIVACY_VERSION = os.getenv(
    "PRIVACY_VERSION", "v0.1-dev"
)

COOKIE_NAME = "student_session"
VERIFICATION_TTL = timedelta(hours=24)
RESEND_COOLDOWN = timedelta(minutes=1)

password_hasher = PasswordHash.recommended()

router = APIRouter(
    prefix="/api/auth",
    tags=["学生注册与登录"]
)


# ====================================
# 2. 工具函数
# ====================================

def utc_now():
    # SQLite 中统一保存不带时区标记的 UTC 时间
    return datetime.now(timezone.utc).replace(
        tzinfo=None
    )


def hash_token(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def check_origin(request: Request):
    # 防止其他网站直接发起跨站修改请求
    origin = request.headers.get("origin")

    if origin is not None:
        if origin.rstrip("/") != PUBLIC_BASE_URL:
            raise HTTPException(
                status_code=403,
                detail="请求来源不合法"
            )

    elif APP_ENV == "production":
        raise HTTPException(
            status_code=403,
            detail="缺少请求来源信息"
        )


def send_verification_email(email, link):

    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "") or username

    if not host or not sender:
        raise HTTPException(
            status_code=503,
            detail="邮件服务尚未配置"
        )

    message = EmailMessage()
    message["Subject"] = "中文发音采集系统 - 邮箱验证"
    message["From"] = sender
    message["To"] = email

    message.set_content(
        "欢迎注册中文发音采集系统。\n\n"
        "请打开下面的链接完成邮箱验证：\n"
        f"{link}\n\n"
        "链接有效期为24小时。"
        "如果不是你本人注册，请忽略此邮件。"
    )

    if port == 465:
        client = smtplib.SMTP_SSL(
            host, port, timeout=15
        )
    else:
        client = smtplib.SMTP(
            host, port, timeout=15
        )

    with client:
        if port != 465:
            client.starttls()

        if username:
            client.login(username, password)

        client.send_message(message)


def issue_verification(db, user, request, message):
    raw_token = secrets.token_urlsafe(32)
    db.add(EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=utc_now() + VERIFICATION_TTL
    ))
    link = PUBLIC_BASE_URL + "/static/auth.html#verify=" + raw_token
    result = {"message": message}
    loopback = {"127.0.0.1", "::1", "localhost"}
    if (
        APP_ENV == "development"
        and not os.getenv("SMTP_HOST", "").strip()
        and urlsplit(PUBLIC_BASE_URL).hostname in loopback
        and request.client is not None
        and request.client.host in loopback
    ):
        result["dev_verify_url"] = link
    else:
        try:
            send_verification_email(user.email, link)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=503,
                detail="邮件发送失败，请稍后重试"
            ) from exc

    db.commit()
    return result


# ====================================
# 3. 注册和登录的数据格式
# ====================================

class RegisterData(BaseModel):

    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128
    )

    nationality: str = Field(
        min_length=1,
        max_length=100
    )

    native_language: str = Field(
        min_length=1,
        max_length=100
    )

    chinese_level: int = Field(
        ge=1,
        le=9
    )

    consent: bool


class LoginData(BaseModel):
    email: EmailStr
    password: str


class VerifyData(BaseModel):
    token: str = Field(
        min_length=20,
        max_length=256
    )


# ====================================
# 4. 注册接口
# ====================================

@router.post("/register", status_code=201)
def register(data: RegisterData, request: Request):

    check_origin(request)

    if not data.consent:
        raise HTTPException(
            status_code=400,
            detail="请先同意隐私协议"
        )

    if (
        APP_ENV == "production"
        and PRIVACY_VERSION == "v0.1-dev"
    ):
        raise HTTPException(
            status_code=503,
            detail="正式隐私协议尚未配置"
        )

    nationality = data.nationality.strip()
    native_language = data.native_language.strip()

    if not nationality or not native_language:
        raise HTTPException(
            status_code=400,
            detail="请填写完整的背景信息"
        )

    email = str(data.email).strip().lower()

    with SessionLocal() as db:

        existing = db.scalar(
            select(User).where(User.email == email)
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail="该邮箱已注册"
            )

        # 为学生生成匿名编号
        anonymous_id = "S-" + uuid.uuid4().hex.upper()

        # 对密码进行哈希处理
        hashed_password = password_hasher.hash(
            data.password
        )

        # 新建学生账号
        user = User(
            anonymous_id=anonymous_id,
            email=email,
            password_hash=hashed_password,
            nationality=nationality,
            native_language=native_language,
            chinese_level=data.chinese_level,
            email_verified=False,
            privacy_policy_version=PRIVACY_VERSION,
            consent_at=utc_now()
        )

        db.add(user)
        db.flush()

        return issue_verification(
            db, user, request, "注册成功，请完成邮箱验证"
        )


@router.post("/resend-verification")
def resend_verification(data: LoginData, request: Request):
    check_origin(request)
    email = str(data.email).strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None or not password_hasher.verify(data.password, user.password_hash):
            raise HTTPException(status_code=401, detail="邮箱或密码错误")

        # 先取得 SQLite 写锁，让并发重发依次检查冷却时间。
        pending = db.execute(
            update(User)
            .where(User.id == user.id, User.email_verified.is_(False))
            .values(email_verified=False)
        )
        if pending.rowcount == 0:
            return {"message": "邮箱已验证，请直接登录"}

        latest_expiry = db.scalar(
            select(EmailVerificationToken.expires_at)
            .where(EmailVerificationToken.user_id == user.id)
            .order_by(EmailVerificationToken.expires_at.desc())
            .limit(1)
        )
        if latest_expiry and utc_now() < latest_expiry - VERIFICATION_TTL + RESEND_COOLDOWN:
            raise HTTPException(
                status_code=429,
                detail="请在上次发送至少 1 分钟后再试"
            )

        return issue_verification(db, user, request, "验证链接已重新发送")


# ====================================
# 5. 邮箱验证接口
# ====================================

@router.post("/verify-email")
def verify_email(data: VerifyData, request: Request):

    check_origin(request)

    with SessionLocal() as db:

        record = db.scalar(
            select(EmailVerificationToken).where(
                EmailVerificationToken.token_hash
                == hash_token(data.token)
            )
        )

        if record is None:
            raise HTTPException(
                status_code=400,
                detail="验证链接无效"
            )

        if record.used_at is not None:
            raise HTTPException(
                status_code=400,
                detail="验证链接已使用"
            )

        if record.expires_at < utc_now():
            raise HTTPException(
                status_code=400,
                detail="验证链接已过期"
            )

        user = db.get(User, record.user_id)

        if user is None:
            raise HTTPException(
                status_code=404,
                detail="账号不存在"
            )

        now = utc_now()
        consumed = db.execute(
            update(EmailVerificationToken)
            .where(
                EmailVerificationToken.id == record.id,
                EmailVerificationToken.used_at.is_(None),
                EmailVerificationToken.expires_at > now
            )
            .values(used_at=now)
        )
        if consumed.rowcount == 0:
            raise HTTPException(status_code=400, detail="验证链接已使用或已过期")

        user.email_verified = True
        db.commit()

    return {
        "message": "邮箱验证成功，现在可以登录"
    }


# ====================================
# 6. 登录接口
# ====================================

@router.post("/login")
def login(
    data: LoginData,
    request: Request,
    response: Response
):

    check_origin(request)

    email = str(data.email).strip().lower()

    with SessionLocal() as db:

        user = db.scalar(
            select(User).where(User.email == email)
        )

        # 检查用户是否存在，密码是否正确
        if (
            user is None
            or not password_hasher.verify(
                data.password,
                user.password_hash
            )
        ):
            raise HTTPException(
                status_code=401,
                detail="邮箱或密码错误"
            )

        # 未完成邮箱验证，禁止登录
        if not user.email_verified:
            return JSONResponse(
                status_code=403,
                content={"detail": "请先完成邮箱验证", "code": "EMAIL_UNVERIFIED"}
            )

        # 创建随机登录凭据
        raw_session = secrets.token_urlsafe(32)

        session = LoginSession(
            user_id=user.id,
            token_hash=hash_token(raw_session),
            created_at=utc_now(),
            expires_at=utc_now() + timedelta(days=7)
        )

        db.add(session)
        db.commit()

        # 通过安全 Cookie 保存登录凭据
        response.set_cookie(
            key=COOKIE_NAME,
            value=raw_session,
            httponly=True,
            secure=(APP_ENV == "production"),
            samesite="strict",
            max_age=7 * 24 * 60 * 60,
            path="/"
        )

        return {
            "message": "登录成功",
            "anonymous_id": user.anonymous_id
        }


# ====================================
# 7. 检查当前学生是否登录
# ====================================

def get_current_user(request: Request):

    raw_session = request.cookies.get(COOKIE_NAME)

    if not raw_session:
        raise HTTPException(
            status_code=401,
            detail="请先登录"
        )

    with SessionLocal() as db:

        session = db.scalar(
            select(LoginSession).where(
                LoginSession.token_hash
                == hash_token(raw_session)
            )
        )

        if (
            session is None
            or session.expires_at < utc_now()
        ):
            raise HTTPException(
                status_code=401,
                detail="登录已过期，请重新登录"
            )

        user = db.get(User, session.user_id)

        if user is None or not user.email_verified:
            raise HTTPException(
                status_code=401,
                detail="无效的学生账号"
            )

        return user


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):

    return {
        "anonymous_id": user.anonymous_id,
        "email": user.email,
        "nationality": user.nationality,
        "native_language": user.native_language,
        "chinese_level": user.chinese_level
    }


# ====================================
# 8. 退出登录接口
# ====================================

@router.post("/logout")
def logout(request: Request, response: Response):

    check_origin(request)

    raw_session = request.cookies.get(COOKIE_NAME)

    if raw_session:

        with SessionLocal() as db:

            session = db.scalar(
                select(LoginSession).where(
                    LoginSession.token_hash
                    == hash_token(raw_session)
                )
            )

            if session:
                db.delete(session)
                db.commit()

    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite="strict"
    )

    return {
        "message": "已退出登录"
    }
