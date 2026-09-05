from __future__ import annotations

import math
import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Product, Review, User, UserRole
from app.schemas.pagination import PaginatedResponse
from app.schemas.product import CategoryRead, ProductCreate, ProductRead, ProductUpdate
from app.schemas.review import ReviewCreate, ReviewRead
from app.services.auth import get_current_optional_user, require_seller

router = APIRouter(prefix="/products", tags=["Products"])


# --- Public Storefront Endpoints ---

@router.get("", response_model=PaginatedResponse[ProductRead])
async def list_products(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None, description="Search product name/title or description"),
    category: Optional[str] = Query(None, description="Filter by category slug or name"),
    tag: Optional[str] = Query(None, description="hot_deal, special_offer, recommended"),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    sort_by: str = Query(
        "newest",
        pattern="^(newest|latest|created_at_desc|oldest|created_at_asc|price_asc|price_desc)$",
        description="Sort option. 'newest' uses creation timestamp for pure date sorting.",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=100),
) -> PaginatedResponse[ProductRead]:
    """Public storefront catalog search and pagination."""
    query = select(Product)

    if q:
        query = query.where(
            or_(
                Product.title.ilike(f"%{q}%"),
                Product.description.ilike(f"%{q}%"),
            )
        )
    if category:
        query = query.where(Product.category.ilike(category))
    if tag:
        query = query.where(Product.tag == tag)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)

    # Sorting
    if sort_by == "price_asc":
        query = query.order_by(Product.price.asc())
    elif sort_by == "price_desc":
        query = query.order_by(Product.price.desc())
    elif sort_by in ("oldest", "created_at_asc"):
        query = query.order_by(Product.created_at.asc())
    else:
        # Default: newest (pure date sorting: new to old)
        query = query.order_by(Product.created_at.desc())

    count_stmt = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    paginated_stmt = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(paginated_stmt)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(
    db: AsyncSession = Depends(get_db),
) -> list[CategoryRead]:
    """Active categories and counts for filter pills."""
    stmt = (
        select(Product.category, func.count(Product.id))
        .where(Product.category.is_not(None))
        .group_by(Product.category)
    )
    result = await db.execute(stmt)
    return [CategoryRead(name=cat, count=cnt) for cat, cnt in result.all() if cat]


@router.get("/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Product:
    """View a single product by UUID."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )
    return product


# --- Product Reviews Endpoints ---

@router.get("/{product_id}/reviews", response_model=PaginatedResponse[ReviewRead])
async def list_product_reviews(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> PaginatedResponse[ReviewRead]:
    """Fetch reviews for a specific product."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    query = select(Review).where(Review.product_id == product_id)
    count_stmt = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    paginated_stmt = (
        query.order_by(Review.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    reviews = (await db.execute(paginated_stmt)).scalars().all()

    items = [
        ReviewRead(
            id=r.id,
            product_id=r.product_id,
            user_id=r.user_id,
            reviewer_name=r.reviewer_name,
            rating=r.rating,
            comment=r.comment,
            created_at=r.created_at,
            product_title=product.title,
        )
        for r in reviews
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


@router.post("/{product_id}/reviews", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_product_review(
    product_id: uuid.UUID,
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_optional_user),
) -> ReviewRead:
    """Submit a rating (1-5) and feedback for a product. Automatically recalculates product average."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    reviewer_name = payload.reviewer_name
    if current_user:
        reviewer_name = reviewer_name or current_user.full_name or current_user.email.split("@")[0]
    if not reviewer_name:
        reviewer_name = "Verified Customer"

    review = Review(
        product_id=product.id,
        user_id=current_user.id if current_user else None,
        reviewer_name=reviewer_name,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(review)
    await db.flush()

    # Re-aggregate authoritative average rating and review count
    stmt = select(
        func.coalesce(func.round(func.avg(Review.rating), 1), Decimal("5.0")),
        func.count(Review.id),
    ).where(Review.product_id == product.id)
    avg_rating, count = (await db.execute(stmt)).one()

    product.rating = Decimal(str(avg_rating))
    product.reviews_count = count

    await db.commit()
    await db.refresh(review)

    return ReviewRead(
        id=review.id,
        product_id=review.product_id,
        user_id=review.user_id,
        reviewer_name=review.reviewer_name,
        rating=review.rating,
        comment=review.comment,
        created_at=review.created_at,
        product_title=product.title,
    )


# --- Product Management Mutations ---

@router.post(
    "",
    response_model=ProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
    """Create a product owned by the authenticated seller."""
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and "title" not in data:
        data["title"] = data.pop("name")
    elif "name" in data:
        data.pop("name")

    data["owner_id"] = seller.id
    product = Product(**data)
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
    """Update a product (owner or superadmin only)."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own products",
        )

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name":
            setattr(product, "title", value)
        else:
            setattr(product, field, value)

    await db.commit()
    await db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> None:
    """Delete a product (owner or superadmin only)."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own products",
        )

    await db.delete(product)
    await db.commit()