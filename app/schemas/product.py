from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProductBase(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    sku: Optional[str] = Field(None, max_length=100, description="Stock Keeping Unit (e.g. CMT-001)")
    description: Optional[str] = None
    price: Decimal = Field(..., ge=0, description="Price in NGN")
    inventory_count: int = Field(default=0, ge=0)
    category: Optional[str] = None
    image_url: Optional[str] = None
    gallery_images: list[str] = Field(
        default_factory=list,
        description="Thumbnail gallery selector image URLs",
    )
    specifications: dict[str, Any] = Field(
        default_factory=dict,
        description="Overview, Supplement Info, Specification, Ingredients, Suggested Use",
    )
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
    sku: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, ge=0)
    inventory_count: Optional[int] = Field(None, ge=0)
    category: Optional[str] = None
    image_url: Optional[str] = None
    gallery_images: Optional[list[str]] = None
    specifications: Optional[dict[str, Any]] = None
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
    sku: Optional[str] = None
    stock_status: str = "in_stock"
    rating: Decimal = Decimal("5.0")
    reviews_count: int = 0
    gallery_images: list[str] = Field(default_factory=list)
    specifications: dict[str, Any] = Field(default_factory=dict)
    owner_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def sync_from_orm(cls, data: Any) -> Any:
        if hasattr(data, "title"):
            title_val = getattr(data, "title")
            inv_count = getattr(data, "inventory_count", 0)
            threshold = getattr(data, "low_stock_threshold", 15)

            if inv_count <= 0:
                status_badge = "out_of_stock"
            elif inv_count <= threshold:
                status_badge = "low_stock"
            else:
                status_badge = "in_stock"

            return {
                "id": getattr(data, "id"),
                "title": title_val,
                "name": getattr(data, "name", title_val) or title_val,
                "sku": getattr(data, "sku", None),
                "stock_status": status_badge,
                "description": getattr(data, "description", None),
                "price": getattr(data, "price"),
                "inventory_count": inv_count,
                "category": getattr(data, "category", None),
                "image_url": getattr(data, "image_url", None),
                "gallery_images": getattr(data, "gallery_images", None) or [],
                "specifications": getattr(data, "specifications", None) or {},
                "original_price": getattr(data, "original_price", None),
                "discount_percentage": getattr(data, "discount_percentage", 0),
                "low_stock_threshold": threshold,
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


class RatingCount(BaseModel):
    stars: int
    count: int
    percentage: float


class ProductRatingsSummary(BaseModel):
    average_rating: Decimal
    reviews_count: int
    breakdown: list[RatingCount]


class StorefrontHomeResponse(BaseModel):
    hot_deals: list[ProductRead]
    special_offers: list[ProductRead]
    categories: list[CategoryRead]
    recommended: list[ProductRead]
    new_arrivals: list[ProductRead]
    mostly_ordered: list[ProductRead]

    model_config = ConfigDict(from_attributes=True)