"""Login com Google — OAuth 2.0 (fluxo de codigo de autorizacao).

Configuravel por env var. Sem credenciais, o botao nao aparece e as rotas
redirecionam de volta ao login. Defina no Railway:
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
E em Google Cloud Console > APIs e Servicos > Credenciais, autorize o redirect:
  https://www.agendazapuap.com.br/auth/google/callback
"""

import os
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email profile"


def google_enabled() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def authorization_url(state: str, redirect_uri: str) -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict | None:
    data = {
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_TOKEN_URL, data=data)
            return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


async def fetch_userinfo(access_token: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None
