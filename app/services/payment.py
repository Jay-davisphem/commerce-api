from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.config import settings
from app.services.paystack import paystack
from app.services.stripe import stripe_service


class PaymentGatewayService:
    """Unified facade that delegates to Paystack or Stripe according to settings.PAYMENT_GATEWAY."""

    @staticmethod
    async def initialize_payment(
        *,
        email: str,
        amount: Decimal,
        reference: str,
        order_id: str,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        gateway = (settings.PAYMENT_GATEWAY or "paystack").lower().strip()

        if gateway == "stripe":
            return await stripe_service.create_checkout_session(
                email=email,
                amount=amount,
                reference=reference,
                order_id=order_id,
                callback_url=callback_url,
            )

        # Default: Paystack
        result = await paystack.initialize_transaction(
            email=email,
            amount=amount,
            reference=reference,
            metadata={"order_id": order_id},
            callback_url=callback_url,
        )
        return {
            "authorization_url": result.get("authorization_url", ""),
            "access_code": result.get("access_code"),
            "reference": reference,
        }


payment_gateway = PaymentGatewayService()