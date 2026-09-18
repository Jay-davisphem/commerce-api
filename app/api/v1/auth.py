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
    PasswordChangeRequest,
    TokenResponse,
    UserProfileUpdate,
    UserRead,
    UserRegister,
)
from app.services.auth import authenticate_user, get_current_user
from app.services.security import create_access_token, hash_password, verify_password

from app.schemas.user import ForgotPasswordRequest, ResetPasswordRequest, VerifyOTPRequest
from app.services.email import email_service
from app.services.otp import generate_otp, store_otp, verify_otp

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(payload: UserRegister, db: AsyncSession = Depends(get_db)) -> TokenResponse:
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
    await db.flush()

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
    await db.flush()

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


@router.patch("/me", response_model=UserRead)
async def update_profile(
    payload: UserProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Update profile details (Name). Accessible by buyers, sellers, and admins."""
    current_user.full_name = payload.full_name.strip()
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.put("/me/password")
async def update_password(
    payload: PasswordChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Change account password. Validates current password and saves new hash."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.hashed_password = hash_password(payload.new_password)
    db.add(current_user)
    await db.commit()
    return {"message": "Password updated successfully"}


@router.put("/me/delivery", response_model=UserRead)
async def update_my_delivery(
    payload: DeliveryDetailsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
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



@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Sends a 6-digit password reset OTP via Resend. Constant response to prevent enumeration."""
    email = payload.email.lower().strip()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user:
        code = generate_otp()
        await store_otp(email, "password_reset", code)
        await email_service.send_otp_email(email, code, purpose="Password Reset")

    return {"message": "If the account exists, a 6-digit reset code has been sent to your email."}


@router.post("/verify-reset-code")
async def verify_reset_code(payload: VerifyOTPRequest) -> dict[str, str]:
    """Optional pre-flight check so the frontend can move the user to the new password input screen."""
    valid = await verify_otp(payload.email, "password_reset", payload.code)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )
    # Re-store code briefly (or issue a reset ticket) for final submission
    await store_otp(payload.email, "password_reset", payload.code)
    return {"message": "Code verified successfully"}


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Validates the reset OTP and updates account password."""
    email = payload.email.lower().strip()
    valid = await verify_otp(email, "password_reset", payload.code)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification code",
        )

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.hashed_password = hash_password(payload.new_password)
    db.add(user)
    await db.commit()

    return {"message": "Password has been reset successfully. You can now log in."}