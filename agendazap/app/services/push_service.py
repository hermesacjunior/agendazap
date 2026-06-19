"""Web Push (notificacoes nativas) para o PWA instalado.

Funciona em Android (Chrome/Edge) e iOS/iPadOS 16.4+ (apenas com o app
adicionado a Tela de Inicio). Usa chaves VAPID das env vars:
  VAPID_PUBLIC_KEY  -> base64url (applicationServerKey, vai para o frontend)
  VAPID_PRIVATE_KEY -> PEM em base64 (privada; usada para assinar o envio)
  VAPID_SUBJECT     -> mailto:...

O envio (pywebpush) e sincrono/bloqueante, entao roda em thread.
"""
import asyncio
import base64
import json
import logging
import os
import tempfile

from sqlalchemy import select, delete

from app.models.push import PushSubscription

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY_B64 = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:hacjdez@gmail.com")

_pem_path = None


def push_enabled() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY_B64)


def _private_key_path():
    """Escreve a chave privada PEM em arquivo temporario uma vez (pywebpush le de arquivo)."""
    global _pem_path
    if _pem_path:
        return _pem_path
    if not VAPID_PRIVATE_KEY_B64:
        return None
    pem = base64.b64decode(VAPID_PRIVATE_KEY_B64)
    f = tempfile.NamedTemporaryFile(prefix="vapid_", suffix=".pem", delete=False)
    f.write(pem)
    f.close()
    _pem_path = f.name
    return _pem_path


def _send_sync(subscription_info: dict, payload: str) -> str:
    """Envia um push. Retorna 'ok', 'gone' (inscricao expirada) ou 'fail'."""
    from pywebpush import webpush, WebPushException
    key = _private_key_path()
    if not key:
        return "fail"
    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=key,
            vapid_claims={"sub": VAPID_SUBJECT},
            ttl=3600,
        )
        return "ok"
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return "gone"
        logger.warning("Falha ao enviar push: %s", exc)
        return "fail"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Erro inesperado no push: %s", exc)
        return "fail"


async def notify_user(db, user_id: str, title: str, body: str, url: str = "/admin/dashboard") -> int:
    """Envia o push para todos os dispositivos do usuario. Remove inscricoes
    expiradas. Retorna quantos envios deram certo. Nunca levanta excecao."""
    if not push_enabled():
        return 0
    try:
        subs = (
            await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))
        ).scalars().all()
    except Exception:
        logger.exception("Erro ao carregar inscricoes de push de %s", user_id)
        return 0

    if not subs:
        return 0

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent = 0
    dead_endpoints = []
    for sub in subs:
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        result = await asyncio.to_thread(_send_sync, info, payload)
        if result == "ok":
            sent += 1
        elif result == "gone":
            dead_endpoints.append(sub.endpoint)

    if dead_endpoints:
        try:
            await db.execute(delete(PushSubscription).where(PushSubscription.endpoint.in_(dead_endpoints)))
            await db.commit()
        except Exception:
            logger.exception("Erro ao remover inscricoes de push expiradas")
    return sent
