"""认证与会话：密码哈希、登录会话、认证依赖"""

import hashlib
import hmac
import logging
import os
import secrets
from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import COOKIE_SECURE, SECRET_KEY
from app.db import SessionLocal, get_session
from app.models import User

logger = logging.getLogger(__name__)

# --- 密码哈希（标准库 pbkdf2，无额外依赖） ---
_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    """生成 pbkdf2_sha256 格式的密码哈希"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    """校验密码与哈希是否匹配"""
    try:
        algorithm, iterations, salt, expected = stored.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations)
    ).hex()
    return hmac.compare_digest(digest, expected)


# --- 会话（itsdangerous 签名 cookie） ---
_SESSION_COOKIE = "bomatch_session"
_SESSION_MAX_AGE = timedelta(days=30)
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="bomatch-session")


def set_session_cookie(response: Response, username: str) -> None:
    """在响应上写入登录会话 cookie"""
    token = _serializer.dumps({"username": username})
    response.set_cookie(
        _SESSION_COOKIE,
        token,
        max_age=int(_SESSION_MAX_AGE.total_seconds()),
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


def clear_session_cookie(response: Response) -> None:
    """清除登录会话 cookie"""
    response.delete_cookie(_SESSION_COOKIE)


def get_optional_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    """解析当前登录用户；未登录或会话无效返回 None"""
    token = request.cookies.get(_SESSION_COOKIE)
    if not token:
        return None
    try:
        payload = _serializer.loads(token, max_age=int(_SESSION_MAX_AGE.total_seconds()))
    except BadSignature, SignatureExpired:
        return None
    username = payload.get("username")
    if not username:
        return None
    return session.execute(select(User).where(User.username == username)).scalar_one_or_none()


def require_auth(user: User | None = Depends(get_optional_user)) -> User:
    """供后续 API 路由使用的认证依赖；未登录时抛出 401"""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或会话已过期")
    return user


def create_default_user_if_needed() -> None:
    """首次运行创建默认管理员（单用户系统）"""
    with SessionLocal() as session:
        existing = session.execute(select(User)).scalars().first()
        if existing is not None:
            return
        username = os.environ.get("BOMATCH_ADMIN_USERNAME", "admin")
        password = os.environ.get("BOMATCH_INIT_PASSWORD")
        if not password:
            password = secrets.token_urlsafe(12)
            logger.warning(
                "首次运行：已创建管理员账号 %s，初始密码 %s（请登录后尽快修改）",
                username,
                password,
            )
        session.add(User(username=username, password_hash=hash_password(password)))
        session.commit()
        logger.info("已创建默认管理员账号: %s", username)
