from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from datetime import datetime, date
import logging
import pytz

from app.database import get_db
from app.models.user import User
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.schedule_service import get_available_slots, get_month_availability
from app.services.whatsapp_service import notify_admin_new_booking
from app.services.email_service import notify_admin_email

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
BRAZIL_TZ = pytz.timezone("America/Sao_Paulo")
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


@router.get("/{slug}", response_class=HTMLResponse)
async def public_booking_page(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug, User.is_active == True))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="Agenda não encontrada")

    result = await db.execute(
        select(Schedule).where(Schedule.user_id == user.id, Schedule.is_active == True)
    )
    schedule = result.scalar_one_or_none()

    if not schedule:
        raise HTTPException(status_code=404, detail="Agenda não disponível")

    free_limit_reached = await free_plan_has_reached_limit(user, db)

    return templates.TemplateResponse("public/booking.html", {
        "request": request,
        "profile": user,
        "schedule": schedule,
        "free_limit_reached": free_limit_reached,
    })


@router.get("/{slug}/slots")
async def get_slots(
    slug: str,
    date_str: str,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)

    result = await db.execute(
        select(Schedule).where(Schedule.user_id == user.id, Schedule.is_active == True)
    )
    schedule = result.scalar_one_or_none()
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
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)

    result = await db.execute(
        select(Schedule).where(Schedule.user_id == user.id, Schedule.is_active == True)
    )
    schedule = result.scalar_one_or_none()
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
    db: AsyncSession = Depends(get_db)
):
    client_name = client_name.strip()
    client_email = client_email.strip().lower()
    client_whatsapp = client_whatsapp.strip()
    notes = notes.strip()

    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404)

    result = await db.execute(
        select(Schedule).where(Schedule.user_id == user.id, Schedule.is_active == True)
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404)

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

        # Email para admin
        sent = await notify_admin_email(user.email, booking_data)
        booking.email_sent_admin = sent

        await db.commit()
    except Exception:
        pass  # Notificações não devem quebrar o agendamento

    return RedirectResponse(
        url=f"/b/{slug}/success?name={client_name}&date={booking_data['date']}&time={booking_data['time']}",
        status_code=302
    )


@router.get("/{slug}/success", response_class=HTMLResponse)
async def booking_success(
    slug: str,
    request: Request,
    name: str = "",
    date: str = "",
    time: str = "",
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.slug == slug))
    user = result.scalar_one_or_none()

    return templates.TemplateResponse("public/success.html", {
        "request": request,
        "profile": user,
        "client_name": name,
        "date": date,
        "time": time,
    })
