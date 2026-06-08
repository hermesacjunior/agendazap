import httpx
import os
import logging
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "AgendaZap <noreply@agendazap.com.br>")
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br"))


def _is_configured(value: str, placeholder_prefixes: tuple[str, ...] = ()) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    return not any(value.startswith(prefix) for prefix in placeholder_prefixes)


async def send_email(to: str, subject: str, html: str) -> bool:
    """Envia email via Resend"""
    if not _is_configured(RESEND_API_KEY, ("re_xxxxx",)):
        logger.warning("RESEND_API_KEY não configurado, email não enviado")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": FROM_EMAIL,
                    "to": [to],
                    "subject": subject,
                    "html": html
                }
            )
            if response.status_code in {200, 201}:
                return True

            logger.error("Resend retornou %s: %s", response.status_code, response.text)
            return False
    except Exception as e:
        logger.error(f"Erro ao enviar email: {e}")
        return False


def booking_confirmation_html(booking_data: dict, is_admin: bool = False) -> str:
    if is_admin:
        return f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1a1a2e;">📅 Novo Agendamento</h2>
            <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0;">
                <p><strong>Cliente:</strong> {booking_data['client_name']}</p>
                <p><strong>Email:</strong> {booking_data['client_email']}</p>
                <p><strong>WhatsApp:</strong> {booking_data.get('client_whatsapp', 'Não informado')}</p>
                <p><strong>Data:</strong> {booking_data['date']}</p>
                <p><strong>Horário:</strong> {booking_data['time']}</p>
                <p><strong>Observações:</strong> {booking_data.get('notes', 'Nenhuma')}</p>
            </div>
            <p style="color: #666; font-size: 12px;">AgendaZap — Sistema de Agendamentos</p>
        </div>
        """
    else:
        return f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1a1a2e;">✅ Agendamento Confirmado!</h2>
            <p>Olá, <strong>{booking_data['client_name']}</strong>!</p>
            <div style="background: #f0fff4; border-left: 4px solid #38a169; border-radius: 4px; padding: 20px; margin: 20px 0;">
                <p><strong>Data:</strong> {booking_data['date']}</p>
                <p><strong>Horário:</strong> {booking_data['time']}</p>
                <p><strong>Com:</strong> {booking_data['admin_name']}</p>
            </div>
            <p>Para cancelar ou remarcar, entre em contato diretamente.</p>
            <p style="color: #666; font-size: 12px;">AgendaZap — Sistema de Agendamentos</p>
        </div>
        """


async def notify_admin_email(admin_email: str, booking_data: dict) -> bool:
    html = booking_confirmation_html(booking_data, is_admin=True)
    return await send_email(
        to=admin_email,
        subject=f"📅 Novo agendamento: {booking_data['client_name']} - {booking_data['date']}",
        html=html
    )


def booking_cancellation_html(booking_data: dict, is_admin: bool = False) -> str:
    if is_admin:
        return f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #1a1a2e;">Agendamento cancelado</h2>
            <div style="background: #fff5f5; border-left: 4px solid #e53e3e; border-radius: 4px; padding: 20px; margin: 20px 0;">
                <p><strong>Cliente:</strong> {booking_data['client_name']}</p>
                <p><strong>Email:</strong> {booking_data['client_email']}</p>
                <p><strong>WhatsApp:</strong> {booking_data.get('client_whatsapp', 'Nao informado')}</p>
                <p><strong>Data:</strong> {booking_data['date']}</p>
                <p><strong>Horario:</strong> {booking_data['time']}</p>
            </div>
            <p style="color: #666; font-size: 12px;">AgendaZap - Sistema de Agendamentos</p>
        </div>
        """

    return f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a1a2e;">Agendamento cancelado</h2>
        <p>Ola, <strong>{booking_data['client_name']}</strong>.</p>
        <div style="background: #fff5f5; border-left: 4px solid #e53e3e; border-radius: 4px; padding: 20px; margin: 20px 0;">
            <p>Seu agendamento foi cancelado.</p>
            <p><strong>Data:</strong> {booking_data['date']}</p>
            <p><strong>Horario:</strong> {booking_data['time']}</p>
            <p><strong>Com:</strong> {booking_data['admin_name']}</p>
        </div>
        <p>Para remarcar, acesse novamente a agenda ou entre em contato diretamente.</p>
        <p style="color: #666; font-size: 12px;">AgendaZap - Sistema de Agendamentos</p>
    </div>
    """


async def notify_admin_cancellation_email(admin_email: str, booking_data: dict) -> bool:
    html = booking_cancellation_html(booking_data, is_admin=True)
    return await send_email(
        to=admin_email,
        subject=f"Agendamento cancelado: {booking_data['client_name']} - {booking_data['date']}",
        html=html,
    )


async def notify_client_cancellation_email(client_email: str, booking_data: dict) -> bool:
    html = booking_cancellation_html(booking_data, is_admin=False)
    return await send_email(
        to=client_email,
        subject=f"Agendamento cancelado - {booking_data['date']} as {booking_data['time']}",
        html=html,
    )


async def notify_client_email(client_email: str, booking_data: dict) -> bool:
    html = booking_confirmation_html(booking_data, is_admin=False)
    return await send_email(
        to=client_email,
        subject=f"✅ Agendamento confirmado — {booking_data['date']} às {booking_data['time']}",
        html=html
    )
