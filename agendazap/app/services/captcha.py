"""Cloudflare Turnstile — captcha anti-bot no cadastro.

Configuravel por env var. Enquanto as chaves nao estiverem definidas, o captcha
fica DESLIGADO e o cadastro funciona normalmente (verify_captcha devolve True).
Para ligar, defina no Railway:
  TURNSTILE_SITE_KEY    (chave publica, vai no formulario)
  TURNSTILE_SECRET_KEY  (chave secreta, verificacao no servidor)
"""

import logging
import os

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "").strip()
SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# Campo que o widget injeta no formulario.
FORM_FIELD = "cf-turnstile-response"


def captcha_enabled() -> bool:
    return bool(SITE_KEY and SECRET_KEY)


def captcha_site_key() -> str:
    return SITE_KEY


async def verify_captcha(token: str, remote_ip: str | None = None) -> bool:
    # Nao configurado: nao bloqueia o cadastro.
    if not captcha_enabled():
        return True
    if not token:
        return False
    data = {"secret": SECRET_KEY, "response": token}
    if remote_ip and remote_ip != "unknown":
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_VERIFY_URL, data=data)
            if resp.status_code != 200:
                logger.error("Turnstile siteverify status %s", resp.status_code)
                return False
            return bool(resp.json().get("success"))
    except Exception as exc:
        # Fail-closed: na duvida, bloqueia (a medida e justamente anti-abuso).
        logger.error("Erro ao verificar Turnstile: %s", exc)
        return False
