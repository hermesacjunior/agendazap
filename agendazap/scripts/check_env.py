from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv


REQUIRED_PRODUCTION = [
    "APP_URL",
    "API_URL",
    "ALLOWED_ORIGINS",
    "ALLOWED_HOSTS",
    "DATABASE_URL",
    "JWT_SECRET",
    "SECRET_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_BASIC_PRICE_ID",
    "STRIPE_PRO_PRICE_ID",
]


def fail(message: str) -> None:
    print(f"ERRO: {message}")
    raise SystemExit(1)


def warn(message: str) -> None:
    print(f"AVISO: {message}")


def main() -> int:
    load_dotenv()
    app_env = os.getenv("APP_ENV", "development").lower()
    app_url = os.getenv("APP_URL", "")
    api_url = os.getenv("API_URL", "")
    database_url = os.getenv("DATABASE_URL", "")

    if app_env != "production":
        print("Ambiente nao esta em production; checagens criticas de deploy foram puladas.")
        return 0

    missing = [name for name in REQUIRED_PRODUCTION if not os.getenv(name)]
    if missing:
        fail("Variaveis obrigatorias ausentes: " + ", ".join(missing))

    if database_url.startswith("sqlite"):
        fail("DATABASE_URL de producao nao pode usar SQLite. Use PostgreSQL com postgresql+asyncpg://.")

    if not database_url.startswith("postgresql+asyncpg://"):
        fail("DATABASE_URL de producao deve usar postgresql+asyncpg://.")

    for name in ("JWT_SECRET", "SECRET_KEY"):
        if len(os.getenv(name, "")) < 32:
            fail(f"{name} precisa ter pelo menos 32 caracteres.")

    if os.getenv("JWT_SECRET") == os.getenv("SECRET_KEY"):
        fail("JWT_SECRET e SECRET_KEY devem ser diferentes.")

    parsed = urlparse(app_url)
    if parsed.scheme != "https" or not parsed.netloc:
        fail("APP_URL de producao precisa ser uma URL HTTPS valida.")

    parsed_api = urlparse(api_url)
    if parsed_api.scheme != "https" or not parsed_api.netloc:
        fail("API_URL de producao precisa ser uma URL HTTPS valida.")

    allowed_hosts = {item.strip() for item in os.getenv("ALLOWED_HOSTS", "").split(",") if item.strip()}
    allowed_origins = {item.strip().rstrip("/") for item in os.getenv("ALLOWED_ORIGINS", "").split(",") if item.strip()}
    expected_hosts = {parsed.netloc, parsed_api.netloc}
    if not expected_hosts.issubset(allowed_hosts):
        fail("ALLOWED_HOSTS precisa incluir os hosts de APP_URL e API_URL.")
    if not {app_url.rstrip("/"), api_url.rstrip("/")}.issubset(allowed_origins):
        fail("ALLOWED_ORIGINS precisa incluir APP_URL e API_URL.")

    if os.getenv("COOKIE_SECURE", "").lower() != "true":
        fail("COOKIE_SECURE precisa ser true em producao.")
    if os.getenv("FORCE_HTTPS", "").lower() != "true":
        fail("FORCE_HTTPS precisa ser true em producao.")

    from_email = os.getenv("FROM_EMAIL", "")
    if "agendazapuap.com.br" not in from_email:
        warn("FROM_EMAIL nao parece usar o dominio agendazapuap.com.br.")

    placeholders = {
        "STRIPE_SECRET_KEY": ("sk_live_...", "sk_test_xxxxx"),
        "STRIPE_WEBHOOK_SECRET": ("whsec_...", "whsec_xxxxx"),
        "STRIPE_BASIC_PRICE_ID": ("price_...", "price_xxxxx"),
        "STRIPE_PRO_PRICE_ID": ("price_...", "price_xxxxx"),
    }
    for name, bad_values in placeholders.items():
        value = os.getenv(name, "")
        if value in bad_values or value.endswith("..."):
            fail(f"{name} ainda parece ser placeholder.")

    print("Ambiente de producao passou nas checagens basicas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
