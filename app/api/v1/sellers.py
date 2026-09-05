from __future__ import annotations

import math
import uuid
from datetime import datetime, time
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Order, OrderStatus, Product, Review, User, UserRole
from app.schemas.pagination import PaginatedResponse
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
# 1. SELLER INVENTORY (READ-ONLY SCOPED)
# ==========================================

@router.get("/products", response_model=PaginatedResponse[ProductRead])
async def list_my_products(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    q: Optional[str] = Query(None, description="Search own products by title"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
) -> PaginatedResponse[ProductRead]:
    """List products owned exclusively by the authenticated seller."""
    query = select(Product).where(Product.owner_id == seller.id)

    if q:
        query = query.where(Product.title.ilike(f"%{q}%"))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one() or 0

    paginated_query = (
        query.order_by(Product.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(paginated_query)
    items = list(result.scalars().all())

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


# ==========================================
# 2. DASHBOARD METRICS & WIDGETS
# ==========================================

@router.get("/dashboard", response_model=SellerDashboardStats)
async def get_seller_dashboard(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> SellerDashboardStats:
    """Fetch dashboard KPI metrics, low-stock items, and recent orders."""
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
# 3. SELLER REVIEWS (DASHBOARD TAB)
# ==========================================

@router.get("/reviews", response_model=PaginatedResponse[ReviewRead])
async def list_seller_reviews(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> PaginatedResponse[ReviewRead]:
    """Fetch customer reviews for all products owned by the authenticated seller."""
    query = (
        select(Review, Product.title)
        .join(Product, Review.product_id == Product.id)
        .where(Product.owner_id == seller.id)
    )

    count_stmt = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    paginated_stmt = (
        query.order_by(Review.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    results = (await db.execute(paginated_stmt)).all()

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
        for review, product_title in results
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


# ==========================================
# 4. SELLER ORDER FULFILLMENT & RESTOCK
# ==========================================

@router.get("/orders", response_model=PaginatedResponse[RecentOrderSummary])
async def list_seller_orders(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> PaginatedResponse[RecentOrderSummary]:
    """Search and filter customer orders with pagination."""
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

    count_stmt = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_stmt)).scalar_one() or 0

    paginated_stmt = (
        query.order_by(Order.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    orders = (await db.execute(paginated_stmt)).scalars().all()

    items = [
        RecentOrderSummary(
            id=o.id,
            order_reference=o.order_reference,
            customer_name=o.customer_name,
            total_amount=o.total_amount,
            status=o.status.value.replace("_", " ").title(),
            created_at=o.created_at,
        )
        for o in orders
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size) if total > 0 else 1,
    )


@router.patch("/orders/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    payload: SellerOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> dict[str, str]:
    """Update order delivery status (in_transit, delivered, cancelled)."""
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
    """Increment inventory count for an alert item."""
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