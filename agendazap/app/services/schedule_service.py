from datetime import datetime, date, time, timedelta
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import pytz

from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus

BRAZIL_TZ = pytz.timezone("America/Sao_Paulo")


def utc_to_brazil(dt: datetime) -> datetime:
    """Converte datetimes salvos em UTC para o horario local da agenda."""
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(BRAZIL_TZ)


def parse_blocks(blocked) -> tuple[set[str], dict[str, set[str]]]:
    """Normaliza schedule.blocked_dates para (dias_inteiros, {data: horarios}).

    Aceita o formato novo {"days": [...], "slots": {data: [horarios]}} e o
    formato antigo (lista simples de datas = dias inteiros bloqueados).
    """
    if isinstance(blocked, dict):
        days = blocked.get("days") or []
        raw_slots = blocked.get("slots") or {}
    elif isinstance(blocked, list):
        days = blocked
        raw_slots = {}
    else:
        days, raw_slots = [], {}

    full_days = {str(d) for d in days}
    slots = {
        str(date): {str(t) for t in (times or [])}
        for date, times in raw_slots.items()
    }
    return full_days, slots


def get_available_slots(
    schedule: Schedule,
    target_date: date,
    existing_bookings: List[Booking]
) -> List[str]:
    """Gera slots disponíveis para uma data específica"""
    weekday = target_date.weekday()  # 0=segunda ... 6=domingo
    availability = schedule.weekly_availability or {}
    day_slots = availability.get(str(weekday), [])

    if not day_slots:
        return []

    iso_date = target_date.isoformat()

    # Datas/horarios bloqueados manualmente pelo dono da agenda.
    full_day_blocks, slot_blocks = parse_blocks(schedule.blocked_dates)
    if iso_date in full_day_blocks:
        return []
    blocked_times = slot_blocks.get(iso_date, set())

    # Verifica se data está no passado
    now = datetime.now(BRAZIL_TZ).date()
    if target_date < now:
        return []

    # Verifica máximo de dias no futuro
    max_date = now + timedelta(days=schedule.max_advance_days)
    if target_date > max_date:
        return []

    # Intervalos ja ocupados (agendamentos de clientes E compromissos do
    # proprio dono), em horario local ingenuo, para checagem por sobreposicao.
    booked_intervals = []
    for booking in existing_bookings:
        if booking.status == BookingStatus.cancelled:
            continue
        b_start = utc_to_brazil(booking.start_datetime).replace(tzinfo=None)
        b_end = utc_to_brazil(booking.end_datetime).replace(tzinfo=None)
        if b_start.date() == target_date or b_end.date() == target_date:
            booked_intervals.append((b_start, b_end))

    slots = []
    slot_duration = timedelta(minutes=schedule.slot_duration)
    buffer = timedelta(minutes=schedule.buffer_time)

    for period in day_slots:
        start_str = period.get("start", "09:00")
        end_str = period.get("end", "18:00")

        start_h, start_m = map(int, start_str.split(":"))
        end_h, end_m = map(int, end_str.split(":"))

        current = datetime.combine(target_date, time(start_h, start_m))
        end = datetime.combine(target_date, time(end_h, end_m))

        while current + slot_duration <= end:
            slot_str = current.strftime("%H:%M")

            # Não mostrar slots já passados se for hoje
            if target_date == now:
                now_time = datetime.now(BRAZIL_TZ).replace(tzinfo=None)
                if current <= now_time + timedelta(minutes=30):
                    current += slot_duration + buffer
                    continue

            slot_finish = current + slot_duration
            is_booked = any(bs < slot_finish and be > current for bs, be in booked_intervals)
            if not is_booked and slot_str not in blocked_times:
                slots.append(slot_str)

            current += slot_duration + buffer

    return slots


async def get_month_availability(
    schedule: Schedule,
    year: int,
    month: int,
    db: AsyncSession
) -> dict:
    """Retorna disponibilidade do mês inteiro"""
    from calendar import monthrange

    result = await db.execute(
        select(Booking).where(
            and_(
                Booking.schedule_id == schedule.id,
                Booking.status != BookingStatus.cancelled
            )
        )
    )
    bookings = result.scalars().all()

    _, days_in_month = monthrange(year, month)
    availability = {}

    for day in range(1, days_in_month + 1):
        target = date(year, month, day)
        slots = get_available_slots(schedule, target, bookings)
        availability[day] = len(slots) > 0

    return availability
