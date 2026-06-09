import secrets
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


CSRF_COOKIE_NAME = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}


def is_local_host(hostname: str | None) -> bool:
    return hostname in LOCAL_HOSTS


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def get_csrf_token(request: Request) -> str:
    token = getattr(request.state, "csrf_token", None)
    if token:
        return token
    token = request.cookies.get(CSRF_COOKIE_NAME) or generate_csrf_token()
    request.state.csrf_token = token
    return token


def install_template_security(templates) -> None:
    templates.env.globals["csrf_token"] = get_csrf_token


def csrf_cookie_secure(request: Request) -> bool:
    return request.url.scheme == "https" and not is_local_host(request.url.hostname)


def set_csrf_cookie(request: Request, response) -> None:
    token = get_csrf_token(request)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=False,
        secure=csrf_cookie_secure(request),
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )


def is_allowed_origin(source: str, allowed_origin_hosts: set[str], local_origins: set[str]) -> bool:
    parsed = urlparse(source)
    if parsed.netloc in allowed_origin_hosts:
        return True
    if parsed.hostname in LOCAL_HOSTS and parsed.scheme == "http":
        return True
    return source.rstrip("/") in local_origins


async def validate_csrf(request: Request) -> JSONResponse | None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if request.url.path.startswith("/webhooks/"):
        return None
    if request.url.path.startswith("/api/"):
        return None
    if request.headers.get("authorization", "").lower().startswith("bearer "):
        return None

    header_token = request.headers.get("x-csrf-token")
    if not header_token:
        return None

    if not csrf_token_is_valid(request, header_token):
        return JSONResponse({"detail": "Token CSRF invalido."}, status_code=403)
    return None


def csrf_token_is_valid(request: Request, submitted_token: str | None) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    return bool(
        cookie_token
        and submitted_token
        and secrets.compare_digest(cookie_token, submitted_token)
    )


def require_csrf_token(request: Request, submitted_token: str | None) -> None:
    if not csrf_token_is_valid(request, submitted_token):
        raise HTTPException(status_code=403, detail="Token CSRF invalido.")


def clean_text(value: str | None, *, max_length: int, default: str = "") -> str:
    if value is None:
        return default
    cleaned = " ".join(value.strip().split())
    return cleaned[:max_length]


def clean_multiline(value: str | None, *, max_length: int) -> str:
    if value is None:
        return ""
    cleaned = value.strip().replace("\x00", "")
    return cleaned[:max_length]


def clean_phone(value: str | None, *, max_length: int = 20) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    return digits[:max_length]


def clean_int(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)
