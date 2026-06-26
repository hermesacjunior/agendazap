from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, delete
from datetime import datetime, timedelta, timezone
import json
import re
import secrets
import uuid
import logging
import os

from app.database import get_db
from app.models.user import User
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.auth_service import require_user
from app.services.email_service import (
    notify_admin_cancellation_email,
    notify_admin_email,
    notify_client_cancellation_email,
)
from app.services.schedule_service import BRAZIL_TZ, utc_to_brazil
from app.services.reminder_service import send_digest_email, send_digest_whatsapp, whatsapp_ready
from app.services.push_service import VAPID_PUBLIC_KEY, push_enabled
from app.models.push import PushSubscription
from app.services.sms_service import notify_client_cancellation_sms
from app.services.whatsapp_service import (
    connect_instance,
    create_instance,
    delete_disconnected_instances_with_prefix,
    delete_instance,
    extract_qrcode,
    extract_pairing_code,
    get_connection_state,
    get_qrcode,
    check_connection,
    logout_instance,
    notify_admin_new_booking,
    set_quiet_instance_settings,
)
from app.security import clean_int, clean_multiline, clean_phone, clean_text, install_template_security, require_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)
logger = logging.getLogger(__name__)
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br")).rstrip("/")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def _clean_time(raw, default: str) -> str:
    s = str(raw or "").strip()
    return s if _TIME_RE.match(s) else default


def _parse_blocked_field(raw) -> dict:
    """Valida o JSON de bloqueios vindo do formulario da agenda.

    Estrutura: {"days": ["YYYY-MM-DD"], "slots": {"YYYY-MM-DD": ["HH:MM"]}}.
    Descarta qualquer entrada malformada; dias inteiros tornam slots redundantes.
    """
    empty = {"days": [], "slots": {}}
    if not raw:
        return empty
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return empty
    if not isinstance(data, dict):
        return empty

    days = sorted({
        d for d in (data.get("days") or [])
        if isinstance(d, str) and _DATE_RE.match(d)
    })
    slots: dict[str, list[str]] = {}
    raw_slots = data.get("slots") or {}
    if isinstance(raw_slots, dict):
        for date, times in raw_slots.items():
            if not (isinstance(date, str) and _DATE_RE.match(date)) or date in days:
                continue
            if not isinstance(times, list):
                continue
            valid = sorted({t for t in times if isinstance(t, str) and _TIME_RE.match(t)})
            if valid:
                slots[date] = valid
    return {"days": days, "slots": slots}


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    # Stats
    result = await db.execute(
        select(func.count(Booking.id)).where(
            and_(Booking.user_id == current_user.id, Booking.status == BookingStatus.confirmed)
        )
    )
    total_bookings = result.scalar() or 0

    result = await db.execute(
        select(func.count(Booking.id)).where(
            and_(
                Booking.user_id == current_user.id,
                Booking.start_datetime >= datetime.utcnow(),
                Booking.status == BookingStatus.confirmed
            )
        )
    )
    upcoming_bookings = result.scalar() or 0

    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.user_id == current_user.id,
                Booking.start_datetime >= datetime.utcnow(),
                Booking.status == BookingStatus.confirmed
            )
        ).order_by(Booking.start_datetime).limit(5)
    )
    next_bookings = result.scalars().all()

    result = await db.execute(
        select(Schedule).where(Schedule.user_id == current_user.id)
    )
    schedules = result.scalars().all()

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "user": current_user,
        "total_bookings": total_bookings,
        "upcoming_bookings": upcoming_bookings,
        "next_bookings": next_bookings,
        "schedules": schedules,
        "app_url": APP_URL,
    })


# Limite de agendas por plano (a tabela Plan nao e usada para enforcement).
PLAN_SCHEDULE_LIMITS = {"free": 1, "basic": 1, "pro": 20}


def _max_schedules(user: User) -> int:
    return PLAN_SCHEDULE_LIMITS.get(user.plan.value, 1)


def _is_pro(user: User) -> bool:
    return user.plan.value == "pro"


async def _user_schedules(db: AsyncSession, user_id: str) -> list[Schedule]:
    result = await db.execute(
        select(Schedule).where(Schedule.user_id == user_id).order_by(Schedule.created_at)
    )
    return list(result.scalars().all())


