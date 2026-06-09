from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from time import time
import uvicorn
import os
import logging
from dotenv import load_dotenv

from app.database import create_tables
from app.routers import auth, admin, booking, webhooks, plans, api

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
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_limit(request: Request) -> tuple[int, int] | None:
    if request.method != "POST":
        return None
    path = request.url.path
    if path in {"/auth/login", "/auth/register"}:
        return (10, 15 * 60)
    if path.endswith("/book") and path.startswith("/b/"):
        return (20, 60)
    return None


def _is_allowed_origin(source: str) -> bool:
    parsed = urlparse(source)
    if parsed.netloc in ALLOWED_ORIGIN_HOSTS:
        return True
    if parsed.hostname in LOCAL_HOSTS and parsed.scheme == "http":
        return True
    return source.rstrip("/") in LOCAL_ORIGINS


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    yield


app = FastAPI(
    title="AgendaZap",
    description="Agendamento com notificação via WhatsApp",
    version="1.0.0",
    lifespan=lifespan,
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
    if FORCE_HTTPS and request.url.scheme == "http" and request.url.hostname not in LOCAL_HOSTS:
        secure_url = request.url.replace(scheme="https")
        return RedirectResponse(str(secure_url), status_code=307)

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
            if source_origin and not _is_allowed_origin(source):
                return JSONResponse({"detail": "Origem da requisicao nao permitida."}, status_code=403)

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if FORCE_HTTPS and request.url.hostname not in LOCAL_HOSTS:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(booking.router, prefix="/b", tags=["booking"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(plans.router, prefix="/plans", tags=["plans"])
app.include_router(api.router, tags=["api"])


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


@app.get("/")
async def root(request: Request):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/auth/login")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
