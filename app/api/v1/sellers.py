from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.database import get_db
from app.models import Order, OrderItem, OrderStatus, PaymentStatus, Product, Review, User, UserRole
from app.schemas.order import DeliveryAddress, OrderItemRead
from app.schemas.pagination import CursorPage, decode_cursor, encode_cursor
from app.schemas.product import ProductRead
from app.schemas.review import ReviewRead
from app.schemas.seller import (
    BuyerInfo,
    InventorySummaryStats,
    LowStockAlertItem,
    RecentOrderSummary,
    RestockRequest,
    SellerDashboardStats,
    SellerOrderDetail,
    SellerOrderStatusUpdate,
    TimelineStep,
)
from app.services.auth import require_seller
from app.services.email import email_service

router = APIRouter(prefix="/sellers", tags=["Sellers"])


# ==========================================
# 1. SELLER INVENTORY (BIDIRECTIONAL CURSOR & STATS)
# ==========================================

@router.get("/inventory/stats", response_model=InventorySummaryStats)
async def get_inventory_stats(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> InventorySummaryStats:
    low_stock_filter = (
        Product.owner_id == seller.id
        if seller.role != UserRole.SUPER_ADMIN
        else True
    )

    total_stmt = select(func.count(Product.id)).where(low_stock_filter)
    total_count = (await db.execute(total_stmt)).scalar_one() or 0

    stock_condition = Product.inventory_count <= Product.low_stock_threshold
    count_low_stmt = select(func.count(Product.id)).where(
        low_stock_filter, stock_condition
    )
    low_stock_count = (await db.execute(count_low_stmt)).scalar_one() or 0

    return InventorySummaryStats(
        total_products=total_count,
        low_stock_count=low_stock_count,
    )


@router.get("/products", response_model=CursorPage[ProductRead])
async def list_my_products(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    q: Optional[str] = Query(None, description="Search own products by title or SKU"),
    after: Optional[str] = Query(None, description="Fetch products after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch products before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=100),
) -> CursorPage[ProductRead]:
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = select(Product).where(Product.owner_id == seller.id)

    if q:
        query = query.where(
            or_(
                Product.title.ilike(f"%{q}%"),
                Product.sku.ilike(f"%{q}%"),
            )
        )

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
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    all_time: bool = Query(False, description="Fetch all-time metrics without date restriction"),
) -> SellerDashboardStats:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be later than end_date",
        )

    date_conditions = []
    if not all_time:
        if start_date is None and end_date is None:
            today = datetime.now(timezone.utc).date()
            start_dt = datetime.combine(today, time.min, tzinfo=timezone.utc)
            end_dt = datetime.combine(today, time.max, tzinfo=timezone.utc)
            date_conditions.extend([Order.created_at >= start_dt, Order.created_at <= end_dt])
        else:
            if start_date:
                start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
                date_conditions.append(Order.created_at >= start_dt)
            if end_date:
                end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
                date_conditions.append(Order.created_at <= end_dt)

    orders_stmt = select(func.count(Order.id))
    if date_conditions:
        orders_stmt = orders_stmt.where(and_(*date_conditions))
    total_orders_count = (await db.execute(orders_stmt)).scalar_one() or 0

    paid_statuses = [
        OrderStatus.PAID,
        OrderStatus.IN_ESCROW,
        OrderStatus.IN_TRANSIT,
        OrderStatus.DELIVERED,
    ]
    sales_conditions = list(date_conditions)
    sales_conditions.append(Order.status.in_(paid_statuses))

    sales_stmt = select(
        func.coalesce(func.sum(Order.total_amount), Decimal("0.00"))
    ).where(and_(*sales_conditions))
    total_sales_amount = (await db.execute(sales_stmt)).scalar_one() or Decimal("0.00")

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
        .options(selectinload(Order.items).joinedload(OrderItem.product))
        .order_by(Order.created_at.desc())
        .limit(5)
    )
    recent_orders_rows = (await db.execute(recent_orders_stmt)).scalars().all()

    return SellerDashboardStats(
        total_orders=total_orders_count,
        today_sales=total_sales_amount,
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
                items_preview=[
                    f"{it.product.title if it.product else 'Item'} x{it.quantity}"
                    for it in o.items
                ],
            )
            for o in recent_orders_rows
        ],
        online_orders_today=total_orders_count,
        pos_sales_today=total_sales_amount,
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
# 4. SELLER ORDERS (BIDIRECTIONAL CURSOR & DETAILS)
# ==========================================

