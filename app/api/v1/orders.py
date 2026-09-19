from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Order, OrderItem, OrderStatus, PaymentStatus, User
from app.schemas.order import (
    BuyerOrderDetail,
    ConfirmReceivedResponse,
    DeliveryAddress,
    OrderItemRead,
    OrderRead,
    TimelineStep,
)
from app.schemas.pagination import CursorPage, decode_cursor, encode_cursor
from app.services.auth import get_current_user
from app.services.email import email_service

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("/me", response_model=CursorPage[OrderRead])
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status_filter: Optional[str] = Query(None, alias="status", description="awaiting_delivery, delivered, cancelled"),
    after: Optional[str] = Query(None, description="Fetch orders after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch orders before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=50),
) -> CursorPage[OrderRead]:
    """List orders placed by the authenticated buyer with tab filtering and bidirectional keyset pagination."""
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
    )

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
        OrderRead(
            id=o.id,
            order_reference=o.order_reference,
            customer_name=o.customer_name,
            guest_email=o.guest_email,
            delivery=DeliveryAddress(
                recipient_name=o.delivery_recipient_name,
                phone=o.delivery_phone,
                address_line1=o.delivery_address_line1,
                address_line2=o.delivery_address_line2,
                city=o.delivery_city,
                state=o.delivery_state,
                postal_code=o.delivery_postal_code,
                country=o.delivery_country,
                notes=o.delivery_notes,
            ),
            total_amount=o.total_amount,
            status=o.status,
            payment_status=o.payment_status,
            paystack_reference=o.paystack_reference,
            paid_at=o.paid_at,
            created_at=o.created_at,
            items=[
                OrderItemRead(
                    id=it.id,
                    product_id=it.product_id,
                    product_title=it.product.title if it.product else "Item",
                    quantity=it.quantity,
                    unit_price=it.unit_price,
                    line_total=it.line_total,
                )
                for it in o.items
            ],
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


@router.get("/{order_id}", response_model=BuyerOrderDetail)
async def get_my_order_detail(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BuyerOrderDetail:
    """Detailed view of an individual order for the authenticated buyer."""
    stmt = (
        select(Order)
        .where(Order.id == order_id, Order.user_id == current_user.id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    is_paid = order.status in (OrderStatus.PAID, OrderStatus.IN_ESCROW, OrderStatus.IN_TRANSIT, OrderStatus.DELIVERED)
    can_mark_received = order.status in (OrderStatus.PAID, OrderStatus.IN_ESCROW, OrderStatus.IN_TRANSIT)

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

    banner_msg = (
        "Funds will be released after buyer confirms delivery."
        if order.status != OrderStatus.DELIVERED
        else "Funds have been released to the seller."
    )

    return BuyerOrderDetail(
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
        items=[
            OrderItemRead(
                id=it.id,
                product_id=it.product_id,
                product_title=it.product.title if it.product else "Item",
                quantity=it.quantity,
                unit_price=it.unit_price,
                line_total=it.line_total,
            )
            for it in order.items
        ],
        delivery=DeliveryAddress(
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
        timeline=timeline,
        escrow_banner_message=banner_msg,
        can_mark_received=can_mark_received,
    )


@router.post("/{order_id}/confirm-received", response_model=ConfirmReceivedResponse)
async def confirm_order_received(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConfirmReceivedResponse:
    """Buyer marks order as received, releasing escrow funds and triggering confirmation email."""
    stmt = (
        select(Order)
        .where(Order.id == order_id, Order.user_id == current_user.id)
        .options(selectinload(Order.items).joinedload(OrderItem.product))
    )
    order = (await db.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.status == OrderStatus.DELIVERED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order has already been confirmed as delivered",
        )

    if order.status in (OrderStatus.CANCELLED, OrderStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot confirm receipt for a cancelled or failed order",
        )

    now = datetime.now(timezone.utc)
    order.status = OrderStatus.DELIVERED
    order.payment_status = PaymentStatus.PAID
    order.delivered_at = now

    await db.commit()

    # Trigger delivered/escrow-released notification to order.guest_email
    await email_service.send_order_status_email(order, "delivered")

    return ConfirmReceivedResponse(
        message="Delivery confirmed and escrow released successfully",
        order_id=order.id,
        order_reference=order.order_reference,
        status=order.status.value,
    )