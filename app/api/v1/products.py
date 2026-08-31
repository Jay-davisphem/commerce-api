import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Product, User, UserRole
from app.schemas.product import ProductCreate, ProductRead, ProductUpdate
from app.services.auth import require_seller

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("", response_model=list[ProductRead])
async def list_products(db: AsyncSession = Depends(get_db)) -> list[Product]:
    """Public — buyers browse all products."""
    result = await db.execute(select(Product).order_by(Product.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Product:
    """Public — buyers view a single product."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_seller),
) -> Product:
    """Sellers and super admins may create products.

    Ownership is derived from the authenticated user — never from the client.
    A super admin may create a product without an owner (system product).
    """
    data = payload.model_dump()
    if user.role == UserRole.SUPER_ADMIN:
        data["owner_id"] = None
    else:
        data["owner_id"] = user.id
    product = Product(**data)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


def _assert_can_manage(product: Product, user: User) -> None:
    """Super admins manage any product; sellers only their own."""
    if user.role == UserRole.SUPER_ADMIN:
        return
    if product.owner_id is None or product.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own products",
        )


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_seller),
) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    _assert_can_manage(product, user)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_seller),
) -> None:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    _assert_can_manage(product, user)
    await db.delete(product)
    await db.commit()
