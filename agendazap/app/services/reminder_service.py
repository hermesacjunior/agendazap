import logging
import os
from datetime import datetime, timedelta
from html import escape

import pytz
from sqlalchemy import select, and_, delete

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.schedule_service import BRAZIL_TZ, utc_to_brazil
from app.services.email_service import send_email
from app.services.whatsapp_service import send_message
from app.services.auth_service import create_booking_cancel_token
from app.services.push_service import notify_user

logger = logging.getLogger(__name__)
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br")).rstrip("/")


BOOKING_RETENTION_DAYS = 7


async def purge_old_bookings(retention_days: int = BOOKING_RETENTION_DAYS) -> int:
    """Remove agendamentos cuja data agendada ja passou ha mais de
    `retention_days` dias. Mantem o banco enxuto (historico antigo nao e
    necessario). Roda diariamente pelo scheduler. Retorna quantos removeu."""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                delete(Booking).where(Booking.start_datetime < cutoff)
            )
            await db.commit()
            removed = result.rowcount or 0
            if removed:
                logger.info(
                    "purge_old_bookings: %s agendamentos anteriores a %s removidos",
                    removed, cutoff.isoformat(),
                )
            return removed
        except Exception:
            logger.exception("Falha ao limpar agendamentos antigos")
            await db.rollback()
            return 0


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


def whatsapp_ready(user: User) -> bool:
    """True se o usuario pode receber o resumo pelo WhatsApp (pre-requisitos tecnicos)."""
    return bool(
        user.plan.value == "pro"
        and user.whatsapp
        and user.evolution_instance
        and user.whatsapp_connected
    )


async def send_digest_email(db, user: User) -> bool:
    """Envia o resumo do dia por e-mail (sem checar o toggle). Retorna True se enviou."""
    items, now_local = await _today_items(db, user)
    date_str = now_local.strftime("%d/%m/%Y")
    return await send_email(
        user.email,
        f"Seus compromissos de hoje ({date_str})",
        _digest_html(user.name, date_str, items),
    )


async def send_digest_whatsapp(db, user: User) -> bool:
    """Envia o resumo do dia pelo WhatsApp (sem checar o toggle). Retorna True se enviou.

    Pressupoe whatsapp_ready(user); o chamador deve validar antes para dar um erro claro.
    """
    items, now_local = await _today_items(db, user)
    date_str = now_local.strftime("%d/%m/%Y")
    return await send_message(user.evolution_instance, user.whatsapp, _digest_text(date_str, items))


async def send_user_digest(db, user: User, force_email: bool = False) -> bool:
    """Envia o resumo do dia pelos canais HABILITADOS (usado pelo cron). Retorna True se enviou.

    force_email envia o e-mail mesmo com o canal desligado.
    """
    sent_any = False
    if user.daily_digest_email or force_email:
        if await send_digest_email(db, user):
            sent_any = True
    if user.daily_digest_whatsapp and whatsapp_ready(user):
        if await send_digest_whatsapp(db, user):
            sent_any = True
    # Push nativo (no-op se o usuario nao tiver dispositivo inscrito).
    try:
        items, now_local = await _today_items(db, user)
        date_str = now_local.strftime("%d/%m/%Y")
        body = "Você não tem compromissos hoje. 🎉" if not items else f"Você tem {len(items)} compromisso(s) hoje."
        await notify_user(db, user.id, f"Resumo do dia {date_str}", body, "/admin/bookings")
    except Exception:
        logger.exception("Falha no push do resumo do usuario %s", user.id)
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
            if user.plan.value != "pro":
                continue
            if user.daily_digest_hour != now_local.hour or user.daily_digest_last_sent == today:
                continue
            try:
                await send_user_digest(db, user)
            except Exception:
                logger.exception("Falha ao enviar resumo diario do usuario %s", user.id)
            user.daily_digest_last_sent = today
        await db.commit()


async def _send_appointment_reminder(db, user: User, booking: Booking) -> None:
    local = utc_to_brazil(booking.start_datetime)
    date_str = local.strftime("%d/%m/%Y")
    time_str = local.strftime("%H:%M")
    cancel_url = f"{APP_URL}/b/cancelar/{create_booking_cancel_token(booking.id)}"

    if user.reminder_email and booking.client_email:
        html = (
            "<div style='font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px'>"
            "<h2 style='color:#1a1a2e'>Lembrete do seu agendamento</h2>"
            f"<p>Olá, <strong>{escape(booking.client_name)}</strong>!</p>"
            "<div style='background:#f0fff4;border-left:4px solid #38a169;border-radius:4px;padding:20px;margin:20px 0'>"
            f"<p><strong>Data:</strong> {escape(date_str)}</p>"
            f"<p><strong>Horario:</strong> {escape(time_str)}</p>"
            f"<p><strong>Com:</strong> {escape(user.name)}</p></div>"
            f"<p style='text-align:center;margin:24px 0'><a href='{escape(cancel_url)}' style='color:#e53e3e;font-size:14px'>Precisa cancelar? Clique aqui</a></p>"
            "<p style='color:#666;font-size:12px'>AgendaZap - Sistema de Agendamentos</p></div>"
        )
        await send_email(booking.client_email, f"Lembrete: agendamento {date_str} às {time_str}", html)

    if (
        user.reminder_whatsapp
        and user.plan.value == "pro"
        and user.evolution_instance
        and user.whatsapp_connected
        and booking.client_whatsapp
    ):
        msg = (
            "⏰ *Lembrete de agendamento*\n\n"
            f"Olá, *{booking.client_name}*!\n"
            "Você tem um horário marcado:\n"
            f"🗓️ *Data:* {date_str}\n⏰ *Horário:* {time_str}\n👤 *Com:* {user.name}\n\n"
            "_AgendaZap_"
        )
        await send_message(user.evolution_instance, booking.client_whatsapp, msg)

    # Push nativo para o dono lembrando do proprio compromisso.
    await notify_user(
        db, user.id,
        "Lembrete de compromisso",
        f"{booking.client_name} — {date_str} {time_str}",
        "/admin/bookings",
    )


async def run_appointment_reminders() -> None:
    """Job frequente: envia lembrete aos clientes cujos agendamentos entram na
    janela de X horas configurada pelo dono, sem repetir (reminder_sent)."""
    async with AsyncSessionLocal() as db:
        now_utc = datetime.utcnow()
        users = (
            await db.execute(
                select(User).where(User.reminder_enabled == True, User.is_active == True)  # noqa: E712
            )
        ).scalars().all()
        for user in users:
            if user.plan.value != "pro":
                continue
            window_end = now_utc + timedelta(hours=user.reminder_hours)
            result = await db.execute(
                select(Booking).where(and_(
                    Booking.user_id == user.id,
                    Booking.status == BookingStatus.confirmed,
                    Booking.reminder_sent == False,  # noqa: E712
                    Booking.start_datetime > now_utc,
                    Booking.start_datetime <= window_end,
                ))
            )
            for booking in result.scalars().all():
                try:
                    await _send_appointment_reminder(db, user, booking)
                except Exception:
                    logger.exception("Falha no lembrete do agendamento %s", booking.id)
                booking.reminder_sent = True
        await db.commit()
