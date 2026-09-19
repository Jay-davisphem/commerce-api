from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.order import OrderStatus, PaymentStatus


class DeliveryAddress(BaseModel):
    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str = Field(min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    country: str = Field(min_length=1, max_length=120)
    notes: str | None = None


class CheckoutItem(BaseModel):
    product_id: uuid.UUID
    quantity: int = Field(gt=0, le=1000)


class CheckoutRequest(BaseModel):
    guest_email: EmailStr | None = None
    delivery: DeliveryAddress | None = None
    use_saved_address: bool = False
    items: list[CheckoutItem] = Field(min_length=1)


class OrderItemRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_title: str | None = None
    quantity: int
    unit_price: Decimal
    line_total: Decimal

    model_config = ConfigDict(from_attributes=True)


class OrderRead(BaseModel):
    id: uuid.UUID
    order_reference: str | None = None
    customer_name: str | None = None
    guest_email: EmailStr
    delivery: DeliveryAddress | None = None
    total_amount: Decimal
    status: OrderStatus
    payment_status: PaymentStatus
    paystack_reference: str | None = None
    paid_at: datetime | None = None
    created_at: datetime
    items: list[OrderItemRead] = []
    items_preview: list[str] = []

    model_config = ConfigDict(from_attributes=True)


OrderResponse = OrderRead


class CheckoutResponse(BaseModel):
    order: OrderRead
    authorization_url: str
    access_code: str | None = None
    reference: str


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


class TimelineStep(BaseModel):
    step_key: str
    title: str
    status: str  # "completed", "current", "pending"
    timestamp: Optional[datetime] = None


class BuyerOrderDetail(BaseModel):
    id: uuid.UUID
    order_reference: str
    status: str
    status_label: str
    payment_status: str
    total_amount: Decimal
    subtotal: Decimal
    escrow_fee: Decimal
    created_at: datetime
    paid_at: Optional[datetime] = None
    items: list[OrderItemRead]
    delivery: DeliveryAddress
    timeline: list[TimelineStep]
    escrow_banner_message: str
    can_mark_received: bool = False

    model_config = ConfigDict(from_attributes=True)


class ConfirmReceivedResponse(BaseModel):
    message: str
    order_id: uuid.UUID
    order_reference: str
    status: str