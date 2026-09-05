from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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

    model_config = ConfigDict(from_attributes=True)


class SellerDashboardStats(BaseModel):
    online_orders_today: int
    pos_sales_today: Decimal
    goods_in_escrow: Decimal
    low_stock_alerts: int
    low_stock_items: list[LowStockAlertItem]
    recent_orders: list[RecentOrderSummary]


class RestockRequest(BaseModel):
    quantity: int = Field(..., gt=0, description="Units to add to inventory")


class SellerOrderStatusUpdate(BaseModel):
    status: str = Field(..., description="in_escrow, in_transit, delivered, cancelled")