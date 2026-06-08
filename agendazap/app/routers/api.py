import os
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.booking import Booking, BookingStatus
from app.models.schedule import Schedule
from app.models.user import User
from app.services.auth_service import create_access_token, get_current_user, get_password_hash, verify_password
from app.services.supabase_auth import send_password_recovery, supabase_is_configured

router = APIRouter(prefix="/api")
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br")).rstrip("/")


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    whatsapp: str | None = Field(default=None, max_length=20)
    bio: str | None = Field(default=None, max_length=1000)

    @field_validator("name", "whatsapp", "bio")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class AuthLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class AuthRegister(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    whatsapp: str | None = Field(default=None, max_length=20)

    @field_validator("name", "whatsapp")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class AuthRecover(BaseModel):
    email: EmailStr


class AgendaPayload(BaseModel):
    name: str = Field(default="Minha Agenda", min_length=2, max_length=100)
    slot_duration: int = Field(default=60, ge=15, le=240)
    buffer_time: int = Field(default=0, ge=0, le=120)
    max_advance_days: int = Field(default=30, ge=1, le=365)
    weekly_availability: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    blocked_dates: list[str] = Field(default_factory=list)
    is_active: bool = True


class AppointmentCreate(BaseModel):
    schedule_id: str
    client_name: str = Field(min_length=2, max_length=100)
    client_email: EmailStr
    client_whatsapp: str | None = Field(default=None, max_length=20)
    client_notes: str | None = Field(default=None, max_length=1000)
    start_datetime: datetime
    end_datetime: datetime

    @field_validator("client_name", "client_whatsapp", "client_notes")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value


class AppointmentUpdate(BaseModel):
    status: BookingStatus | None = None
    client_notes: str | None = Field(default=None, max_length=1000)


async def require_api_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticacao obrigatoria.")
    return user


def _booking_to_dict(booking: Booking) -> dict[str, Any]:
    return {
        "id": booking.id,
        "schedule_id": booking.schedule_id,
        "client_name": booking.client_name,
        "client_email": booking.client_email,
        "client_whatsapp": booking.client_whatsapp,
        "client_notes": booking.client_notes,
        "start_datetime": booking.start_datetime.isoformat(),
        "end_datetime": booking.end_datetime.isoformat(),
        "status": booking.status.value,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
    }


def _generate_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]", "-", name.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"{slug}-{str(uuid.uuid4())[:6]}"


