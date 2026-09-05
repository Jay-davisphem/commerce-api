from __future__ import annotations

import math
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Order, User
from app.schemas.order import OrderRead
from app.schemas.pagination import PaginatedResponse
from app.services.auth import get_current_user

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("/me", response_model=PaginatedResponse[OrderRead])
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
) -> PaginatedResponse[OrderRead]:
    """List orders placed by the currently authenticated buyer."""
    query = (
        select(Order)
        .where(Order.user_id == current_user.id)
        .options(selectinload(Order.items))
        .order_by(Order.created_at.desc())
    )

    count_stmt = select(func.count()).select_from(
        select(Order.id).where(Order.user_id == current_user.id).subquery()
    )
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