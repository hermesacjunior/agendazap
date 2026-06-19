from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from datetime import datetime, date
import logging
import os
import pytz

from app.database import get_db
from app.models.user import User
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.schedule_service import get_available_slots, get_month_availability
from app.services.schedule_service import utc_to_brazil
from app.services.whatsapp_service import notify_admin_new_booking
from app.services.email_service import (
    notify_admin_email,
    notify_client_email,
    notify_admin_cancellation_email,
    notify_client_cancellation_email,
)
from app.services.auth_service import create_booking_cancel_token, decode_booking_cancel_token
from app.services.push_service import notify_user
from app.security import clean_multiline, clean_phone, clean_text, install_template_security, require_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)
BRAZIL_TZ = pytz.timezone("America/Sao_Paulo")
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br")).rstrip("/")
logger = logging.getLogger(__name__)


async def free_plan_has_reached_limit(user: User, db: AsyncSession) -> bool:
    if user.plan.value != "free":
        return False

    result = await db.execute(
        select(func.count(Booking.id)).where(
            and_(
                Booking.user_id == user.id,
                Booking.status != BookingStatus.cancelled,
            )
        )
    )
    return (result.scalar() or 0) >= 1


async def basic_plan_has_reached_month_limit(user: User, target_start_utc: datetime, db: AsyncSession) -> bool:
    if user.plan.value != "basic":
        return False

    local_start = target_start_utc.astimezone(BRAZIL_TZ)
    month_start = BRAZIL_TZ.localize(datetime(local_start.year, local_start.month, 1))
    if local_start.month == 12:
        next_month = BRAZIL_TZ.localize(datetime(local_start.year + 1, 1, 1))
    else:
        next_month = BRAZIL_TZ.localize(datetime(local_start.year, local_start.month + 1, 1))

    result = await db.execute(
        select(func.count(Booking.id)).where(
            and_(
                Booking.user_id == user.id,
                Booking.start_datetime >= month_start.astimezone(pytz.utc).replace(tzinfo=None),
                Booking.start_datetime < next_month.astimezone(pytz.utc).replace(tzinfo=None),
                Booking.status != BookingStatus.cancelled,
            )
        )
    )
    return (result.scalar() or 0) >= 100


async def _active_schedules(db: AsyncSession, user_id: str) -> list[Schedule]:
    result = await db.execute(
        select(Schedule)
        .where(Schedule.user_id == user_id, Schedule.is_active == True)
        .order_by(Schedule.created_at)
    )
    return list(result.scalars().all())


async def _pick_schedule(db: AsyncSession, user_id: str, schedule_id: str = "") -> Schedule | None:
    """Resolve a agenda do fluxo publico.

    Com id: a agenda correspondente (ou None se invalida). Sem id: a unica
    agenda ativa, ou None quando ha varias (exige escolha) ou nenhuma.
    """
    schedules = await _active_schedules(db, user_id)
    if schedule_id:
        return next((s for s in schedules if s.id == schedule_id), None)
    return schedules[0] if len(schedules) == 1 else None


async def _booking_from_cancel_token(db: AsyncSession, token: str) -> Booking | None:
    booking_id = decode_booking_cancel_token(token)
    if not booking_id:
        return None
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        return None
    # Cancelamento self-service e recurso Pro: vale conforme o plano do dono.
    owner = (await db.execute(select(User).where(User.id == booking.user_id))).scalar_one_or_none()
    if not owner or owner.plan.value != "pro":
        return None
    return booking


