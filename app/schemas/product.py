from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class ProductBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(gt=0, description="Price in the storefront currency")
    inventory_count: int = Field(default=0, ge=0)
    image_url: HttpUrl | None = None


class ProductCreate(ProductBase):
    """Payload for creating a product (admin)."""


class ProductUpdate(BaseModel):
    """Partial update — all fields optional."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(default=None, gt=0)
    inventory_count: int | None = Field(default=None, ge=0)
    image_url: HttpUrl | None = None


class ProductRead(ProductBase):
    """Response schema. Uses `from_attributes` to map from the ORM model."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Owner (seller) of this product; None for system/admin-created products.
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
