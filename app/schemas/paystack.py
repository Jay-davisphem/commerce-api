from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class PaystackEventData(BaseModel):
    """The `data` object in a Paystack webhook payload."""

    id: int | None = None
    reference: str
    status: str | None = None
    amount: int | None = None  # in kobo (Paystack minor units)
    currency: str | None = None
    paid_at: Optional[datetime | str] = None
    customer: dict[str, Any] | None = None
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