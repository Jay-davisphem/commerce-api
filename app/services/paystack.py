"""Paystack payment gateway client (async via httpx).

Phase 1 scope: initialize a transaction and return the `authorization_url`.
The webhook verification lives in `app/services/webhook_security.py`.
"""

from __future__ import annotations

import hmac
import hashlib
from decimal import Decimal

import httpx

from app.core.config import settings


class PaystackError(Exception):
    """Raised when Paystack responds with an error or non-2xx status."""


class PaystackService:
    """Thin async wrapper around the Paystack REST API."""

    def __init__(self) -> None:
        self.base_url = settings.PAYSTACK_BASE_URL.rstrip("/")
        self.secret_key = settings.PAYSTACK_SECRET_KEY

    @staticmethod
    def to_kobo(amount: Decimal) -> int:
        """Convert a Decimal storefront amount to Paystack minor units (kobo).

        Paystack operates in kobo (1 NGN = 100 kobo), like cents. We round to
        the nearest integer kobo to avoid float drift.
        """
        return int((amount * 100).quantize(Decimal("1")))

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def initialize_transaction(
        self,
        *,
        email: str,
        amount: Decimal,
        reference: str,
        metadata: dict | None = None,
        callback_url: str | None = None,
    ) -> dict:
        """Create a Paystack transaction and return its raw JSON response.

        Returns a dict containing (at least) `authorization_url`,
        `access_code`, and `reference`.
        """
        if not self.secret_key:
            raise PaystackError("PAYSTACK_SECRET_KEY is not configured")

        payload: dict = {
            "email": email,
            "amount": self.to_kobo(amount),
            "reference": reference,
            "metadata": metadata or {},
        }
        if callback_url:
            payload["callback_url"] = callback_url

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.base_url}/transaction/initialize",
                json=payload,
                headers=self._headers(),
            )

        body = resp.json()
        if not resp.is_success or not body.get("status"):
            raise PaystackError(f"Paystack initialize failed: {body}")

        return body["data"]

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify the Paystack webhook `x-paystack-signature` HMAC-SHA512."""
        secret = settings.PAYSTACK_WEBHOOK_SECRET or self.secret_key
        if not secret:
            return False
        expected = hmac.new(secret.encode(), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)


paystack = PaystackService()
