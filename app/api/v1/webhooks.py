from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.webhook import PaystackWebhookHandler

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receives Paystack events (charge.success) and updates the Order."""
    return await PaystackWebhookHandler(db).handle(request)
