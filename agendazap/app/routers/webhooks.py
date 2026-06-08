from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe
import os
from dotenv import load_dotenv

from app.database import get_db, AsyncSessionLocal
from app.models.user import User, PlanType

router = APIRouter()
load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")


def webhook_secret_is_configured() -> bool:
    return bool(WEBHOOK_SECRET) and not WEBHOOK_SECRET.startswith("whsec_xxxxx")


@router.post("/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if webhook_secret_is_configured():
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
        except Exception:
            raise HTTPException(status_code=400)
    else:
        try:
            event = stripe.Event.construct_from(await request.json(), stripe.api_key)
        except Exception:
            raise HTTPException(status_code=400)

    async with AsyncSessionLocal() as db:
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            user_id = session.get("metadata", {}).get("user_id")
            plan_slug = session.get("metadata", {}).get("plan")

            if user_id and plan_slug:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user:
                    user.plan = PlanType(plan_slug) if plan_slug in ["basic", "pro"] else PlanType.free
                    user.stripe_subscription_id = session.get("subscription")
                    await db.commit()

        elif event["type"] in {"customer.subscription.updated", "customer.subscription.deleted"}:
            sub = event["data"]["object"]
            customer_id = sub.get("customer")
            result = await db.execute(
                select(User).where(User.stripe_customer_id == customer_id)
            )
            user = result.scalar_one_or_none()
            if user:
                if event["type"] == "customer.subscription.deleted" or sub.get("status") not in {"active", "trialing"}:
                    user.plan = PlanType.free
                    user.stripe_subscription_id = None
                else:
                    user.stripe_subscription_id = sub.get("id")
                await db.commit()

    return JSONResponse({"status": "ok"})
