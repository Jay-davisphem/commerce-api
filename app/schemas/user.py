"""Pydantic v2 schemas for users, registration, and token responses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.user import UserRole


class UserRegister(BaseModel):
    """Self-registration payload. New accounts default to the SELLER role."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


class UserCreate(BaseModel):
    """Admin-created user payload (role is explicitly chosen by the admin)."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.SELLER


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class DeliveryDetailsUpdate(BaseModel):
    """Update a user's saved default delivery details (all optional, partial)."""

    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=30)
    country: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    created_at: datetime
    # Saved default delivery details (nullable until set).
    default_recipient_name: str | None = None
    default_phone: str | None = None
    default_address_line1: str | None = None
    default_address_line2: str | None = None
    default_city: str | None = None
    default_state: str | None = None
    default_postal_code: str | None = None
    default_country: str | None = None
    default_notes: str | None = None


# Resolve forward ref for TokenResponse → UserRead.
TokenResponse.model_rebuild()
