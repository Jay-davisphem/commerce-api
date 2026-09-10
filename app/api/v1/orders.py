from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Order, User
from app.schemas.order import OrderRead
from app.schemas.pagination import CursorPage, decode_cursor, encode_cursor
from app.services.auth import get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("/me", response_model=CursorPage[OrderRead])
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    after: Optional[str] = Query(None, description="Fetch orders after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch orders before this cursor (Previous page)"),
    limit: int = Query(10, ge=1, le=50),
) -> CursorPage[OrderRead]:
    """List orders placed by the authenticated buyer with bidirectional cursor pagination."""
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .options(selectinload(Order.items))
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

    next_cursor = encode_cursor(page_orders[-1].created_at, page_orders[-1].id) if (has_next and page_orders) else None
    prev_cursor = encode_cursor(page_orders[0].created_at, page_orders[0].id) if (has_prev and page_orders) else None

    return CursorPage(
        items=page_orders,
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        has_next=has_next,
        has_prev=has_prev,
        limit=limit,
    )