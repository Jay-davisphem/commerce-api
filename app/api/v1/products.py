from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_service
from app.core.config import settings
from app.core.database import get_db
from app.models import Product, Review, User, UserRole
from app.models.order_item import OrderItem
from app.schemas.pagination import CursorPage, decode_cursor, encode_cursor
from app.schemas.product import (
    BatchProductRequest,
    CategoryRead,
    ProductCreate,
    ProductRatingsSummary,
    ProductRead,
    ProductUpdate,
    RatingCount,
    StorefrontHomeResponse,
)
from app.schemas.review import ReviewCreate, ReviewRead
from app.services.auth import get_current_optional_user, require_seller
from app.services.storage import storage_service

router = APIRouter(prefix="/products", tags=["Products"])


# ==========================================
# 1. STOREFRONT CATALOG & FEEDS
# ==========================================

@router.get("/storefront/home", response_model=StorefrontHomeResponse)
async def get_storefront_homepage(db: AsyncSession = Depends(get_db)) -> StorefrontHomeResponse:
    """Consolidated endpoint delivering all homepage shelves in a single cached call."""
    cache_key = "storefront:homepage:v1"
    cached = await cache_service.get(cache_key)
    if cached:
        return StorefrontHomeResponse(**cached)

    # 1. Hot Deals
    hot_deals = (await db.execute(
        select(Product).where(Product.tag == "hot_deal").limit(5)
    )).scalars().all()

    # 2. Special Offers
    special_offers = (await db.execute(
        select(Product).where(Product.tag == "special_offer").limit(6)
    )).scalars().all()

    # 3. Recommended
    recommended = (await db.execute(
        select(Product).where(Product.tag == "recommended").limit(5)
    )).scalars().all()

    # 4. New Arrivals
    new_arrivals = (await db.execute(
        select(Product).order_by(Product.created_at.desc()).limit(5)
    )).scalars().all()

    # 5. Mostly Ordered
    mostly_ordered_stmt = (
        select(Product)
        .outerjoin(OrderItem, Product.id == OrderItem.product_id)
        .group_by(Product.id)
        .order_by(func.coalesce(func.sum(OrderItem.quantity), 0).desc())
        .limit(8)
    )
    mostly_ordered = (await db.execute(mostly_ordered_stmt)).scalars().all()

    # 6. Categories
    cat_stmt = (
        select(Product.category, func.count(Product.id))
        .where(Product.category.is_not(None))
        .group_by(Product.category)
    )
    cats = [CategoryRead(name=c, count=cnt) for c, cnt in (await db.execute(cat_stmt)).all() if c]

    response_data = {
        "hot_deals": [ProductRead.model_validate(p).model_dump() for p in hot_deals],
        "special_offers": [ProductRead.model_validate(p).model_dump() for p in special_offers],
        "categories": [c.model_dump() for c in cats],
        "recommended": [ProductRead.model_validate(p).model_dump() for p in recommended],
        "new_arrivals": [ProductRead.model_validate(p).model_dump() for p in new_arrivals],
        "mostly_ordered": [ProductRead.model_validate(p).model_dump() for p in mostly_ordered],
    }

    await cache_service.set(cache_key, response_data, ttl_seconds=300)
    return StorefrontHomeResponse(**response_data)


@router.get("/categories", response_model=list[CategoryRead])
async def list_categories(db: AsyncSession = Depends(get_db)) -> list[CategoryRead]:
    cache_key = "catalog:categories:v1"
    cached = await cache_service.get(cache_key)
    if cached:
        return [CategoryRead(**c) for c in cached]

    stmt = (
        select(Product.category, func.count(Product.id))
        .where(Product.category.is_not(None))
        .group_by(Product.category)
    )
    result = await db.execute(stmt)
    cats = [CategoryRead(name=cat, count=cnt) for cat, cnt in result.all() if cat]
    await cache_service.set(cache_key, [c.model_dump() for c in cats], ttl_seconds=300)
    return cats


