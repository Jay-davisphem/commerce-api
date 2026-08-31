"""Authentication endpoints: self-registration, login, and current-user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Order, User, UserRole
from app.schemas.user import (
    DeliveryDetailsUpdate,
    LoginRequest,
    TokenResponse,
    UserRead,
    UserRegister,
)
from app.services.auth import authenticate_user, get_current_user
from app.services.security import create_access_token, hash_password

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Create a new seller account and return a JWT.

    Past guest orders placed with the same email are linked to the new user so
    buyers can track their purchase history after creating a password.
    """
    email = payload.email.lower()

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.SELLER,
    )
    db.add(user)
    await db.flush()  # assign user.id

    # Link any past guest orders that used this email.
    await db.execute(
        update(Order)
        .where(Order.guest_email == email, Order.user_id.is_(None))
        .values(user_id=user.id)
    )

    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=user.email, role=user.role, user_id=str(user.id))
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post(
    "/register-buyer",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_buyer(
    payload: UserRegister,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Guest opt-in account creation after checkout.

    A guest who just paid can create a password to save their account and track
    orders. Creates a `BUYER` (no product-management rights). Past guest orders
    placed with the same email are linked so purchase history is preserved.
    """
    email = payload.email.lower()

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=UserRole.BUYER,
    )
    db.add(user)
    await db.flush()  # assign user.id

    # Link any past guest orders that used this email.
    await db.execute(
        update(Order)
        .where(Order.guest_email == email, Order.user_id.is_(None))
        .values(user_id=user.id)
    )

    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=user.email, role=user.role, user_id=str(user.id))
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Exchange valid credentials for an access token."""
    email = payload.email.lower()
    user = await authenticate_user(db, email, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(subject=user.email, role=user.role, user_id=str(user.id))
    return TokenResponse(access_token=token, user=UserRead.model_validate(user))


@router.get("/me", response_model=UserRead)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's profile."""
    return current_user


@router.put("/me/delivery", response_model=UserRead)
async def update_my_delivery(
    payload: DeliveryDetailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Save/update the authenticated user's default delivery details.

    Only the fields present in the payload are updated (partial update). These
    prefill checkout when the buyer chooses "use saved address".
    """
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)

    # Map profile field names to the User model's `default_*` columns.
    field_map = {
        "recipient_name": "default_recipient_name",
        "phone": "default_phone",
        "address_line1": "default_address_line1",
        "address_line2": "default_address_line2",
        "city": "default_city",
        "state": "default_state",
        "postal_code": "default_postal_code",
        "country": "default_country",
        "notes": "default_notes",
    }
    for api_field, model_attr in field_map.items():
        if api_field in updates:
            setattr(current_user, model_attr, updates[api_field])

    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user
