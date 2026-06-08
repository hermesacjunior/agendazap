from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import re
import uuid
import os

from app.database import get_db
from app.models.user import User
from app.services.auth_service import (
    verify_password, get_password_hash, create_access_token, get_current_user, cookie_secure
)
from app.services.supabase_auth import send_password_recovery, supabase_is_configured

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def generate_slug(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]', '-', name.lower().strip())
    slug = re.sub(r'-+', '-', slug).strip('-')
    return f"{slug}-{str(uuid.uuid4())[:6]}"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, current_user=Depends(get_current_user)):
    if current_user:
        return RedirectResponse(url="/admin/dashboard")
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    email = email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Email ou senha inválidos"
        })

    token = create_access_token({"sub": user.id})
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=604800,
    )
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request})


@router.post("/register")
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    whatsapp: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    name = name.strip()
    email = email.strip().lower()
    whatsapp = whatsapp.strip()

    if len(password) < 8:
        return templates.TemplateResponse("auth/register.html", {
            "request": request,
            "error": "A senha deve ter pelo menos 8 caracteres"
        })

    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        return templates.TemplateResponse("auth/register.html", {
            "request": request,
            "error": "Email já cadastrado"
        })

    slug = generate_slug(name)
    user = User(
        name=name,
        email=email,
        hashed_password=get_password_hash(password),
        whatsapp=whatsapp,
        slug=slug
    )
    db.add(user)
    await db.flush()

    # Criar agenda padrão
    from app.models.schedule import Schedule
    schedule = Schedule(
        user_id=user.id,
        name=f"Agenda de {name}",
        weekly_availability={
            "0": [{"start": "09:00", "end": "18:00"}],
            "1": [{"start": "09:00", "end": "18:00"}],
            "2": [{"start": "09:00", "end": "18:00"}],
            "3": [{"start": "09:00", "end": "18:00"}],
            "4": [{"start": "09:00", "end": "18:00"}],
        }
    )
    db.add(schedule)
    await db.commit()

    token = create_access_token({"sub": user.id})
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        max_age=604800,
    )
    return response


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request, email: str = Form(...)):
    email = email.strip().lower()
    sent = False
    if supabase_is_configured():
        redirect_to = f"{os.getenv('APP_URL', 'https://agendazapuap.com.br').rstrip('/')}/auth/login"
        sent = await send_password_recovery(email, redirect_to)

    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request,
        "success": "Se este email existir, enviaremos as instrucoes de recuperacao.",
        "warning": None if sent else "Recuperacao via Supabase ainda nao configurada no ambiente.",
    })


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token", samesite="lax", secure=cookie_secure())
    return response
