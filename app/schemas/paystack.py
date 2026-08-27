from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PaystackEventData(BaseModel):
    """The `data` object in a Paystack webhook payload."""

    id: int | None = None
    reference: str
    status: str | None = None
    amount: int | None = None  # in kobo (Paystack minor units)
    currency: str | None = None
    paid_at: str | None = None
    customer: dict[str, Any] | None = None
    # Paystack sends a fully typed account object; we keep it loosely typed here
    # to be resilient to schema drift, but the fields we rely on (reference,
    # status, amount) are validated explicitly.
    metadata: dict[str, Any] | None = None


class PaystackWebhook(BaseModel):
    """Webhook body Paystack POSTs on `charge.success`."""

    event: str = Field(description="e.g. 'charge.success'")
    data: PaystackEventData


class PaymentVerification(BaseModel):
    """Result of verifying a Paystack transaction via `GET /transaction/verify`."""

    verified: bool
    reference: str
    status: str
    amount_paid_minor: int | None = None
    order_id: str | None = None
