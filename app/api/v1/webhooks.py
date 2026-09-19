from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.webhook import PaystackWebhookHandler, StripeWebhookHandler

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receives Paystack events (charge.success) and marks orders paid."""
    return await PaystackWebhookHandler(db).handle(request)


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receives Stripe events (checkout.session.completed) and marks orders paid."""
    return await StripeWebhookHandler(db).handle(request)