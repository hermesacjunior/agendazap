import logging
from datetime import datetime, timedelta
from html import escape

import pytz
from sqlalchemy import select, and_

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.schedule_service import BRAZIL_TZ, utc_to_brazil
from app.services.email_service import send_email
from app.services.whatsapp_service import send_message

logger = logging.getLogger(__name__)


async def _today_items(db, user: User):
    """Compromissos confirmados do dia (horario local), de todas as agendas."""
    now_local = datetime.now(BRAZIL_TZ)
    start_local = BRAZIL_TZ.localize(datetime(now_local.year, now_local.month, now_local.day))
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(pytz.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(pytz.utc).replace(tzinfo=None)

    result = await db.execute(
        select(Booking).where(and_(
            Booking.user_id == user.id,
            Booking.status == BookingStatus.confirmed,
            Booking.start_datetime >= start_utc,
            Booking.start_datetime < end_utc,
        )).order_by(Booking.start_datetime)
    )
    bookings = result.scalars().all()

    sched_result = await db.execute(select(Schedule).where(Schedule.user_id == user.id))
    names = {s.id: s.name for s in sched_result.scalars().all()}

    items = [
        {
            "time": utc_to_brazil(b.start_datetime).strftime("%H:%M"),
            "client_name": b.client_name,
            "schedule": names.get(b.schedule_id, ""),
        }
        for b in bookings
    ]
    return items, now_local


def _digest_text(date_str: str, items: list[dict]) -> str:
    if not items:
        return f"📅 *Resumo do dia {date_str}*\n\nVocê não tem compromissos hoje. 🎉\n\n_AgendaZap_"
    linhas = "\n".join(f"⏰ *{i['time']}* — {i['client_name']}" for i in items)
    return f"📅 *Resumo do dia {date_str}*\n\nVocê tem {len(items)} compromisso(s):\n{linhas}\n\n_AgendaZap_"


def _digest_html(name: str, date_str: str, items: list[dict]) -> str:
    if items:
        linhas = "".join(
            f"<tr><td style='padding:6px 12px;font-weight:600'>{escape(i['time'])}</td>"
            f"<td style='padding:6px 12px'>{escape(i['client_name'])}</td>"
            f"<td style='padding:6px 12px;color:#666'>{escape(i['schedule'])}</td></tr>"
            for i in items
        )
        corpo = (
            f"<p>Você tem <strong>{len(items)}</strong> compromisso(s) hoje:</p>"
            f"<table style='border-collapse:collapse;width:100%'>{linhas}</table>"
        )
    else:
        corpo = "<p>Você não tem compromissos hoje. 🎉</p>"
    return (
        "<div style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px'>"
        f"<h2 style='color:#1a1a2e'>Resumo do dia {escape(date_str)}</h2>"
        f"<p>Olá, <strong>{escape(name)}</strong>!</p>{corpo}"
        "<p style='color:#666;font-size:12px'>AgendaZap - Sistema de Agendamentos</p></div>"
    )


async def send_user_digest(db, user: User, force_email: bool = False) -> bool:
    """Envia o resumo do dia pelos canais habilitados. Retorna True se enviou.

    force_email envia o e-mail mesmo com o canal desligado (usado no teste manual).
    """
    items, now_local = await _today_items(db, user)
    date_str = now_local.strftime("%d/%m/%Y")
    sent_any = False

    if user.daily_digest_email or force_email:
        if await send_email(user.email, f"Seus compromissos de hoje ({date_str})", _digest_html(user.name, date_str, items)):
            sent_any = True

    if (
        user.daily_digest_whatsapp
        and user.plan.value == "pro"
        and user.whatsapp
        and user.evolution_instance
        and user.whatsapp_connected
    ):
        if await send_message(user.evolution_instance, user.whatsapp, _digest_text(date_str, items)):
            sent_any = True

    return sent_any


async def run_daily_digests() -> None:
    """Job horario: envia o resumo a quem habilitou e cujo horario chegou."""
    async with AsyncSessionLocal() as db:
        now_local = datetime.now(BRAZIL_TZ)
        today = now_local.strftime("%Y-%m-%d")
        result = await db.execute(
            select(User).where(User.daily_digest_enabled == True, User.is_active == True)  # noqa: E712
        )
        users = result.scalars().all()
        for user in users:
            if user.daily_digest_hour != now_local.hour or user.daily_digest_last_sent == today:
                continue
            try:
                await send_user_digest(db, user)
            except Exception:
                logger.exception("Falha ao enviar resumo diario do usuario %s", user.id)
            user.daily_digest_last_sent = today
        await db.commit()