@router.get("/orders", response_model=CursorPage[RecentOrderSummary])
async def list_seller_orders(
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
    status_filter: Optional[str] = Query(None, alias="status", description="awaiting_delivery, delivered, cancelled"),
    search: Optional[str] = Query(None),
    after: Optional[str] = Query(None, description="Fetch orders after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch orders before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=50),
) -> CursorPage[RecentOrderSummary]:
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = select(Order).options(selectinload(Order.items).joinedload(OrderItem.product))

    if status_filter:
        norm = status_filter.lower().strip().replace(" ", "_")
        if norm == "awaiting_delivery":
            query = query.where(Order.status.in_([OrderStatus.PAID, OrderStatus.IN_ESCROW, OrderStatus.IN_TRANSIT]))
        elif norm == "delivered":
            query = query.where(Order.status == OrderStatus.DELIVERED)
        elif norm == "cancelled":
            query = query.where(Order.status.in_([OrderStatus.CANCELLED, OrderStatus.FAILED]))
        else:
            try:
                query = query.where(Order.status == OrderStatus(norm))
            except ValueError:
                pass

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
            items_preview=[
                f"{it.product.title if it.product else 'Item'} x{it.quantity}"
                for it in o.items
            ],
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


@router.get("/orders/{order_id}", response_model=SellerOrderDetail)
async def get_seller_order_detail(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> SellerOrderDetail:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    is_paid = order.status in (OrderStatus.PAID, OrderStatus.IN_ESCROW, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED)
    timeline = [
        TimelineStep(
            step_key="order_placed",
            title="Order Placed",
            status="completed",
            timestamp=order.created_at,
        ),
        TimelineStep(
            step_key="payment_secured",
            title="Payment Secured (Escrow)",
            status="completed" if is_paid else "pending",
            timestamp=order.paid_at or (order.created_at if is_paid else None),
        ),
        TimelineStep(
            step_key="awaiting_pickup",
            title="Awaiting Pickup",
            status="completed" if order.status in (OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED)
            else ("current" if order.status in (OrderStatus.PAID, OrderStatus.IN_ESCROW) else "pending"),
            timestamp=None,
        ),
        TimelineStep(
            step_key="in_transit",
            title="In Transit",
            status="completed" if order.status == OrderStatus.DELIVERED
            else ("current" if order.status == OrderStatus.IN_TRANSIT else "pending"),
            timestamp=order.in_transit_at,
        ),
        TimelineStep(
            step_key="delivery",
            title="Delivery",
            status="completed" if order.status == OrderStatus.DELIVERED else "pending",
            timestamp=order.delivered_at,
        ),
    ]

    status_formatted = order.status.value.replace("_", " ").title()
    status_label = f"{status_formatted} - Payment Secured" if is_paid else f"{status_formatted} - Unpaid"

    buyer_info = BuyerInfo(
        guest_email=order.guest_email,
        recipient_name=order.delivery_recipient_name or order.customer_name,
        phone=order.delivery_phone,
        address=DeliveryAddress(
            recipient_name=order.delivery_recipient_name,
            phone=order.delivery_phone,
            address_line1=order.delivery_address_line1,
            address_line2=order.delivery_address_line2,
            city=order.delivery_city,
            state=order.delivery_state,
            postal_code=order.delivery_postal_code,
            country=order.delivery_country,
            notes=order.delivery_notes,
        ),
    )

    items_read = [
        OrderItemRead(
            id=it.id,
            product_id=it.product_id,
            product_title=it.product.title if it.product else "Item",
            quantity=it.quantity,
            unit_price=it.unit_price,
            line_total=it.line_total,
        )
        for it in order.items
    ]

    return SellerOrderDetail(
        id=order.id,
        order_reference=order.order_reference,
        status=order.status.value,
        status_label=status_label,
        payment_status=order.payment_status.value,
        total_amount=order.total_amount,
        subtotal=order.subtotal,
        escrow_fee=order.escrow_fee,
        created_at=order.created_at,
        paid_at=order.paid_at,
        items=items_read,
        buyer_info=buyer_info,
        timeline=timeline,
        escrow_banner_message="Funds will be released after buyer confirms delivery.",
    )


@router.patch("/orders/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    payload: SellerOrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    seller: User = Depends(require_seller),
) -> dict[str, str]:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    normalized_status = payload.status.lower().replace(" ", "_")
    try:
        new_status = OrderStatus(normalized_status)
        order.status = new_status
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid order status: {payload.status}",
        )

    now = datetime.now(timezone.utc)
    if new_status == OrderStatus.IN_TRANSIT and not order.in_transit_at:
        order.in_transit_at = now
    elif new_status == OrderStatus.DELIVERED:
        if not order.delivered_at:
            order.delivered_at = now
        order.payment_status = PaymentStatus.PAID
    elif new_status in (OrderStatus.PAID, OrderStatus.IN_ESCROW) and not order.paid_at:
        order.paid_at = now
        order.payment_status = PaymentStatus.PAID

    await db.commit()

    # Trigger transactional status update email to customer
    await email_service.send_order_status_email(order, order.status.value)

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