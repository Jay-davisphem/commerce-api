from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.order import DeliveryAddress, OrderItemRead


class LowStockAlertItem(BaseModel):
    product_id: uuid.UUID
    name: str
    inventory_count: int
    low_stock_threshold: int

    model_config = ConfigDict(from_attributes=True)


class RecentOrderSummary(BaseModel):
    id: uuid.UUID
    order_reference: str
    customer_name: str
    total_amount: Decimal
    status: str
    created_at: datetime
    items_preview: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class SellerDashboardStats(BaseModel):
    total_orders: int
    today_sales: Decimal
    goods_in_escrow: Decimal
    low_stock_alerts: int
    low_stock_items: list[LowStockAlertItem]
    recent_orders: list[RecentOrderSummary]

    online_orders_today: Optional[int] = None
    pos_sales_today: Optional[Decimal] = None

    model_config = ConfigDict(from_attributes=True)


class InventorySummaryStats(BaseModel):
    total_products: int
    low_stock_count: int

    model_config = ConfigDict(from_attributes=True)


class TimelineStep(BaseModel):
    step_key: str
    title: str
    status: str  # "completed", "current", "pending"
    timestamp: Optional[datetime] = None


class BuyerInfo(BaseModel):
    guest_email: str
    recipient_name: Optional[str] = None
    phone: Optional[str] = None
    address: DeliveryAddress


class SellerOrderDetail(BaseModel):
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
    buyer_info: BuyerInfo
    timeline: list[TimelineStep]
    escrow_banner_message: str

    model_config = ConfigDict(from_attributes=True)


class RestockRequest(BaseModel):
    quantity: int = Field(..., gt=0, description="Units to add to inventory")


class SellerOrderStatusUpdate(BaseModel):
    status: str = Field(..., description="in_escrow, in_transit, delivered, cancelled")