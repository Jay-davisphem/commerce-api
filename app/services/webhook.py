"""Paystack webhook handler.

Paystack POSTs events (e.g. `charge.success`) to our endpoint. We:
1. Verify the `x-paystack-signature` HMAC against the secret key.
2. On `charge.success`, find the Order by reference and mark it paid.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderStatus, PaymentStatus
from app.schemas.paystack import PaystackWebhook
from app.services.paystack import paystack


class PaystackWebhookHandler:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def handle(self, request: Request) -> dict:
        payload_bytes = await request.body()
        signature = request.headers.get("x-paystack-signature", "")

        if not paystack.verify_webhook_signature(payload_bytes, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

        event = PaystackWebhook.model_validate_json(payload_bytes)

        if event.event == "charge.success":
            await self._mark_paid(event)

        # Paystack expects a 200 with an empty body on success.
        return {"status": "ok"}

    async def _mark_paid(self, event: PaystackWebhook) -> None:
        reference = event.data.reference
        stmt = select(Order).where(Order.paystack_reference == reference)
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No order for reference {reference}",
            )

        order.status = OrderStatus.PAID
        order.payment_status = PaymentStatus.PAID
        if event.data.paid_at:
            order.paid_at = event.data.paid_at
        await self.db.commit()
