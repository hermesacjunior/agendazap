"""Google reCAPTCHA v2 ("Nao sou um robo") — captcha anti-bot no cadastro.

Configuravel por env var. Enquanto as chaves nao estiverem definidas, o captcha
fica DESLIGADO e o cadastro funciona normalmente (verify_captcha devolve True).
Para ligar, defina no Railway:
  RECAPTCHA_SITE_KEY    (chave do site, publica, vai no formulario)
  RECAPTCHA_SECRET_KEY  (chave secreta, verificacao no servidor)
"""

import logging
import os

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

SITE_KEY = os.getenv("RECAPTCHA_SITE_KEY", "").strip()
SECRET_KEY = os.getenv("RECAPTCHA_SECRET_KEY", "").strip()
_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
# Campo que o widget reCAPTCHA injeta no formulario.
FORM_FIELD = "g-recaptcha-response"


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
                logger.error("reCAPTCHA siteverify status %s", resp.status_code)
                return False
            return bool(resp.json().get("success"))
    except Exception as exc:
        # Fail-closed: na duvida, bloqueia (a medida e justamente anti-abuso).
        logger.error("Erro ao verificar reCAPTCHA: %s", exc)
        return False
