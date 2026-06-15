from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from datetime import datetime, timedelta
import json
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
    notify_client_cancellation_email,
)
from app.services.schedule_service import utc_to_brazil
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
    set_quiet_instance_settings,
)
from app.security import clean_int, clean_multiline, clean_phone, clean_text, install_template_security, require_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)
logger = logging.getLogger(__name__)
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br")).rstrip("/")


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


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_config(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Schedule).where(Schedule.user_id == current_user.id)
    )
    schedule = result.scalar_one_or_none()
    return templates.TemplateResponse("admin/schedule.html", {
        "request": request,
        "user": current_user,
        "schedule": schedule,
        "app_url": APP_URL,
    })


@router.post("/schedule")
async def save_schedule(
    request: Request,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db)
):
    data = await request.form()
    require_csrf_token(request, str(data.get("csrf_token") or ""))
    result = await db.execute(
        select(Schedule).where(Schedule.user_id == current_user.id)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        schedule = Schedule(user_id=current_user.id)
        db.add(schedule)

    schedule.name = clean_text(data.get("name"), max_length=100, default="Minha Agenda")
    schedule.slot_duration = clean_int(data.get("slot_duration"), default=60, minimum=15, maximum=240)
    schedule.buffer_time = clean_int(data.get("buffer_time"), default=0, minimum=0, maximum=120)
    schedule.max_advance_days = clean_int(data.get("max_advance_days"), default=30, minimum=1, maximum=365)

    # Parse availability
    availability = {}
    days = ["0", "1", "2", "3", "4", "5", "6"]
    for day in days:
        if data.get(f"day_{day}"):
            start = data.get(f"start_{day}", "09:00")
            end = data.get(f"end_{day}", "18:00")
            availability[day] = [{"start": start, "end": end}]

    schedule.weekly_availability = availability
    await db.commit()

    return RedirectResponse(url="/admin/dashboard?saved=1", status_code=302)


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

    return templates.TemplateResponse("admin/bookings.html", {
        "request": request,
        "user": current_user,
        "bookings": bookings,
        "app_url": APP_URL,
    })


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
    await db.commit()
    return RedirectResponse(url="/admin/profile?saved=1", status_code=302)
