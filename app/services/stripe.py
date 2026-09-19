from __future__ import annotations

import hashlib
import hmac
import logging
from decimal import Decimal
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class StripeError(Exception):
    """Raised when Stripe responds with an error or non-2xx status."""


class StripeService:
    """Async wrapper around the Stripe REST API."""

    BASE_URL = "https://api.stripe.com/v1"

    def __init__(self) -> None:
        self.secret_key = settings.STRIPE_SECRET_KEY

    @staticmethod
    def to_minor_units(amount: Decimal) -> int:
        """Convert Decimal storefront amount to minor units (e.g. kobo or cents)."""
        return int((amount * 100).quantize(Decimal("1")))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def create_checkout_session(
        self,
        *,
        email: str,
        amount: Decimal,
        reference: str,
        order_id: str,
        callback_url: str | None = None,
    ) -> dict:
        """Create a Stripe Checkout Session.

        With Stripe Adaptive Pricing enabled in your dashboard, international buyers
        will see prices automatically converted to their home currency.
        """
        if not self.secret_key:
            raise StripeError("STRIPE_SECRET_KEY is not configured")

        success_redirect = (
            f"{callback_url}?session_id={{CHECKOUT_SESSION_ID}}&reference={reference}"
            if callback_url
            else f"{settings.FRONTEND_URL}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}&reference={reference}"
        )
        cancel_redirect = f"{settings.FRONTEND_URL}/cart"

        payload = {
            "mode": "payment",
            "customer_email": email,
            "client_reference_id": reference,
            "success_url": success_redirect,
            "cancel_url": cancel_redirect,
            "metadata[order_id]": order_id,
            "metadata[reference]": reference,
            "line_items[0][price_data][currency]": settings.STRIPE_CURRENCY.lower(),
            "line_items[0][price_data][unit_amount]": str(self.to_minor_units(amount)),
            "line_items[0][price_data][product_data][name]": f"BLHMI Order #{order_id[:8].upper()}",
            "line_items[0][quantity]": "1",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/checkout/sessions",
                data=payload,
                headers=self._headers(),
            )

        body = resp.json()
        if not resp.is_success:
            raise StripeError(f"Stripe session creation failed: {body.get('error', body)}")

        return {
            "authorization_url": body.get("url"),
            "access_code": body.get("id"),
            "reference": reference,
        }

    def verify_webhook_signature(self, payload: bytes, signature_header: str) -> bool:
        """Verify Stripe webhook signature header without the stripe-python SDK."""
        secret = settings.STRIPE_WEBHOOK_SECRET or self.secret_key
        if not secret or not signature_header:
            return False

        try:
            elements = dict(
                item.strip().split("=", 1)
                for item in signature_header.split(",")
                if "=" in item
            )
            timestamp = elements.get("t")
            expected_sig = elements.get("v1")

            if not timestamp or not expected_sig:
                return False

            signed_payload = f"{timestamp}.".encode("utf-8") + payload
            computed = hmac.new(
                secret.encode("utf-8"),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()

            return hmac.compare_digest(computed, expected_sig)
        except Exception as exc:
            logger.warning("Stripe webhook verification error: %s", exc)
            return False


stripe_service = StripeService()