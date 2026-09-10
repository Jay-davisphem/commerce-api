"""Super-admin-only user management (create users, list, view, update role)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import User, UserRole
from app.schemas.pagination import CursorPage, decode_cursor, encode_cursor
from app.schemas.user import UserCreate, UserRead
from app.services.auth import require_superadmin
from app.services.security import hash_password

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(require_superadmin)],
)


class RoleUpdate(BaseModel):
    role: UserRole


@router.get("", response_model=CursorPage[UserRead])
async def list_users(
    db: AsyncSession = Depends(get_db),
    role: Optional[UserRole] = Query(None, description="Filter users by system role"),
    search: Optional[str] = Query(None, description="Search by email or full name"),
    after: Optional[str] = Query(None, description="Fetch users after this cursor (Next page)"),
    before: Optional[str] = Query(None, description="Fetch users before this cursor (Previous page)"),
    limit: int = Query(20, ge=1, le=100),
) -> CursorPage[UserRead]:
    """List platform users via bidirectional keyset pagination (Super Admin only)."""
    if after and before:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot provide both 'after' and 'before' cursors simultaneously",
        )

    query = select(User)

    if role:
        query = query.where(User.role == role)

    if search:
        query = query.where(
            or_(
                User.email.ilike(f"%{search}%"),
                User.full_name.ilike(f"%{search}%"),
            )
        )

    is_backward = before is not None

    if after:
        try:
            val_str, cursor_id = decode_cursor(after)
            cursor_dt = datetime.fromisoformat(val_str)
            query = query.where(
                or_(
                    User.created_at < cursor_dt,
                    and_(User.created_at == cursor_dt, User.id < cursor_id),
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
                    User.created_at > cursor_dt,
                    and_(User.created_at == cursor_dt, User.id > cursor_id),
                )
            )
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor")

    if is_backward:
        query = query.order_by(User.created_at.asc(), User.id.asc())
    else:
        query = query.order_by(User.created_at.desc(), User.id.desc())

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
        has_more=has_next,
        limit=limit,
    )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> User:
    email = payload.email.lower()
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )
    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}/role", response_model=UserRead)
async def update_role(
    user_id: uuid.UUID,
    payload: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_superadmin),
) -> User:
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role",
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.role = payload.role
    await db.commit()
    await db.refresh(user)
    return user