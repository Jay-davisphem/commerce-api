"""Seller dashboard endpoints.

Sellers manage *their own* products under the `/sellers` base URL. Ownership
is always derived from the authenticated seller — never from client input.

Public product browsing stays on the shared `/products` routes in
`app/api/v1/products.py`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Product, User, UserRole
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.auth import require_seller

router = APIRouter(prefix="/sellers", tags=["Sellers"])


@router.get("/products", response_model=list[ProductRead])
async def list_my_products(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> list[Product]:
    """List the products owned by the authenticated seller."""
    result = await db.execute(
        select(Product)
        .where(Product.owner_id == seller.id)
        .order_by(Product.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/products",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_my_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
    """Create a product owned by the authenticated seller."""
    data = payload.model_dump()
    data["owner_id"] = seller.id
    product = Product(**data)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductRead)
async def update_my_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
    """Update one of the authenticated seller's own products (403 otherwise)."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Sellers may only edit their own products. Super admins may also use this
    # endpoint but ownership is still enforced for sellers.
    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own products",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> None:
    """Delete one of the authenticated seller's own products (403 otherwise)."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own products",
        )

    await db.delete(product)
    await db.commit()
