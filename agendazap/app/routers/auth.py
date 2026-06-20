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
    create_access_token_for,
    create_password_reset_token,
    decode_password_reset_token,
    create_email_verification_token,
    decode_email_verification_token,
    get_current_user,
    cookie_secure,
)
from app.services.supabase_auth import send_password_recovery, supabase_is_configured
from app.services.email_validation import validate_signup_email
from app.services.email_service import send_account_verification
from app.security import clean_phone, clean_text, install_template_security, require_csrf_token
from app import security_guard as guard

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)
LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
APP_URL = os.getenv("APP_URL", "https://www.agendazapuap.com.br").rstrip("/")


async def _send_verification_email(user) -> None:
    token = create_email_verification_token(user)
    verify_url = f"{APP_URL}/auth/confirm-email?token={token}"
    await send_account_verification(user.email, user.name, verify_url)


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
    ip = guard.client_ip(request)

    # Trava de forca-bruta: apos varias falhas para esta conta+IP, bloqueia por
    # um tempo (independe de o e-mail existir, para nao vazar contas validas).
    block_ttl = guard.login_block_ttl(ip, email)
    if block_ttl is not None:
        minutos = max(1, block_ttl // 60)
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": f"Muitas tentativas de login. Aguarde {minutos} min e tente novamente.",
        })

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user and getattr(user, "is_blocked", False) and verify_password(password, user.hashed_password):
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Esta conta foi bloqueada. Entre em contato com o suporte."
        })

    if not user or not user.is_active or getattr(user, "is_blocked", False) or not verify_password(password, user.hashed_password):
        guard.record_login_failure(ip, email)
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Email ou senha inválidos"
        })

    # Credenciais corretas, mas e-mail ainda nao confirmado: reenvia o link e barra.
    if not getattr(user, "email_verified", True):
        guard.clear_login_failures(ip, email)
        await _send_verification_email(user)
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Confirme seu e-mail para entrar. Enviamos um novo link para sua caixa de entrada.",
        })

    guard.clear_login_failures(ip, email)
    token = create_access_token_for(user)
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

    email_ok, email_error = validate_signup_email(email)
    if not email_ok:
        return templates.TemplateResponse("auth/register.html", {
            "request": request,
            "error": email_error,
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
        slug=slug,
        email_verified=False,
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

    # Conta nasce nao confirmada: envia o link e nao faz login automatico.
    await _send_verification_email(user)
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "success": f"Conta criada! Enviamos um link de confirmação para {email}. Confirme seu e-mail para entrar.",
    })


@router.get("/confirm-email", response_class=HTMLResponse, name="confirm_email")
async def confirm_email(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    payload = decode_email_verification_token(token)
    if not payload:
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Link de confirmação inválido ou expirado. Entre para receber um novo.",
        })

    result = await db.execute(select(User).where(User.id == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user:
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Conta não encontrada.",
        })

    if not user.email_verified:
        user.email_verified = True
        await db.commit()

    # Conta bloqueada/inativa: confirma mas nao loga.
    if not user.is_active or getattr(user, "is_blocked", False):
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "success": "E-mail confirmado. Faça login para continuar.",
        })

    # Login automatico apos confirmar (boa UX).
    auth_token = create_access_token_for(user)
    response = RedirectResponse(url="/admin/dashboard", status_code=302)
    response.set_cookie(
        "access_token",
        auth_token,
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

    # Token de reset e de uso unico: se a versao nao bate, ele ja foi usado
    # (ou a senha mudou por outro meio) e nao vale mais.
    if payload.get("ver", 0) != (user.token_version or 0):
        return templates.TemplateResponse("auth/reset_password.html", {
            "request": request,
            "error": "Link de recuperacao invalido ou expirado.",
        })

    user.hashed_password = get_password_hash(password)
    # Incrementa a versao: invalida este token de reset e todas as sessoes
    # ativas, forcando login com a nova senha.
    user.token_version = (user.token_version or 0) + 1
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