@router.get("", response_model=CursorPage[ProductRead])
async def list_products(
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(None, description="Search product title/description (GIN Trigram indexed)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="hot_deal, special_offer, recommended"),
    min_price: Optional[Decimal] = Query(None, ge=0),
    max_price: Optional[Decimal] = Query(None, ge=0),
    sort_by: str = Query(
        "newest",
        pattern="^(newest|latest|oldest|price_asc|price_desc)$",
    ),
    after: Optional[str] = Query(None, description="Fetch items after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch items before this cursor (Previous page)"),
    limit: int = Query(12, ge=1, le=100),
) -> CursorPage[ProductRead]:
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = select(Product)

    if q:
        query = query.where(or_(Product.title.ilike(f"%{q}%"), Product.description.ilike(f"%{q}%")))
    if category:
        query = query.where(Product.category.ilike(category))
    if tag:
        query = query.where(Product.tag == tag)
    if min_price is not None:
        query = query.where(Product.price >= min_price)
    if max_price is not None:
        query = query.where(Product.price <= max_price)

    # Forward seek
    if after:
        val_str, cursor_id = decode_cursor(after)
        if sort_by in ("newest", "latest"):
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(Product.created_at < cursor_dt, and_(Product.created_at == cursor_dt, Product.id < cursor_id))
            )
        elif sort_by == "oldest":
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(Product.created_at > cursor_dt, and_(Product.created_at == cursor_dt, Product.id > cursor_id))
            )
        elif sort_by == "price_asc":
            cursor_price = Decimal(val_str)
            query = query.where(
                or_(Product.price > cursor_price, and_(Product.price == cursor_price, Product.id > cursor_id))
            )
        elif sort_by == "price_desc":
            cursor_price = Decimal(val_str)
            query = query.where(
                or_(Product.price < cursor_price, and_(Product.price == cursor_price, Product.id < cursor_id))
            )

    # Backward seek
    elif before:
        val_str, cursor_id = decode_cursor(before)
        if sort_by in ("newest", "latest"):
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(Product.created_at > cursor_dt, and_(Product.created_at == cursor_dt, Product.id > cursor_id))
            )
        elif sort_by == "oldest":
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(Product.created_at < cursor_dt, and_(Product.created_at == cursor_dt, Product.id < cursor_id))
            )
        elif sort_by == "price_asc":
            cursor_price = Decimal(val_str)
            query = query.where(
                or_(Product.price < cursor_price, and_(Product.price == cursor_price, Product.id < cursor_id))
            )
        elif sort_by == "price_desc":
            cursor_price = Decimal(val_str)
            query = query.where(
                or_(Product.price > cursor_price, and_(Product.price == cursor_price, Product.id > cursor_id))
            )

    is_backward = before is not None
    if sort_by == "price_asc":
        query = query.order_by(
            Product.price.desc() if is_backward else Product.price.asc(),
            Product.id.desc() if is_backward else Product.id.asc(),
        )
    elif sort_by == "price_desc":
        query = query.order_by(
            Product.price.asc() if is_backward else Product.price.desc(),
            Product.id.asc() if is_backward else Product.id.desc(),
        )
    elif sort_by == "oldest":
        query = query.order_by(
            Product.created_at.desc() if is_backward else Product.created_at.asc(),
            Product.id.desc() if is_backward else Product.id.asc(),
        )
    else:
        query = query.order_by(
            Product.created_at.asc() if is_backward else Product.created_at.desc(),
            Product.id.asc() if is_backward else Product.id.desc(),
        )

    result = await db.execute(query.limit(limit + 1))
    rows = list(result.scalars().all())

    has_more = len(rows) > limit
    items = rows[:limit]

    if is_backward:
        items.reverse()
        has_next = True
        has_prev = has_more
    else:
        has_next = has_more
        has_prev = after is not None

    def get_sort_key(item: Product) -> Any:
        return item.price if "price" in sort_by else item.created_at

    next_cursor = encode_cursor(get_sort_key(items[-1]), items[-1].id) if (has_next and items) else None
    prev_cursor = encode_cursor(get_sort_key(items[0]), items[0].id) if (has_prev and items) else None

    return CursorPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        has_more=has_next,
        limit=limit,
    )


