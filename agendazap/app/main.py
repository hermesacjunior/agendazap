from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from time import time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import uvicorn
import os
import logging
from dotenv import load_dotenv

from app.database import create_tables
from app.routers import auth, admin, booking, webhooks, plans, api, superadmin, share
from app.security import is_allowed_origin, set_csrf_cookie, validate_csrf, install_template_security
from app.services.auth_service import get_current_user
from app import security_guard as guard

load_dotenv()


def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://www.agendazapuap.com.br")).rstrip("/")
APP_ENV = os.getenv("APP_ENV", "development").lower()
ALLOWED_ORIGINS = _csv_env("ALLOWED_ORIGINS", APP_URL)
ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "agendazapuap.com.br,www.agendazapuap.com.br,api.agendazapuap.com.br")
ALLOWED_ORIGIN_HOSTS = {urlparse(origin).netloc for origin in ALLOWED_ORIGINS if urlparse(origin).netloc}
FORCE_HTTPS = os.getenv("FORCE_HTTPS", "false").lower() == "true"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
LOCAL_ORIGINS = {"http://127.0.0.1:8000", "http://localhost:8000"}
logger = logging.getLogger(__name__)
RATE_LIMIT_BUCKETS: dict[tuple[str, str], list[float]] = {}


def _client_ip(request: Request) -> str:
    # Atras da Cloudflare, o IP real do visitante vem em CF-Connecting-IP.
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> tuple[int, int] | None:
    path = request.url.path
    if request.method == "POST":
        if path in {"/auth/login", "/auth/register", "/api/auth/login", "/api/auth/register"}:
            return (10, 15 * 60)
        if path.endswith("/book") and path.startswith("/b/"):
            return (20, 60)
        return None
    # Leituras publicas (paginas/links de agenda): limite generoso por IP para
    # conter scraping e tentativas de sobrecarga, sem atrapalhar o uso normal.
    if request.method == "GET" and (path.startswith("/b/") or path.startswith("/share/")):
        return (200, 60)
    return None


scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    # ENABLE_SCHEDULER=false desliga os jobs (ex.: staging, para nao duplicar
    # resumos/lembretes contra o mesmo banco da producao).
    scheduler_on = os.getenv("ENABLE_SCHEDULER", "true").lower() != "false"
    if scheduler_on:
        # Resumo diario: roda no minuto 0 de cada hora; o servico decide quem
        # esta no horario escolhido (e nao reenvia no mesmo dia).
        from app.services.reminder_service import run_daily_digests, run_appointment_reminders
        scheduler.add_job(run_daily_digests, CronTrigger(minute=0), id="daily_digests", replace_existing=True)
        # Lembretes por agendamento: verifica a cada 15 min quem entrou na janela.
        scheduler.add_job(run_appointment_reminders, CronTrigger(minute="*/15"), id="appt_reminders", replace_existing=True)
        scheduler.start()
    try:
        yield
    finally:
        if scheduler_on:
            scheduler.shutdown(wait=False)


# Em producao, esconde a superficie da API (docs/OpenAPI) de quem sonda o sistema.
_docs_enabled = APP_ENV != "production"
app = FastAPI(
    title="AgendaZap",
    description="Agendamento com notificação via WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

if APP_ENV == "production" or ALLOWED_HOSTS != ["agendazapuap.com.br", "www.agendazapuap.com.br", "api.agendazapuap.com.br"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*ALLOWED_HOSTS, *LOCAL_HOSTS])

