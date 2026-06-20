from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.user import User, PlanType
from app.models.schedule import Schedule
from app.models.booking import Booking, BookingStatus
from app.services.auth_service import require_superadmin
from app.services.schedule_service import utc_to_brazil
from app.security import install_template_security, require_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)

VALID_PLANS = {"free", "basic", "pro"}


async def _load_user(db: AsyncSession, user_id: str) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
    return user


@router.get("", response_class=HTMLResponse)
async def users_list(
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    booking_counts = dict(
        (await db.execute(select(Booking.user_id, func.count(Booking.id)).group_by(Booking.user_id))).all()
    )

    plan_totals = {"free": 0, "basic": 0, "pro": 0}
    for u in users:
        plan_totals[u.plan.value] = plan_totals.get(u.plan.value, 0) + 1
    total_bookings = (await db.execute(select(func.count(Booking.id)))).scalar() or 0

    return templates.TemplateResponse(
        "admin/super_users.html",
        {
            "request": request,
            "user": current_user,
            "users": users,
            "booking_counts": booking_counts,
            "total_users": len(users),
            "total_bookings": total_bookings,
            "plan_totals": plan_totals,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def user_detail(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    target = await _load_user(db, user_id)
    bookings = (
        await db.execute(
            select(Booking).where(Booking.user_id == user_id).order_by(Booking.start_datetime.desc()).limit(100)
        )
    ).scalars().all()
    schedules_count = (
        await db.execute(select(func.count(Schedule.id)).where(Schedule.user_id == user_id))
    ).scalar() or 0

    history = []
    for b in bookings:
        local = utc_to_brazil(b.start_datetime)
        history.append(
            {
                "client_name": b.client_name,
                "client_email": b.client_email,
                "date": local.strftime("%d/%m/%Y"),
                "time": local.strftime("%H:%M"),
                "status": b.status.value,
            }
        )

    return templates.TemplateResponse(
        "admin/super_user_detail.html",
        {
            "request": request,
            "user": current_user,
            "target": target,
            "history": history,
            "schedules_count": schedules_count,
        },
    )


@router.post("/users/{user_id}/plan")
async def change_plan(
    user_id: str,
    request: Request,
    plan: str = Form(...),
    csrf_token: str = Form(""),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    if plan not in VALID_PLANS:
        raise HTTPException(status_code=400, detail="Plano invalido.")
    target = await _load_user(db, user_id)
    target.plan = PlanType(plan)
    await db.commit()
    return RedirectResponse(url=f"/admin/super/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/active")
async def toggle_active(
    user_id: str,
    request: Request,
    csrf_token: str = Form(""),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    target = await _load_user(db, user_id)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Voce nao pode desativar a propria conta.")
    target.is_active = not bool(target.is_active)
    await db.commit()
    return RedirectResponse(url=f"/admin/super/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/blocked")
async def toggle_blocked(
    user_id: str,
    request: Request,
    csrf_token: str = Form(""),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    target = await _load_user(db, user_id)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Voce nao pode bloquear a propria conta.")
    target.is_blocked = not bool(target.is_blocked)
    await db.commit()
    return RedirectResponse(url=f"/admin/super/users/{user_id}", status_code=302)


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: str,
    request: Request,
    csrf_token: str = Form(""),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    target = await _load_user(db, user_id)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Voce nao pode excluir a propria conta.")
    # Agendas e agendamentos somem em cascata (cascade="all, delete-orphan").
    await db.delete(target)
    await db.commit()
    return RedirectResponse(url="/admin/super", status_code=302)


@router.post("/users/{user_id}/superadmin")
async def toggle_superadmin(
    user_id: str,
    request: Request,
    csrf_token: str = Form(""),
    current_user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    target = await _load_user(db, user_id)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="Voce nao pode revogar o proprio acesso de administrador.")
    target.is_superadmin = not bool(target.is_superadmin)
    await db.commit()
    return RedirectResponse(url=f"/admin/super/users/{user_id}", status_code=302)
