from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Order, OrderStatus, Product, Review, User, UserRole
from app.schemas.pagination import CursorPage, decode_cursor, encode_cursor
from app.schemas.product import ProductRead
from app.schemas.review import ReviewRead
from app.schemas.seller import (
    LowStockAlertItem,
    RecentOrderSummary,
    RestockRequest,
    SellerDashboardStats,
    SellerOrderStatusUpdate,
)
from app.services.auth import require_seller

router = APIRouter(prefix="/sellers", tags=["Sellers"])


# ==========================================
# 1. SELLER INVENTORY (BIDIRECTIONAL CURSOR)
# ==========================================

@router.get("/products", response_model=CursorPage[ProductRead])
async def list_my_products(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    q: Optional[str] = Query(None, description="Search own products by title"),
    after: Optional[str] = Query(None, description="Fetch products after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch products before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=100),
) -> CursorPage[ProductRead]:
    """List products owned exclusively by the seller with bidirectional cursor pagination."""
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = select(Product).where(Product.owner_id == seller.id)

    if q:
        query = query.where(Product.title.ilike(f"%{q}%"))

    is_backward = before is not None

    if after:
        try:
            val_str, cursor_id = decode_cursor(after)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    Product.created_at < cursor_dt,
                    and_(Product.created_at == cursor_dt, Product.id < cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")
    elif before:
        try:
            val_str, cursor_id = decode_cursor(before)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    Product.created_at > cursor_dt,
                    and_(Product.created_at == cursor_dt, Product.id > cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")

    # Invert sorting on backward navigation
    if is_backward:
        query = query.order_by(Product.created_at.asc(), Product.id.asc())
    else:
        query = query.order_by(Product.created_at.desc(), Product.id.desc())

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

    next_cursor = encode_cursor(items[-1].created_at, items[-1].id) if (has_next and items) else None
    prev_cursor = encode_cursor(items[0].created_at, items[0].id) if (has_prev and items) else None

    return CursorPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


# ==========================================
# 2. DASHBOARD METRICS & WIDGETS
# ==========================================

@router.get("/dashboard", response_model=SellerDashboardStats)
async def get_seller_dashboard(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> SellerDashboardStats:
    today_start = datetime.combine(datetime.utcnow().date(), time.min)

    online_stmt = select(func.count(Order.id)).where(
        Order.created_at >= today_start,
        Order.order_source == "ONLINE",
    )
    online_orders_today = (await db.execute(online_stmt)).scalar_one() or 0

    pos_stmt = select(func.coalesce(func.sum(Order.total_amount), Decimal("0.00"))).where(
        Order.created_at >= today_start,
        Order.order_source == "POS",
    )
    pos_sales_today = (await db.execute(pos_stmt)).scalar_one() or Decimal("0.00")

    escrow_stmt = select(func.coalesce(func.sum(Order.total_amount), Decimal("0.00"))).where(
        Order.status.in_([OrderStatus.PAID, OrderStatus.IN_ESCROW, OrderStatus.IN_TRANSIT])
    )
    goods_in_escrow = (await db.execute(escrow_stmt)).scalar_one() or Decimal("0.00")

    low_stock_filter = (
        Product.owner_id == seller.id
        if seller.role != UserRole.SUPER_ADMIN
        else True
    )
    stock_condition = Product.inventory_count <= Product.low_stock_threshold

    count_low_stmt = select(func.count(Product.id)).where(
        low_stock_filter, stock_condition
    )
    low_stock_count = (await db.execute(count_low_stmt)).scalar_one() or 0

    items_low_stmt = (
        select(Product)
        .where(low_stock_filter, stock_condition)
        .order_by(Product.inventory_count.asc())
        .limit(5)
    )
    low_stock_rows = (await db.execute(items_low_stmt)).scalars().all()

    recent_orders_stmt = (
        select(Order)
        .order_by(Order.created_at.desc())
        .limit(5)
    )
    recent_orders_rows = (await db.execute(recent_orders_stmt)).scalars().all()

    return SellerDashboardStats(
        online_orders_today=online_orders_today,
        pos_sales_today=pos_sales_today,
        goods_in_escrow=goods_in_escrow,
        low_stock_alerts=low_stock_count,
        low_stock_items=[
            LowStockAlertItem(
                product_id=p.id,
                name=p.title,
                inventory_count=p.inventory_count,
                low_stock_threshold=p.low_stock_threshold,
            )
            for p in low_stock_rows
        ],
        recent_orders=[
            RecentOrderSummary(
                id=o.id,
                order_reference=o.order_reference,
                customer_name=o.customer_name,
                total_amount=o.total_amount,
                status=o.status.value.replace("_", " ").title(),
                created_at=o.created_at,
            )
            for o in recent_orders_rows
        ],
    )


# ==========================================
# 3. SELLER REVIEWS (BIDIRECTIONAL CURSOR)
# ==========================================

@router.get("/reviews", response_model=CursorPage[ReviewRead])
async def list_seller_reviews(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    after: Optional[str] = Query(None, description="Fetch reviews after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch reviews before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=50),
) -> CursorPage[ReviewRead]:
    """Fetch reviews for products owned by this seller with bidirectional cursor pagination."""
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = (
        select(Review, Product.title)
        .join(Product, Review.product_id == Product.id)
        .where(Product.owner_id == seller.id)
    )

    is_backward = before is not None

    if after:
        try:
            val_str, cursor_id = decode_cursor(after)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    Review.created_at < cursor_dt,
                    and_(Review.created_at == cursor_dt, Review.id < cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")
    elif before:
        try:
            val_str, cursor_id = decode_cursor(before)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    Review.created_at > cursor_dt,
                    and_(Review.created_at == cursor_dt, Review.id > cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")

    if is_backward:
        query = query.order_by(Review.created_at.asc(), Review.id.asc())
    else:
        query = query.order_by(Review.created_at.desc(), Review.id.desc())

    results = list((await db.execute(query.limit(limit + 1))).all())

    has_more = len(results) > limit
    page_results = results[:limit]

    if is_backward:
        page_results.reverse()
        has_next = True
        has_prev = has_more
    else:
        has_next = has_more
        has_prev = after is not None

    items = [
        ReviewRead(
            id=review.id,
            product_id=review.product_id,
            user_id=review.user_id,
            reviewer_name=review.reviewer_name,
            rating=review.rating,
            comment=review.comment,
            created_at=review.created_at,
            product_title=product_title,
        )
        for review, product_title in page_results
    ]

    next_cursor = encode_cursor(page_results[-1][0].created_at, page_results[-1][0].id) if (has_next and page_results) else None
    prev_cursor = encode_cursor(page_results[0][0].created_at, page_results[0][0].id) if (has_prev and page_results) else None

    return CursorPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


# ==========================================
# 4. SELLER ORDERS (BIDIRECTIONAL CURSOR)
# ==========================================

@router.get("/orders", response_model=CursorPage[RecentOrderSummary])
async def list_seller_orders(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    after: Optional[str] = Query(None, description="Fetch orders after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch orders before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=50),
) -> CursorPage[RecentOrderSummary]:
    """Search and filter customer orders with bidirectional cursor pagination."""
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = select(Order)

    if status_filter:
        canonical_status = status_filter.lower().replace(" ", "_")
        query = query.where(Order.status == canonical_status)

    if search:
        query = query.where(
            or_(
                Order.paystack_reference.ilike(f"%{search}%"),
                Order.delivery_recipient_name.ilike(f"%{search}%"),
            )
        )

    is_backward = before is not None

    if after:
        try:
            val_str, cursor_id = decode_cursor(after)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    Order.created_at < cursor_dt,
                    and_(Order.created_at == cursor_dt, Order.id < cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")
    elif before:
        try:
            val_str, cursor_id = decode_cursor(before)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    Order.created_at > cursor_dt,
                    and_(Order.created_at == cursor_dt, Order.id > cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")

    if is_backward:
        query = query.order_by(Order.created_at.asc(), Order.id.asc())
    else:
        query = query.order_by(Order.created_at.desc(), Order.id.desc())

    orders = list((await db.execute(query.limit(limit + 1))).scalars().all())

    has_more = len(orders) > limit
    page_orders = orders[:limit]

    if is_backward:
        page_orders.reverse()
        has_next = True
        has_prev = has_more
    else:
        has_next = has_more
        has_prev = after is not None

    items = [
        RecentOrderSummary(
            id=o.id,
            order_reference=o.order_reference,
            customer_name=o.customer_name,
            total_amount=o.total_amount,
            status=o.status.value.replace("_", " ").title(),
            created_at=o.created_at,
        )
        for o in page_orders
    ]

    next_cursor = encode_cursor(page_orders[-1].created_at, page_orders[-1].id) if (has_next and page_orders) else None
    prev_cursor = encode_cursor(page_orders[0].created_at, page_orders[0].id) if (has_prev and page_orders) else None

    return CursorPage(
        items=items,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )


@router.patch("/orders/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    payload: SellerOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> dict[str, str]:
    order = await db.get(Order, order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    normalized_status = payload.status.lower().replace(" ", "_")
    try:
        order.status = OrderStatus(normalized_status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid order status: {payload.status}",
        )

    await db.commit()
    return {"message": "Order status updated", "status": order.status.value}


@router.post("/products/{product_id}/restock")
async def restock_product(
    product_id: uuid.UUID,
    payload: RestockRequest,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> dict[str, object]:
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
            detail="You can only restock your own products",
        )

    product.inventory_count += payload.quantity
    await db.commit()
    await db.refresh(product)

    return {
        "message": "Product restocked successfully",
        "product_id": str(product.id),
        "inventory_count": product.inventory_count,
    }