import httpx
import os
from typing import Optional
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", os.getenv("VITE_API_URL", "https://api.agendazapuap.com.br")).rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY") or os.getenv("WHATSAPP_API_KEY", "")

QUIET_INSTANCE_SETTINGS = {
    "reject_call": False,
    "groups_ignore": True,
    "always_online": False,
    "read_messages": False,
    "read_status": False,
    "sync_full_history": False,
    "msg_call": "",
}

QUIET_INSTANCE_CREATE_OPTIONS = {
    "rejectCall": False,
    "groupsIgnore": True,
    "alwaysOnline": False,
    "readMessages": False,
    "readStatus": False,
    "syncFullHistory": False,
    "msgCall": "",
}


def _headers() -> dict:
    if not EVOLUTION_API_KEY:
        raise RuntimeError("EVOLUTION_API_KEY nao configurada")
    return {"apikey": EVOLUTION_API_KEY}


def extract_qrcode(data: dict) -> Optional[str]:
    """Extrai o QR Code dos formatos retornados pela Evolution API."""
    if not isinstance(data, dict):
        return None

    qrcode = data.get("qrcode")
    if isinstance(qrcode, dict):
        return qrcode.get("base64") or qrcode.get("code")
    if isinstance(qrcode, str):
        return qrcode

    return data.get("base64") or data.get("code")


def extract_pairing_code(data: dict) -> Optional[str]:
    """Extrai o codigo de pareamento quando a Evolution API retornar um."""
    if not isinstance(data, dict):
        return None

    pairing_code = data.get("pairingCode") or data.get("pairing_code")
    if isinstance(pairing_code, str) and pairing_code.strip():
        return pairing_code.strip()
    return None


def _raise_evolution_error(response: httpx.Response) -> None:
    try:
        data = response.json()
    except ValueError:
        data = response.text

    detail = data.get("message") if isinstance(data, dict) else data
    if isinstance(detail, list):
        detail = "; ".join(str(item) for item in detail)
    detail = detail or response.reason_phrase

    raise RuntimeError(f"Evolution API retornou {response.status_code}: {detail}")


def format_whatsapp(number: str) -> str:
    """Formata número para padrão Evolution API: 5511999999999"""
    digits = "".join(filter(str.isdigit, number))
    if not digits.startswith("55"):
        digits = "55" + digits
    return digits


async def create_instance(instance_name: str) -> dict:
    """Cria instância do WhatsApp para um usuário"""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{EVOLUTION_API_URL}/instance/create",
            headers=_headers(),
            json={
                "instanceName": instance_name,
                "qrcode": True,
                "integration": "WHATSAPP-BAILEYS",
                **QUIET_INSTANCE_CREATE_OPTIONS,
            }
        )
        if response.status_code == 403:
            logger.info("Instancia %s ja existe na Evolution API", instance_name)
            return {}
        if response.status_code >= 400:
            _raise_evolution_error(response)
        return response.json()


async def set_quiet_instance_settings(instance_name: str) -> bool:
    """Configura a instancia para nao sincronizar historico nem ler mensagens."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{EVOLUTION_API_URL}/settings/set/{instance_name}",
                headers=_headers(),
                json=QUIET_INSTANCE_CREATE_OPTIONS,
            )
            if response.status_code in {200, 201}:
                return True
            if response.status_code != 404:
                logger.warning(
                    "Evolution API nao aplicou settings silenciosos em %s: %s %s",
                    instance_name,
                    response.status_code,
                    response.text,
                )
    except Exception as exc:
        logger.warning("Erro ao configurar settings silenciosos em %s: %s", instance_name, exc)
    return False


async def connect_instance(instance_name: str, number: str = "") -> dict:
    """Inicia conexao e retorna dados de QR Code/codigo de pareamento."""
    async with httpx.AsyncClient(timeout=15) as client:
        params = {}
        if number:
            params["number"] = format_whatsapp(number)

        response = await client.get(
            f"{EVOLUTION_API_URL}/instance/connect/{instance_name}",
            headers=_headers(),
            params=params,
        )
        if response.status_code >= 400:
            _raise_evolution_error(response)
        return response.json()


async def get_qrcode(instance_name: str, number: str = "") -> Optional[str]:
    """Retorna QR code para conectar WhatsApp."""
    return extract_qrcode(await connect_instance(instance_name, number))


async def fetch_instances() -> list[dict]:
    """Lista instancias registradas na Evolution API."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"{EVOLUTION_API_URL}/instance/fetchInstances",
            headers=_headers(),
        )
        if response.status_code >= 400:
            _raise_evolution_error(response)
        data = response.json()
        return data if isinstance(data, list) else []


async def delete_disconnected_instances_with_prefix(prefix: str) -> None:
    """Remove tentativas antigas do mesmo usuario que ficaram presas."""
    for instance in await fetch_instances():
        name = instance.get("name") or instance.get("instanceName")
        state = instance.get("connectionStatus") or instance.get("state")
        if not name or not name.startswith(prefix):
            continue
        if state in {"open", "connected"}:
            continue
        try:
            await delete_instance(name)
        except Exception as exc:
            logger.warning("Erro ao remover instancia antiga %s: %s", name, exc)


