from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProductBase(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Decimal = Field(..., ge=0, description="Price in NGN")
    inventory_count: int = Field(default=0, ge=0)

    category: Optional[str] = None
    image_url: Optional[str] = None
    original_price: Optional[Decimal] = Field(None, ge=0)
    discount_percentage: Optional[int] = Field(default=0, ge=0, le=100)
    low_stock_threshold: int = Field(default=15, ge=0)
    tag: Optional[str] = None
    rating: Decimal = Field(default=Decimal("5.0"), ge=1, le=5)
    reviews_count: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def sync_title_and_name(cls, data: Any) -> Any:
        if isinstance(data, dict):
            val = data.get("title") or data.get("name")
            if not val:
                raise ValueError("Either 'title' or 'name' is required")
            data["title"] = val
            data["name"] = val
        return data


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0)
    inventory_count: Optional[int] = Field(None, ge=0)
    category: Optional[str] = None
    image_url: Optional[str] = None
    original_price: Optional[Decimal] = Field(None, ge=0)
    discount_percentage: Optional[int] = Field(None, ge=0, le=100)
    low_stock_threshold: Optional[int] = Field(None, ge=0)
    tag: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def sync_title_and_name(cls, data: Any) -> Any:
        if isinstance(data, dict):
            val = data.get("title") or data.get("name")
            if val is not None:
                data["title"] = val
                data["name"] = val
        return data


class ProductRead(ProductBase):
    id: uuid.UUID
    title: str
    name: str
    rating: Decimal = Decimal("5.0")
    reviews_count: int = 0
    owner_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def sync_from_orm(cls, data: Any) -> Any:
        if hasattr(data, "title"):
            title_val = getattr(data, "title")
            return {
                "id": getattr(data, "id"),
                "title": title_val,
                "name": getattr(data, "name", title_val) or title_val,
                "description": getattr(data, "description", None),
                "price": getattr(data, "price"),
                "inventory_count": getattr(data, "inventory_count", 0),
                "category": getattr(data, "category", None),
                "image_url": getattr(data, "image_url", None),
                "original_price": getattr(data, "original_price", None),
                "discount_percentage": getattr(data, "discount_percentage", 0),
                "low_stock_threshold": getattr(data, "low_stock_threshold", 15),
                "tag": getattr(data, "tag", None),
                "rating": getattr(data, "rating", Decimal("5.0")),
                "reviews_count": getattr(data, "reviews_count", 0),
                "owner_id": getattr(data, "owner_id", None),
                "created_at": getattr(data, "created_at"),
                "updated_at": getattr(data, "updated_at", None),
            }
        return data


class CategoryRead(BaseModel):
    name: str
    count: int