@router.post("/auth/login")
async def api_login(payload: AuthLogin, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou senha invalidos.")
    return {"access_token": create_access_token({"sub": user.id}), "token_type": "bearer"}


@router.post("/auth/register", status_code=201)
async def api_register(payload: AuthRegister, db: AsyncSession = Depends(get_db)):
    email = payload.email.lower()
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email ja cadastrado.")

    user = User(
        name=payload.name,
        email=email,
        hashed_password=get_password_hash(payload.password),
        whatsapp=payload.whatsapp,
        slug=_generate_slug(payload.name),
    )
    db.add(user)
    await db.flush()
    db.add(
        Schedule(
            user_id=user.id,
            name=f"Agenda de {payload.name}",
            weekly_availability={
                "0": [{"start": "09:00", "end": "18:00"}],
                "1": [{"start": "09:00", "end": "18:00"}],
                "2": [{"start": "09:00", "end": "18:00"}],
                "3": [{"start": "09:00", "end": "18:00"}],
                "4": [{"start": "09:00", "end": "18:00"}],
            },
        )
    )
    await db.commit()
    return {"access_token": create_access_token({"sub": user.id}), "token_type": "bearer"}


@router.post("/auth/recover")
async def api_recover_password(payload: AuthRecover):
    sent = False
    if supabase_is_configured():
        redirect_to = f"{os.getenv('APP_URL', 'https://www.agendazapuap.com.br').rstrip('/')}/auth/login"
        sent = await send_password_recovery(payload.email.lower(), redirect_to)
    return {"ok": True, "configured": sent}


@router.post("/auth/logout")
async def api_logout():
    return {"ok": True}


@router.get("/auth/me")
async def auth_me(current_user: User = Depends(require_api_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "plan": current_user.plan.value,
        "slug": current_user.slug,
    }


@router.get("/profile")
async def get_profile(current_user: User = Depends(require_api_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "whatsapp": current_user.whatsapp,
        "bio": current_user.bio,
        "slug": current_user.slug,
        "plan": current_user.plan.value,
        "public_link": f"{APP_URL}/b/{current_user.slug}",
    }


@router.patch("/profile")
async def update_profile(
    payload: ProfileUpdate,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    await db.commit()
    return {"ok": True}


@router.get("/agenda")
async def list_agendas(
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Schedule).where(Schedule.user_id == current_user.id))
    schedules = result.scalars().all()
    return {
        "agendas": [
            {
                "id": schedule.id,
                "name": schedule.name,
                "slot_duration": schedule.slot_duration,
                "buffer_time": schedule.buffer_time,
                "max_advance_days": schedule.max_advance_days,
                "weekly_availability": schedule.weekly_availability,
                "blocked_dates": schedule.blocked_dates,
                "is_active": schedule.is_active,
            }
            for schedule in schedules
        ]
    }


@router.post("/agenda", status_code=201)
async def create_agenda(
    payload: AgendaPayload,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    schedule = Schedule(user_id=current_user.id, **payload.model_dump())
    db.add(schedule)
    await db.commit()
    await db.refresh(schedule)
    return {"id": schedule.id}


@router.patch("/agenda/{agenda_id}")
async def update_agenda(
    agenda_id: str,
    payload: AgendaPayload,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Schedule).where(and_(Schedule.id == agenda_id, Schedule.user_id == current_user.id)))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Agenda nao encontrada.")

    for field, value in payload.model_dump().items():
        setattr(schedule, field, value)
    await db.commit()
    return {"ok": True}


@router.get("/availability")
async def get_availability(
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Schedule).where(Schedule.user_id == current_user.id))
    schedule = result.scalar_one_or_none()
    if not schedule:
        return {"availability": {}, "blocked_dates": []}
    return {"availability": schedule.weekly_availability, "blocked_dates": schedule.blocked_dates}


@router.patch("/availability/{agenda_id}")
async def update_availability(
    agenda_id: str,
    payload: AgendaPayload,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Schedule).where(and_(Schedule.id == agenda_id, Schedule.user_id == current_user.id)))
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Agenda nao encontrada.")
    schedule.weekly_availability = payload.weekly_availability
    schedule.blocked_dates = payload.blocked_dates
    await db.commit()
    return {"ok": True}


@router.get("/appointments")
async def list_appointments(
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Booking).where(Booking.user_id == current_user.id).order_by(Booking.start_datetime.desc())
    )
    return {"appointments": [_booking_to_dict(booking) for booking in result.scalars().all()]}


@router.post("/appointments", status_code=201)
async def create_appointment(
    payload: AppointmentCreate,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.end_datetime <= payload.start_datetime:
        raise HTTPException(status_code=400, detail="Horario final precisa ser maior que o inicial.")

    result = await db.execute(
        select(Schedule).where(and_(Schedule.id == payload.schedule_id, Schedule.user_id == current_user.id))
    )
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Agenda nao encontrada.")

    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.schedule_id == payload.schedule_id,
                Booking.start_datetime < payload.end_datetime,
                Booking.end_datetime > payload.start_datetime,
                Booking.status != BookingStatus.cancelled,
            )
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Horario indisponivel.")

    booking = Booking(
        user_id=current_user.id,
        schedule_id=payload.schedule_id,
        client_name=payload.client_name,
        client_email=payload.client_email.lower(),
        client_whatsapp=payload.client_whatsapp,
        client_notes=payload.client_notes,
        start_datetime=payload.start_datetime,
        end_datetime=payload.end_datetime,
        status=BookingStatus.confirmed,
    )
    db.add(booking)
    await db.commit()
    await db.refresh(booking)
    return {"id": booking.id}


@router.patch("/appointments/{appointment_id}")
async def update_appointment(
    appointment_id: str,
    payload: AppointmentUpdate,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Booking).where(and_(Booking.id == appointment_id, Booking.user_id == current_user.id)))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")

    if payload.status is not None:
        booking.status = payload.status
    if payload.client_notes is not None:
        booking.client_notes = payload.client_notes.strip()
    await db.commit()
    return {"ok": True}


@router.delete("/appointments/{appointment_id}")
async def delete_cancelled_appointment(
    appointment_id: str,
    current_user: User = Depends(require_api_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Booking).where(and_(Booking.id == appointment_id, Booking.user_id == current_user.id)))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Agendamento nao encontrado.")
    if booking.status != BookingStatus.cancelled:
        raise HTTPException(status_code=400, detail="Apenas agendamentos cancelados podem ser excluidos.")
    await db.delete(booking)
    await db.commit()
    return {"ok": True}