async def get_connection_state(instance_name: str) -> dict:
    """Retorna estado normalizado da instancia na Evolution API."""
    state_data = {
        "state": "unknown",
        "connected": False,
        "owner_jid": None,
        "number": None,
        "profile_name": None,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{EVOLUTION_API_URL}/instance/connectionState/{instance_name}",
                headers=_headers()
            )
            if response.status_code >= 400:
                _raise_evolution_error(response)
            data = response.json()
            state = data.get("instance", {}).get("state") or data.get("state")
            if state:
                state_data["state"] = state

            fetch_response = await client.get(
                f"{EVOLUTION_API_URL}/instance/fetchInstances",
                headers=_headers(),
                params={"instanceName": instance_name},
            )
            if fetch_response.status_code < 400:
                instances = fetch_response.json()
                if isinstance(instances, list) and instances:
                    instance = instances[0]
                    state_data["state"] = (
                        instance.get("connectionStatus")
                        or instance.get("state")
                        or state_data["state"]
                    )
                    state_data["owner_jid"] = instance.get("ownerJid")
                    state_data["number"] = instance.get("number")
                    state_data["profile_name"] = instance.get("profileName")

            state_data["connected"] = state_data["state"] in {"open", "connected"}
            return state_data
    except Exception as e:
        logger.warning("Erro ao verificar conexao WhatsApp: %s", e)
        return state_data


async def check_connection(instance_name: str) -> bool:
    """Verifica se WhatsApp esta conectado."""
    state = await get_connection_state(instance_name)
    return state["connected"]


async def logout_instance(instance_name: str) -> None:
    """Desconecta a instancia na Evolution API quando possivel."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.delete(
            f"{EVOLUTION_API_URL}/instance/logout/{instance_name}",
            headers=_headers(),
        )
        if response.status_code >= 400 and response.status_code != 404:
            _raise_evolution_error(response)


async def delete_instance(instance_name: str) -> None:
    """Remove a instancia para permitir gerar um QR Code limpo."""
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.delete(
            f"{EVOLUTION_API_URL}/instance/delete/{instance_name}",
            headers=_headers(),
        )
        if response.status_code >= 400 and response.status_code != 404:
            _raise_evolution_error(response)


async def send_message(instance_name: str, to: str, message: str) -> bool:
    """Envia mensagem de texto via WhatsApp"""
    try:
        number = format_whatsapp(to)
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{EVOLUTION_API_URL}/message/sendText/{instance_name}",
                headers=_headers(),
                json={
                    "number": number,
                    "text": message
                }
            )
            return response.status_code == 201
    except Exception as e:
        logger.error(f"Erro ao enviar WhatsApp: {e}")
        return False


async def notify_admin_new_booking(
    instance_name: str,
    admin_whatsapp: str,
    booking_data: dict
) -> bool:
    """Notifica admin sobre novo agendamento"""
    message = (
        f"📅 *Novo Agendamento!*\n\n"
        f"👤 *Cliente:* {booking_data['client_name']}\n"
        f"📱 *WhatsApp:* {booking_data.get('client_whatsapp', 'Não informado')}\n"
        f"📧 *Email:* {booking_data['client_email']}\n"
        f"🗓️ *Data:* {booking_data['date']}\n"
        f"⏰ *Horário:* {booking_data['time']}\n"
        f"📝 *Obs:* {booking_data.get('notes', 'Nenhuma')}\n\n"
        f"_AgendaZap_ ✅"
    )
    return await send_message(instance_name, admin_whatsapp, message)


async def notify_client_confirmation(
    instance_name: str,
    client_whatsapp: str,
    booking_data: dict
) -> bool:
    """Confirma agendamento para o cliente"""
    message = (
        f"✅ *Agendamento Confirmado!*\n\n"
        f"Olá, *{booking_data['client_name']}*!\n\n"
        f"Seu agendamento foi confirmado:\n"
        f"🗓️ *Data:* {booking_data['date']}\n"
        f"⏰ *Horário:* {booking_data['time']}\n"
        f"👤 *Com:* {booking_data['admin_name']}\n\n"
        f"Para cancelar, entre em contato diretamente.\n\n"
        f"_AgendaZap_ ✅"
    )
    return await send_message(instance_name, client_whatsapp, message)


async def notify_cancellation(
    instance_name: str,
    whatsapp: str,
    booking_data: dict,
    is_admin: bool = False
) -> bool:
    """Notifica cancelamento"""
    if is_admin:
        message = (
            f"❌ *Agendamento Cancelado*\n\n"
            f"👤 *Cliente:* {booking_data['client_name']}\n"
            f"🗓️ *Data:* {booking_data['date']}\n"
            f"⏰ *Horário:* {booking_data['time']}\n\n"
            f"_AgendaZap_"
        )
    else:
        message = (
            f"❌ *Agendamento Cancelado*\n\n"
            f"Olá, *{booking_data['client_name']}*!\n"
            f"Seu agendamento de {booking_data['date']} às {booking_data['time']} foi cancelado.\n\n"
            f"_AgendaZap_"
        )
    return await send_message(instance_name, whatsapp, message)