app.add_middleware(
    CORSMiddleware,
    allow_origins=[*ALLOWED_ORIGINS, *LOCAL_ORIGINS],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if (
        FORCE_HTTPS
        and request.url.path != "/health"
        and request.url.scheme == "http"
        and request.url.hostname not in LOCAL_HOSTS
    ):
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(str(secure_url), status_code=307)

    # ───── Protecao contra acessos/trafego suspeito ─────
    # Healthcheck do Railway e webhooks (Stripe) ficam de fora: nunca devem ser
    # bloqueados, banidos ou throttled.
    path = request.url.path
    if path != "/health" and not path.startswith("/webhooks/"):
        request_ip = guard.client_ip(request)

        ttl = guard.banned_ttl(request_ip)
        if ttl is not None:
            return JSONResponse(
                {"detail": "Acesso temporariamente bloqueado por atividade suspeita."},
                status_code=429,
                headers={"Retry-After": str(ttl)},
            )

        user_agent = request.headers.get("user-agent", "")
        if guard.is_scanner_ua(user_agent):
            guard.ban_ip(request_ip, guard.BAN_SCANNER_SECONDS, "scanner-ua")
            return JSONResponse({"detail": "Acesso negado."}, status_code=403)

        # Sondagem de caminhos sensiveis (.env, .git, *.php...) -> ban + 404.
        if guard.is_honeypot_path(path):
            guard.ban_ip(request_ip, guard.BAN_HONEYPOT_SECONDS, "honeypot")
            return JSONResponse({"detail": "Nao encontrado."}, status_code=404)

        # Flood / scraping agressivo de um mesmo IP.
        if guard.over_global_limit(request_ip):
            guard.ban_ip(request_ip, guard.BAN_FLOOD_SECONDS, "flood")
            return JSONResponse(
                {"detail": "Muitas requisicoes. Aguarde e tente novamente."},
                status_code=429,
                headers={"Retry-After": str(guard.GLOBAL_IP_WINDOW)},
            )

    # Limite de tamanho do corpo (anti-DoS). Webhooks (Stripe) ficam isentos.
    if request.method in {"POST", "PUT", "PATCH"} and not request.url.path.startswith("/webhooks/"):
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > 200_000:
            return JSONResponse({"detail": "Requisicao muito grande."}, status_code=413)

    limit = _rate_limit(request)
    if limit:
        max_requests, window_seconds = limit
        now = time()
        key = (_client_ip(request), request.url.path)
        attempts = [stamp for stamp in RATE_LIMIT_BUCKETS.get(key, []) if now - stamp < window_seconds]
        if len(attempts) >= max_requests:
            return JSONResponse({"detail": "Muitas tentativas. Aguarde e tente novamente."}, status_code=429)
        attempts.append(now)
        RATE_LIMIT_BUCKETS[key] = attempts

    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.url.path.startswith("/webhooks/"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = origin or referer
        if source:
            source_origin = urlparse(source).netloc
            if source_origin and not is_allowed_origin(source, ALLOWED_ORIGIN_HOSTS, LOCAL_ORIGINS):
                return JSONResponse({"detail": "Origem da requisicao nao permitida."}, status_code=403)

    csrf_error = await validate_csrf(request)
    if csrf_error:
        return csrf_error

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://www.gstatic.com; script-src 'self' 'unsafe-inline' https://www.google.com https://www.gstatic.com; connect-src 'self'; frame-src https://www.google.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://checkout.stripe.com https://billing.stripe.com",
    )
    if request.url.path.startswith(("/admin", "/auth", "/plans")):
        response.headers.setdefault("Cache-Control", "no-store")
    if FORCE_HTTPS and request.url.hostname not in LOCAL_HOSTS:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    set_csrf_cookie(request, response)
    return response

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(superadmin.router, prefix="/admin/super", tags=["superadmin"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(booking.router, prefix="/b", tags=["booking"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(plans.router, prefix="/plans", tags=["plans"])
app.include_router(api.router, tags=["api"])
app.include_router(share.router, prefix="/share", tags=["share"])


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in {301, 302, 303, 307, 308}:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=exc.headers.get("Location", "/"), status_code=exc.status_code)

    detail = exc.detail if exc.status_code < 500 else "Erro interno do servidor."
    return JSONResponse({"detail": detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Erro nao tratado em %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Erro interno do servidor."}, status_code=500)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, current_user=Depends(get_current_user)):
    return templates.TemplateResponse(
        "public/landing.html",
        {"request": request, "logged_in": current_user is not None},
    )


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    # Servido na raiz para que o escopo do service worker possa cobrir "/".
    from fastapi.responses import FileResponse
    return FileResponse(
        "app/static/sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