# ==========================================
# 2. PRODUCT DETAILS & RELATED DATA
# ==========================================

@router.get("/{product_id}", response_model=ProductRead)
async def get_product(product_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Product:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.get("/{product_id}/similar", response_model=list[ProductRead])
async def get_similar_products(
    product_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[Product]:
    """Fetch similar products in the same category (or fallback to top-rated items)."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    query = select(Product).where(Product.id != product_id)
    if product.category:
        query = query.where(Product.category == product.category)

    results = list(
        (await db.execute(query.order_by(Product.rating.desc(), Product.created_at.desc()).limit(limit))).scalars().all()
    )

    # Fallback to general popular items if same category has fewer than requested
    if len(results) < limit:
        additional_needed = limit - len(results)
        existing_ids = [p.id for p in results] + [product_id]
        fallback_stmt = (
            select(Product)
            .where(Product.id.not_in(existing_ids))
            .order_by(Product.rating.desc(), Product.created_at.desc())
            .limit(additional_needed)
        )
        fallback_results = list((await db.execute(fallback_stmt)).scalars().all())
        results.extend(fallback_results)

    return results


@router.get("/{product_id}/ratings-summary", response_model=ProductRatingsSummary)
async def get_product_ratings_summary(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ProductRatingsSummary:
    """Provides ratings aggregate score and breakdown histogram (5, 4, 3, 2, 1 stars)."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    stmt = (
        select(Review.rating, func.count(Review.id))
        .where(Review.product_id == product_id)
        .group_by(Review.rating)
    )
    result = await db.execute(stmt)
    counts_map = dict(result.all())

    total = product.reviews_count or sum(counts_map.values()) or 0

    breakdown = []
    for star in range(5, 0, -1):
        c = counts_map.get(star, 0)
        pct = round((c / total * 100.0), 1) if total > 0 else 0.0
        breakdown.append(RatingCount(stars=star, count=c, percentage=pct))

    return ProductRatingsSummary(
        average_rating=product.rating,
        reviews_count=total,
        breakdown=breakdown,
    )


@router.get("/{product_id}/reviews", response_model=CursorPage[ReviewRead])
async def list_product_reviews(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    after: Optional[str] = Query(None, description="Fetch reviews after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch reviews before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=50),
) -> CursorPage[ReviewRead]:
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    query = select(Review).where(Review.product_id == product_id)

    is_backward = before is not None
    if after:
        try:
            val_str, cursor_id = decode_cursor(after)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(Review.created_at < cursor_dt, and_(Review.created_at == cursor_dt, Review.id < cursor_id))
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")
    elif before:
        try:
            val_str, cursor_id = decode_cursor(before)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(Review.created_at > cursor_dt, and_(Review.created_at == cursor_dt, Review.id > cursor_id))
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")

    if is_backward:
        query = query.order_by(Review.created_at.asc(), Review.id.asc())
    else:
        query = query.order_by(Review.created_at.desc(), Review.id.desc())

    reviews = list((await db.execute(query.limit(limit + 1))).scalars().all())
    has_more = len(reviews) > limit
    page_reviews = reviews[:limit]

    if is_backward:
        page_reviews.reverse()
        has_next = True
        has_prev = has_more
    else:
        has_next = has_more
        has_prev = after is not None

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
        for r in page_reviews
    ]

    next_cursor = encode_cursor(page_reviews[-1].created_at, page_reviews[-1].id) if (has_next and page_reviews) else None
    prev_cursor = encode_cursor(page_reviews[0].created_at, page_reviews[0].id) if (has_prev and page_reviews) else None

    return CursorPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        has_more=has_next,
        limit=limit,
    )


