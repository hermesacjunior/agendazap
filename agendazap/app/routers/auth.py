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
    verify_password,
    get_password_hash,
    create_access_token,
    create_password_reset_token,
    decode_password_reset_token,
    get_current_user,
    cookie_secure,
)
from app.services.supabase_auth import send_password_recovery, supabase_is_configured
from app.security import clean_phone, clean_text, install_template_security, require_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}


def generate_slug(name: str) -> str:
    slug = re.sub(r'[^a-z0-9]', '-', name.lower().strip())
    slug = re.sub(r'-+', '-', slug).strip('-')
    return f"{slug}-{str(uuid.uuid4())[:6]}"


def is_local_request(request: Request) -> bool:
    return request.url.hostname in LOCAL_HOSTS


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
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, csrf_token)
    email = email.strip().lower()
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if not user or not user.is_active or not verify_password(password, user.hashed_password):
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
        secure=cookie_secure(request),
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
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, csrf_token)
    name = clean_text(name, max_length=100)
    email = email.strip().lower()
    whatsapp = clean_phone(whatsapp)

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
        secure=cookie_secure(request),
        samesite="lax",
        max_age=604800,
    )
    return response


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    require_csrf_token(request, csrf_token)
    email = email.strip().lower()
    sent = False
    if supabase_is_configured():
        redirect_to = f"{os.getenv('APP_URL', 'https://www.agendazapuap.com.br').rstrip('/')}/auth/login"
        sent = await send_password_recovery(email, redirect_to)
    elif is_local_request(request):
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        reset_url = None
        if user:
            token = create_password_reset_token(user)
            reset_url = str(request.url_for("reset_password_page")) + f"?token={token}"

        return templates.TemplateResponse("auth/forgot_password.html", {
            "request": request,
            "success": "Use o link abaixo para redefinir sua senha neste ambiente local.",
            "reset_url": reset_url,
        })

    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request,
        "success": "Se este email existir, enviaremos as instrucoes de recuperacao.",
        "warning": None if sent else "Recuperacao via Supabase ainda nao configurada no ambiente.",
    })


@router.get("/reset-password", response_class=HTMLResponse, name="reset_password_page")
async def reset_password_page(request: Request, token: str = ""):
    payload = decode_password_reset_token(token)
    if not payload:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request,
            "error": "Link de recuperacao invalido ou expirado.",
        })

    return templates.TemplateResponse("auth/reset_password.html", {
        "request": request,
        "token": token,
        "email": payload.get("email", ""),
    })


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    payload = decode_password_reset_token(token)
    if not payload:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request,
            "error": "Link de recuperacao invalido ou expirado.",
        })

    if len(password) < 8:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request,
            "token": token,
            "email": payload.get("email", ""),
            "error": "A senha deve ter pelo menos 8 caracteres.",
        })

    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user:
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request,
            "error": "Usuario nao encontrado.",
        })

    user.hashed_password = get_password_hash(password)
    await db.commit()

    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "success": "Senha atualizada. Entre com sua nova senha.",
    })


@router.post("/logout")
async def logout(request: Request, csrf_token: str = Form("")):
    require_csrf_token(request, csrf_token)
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie("access_token", samesite="lax", secure=cookie_secure(request))
    return response