@router.get("/cancelar/{token}", response_class=HTMLResponse)
async def cancel_booking_page(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    booking = await _booking_from_cancel_token(db, token)
    if not booking:
        return templates.TemplateResponse("public/cancel.html", {
            "request": request, "error": "Link de cancelamento inválido ou expirado.",
        })
    if booking.status == BookingStatus.cancelled:
        return templates.TemplateResponse("public/cancel.html", {"request": request, "done": True})
    local = utc_to_brazil(booking.start_datetime)
    return templates.TemplateResponse("public/cancel.html", {
        "request": request,
        "token": token,
        "client_name": booking.client_name,
        "date": local.strftime("%d/%m/%Y"),
        "time": local.strftime("%H:%M"),
    })


@router.post("/cancelar/{token}", response_class=HTMLResponse)
async def cancel_booking_action(
    token: str,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    booking = await _booking_from_cancel_token(db, token)
    if not booking:
        return templates.TemplateResponse("public/cancel.html", {
            "request": request, "error": "Link de cancelamento inválido ou expirado.",
        })

    if booking.status != BookingStatus.cancelled:
        booking.status = BookingStatus.cancelled
        owner = (
            await db.execute(select(User).where(User.id == booking.user_id))
        ).scalar_one_or_none()
        local = utc_to_brazil(booking.start_datetime)
        data = {
            "client_name": booking.client_name,
            "client_email": booking.client_email,
            "client_whatsapp": booking.client_whatsapp,
            "admin_name": owner.name if owner else "",
            "date": local.strftime("%d/%m/%Y"),
            "time": local.strftime("%H:%M"),
        }
        await db.commit()
        try:
            if owner and owner.email_notifications:
                await notify_admin_cancellation_email(owner.email, data)
            if booking.client_email:
                await notify_client_cancellation_email(booking.client_email, data)
        except Exception:
            pass
        if owner:
            await notify_user(
                db, owner.id,
                "Agendamento cancelado",
                f"{booking.client_name} — {data['date']} {data['time']}",
                "/admin/bookings",
            )

    return templates.TemplateResponse("public/cancel.html", {"request": request, "done": True})


@router.get("/{slug}", response_class=HTMLResponse)
async def public_booking_page(
    slug: str,
    request: Request,
    agenda: str = "",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Agenda não encontrada")

    schedules = await _active_schedules(db, user.id)
    if not schedules:
        raise HTTPException(status_code=404, detail="Agenda não disponível")

    if agenda:
        selected = next((s for s in schedules if s.id == agenda), None)
    elif len(schedules) == 1:
        selected = schedules[0]
    else:
        selected = None

    # Varias agendas e nenhuma escolhida: mostra o seletor.
    if selected is None:
        return templates.TemplateResponse("public/select_agenda.html", {
            "request": request,
            "profile": user,
            "schedules": schedules,
        })

    free_limit_reached = await free_plan_has_reached_limit(user, db)

    return templates.TemplateResponse("public/booking.html", {
        "request": request,
        "profile": user,
        "schedule": selected,
        "free_limit_reached": free_limit_reached,
    })


@router.get("/{slug}/slots")
async def get_slots(
    slug: str,
    date_str: str,
    schedule_id: str = "",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)

    schedule = await _pick_schedule(db, user.id, schedule_id)
    if not schedule:
        return JSONResponse({"slots": []})

    if await free_plan_has_reached_limit(user, db):
        return JSONResponse({"slots": [], "duration": schedule.slot_duration})

    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data inválida")

    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.schedule_id == schedule.id,
                Booking.status != BookingStatus.cancelled
            )
        )
    )
    bookings = result.scalars().all()
    slots = get_available_slots(schedule, target_date, bookings)
    return JSONResponse({"slots": slots, "duration": schedule.slot_duration})


@router.get("/{slug}/availability")
async def get_availability(
    slug: str,
    year: int,
    month: int,
    schedule_id: str = "",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)

    schedule = await _pick_schedule(db, user.id, schedule_id)
    if not schedule:
        return JSONResponse({"availability": {}})

    if await free_plan_has_reached_limit(user, db):
        return JSONResponse({"availability": {}})

    availability = await get_month_availability(schedule, year, month, db)
    return JSONResponse({"availability": availability})