@router.post("/{product_id}/reviews", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
async def create_product_review(
    product_id: uuid.UUID,
    payload: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_optional_user),
) -> ReviewRead:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

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


# ==========================================
# 3. SELLER MUTATIONS & R2 UPLOADS
# ==========================================

@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
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
    await cache_service.invalidate_prefix("catalog:categories")
    await cache_service.invalidate_prefix("storefront:homepage")
    return product


@router.post("/{product_id}/image", response_model=ProductRead)
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
    """Stream primary product image to Cloudflare R2 and update image_url."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only upload images for your own products",
        )

    content_type = (file.content_type or "").lower()
    if content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed: {', '.join(settings.ALLOWED_IMAGE_TYPES)}",
        )

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/avif": ".avif",
    }
    ext = ext_map.get(content_type, ".jpg")
    filename = f"products/{product_id}_{uuid.uuid4().hex[:8]}{ext}"

    file_bytes = bytearray()
    chunk_size = 1024 * 1024
    while chunk := await file.read(chunk_size):
        file_bytes.extend(chunk)
        if len(file_bytes) > settings.MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed size of {settings.MAX_IMAGE_SIZE_BYTES // (1024 * 1024)} MB",
            )

    if product.image_url:
        await storage_service.delete_file(product.image_url)

    public_url = await storage_service.upload_file(bytes(file_bytes), filename, content_type)
    product.image_url = public_url

    await db.commit()
    await db.refresh(product)
    await cache_service.invalidate_prefix("storefront:homepage")
    return product


@router.post("/{product_id}/gallery-image", response_model=ProductRead)
async def upload_product_gallery_image(
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> Product:
    """Stream a gallery image to Cloudflare R2 and append to gallery_images array."""
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only upload images for your own products",
        )

    content_type = (file.content_type or "").lower()
    if content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type. Allowed: {', '.join(settings.ALLOWED_IMAGE_TYPES)}",
        )

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/avif": ".avif",
    }
    ext = ext_map.get(content_type, ".jpg")
    filename = f"products/{product_id}_gallery_{uuid.uuid4().hex[:8]}{ext}"

    file_bytes = bytearray()
    chunk_size = 1024 * 1024
    while chunk := await file.read(chunk_size):
        file_bytes.extend(chunk)
        if len(file_bytes) > settings.MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds maximum allowed size of {settings.MAX_IMAGE_SIZE_BYTES // (1024 * 1024)} MB",
            )

    public_url = await storage_service.upload_file(bytes(file_bytes), filename, content_type)

    # Re-assign list so SQLAlchemy change tracker detects update
    existing_gallery = list(product.gallery_images or [])
    existing_gallery.append(public_url)
    product.gallery_images = existing_gallery

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
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only manage your own products")

    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "name":
            setattr(product, "title", value)
        else:
            setattr(product, field, value)

    await db.commit()
    await db.refresh(product)
    await cache_service.invalidate_prefix("catalog:categories")
    await cache_service.invalidate_prefix("storefront:homepage")
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> None:
    product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if seller.role != UserRole.SUPER_ADMIN and (
        product.owner_id is None or product.owner_id != seller.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only manage your own products")

    if product.image_url:
        await storage_service.delete_file(product.image_url)

    if product.gallery_images:
        for img in product.gallery_images:
            await storage_service.delete_file(img)

    await db.delete(product)
    await db.commit()
    await cache_service.invalidate_prefix("catalog:categories")
    await cache_service.invalidate_prefix("storefront:homepage")
    

@router.post("/batch", response_model=list[ProductRead])
async def get_products_batch(
    payload: BatchProductRequest,
    db: AsyncSession = Depends(get_db),
) -> list[Product]:
    """Hydrates and validates client cart items stored in localStorage in a single call."""
    stmt = select(Product).where(Product.id.in_(payload.product_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())