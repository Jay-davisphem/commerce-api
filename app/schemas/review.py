from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Star rating from 1 to 5")
    reviewer_name: Optional[str] = Field(None, max_length=255, description="Optional name if guest or override")
    comment: Optional[str] = Field(None, description="Written feedback / review note")


class ReviewRead(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    reviewer_name: str
    rating: int
    comment: Optional[str] = None
    created_at: datetime
    product_title: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)