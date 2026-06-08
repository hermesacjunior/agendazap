import os
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


def supabase_is_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))


async def fetch_supabase_user(access_token: str) -> dict[str, Any] | None:
    """Validate a Supabase access token and return the auth user payload."""
    supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or ""
    if not supabase_url or not anon_key:
        return None

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": anon_key,
            },
        )
    if response.status_code != 200:
        return None
    return response.json()


async def send_password_recovery(email: str, redirect_to: str) -> bool:
    supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    anon_key = os.getenv("SUPABASE_ANON_KEY") or ""
    if not supabase_url or not anon_key:
        return False

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{supabase_url}/auth/v1/recover",
            headers={
                "apikey": anon_key,
                "Content-Type": "application/json",
            },
            json={"email": email, "redirect_to": redirect_to},
        )
    return response.status_code in {200, 201}


async def get_local_user_from_supabase_token(access_token: str, db: AsyncSession) -> User | None:
    payload = await fetch_supabase_user(access_token)
    if not payload:
        return None

    email = (payload.get("email") or "").strip().lower()
    supabase_id = payload.get("id")
    if not email and not supabase_id:
        return None

    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()