@router.post("/{slug}/book")
async def create_booking(
    slug: str,
    request: Request,
    client_name: str = Form(...),
    client_email: str = Form(...),
    client_whatsapp: str = Form(""),
    date_str: str = Form(...),
    time_str: str = Form(...),
    notes: str = Form(""),
    schedule_id: str = Form(""),
    website: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, csrf_token)
    # Honeypot: campo escondido que humanos nunca preenchem; se vier preenchido,
    # e um bot — descarta silenciosamente sem criar agendamento.
    if website.strip():
        return RedirectResponse(url=f"/b/{slug}", status_code=302)
    client_name = clean_text(client_name, max_length=100)
    client_email = client_email.strip().lower()
    client_whatsapp = clean_phone(client_whatsapp)
    notes = clean_multiline(notes, max_length=1000)

    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)

    schedule = await _pick_schedule(db, user.id, schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Agenda não encontrada")

    if await free_plan_has_reached_limit(user, db):
        return templates.TemplateResponse("public/booking.html", {
            "request": request,
            "profile": user,
            "schedule": schedule,
            "free_limit_reached": True,
            "error": "Esta agenda gratuita ja atingiu o limite de 1 agendamento ativo.",
        })

    # Parse datetime
    try:
        naive_start = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        local_start = BRAZIL_TZ.localize(naive_start)
        utc_start = local_start.astimezone(pytz.utc)
        from datetime import timedelta
        utc_end = utc_start + timedelta(minutes=schedule.slot_duration)
        utc_start_db = utc_start.replace(tzinfo=None)
        utc_end_db = utc_end.replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data/hora inválida")

    if await basic_plan_has_reached_month_limit(user, utc_start, db):
        return templates.TemplateResponse("public/booking.html", {
            "request": request,
            "profile": user,
            "schedule": schedule,
            "error": "Esta agenda Basic ja atingiu o limite de 100 agendamentos neste mes.",
        })

    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.schedule_id == schedule.id,
                Booking.status != BookingStatus.cancelled
            )
        )
    )
    existing_bookings = result.scalars().all()
    if time_str not in get_available_slots(schedule, local_start.date(), existing_bookings):
        return templates.TemplateResponse("public/booking.html", {
            "request": request,
            "profile": user,
            "schedule": schedule,
            "error": "Este horario nao esta disponivel. Por favor, escolha outro.",
        })

    # Verificar conflito
    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.schedule_id == schedule.id,
                Booking.start_datetime < utc_end_db,
                Booking.end_datetime > utc_start_db,
                Booking.status != BookingStatus.cancelled
            )
        )
    )
    if result.scalar_one_or_none():
        return templates.TemplateResponse("public/booking.html", {
            "request": request,
            "profile": user,
            "schedule": schedule,
            "error": "Este horário não está mais disponível. Por favor, escolha outro.",
        })

    booking = Booking(
        user_id=user.id,
        schedule_id=schedule.id,
        client_name=client_name,
        client_email=client_email,
        client_whatsapp=client_whatsapp,
        client_notes=notes,
        start_datetime=utc_start_db,
        end_datetime=utc_end_db,
        status=BookingStatus.confirmed,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    # Formatar dados para notificação
    booking_data = {
        "client_name": client_name,
        "client_email": client_email,
        "client_whatsapp": client_whatsapp,
        "admin_name": user.name,
        "date": local_start.strftime("%d/%m/%Y"),
        "time": local_start.strftime("%H:%M"),
        "notes": notes,
        # Link para o cliente cancelar sozinho (recurso Pro do dono da agenda).
        "cancel_url": (
            f"{APP_URL}/b/cancelar/{create_booking_cancel_token(booking.id)}"
            if user.plan.value == "pro" else ""
        ),
    }

    # Enviar notificações (não bloqueia se falhar)
    try:
        can_use_whatsapp = user.plan.value == "pro"
        # WhatsApp para admin
        if can_use_whatsapp and user.whatsapp and user.evolution_instance and user.whatsapp_connected:
            sent = await notify_admin_new_booking(
                user.evolution_instance, user.whatsapp, booking_data
            )
            booking.whatsapp_sent_admin = sent

        # Email para admin (respeita a preferencia do dono da agenda)
        if user.email_notifications:
            booking.email_sent_admin = await notify_admin_email(user.email, booking_data)

        # Email de confirmacao para o cliente
        if client_email:
            booking.email_sent_client = await notify_client_email(client_email, booking_data)

        await db.commit()
    except Exception:
        pass  # Notificações não devem quebrar o agendamento

    # Push nativo para o dono (PWA instalado).
    await notify_user(
        db, user.id,
        "Novo agendamento",
        f"{client_name} — {local_start.strftime('%d/%m %H:%M')}",
        "/admin/bookings",
    )

    return RedirectResponse(
        url=f"/b/{slug}/success?booking_id={booking.id}",
        status_code=302
    )


@router.get("/{slug}/success", response_class=HTMLResponse)
async def booking_success(
    slug: str,
    request: Request,
    booking_id: str = "",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    booking = None
    booking_date = "-"
    booking_time = "-"
    cancel_token = ""
    if user and booking_id:
        result = await db.execute(
            select(Booking).where(and_(Booking.id == booking_id, Booking.user_id == user.id))
        )
        booking = result.scalar_one_or_none()
        if booking:
            local_start = utc_to_brazil(booking.start_datetime)
            booking_date = local_start.strftime("%d/%m/%Y")
            booking_time = local_start.strftime("%H:%M")
            if user.plan.value == "pro":
                cancel_token = create_booking_cancel_token(booking.id)

    return templates.TemplateResponse("public/success.html", {
        "request": request,
        "profile": user,
        "booking": booking,
        "booking_date": booking_date,
        "booking_time": booking_time,
        "cancel_token": cancel_token,
    })
