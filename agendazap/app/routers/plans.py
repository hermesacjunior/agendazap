from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
import os
import stripe
from dotenv import load_dotenv

from app.database import get_db
from app.models.user import User
from app.models.user import PlanType
from app.services.auth_service import require_user
from app.security import install_template_security, require_csrf_token

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
install_template_security(templates)

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
APP_URL = os.getenv("APP_URL", os.getenv("VITE_APP_URL", "https://agendazapuap.com.br")).rstrip("/")

PLANS = {
    "basic": {
        "name": "Basic",
        "price": "R$ 49/mes",
        "stripe_price_id": os.getenv("STRIPE_BASIC_PRICE_ID", ""),
        "features": [
            "Ate 100 agendamentos/mes",
            "Notificacao por Email",
            "1 agenda",
            "Link personalizado",
        ],
    },
    "pro": {
        "name": "Pro",
        "price": "R$ 99/mes",
        "stripe_price_id": os.getenv("STRIPE_PRO_PRICE_ID", ""),
        "features": [
            "Agendamentos ilimitados",
            "Notificacao via WhatsApp",
            "Notificacao por Email",
            "Multiplas agendas",
            "Link personalizado",
            "Suporte prioritario",
        ],
    },
}


def stripe_is_configured() -> bool:
    return bool(stripe.api_key) and not stripe.api_key.startswith("sk_test_xxxxx")


def price_is_configured(price_id: str) -> bool:
    return bool(price_id) and not price_id.startswith("price_xxxxx")


def checkout_url(path: str) -> str:
    return f"{APP_URL}{path}"


def render_plans(
    request: Request,
    current_user: User,
    *,
    status_code: int = 200,
    success: bool = False,
    error: str | None = None,
):
    return templates.TemplateResponse(
        "admin/plans.html",
        {
            "request": request,
            "user": current_user,
            "plans": PLANS,
            "success": success,
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/", response_class=HTMLResponse)
async def plans_page(request: Request, current_user: User = Depends(require_user)):
    return render_plans(request, current_user)


@router.get("/subscribe/{plan_slug}")
async def subscribe_get(plan_slug: str):
    return RedirectResponse(url="/plans/", status_code=302)


@router.post("/subscribe/{plan_slug}")
async def create_checkout(
    request: Request,
    plan_slug: str,
    csrf_token: str = Form(""),
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    require_csrf_token(request, csrf_token)
    if not stripe_is_configured():
        return render_plans(
            request,
            current_user,
            status_code=400,
            error="Stripe nao configurado. Configure STRIPE_SECRET_KEY no arquivo .env.",
        )

    plan = PLANS.get(plan_slug)
    if not plan or not price_is_configured(plan["stripe_price_id"]):
        return render_plans(
            request,
            current_user,
            status_code=400,
            error="Plano invalido ou sem Price ID configurado no Stripe.",
        )

    try:
        if not current_user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.name,
                metadata={"user_id": current_user.id},
            )
            current_user.stripe_customer_id = customer.id
            await db.commit()

        session = stripe.checkout.Session.create(
            customer=current_user.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{"price": plan["stripe_price_id"], "quantity": 1}],
            mode="subscription",
            success_url=checkout_url("/plans/success?session_id={CHECKOUT_SESSION_ID}"),
            cancel_url=checkout_url("/plans/"),
            metadata={"user_id": current_user.id, "plan": plan_slug},
        )
    except stripe.error.StripeError as exc:
        await db.rollback()
        await db.refresh(current_user)
        message = exc.user_message or str(exc)
        return render_plans(
            request,
            current_user,
            status_code=400,
            error=f"Nao foi possivel iniciar o checkout no Stripe: {message}",
        )

    return RedirectResponse(url=session.url, status_code=302)


@router.post("/portal")
async def billing_portal(
    request: Request,
    csrf_token: str = Form(""),
    current_user: User = Depends(require_user),
):
    require_csrf_token(request, csrf_token)
    if not stripe_is_configured():
        return render_plans(
            request,
            current_user,
            status_code=400,
            error="Stripe nao configurado. Configure STRIPE_SECRET_KEY no arquivo .env.",
        )

    if not current_user.stripe_customer_id:
        return render_plans(
            request,
            current_user,
            status_code=400,
            error="Este usuario ainda nao possui cliente no Stripe.",
        )

    try:
        session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=checkout_url("/plans/"),
        )
    except stripe.error.StripeError as exc:
        message = exc.user_message or str(exc)
        return render_plans(
            request,
            current_user,
            status_code=400,
            error=f"Nao foi possivel abrir o portal do Stripe: {message}",
        )

    return RedirectResponse(url=session.url, status_code=302)


@router.get("/success")
async def payment_success(
    request: Request,
    session_id: str,
    current_user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if stripe_is_configured() and session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.get("payment_status") == "paid":
                plan_slug = session.get("metadata", {}).get("plan")
                if plan_slug in {"basic", "pro"}:
                    current_user.plan = PlanType(plan_slug)
                    current_user.stripe_subscription_id = session.get("subscription")
                    await db.commit()
        except stripe.error.StripeError:
            pass

    return render_plans(request, current_user, success=True)