def _apply_schedule_form(schedule: Schedule, data, allow_blocks: bool = True) -> None:
    schedule.name = clean_text(data.get("name"), max_length=100, default="Minha Agenda")
    schedule.slot_duration = clean_int(data.get("slot_duration"), default=60, minimum=15, maximum=240)
    schedule.buffer_time = clean_int(data.get("buffer_time"), default=0, minimum=0, maximum=120)
    schedule.max_advance_days = clean_int(data.get("max_advance_days"), default=30, minimum=1, maximum=365)

    availability = {}
    for day in ["0", "1", "2", "3", "4", "5", "6"]:
        if data.get(f"day_{day}"):
            availability[day] = [{
                "start": data.get(f"start_{day}", "09:00"),
                "end": data.get(f"end_{day}", "18:00"),
            }]
    schedule.weekly_availability = availability
    # Bloqueio de datas/horarios e horario de almoco sao recursos Pro.
    if allow_blocks:
        schedule.blocked_dates = _parse_blocked_field(data.get("blocked"))
        schedule.lunch_break_enabled = bool(data.get("lunch_break_enabled"))
        schedule.lunch_start = _clean_time(data.get("lunch_start"), "12:00")
        schedule.lunch_end = _clean_time(data.get("lunch_end"), "14:00")


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_config(
    request: Request,
    sid: str = "",
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    schedules = await _user_schedules(db, current_user.id)
    selected = next((s for s in schedules if s.id == sid), None) if sid else None
    if selected is None:
        selected = schedules[0] if schedules else None
    limit = _max_schedules(current_user)
    return templates.TemplateResponse("admin/schedule.html", {
        "request": request,
        "user": current_user,
        "schedule": selected,
        "schedules": schedules,
        "can_add": len(schedules) < limit,
        "max_schedules": limit,
        "app_url": APP_URL,
    })


@router.post("/schedule/new")
async def new_schedule(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    require_csrf_token(request, str(form.get("csrf_token") or ""))
    schedules = await _user_schedules(db, current_user.id)
    if len(schedules) >= _max_schedules(current_user):
        return RedirectResponse(url="/admin/schedule?err=limit", status_code=302)

    schedule = Schedule(
        user_id=current_user.id,
        name=f"Agenda {len(schedules) + 1}",
        weekly_availability={str(d): [{"start": "09:00", "end": "18:00"}] for d in range(5)},
    )
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return RedirectResponse(url=f"/admin/schedule?sid={schedule.id}", status_code=302)


@router.post("/schedule")
async def save_schedule(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    data = await request.form()
    require_csrf_token(request, str(data.get("csrf_token") or ""))
    schedule_id = str(data.get("schedule_id") or "")

    schedule = None
    if schedule_id:
        result = await db.execute(
            select(Schedule).where(and_(Schedule.id == schedule_id, Schedule.user_id == current_user.id))
        )
        schedule = result.scalar_one_or_none()
    if schedule is None:
        existing = await _user_schedules(db, current_user.id)
        if existing and len(existing) >= _max_schedules(current_user):
            schedule = existing[0]  # ja no limite: edita a primeira em vez de criar
        else:
            schedule = Schedule(user_id=current_user.id)
            db.add(schedule)

    _apply_schedule_form(schedule, data, allow_blocks=_is_pro(current_user))
    await db.commit()
    await db.refresh(schedule)
    return RedirectResponse(url=f"/admin/schedule?sid={schedule.id}&saved=1", status_code=302)


@router.post("/schedule/{schedule_id}/delete")
async def delete_schedule(
    schedule_id: str,
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    require_csrf_token(request, str(form.get("csrf_token") or ""))
    schedules = await _user_schedules(db, current_user.id)
    if len(schedules) <= 1:
        return RedirectResponse(url="/admin/schedule?err=last", status_code=302)
    target = next((s for s in schedules if s.id == schedule_id), None)
    if not target:
        raise HTTPException(status_code=404)
    await db.delete(target)  # cascade remove os agendamentos dessa agenda
    await db.commit()
    return RedirectResponse(url="/admin/schedule?deleted=1", status_code=302)


async def _own_schedule_or_404(db: AsyncSession, user: User, schedule_id: str) -> Schedule:
    result = await db.execute(
        select(Schedule).where(and_(Schedule.id == schedule_id, Schedule.user_id == user.id))
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404)
    return schedule


@router.post("/schedule/{schedule_id}/share")
async def share_schedule(
    schedule_id: str,
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    require_csrf_token(request, str(form.get("csrf_token") or ""))
    if not _is_pro(current_user):
        return RedirectResponse(url="/admin/schedule?err=pro", status_code=302)
    schedule = await _own_schedule_or_404(db, current_user, schedule_id)
    schedule.share_token = secrets.token_urlsafe(24)
    await db.commit()
    return RedirectResponse(url=f"/admin/schedule?sid={schedule.id}&shared=1", status_code=302)


@router.post("/schedule/{schedule_id}/unshare")
async def unshare_schedule(
    schedule_id: str,
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    require_csrf_token(request, str(form.get("csrf_token") or ""))
    schedule = await _own_schedule_or_404(db, current_user, schedule_id)
    schedule.share_token = None
    await db.commit()
    return RedirectResponse(url=f"/admin/schedule?sid={schedule.id}", status_code=302)


@router.get("/bookings", response_class=HTMLResponse)
async def bookings_list(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Booking).where(Booking.user_id == current_user.id)
        .order_by(Booking.start_datetime.desc())
    )
    bookings = result.scalars().all()
    schedules = await _user_schedules(db, current_user.id)

    return templates.TemplateResponse("admin/bookings.html", {
        "request": request,
        "user": current_user,
        "bookings": bookings,
        "schedules": schedules,
        "schedule_names": {s.id: s.name for s in schedules},
        "app_url": APP_URL,
    })


@router.post("/bookings/new")
async def create_own_booking(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    data = await request.form()
    require_csrf_token(request, str(data.get("csrf_token") or ""))
    schedule_id = str(data.get("schedule_id") or "")
    date_str = str(data.get("date_str") or "")
    time_str = str(data.get("time_str") or "")
    title = clean_text(data.get("title"), max_length=100, default="Compromisso")
    notes = clean_multiline(data.get("notes"), max_length=1000)
    duration = clean_int(data.get("duration"), default=0, minimum=0, maximum=1440)

    # Resolve a agenda (precisa ser do proprio usuario).
    schedule = None
    if schedule_id:
        result = await db.execute(
            select(Schedule).where(and_(Schedule.id == schedule_id, Schedule.user_id == current_user.id))
        )
        schedule = result.scalar_one_or_none()
    if schedule is None:
        schedules = await _user_schedules(db, current_user.id)
        schedule = schedules[0] if schedules else None
    if not _is_pro(current_user):
        return RedirectResponse(url="/admin/bookings?err=pro", status_code=302)
    if schedule is None:
        return RedirectResponse(url="/admin/bookings?err=noagenda", status_code=302)

    try:
        naive_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        local_start = BRAZIL_TZ.localize(naive_start)
        minutes = duration or schedule.slot_duration
        utc_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        utc_end = utc_start + timedelta(minutes=minutes)
    except ValueError:
        return RedirectResponse(url="/admin/bookings?err=data", status_code=302)

    # Conflito por sobreposicao com qualquer agendamento ativo da mesma agenda.
    result = await db.execute(
        select(Booking).where(and_(
            Booking.schedule_id == schedule.id,
            Booking.start_datetime < utc_end,
            Booking.end_datetime > utc_start,
            Booking.status != BookingStatus.cancelled,
        ))
    )
    if result.scalar_one_or_none():
        return RedirectResponse(url="/admin/bookings?err=conflito", status_code=302)

    booking = Booking(
        user_id=current_user.id,
        schedule_id=schedule.id,
        client_name=title,
        client_email=current_user.email,
        client_whatsapp=current_user.whatsapp or "",
        client_notes=notes,
        start_datetime=utc_start,
        end_datetime=utc_end,
        status=BookingStatus.confirmed,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    # Notifica o proprio dono (mesma logica do agendamento publico) e registra
    # os flags para a coluna "Notificações" refletir o que foi enviado.
    booking_data = {
        "client_name": title,
        "client_email": current_user.email,
        "client_whatsapp": current_user.whatsapp or "Não informado",
        "admin_name": current_user.name,
        "date": local_start.strftime("%d/%m/%Y"),
        "time": local_start.strftime("%H:%M"),
        "notes": notes or "Nenhuma",
    }
    try:
        if (
            current_user.plan.value == "pro"
            and current_user.whatsapp
            and current_user.evolution_instance
            and current_user.whatsapp_connected
        ):
            booking.whatsapp_sent_admin = await notify_admin_new_booking(
                current_user.evolution_instance, current_user.whatsapp, booking_data
            )
        if current_user.email_notifications:
            booking.email_sent_admin = await notify_admin_email(current_user.email, booking_data)
        await db.commit()
    except Exception:
        logger.exception("Falha ao notificar self-booking do usuario %s", current_user.id)

    return RedirectResponse(url="/admin/bookings?created=1", status_code=302)


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: str,
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    require_csrf_token(request, str(form.get("csrf_token") or ""))
    result = await db.execute(
        select(Booking).where(
            and_(Booking.id == booking_id, Booking.user_id == current_user.id)
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404)

    booking.status = BookingStatus.cancelled
    local_start = utc_to_brazil(booking.start_datetime)
    booking_data = {
        "client_name": booking.client_name,
        "client_email": booking.client_email,
        "client_whatsapp": booking.client_whatsapp,
        "admin_name": current_user.name,
        "date": local_start.strftime("%d/%m/%Y"),
        "time": local_start.strftime("%H:%M"),
    }

    try:
        if current_user.email_notifications:
            booking.email_sent_admin = await notify_admin_cancellation_email(
                current_user.email, booking_data
            )

        if booking.client_email:
            booking.email_sent_client = await notify_client_cancellation_email(
                booking.client_email, booking_data
            )

        if current_user.plan.value == "pro":
            if current_user.whatsapp and current_user.evolution_instance and current_user.whatsapp_connected:
                from app.services.whatsapp_service import notify_cancellation

                booking.whatsapp_sent_admin = await notify_cancellation(
                    current_user.evolution_instance,
                    current_user.whatsapp,
                    booking_data,
                    is_admin=True,
                )

            if booking.client_whatsapp:
                await notify_client_cancellation_sms(booking.client_whatsapp, booking_data)
    except Exception:
        pass

    await db.commit()
    return RedirectResponse(url="/admin/bookings", status_code=302)


@router.post("/bookings/{booking_id}/delete")
async def delete_cancelled_booking(
    booking_id: str,
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    form = await request.form()
    require_csrf_token(request, str(form.get("csrf_token") or ""))
    result = await db.execute(
        select(Booking).where(
            and_(Booking.id == booking_id, Booking.user_id == current_user.id)
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404)

    if booking.status != BookingStatus.cancelled:
        raise HTTPException(
            status_code=400,
            detail="Apenas agendamentos cancelados podem ser excluidos.",
        )

    await db.delete(booking)
    await db.commit()
    return RedirectResponse(url="/admin/bookings?deleted=1", status_code=302)


@router.get("/whatsapp", response_class=HTMLResponse)
async def whatsapp_setup(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    is_connected = False
    if current_user.evolution_instance:
        is_connected = await check_connection(current_user.evolution_instance)
        if is_connected != current_user.whatsapp_connected:
            current_user.whatsapp_connected = is_connected
            await db.commit()

    return templates.TemplateResponse("admin/whatsapp.html", {
        "request": request,
        "user": current_user,
        "is_connected": is_connected,
    })


@router.post("/whatsapp/connect")
async def connect_whatsapp(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    data = await request.form()
    require_csrf_token(request, str(data.get("csrf_token") or ""))
    whatsapp_number = clean_phone(data.get("whatsapp") or current_user.whatsapp or "")
    instance_prefix = f"agendazap-{current_user.id[:8]}"
    instance_name = f"{instance_prefix}-{uuid.uuid4().hex[:6]}"

    try:
        if current_user.evolution_instance:
            state = await get_connection_state(current_user.evolution_instance)
            if state["connected"]:
                return JSONResponse(
                    {"error": "Este WhatsApp ja esta conectado."},
                    status_code=409,
                )

        await delete_disconnected_instances_with_prefix(instance_prefix)

        created_instance = await create_instance(instance_name)
        await set_quiet_instance_settings(instance_name)
        current_user.evolution_instance = instance_name
        current_user.whatsapp_connected = False
        if whatsapp_number:
            current_user.whatsapp = whatsapp_number
        await db.commit()

        qrcode = extract_qrcode(created_instance)
        pairing_code = extract_pairing_code(created_instance)
        count = created_instance.get("count") if isinstance(created_instance, dict) else None

        if not qrcode or (whatsapp_number and not pairing_code):
            connect_data = await connect_instance(instance_name, whatsapp_number)
            qrcode = qrcode or extract_qrcode(connect_data)
            pairing_code = pairing_code or extract_pairing_code(connect_data)
            count = connect_data.get("count", count)

        # Algumas versoes da Evolution demoram um instante para popular o QR.
        if not qrcode:
            qrcode = await get_qrcode(instance_name, whatsapp_number)
    except Exception as exc:
        logger.warning("Erro ao conectar WhatsApp do usuario %s: %s", current_user.id, exc)
        return JSONResponse(
            {"error": "Erro ao conectar com a Evolution API. Verifique a configuracao no servidor."},
            status_code=500,
        )

    if not qrcode:
        return JSONResponse(
            {
                "error": (
                    "A Evolution API respondeu, mas ainda nao retornou o QR Code. "
                    "Tente novamente em alguns segundos."
                ),
                "instance": instance_name,
            },
            status_code=502,
        )

    return JSONResponse({
        "qrcode": qrcode,
        "pairing_code": pairing_code,
        "count": count,
        "instance": instance_name,
    })


@router.get("/whatsapp/status")
async def whatsapp_status(
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    if not current_user.evolution_instance:
        return JSONResponse({"connected": False, "state": "not_created"})

    state = await get_connection_state(current_user.evolution_instance)
    connected = state["connected"]
    if connected != current_user.whatsapp_connected:
        current_user.whatsapp_connected = connected
        await db.commit()

    return JSONResponse({
        "connected": connected,
        "state": state["state"],
        "number": state["number"],
        "profile_name": state["profile_name"],
    })


@router.post("/whatsapp/silence")
async def silence_whatsapp(
    request: Request,
    current_user: User = Depends(require_user),
):
    require_csrf_token(request, request.headers.get("x-csrf-token"))
    if not current_user.evolution_instance:
        return JSONResponse({"ok": False, "error": "Nenhuma instancia conectada."}, status_code=404)

    ok = await set_quiet_instance_settings(current_user.evolution_instance)
    return JSONResponse({"ok": ok})


@router.post("/whatsapp/reset")
async def reset_whatsapp(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, request.headers.get("x-csrf-token"))
    instance_name = current_user.evolution_instance
    if instance_name:
        try:
            await logout_instance(instance_name)
        except Exception:
            pass
        try:
            await delete_instance(instance_name)
        except Exception as exc:
            logger.warning("Erro ao remover instancia WhatsApp do usuario %s: %s", current_user.id, exc)
            return JSONResponse(
                {"error": "Erro ao remover instancia na Evolution API."},
                status_code=500,
            )
    else:
        try:
            await delete_disconnected_instances_with_prefix(f"agendazap-{current_user.id[:8]}")
        except Exception:
            pass

    current_user.evolution_instance = None
    current_user.whatsapp_connected = False
    await db.commit()
    return JSONResponse({"ok": True})


@router.get("/profile", response_class=HTMLResponse)
async def profile(
    request: Request,
    current_user: User = Depends(require_user)
):
    return templates.TemplateResponse("admin/profile.html", {
        "request": request,
        "user": current_user,
        "app_url": APP_URL,
        "vapid_public_key": VAPID_PUBLIC_KEY,
        "push_enabled": push_enabled(),
    })


@router.post("/profile")
async def save_profile(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    data = await request.form()
    require_csrf_token(request, str(data.get("csrf_token") or ""))
    current_user.name = clean_text(data.get("name"), max_length=100, default=current_user.name)
    current_user.whatsapp = clean_phone(data.get("whatsapp") or current_user.whatsapp)
    current_user.bio = clean_multiline(data.get("bio"), max_length=1000)
    # Foto de perfil (data URL redimensionada no cliente). Campo vazio => remove;
    # so aceita data:image/ dentro de um limite de tamanho (defesa extra alem do
    # limite de corpo do middleware). Qualquer outra coisa preserva o atual.
    avatar_raw = (data.get("avatar") or "").strip()
    if avatar_raw == "":
        current_user.avatar = None
    elif avatar_raw.startswith("data:image/") and len(avatar_raw) <= 300_000:
        current_user.avatar = avatar_raw
    current_user.email_notifications = bool(data.get("email_notifications"))
    # Resumo diario e lembretes sao recursos Pro: nao-Pro nunca fica ativo.
    pro = _is_pro(current_user)
    current_user.daily_digest_enabled = bool(data.get("daily_digest_enabled")) and pro
    current_user.daily_digest_email = bool(data.get("daily_digest_email"))
    current_user.daily_digest_whatsapp = bool(data.get("daily_digest_whatsapp"))
    current_user.daily_digest_hour = clean_int(data.get("daily_digest_hour"), default=7, minimum=0, maximum=23)
    current_user.reminder_enabled = bool(data.get("reminder_enabled")) and pro
    current_user.reminder_email = bool(data.get("reminder_email"))
    current_user.reminder_whatsapp = bool(data.get("reminder_whatsapp"))
    current_user.reminder_hours = clean_int(data.get("reminder_hours"), default=24, minimum=1, maximum=168)
    await db.commit()
    return RedirectResponse(url="/admin/profile?saved=1", status_code=302)


@router.post("/push/subscribe")
async def push_subscribe(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, request.headers.get("x-csrf-token"))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Dados inválidos."}, status_code=400)
    endpoint = (body or {}).get("endpoint")
    keys = (body or {}).get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")
    if not endpoint or not p256dh or not auth:
        return JSONResponse({"ok": False, "error": "Inscrição incompleta."}, status_code=400)

    existing = (
        await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    ).scalar_one_or_none()
    if existing:
        existing.user_id = current_user.id
        existing.p256dh = p256dh
        existing.auth = auth
    else:
        db.add(PushSubscription(user_id=current_user.id, endpoint=endpoint, p256dh=p256dh, auth=auth))
    await db.commit()
    return JSONResponse({"ok": True})


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, request.headers.get("x-csrf-token"))
    try:
        body = await request.json()
    except Exception:
        body = {}
    endpoint = (body or {}).get("endpoint")
    if endpoint:
        await db.execute(
            delete(PushSubscription).where(and_(
                PushSubscription.endpoint == endpoint,
                PushSubscription.user_id == current_user.id,
            ))
        )
        await db.commit()
    return JSONResponse({"ok": True})


@router.post("/profile/digest/email")
async def send_digest_email_now(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, request.headers.get("x-csrf-token"))
    if not _is_pro(current_user):
        return JSONResponse({"ok": False, "error": "Recurso disponível no plano Pro."}, status_code=403)
    try:
        sent = await send_digest_email(db, current_user)
    except Exception:
        logger.exception("Erro ao enviar resumo por e-mail do usuario %s", current_user.id)
        sent = False
    if sent:
        return JSONResponse({"ok": True})
    return JSONResponse(
        {"ok": False, "error": "Falha ao enviar. Verifique a configuracao de e-mail no servidor."},
        status_code=502,
    )


@router.post("/profile/digest/whatsapp")
async def send_digest_whatsapp_now(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, request.headers.get("x-csrf-token"))
    if not _is_pro(current_user):
        return JSONResponse({"ok": False, "error": "Recurso disponível no plano Pro."}, status_code=403)
    if not whatsapp_ready(current_user):
        return JSONResponse(
            {"ok": False, "error": "Conecte seu WhatsApp e cadastre seu número no perfil antes de enviar."},
            status_code=400,
        )
    try:
        sent = await send_digest_whatsapp(db, current_user)
    except Exception:
        logger.exception("Erro ao enviar resumo por WhatsApp do usuario %s", current_user.id)
        sent = False
    if sent:
        return JSONResponse({"ok": True})
    return JSONResponse(
        {"ok": False, "error": "Falha ao enviar pelo WhatsApp. Verifique a conexão e tente novamente."},
        status_code=502,
    )
