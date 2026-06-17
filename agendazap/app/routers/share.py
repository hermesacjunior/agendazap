from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from datetime import date

from app.database import get_db
from app.models.user import User
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.schedule_service import get_available_slots, get_month_availability
from app.security import install_template_security

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)


async def _schedule_by_token(db: AsyncSession, token: str) -> Schedule | None:
    if not token:
        return None
    result = await db.execute(
        select(Schedule).where(Schedule.share_token == token, Schedule.is_active == True)
    )
    return result.scalar_one_or_none()


@router.get("/{token}", response_class=HTMLResponse)
async def share_view(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    schedule = await _schedule_by_token(db, token)
    if not schedule:
        raise HTTPException(status_code=404, detail="Agenda não encontrada")
    owner = (
        await db.execute(select(User).where(User.id == schedule.user_id))
    ).scalar_one_or_none()
    if not owner or not owner.is_active:
        raise HTTPException(status_code=404, detail="Agenda não encontrada")

    return templates.TemplateResponse("public/share_view.html", {
        "request": request,
        "owner_name": owner.name,
        "schedule": schedule,
        "token": token,
    })


@router.get("/{token}/availability")
async def share_availability(
    token: str,
    year: int,
    month: int,
    db: AsyncSession = Depends(get_db),
):
    schedule = await _schedule_by_token(db, token)
    if not schedule:
        return JSONResponse({"availability": {}})
    availability = await get_month_availability(schedule, year, month, db)
    return JSONResponse({"availability": availability})


@router.get("/{token}/slots")
async def share_slots(
    token: str,
    date_str: str,
    db: AsyncSession = Depends(get_db),
):
    schedule = await _schedule_by_token(db, token)
    if not schedule:
        return JSONResponse({"slots": []})
    try:
        target = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Data inválida")

    result = await db.execute(
        select(Booking).where(
            and_(Booking.schedule_id == schedule.id, Booking.status != BookingStatus.cancelled)
        )
    )
    bookings = result.scalars().all()
    slots = get_available_slots(schedule, target, bookings)
    return JSONResponse({"slots": slots, "duration": schedule.slot_duration})
