from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import os
from dotenv import load_dotenv

from app.database import get_db
from app.models.user import User
from app.services.supabase_auth import get_local_user_from_supabase_token, supabase_is_configured

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY", "agendazap-secret-change-in-production-2024")
APP_ENV = os.getenv("APP_ENV", "development").lower()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24 * 7  # 7 dias

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

if APP_ENV == "production" and SECRET_KEY == "agendazap-secret-change-in-production-2024":
    raise RuntimeError("JWT_SECRET ou SECRET_KEY precisa ser configurada em producao")


def cookie_secure(request: Request | None = None) -> bool:
    if request and request.url.hostname in {"127.0.0.1", "localhost", "testserver"}:
        return False

    configured = os.getenv("COOKIE_SECURE")
    if configured is not None:
        return configured.lower() == "true"
    if request:
        return request.url.scheme == "https"
    return os.getenv("APP_URL", "").startswith("https://")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    # Try cookie first (web), then Bearer token (API)
    token = request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        return None

    if supabase_is_configured() and "Authorization" in request.headers:
        supabase_user = await get_local_user_from_supabase_token(token, db)
        if supabase_user:
            return supabase_user

    payload = decode_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    return user


async def require_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    user = await get_current_user(request, db)
    if not user:
        from fastapi.responses import RedirectResponse
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/auth/login"}
        )
    return user
