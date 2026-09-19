"""Payment webhook handlers for Paystack and Stripe."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderStatus, PaymentStatus
from app.schemas.paystack import PaystackWebhook
from app.services.paystack import paystack
from app.services.stripe import stripe_service

logger = logging.getLogger(__name__)


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

        return {"status": "ok"}

    async def _mark_paid(self, event: PaystackWebhook) -> None:
        reference = event.data.reference
        stmt = select(Order).where(Order.paystack_reference == reference)
        result = await self.db.execute(stmt)
        order_obj = result.scalar_one_or_none()
        if order_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No order for reference {reference}",
            )

        order_obj.status = OrderStatus.PAID
        order_obj.payment_status = PaymentStatus.PAID

        raw_paid_at = event.data.paid_at
        if isinstance(raw_paid_at, str):
            try:
                order_obj.paid_at = datetime.fromisoformat(raw_paid_at.replace("Z", "+00:00"))
            except ValueError:
                order_obj.paid_at = datetime.now(timezone.utc)
        elif isinstance(raw_paid_at, datetime):
            order_obj.paid_at = raw_paid_at
        else:
            order_obj.paid_at = datetime.now(timezone.utc)

        await self.db.commit()


class StripeWebhookHandler:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def handle(self, request: Request) -> dict:
        payload_bytes = await request.body()
        signature = request.headers.get("stripe-signature", "")
        if not stripe_service.verify_webhook_signature(payload_bytes, signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Stripe webhook signature",
            )

        try:
            event = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed JSON payload",
            )

        event_type = event.get("type")
        if event_type in ("checkout.session.completed", "payment_intent.succeeded"):
            await self._mark_paid(event)

        return {"status": "ok"}

    async def _mark_paid(self, event: dict) -> None:
        data_object = event.get("data", {}).get("object", {})
        reference = data_object.get("client_reference_id")
        order_id_str = data_object.get("metadata", {}).get("order_id")

        conditions = []
        if reference:
            conditions.append(Order.paystack_reference == reference)
        if order_id_str:
            try:
                order_uuid = uuid.UUID(order_id_str)
                conditions.append(Order.id == order_uuid)
            except ValueError:
                pass

        if not conditions:
            logger.warning("Stripe webhook received without reference or order_id metadata")
            return

        stmt = select(Order).where(or_(*conditions))
        order = (await self.db.execute(stmt)).scalar_one_or_none()
        if order is None:
            logger.warning("No matching order found for Stripe event %s", event.get("id"))
            return

        order.status = OrderStatus.PAID
        order.payment_status = PaymentStatus.PAID
        order.paid_at = datetime.now(timezone.utc)
        await self.db.commit()