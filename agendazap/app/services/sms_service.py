import logging
import os

import httpx

from app.services.whatsapp_service import format_whatsapp

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")


def format_sms_number(number: str) -> str:
    digits = format_whatsapp(number)
    return f"+{digits}"


async def send_sms(to: str, message: str) -> bool:
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        logger.warning("Twilio nao configurado, SMS nao enviado")
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                data={
                    "From": TWILIO_FROM_NUMBER,
                    "To": format_sms_number(to),
                    "Body": message,
                },
            )
            if response.status_code in {200, 201}:
                return True

            logger.error("Twilio retornou %s: %s", response.status_code, response.text)
            return False
    except Exception as exc:
        logger.error("Erro ao enviar SMS: %s", exc)
        return False


async def notify_client_cancellation_sms(client_phone: str, booking_data: dict) -> bool:
    message = (
        f"AgendaZap: seu agendamento com {booking_data['admin_name']} "
        f"em {booking_data['date']} as {booking_data['time']} foi cancelado."
    )
    return await send_sms(client_phone, message)
