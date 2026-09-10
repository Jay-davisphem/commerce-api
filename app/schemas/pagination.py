from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: Optional[str] = Field(None, description="Cursor for the next page")
    prev_cursor: Optional[str] = Field(None, description="Cursor for the previous page")
    has_next: bool = Field(False, description="Whether a next page exists")
    has_prev: bool = Field(False, description="Whether a previous page exists")
    has_more: bool = Field(False, description="Alias for has_next for compatibility")
    limit: int = Field(..., description="Number of items requested")


def encode_cursor(sort_value: Any, item_id: uuid.UUID) -> str:
    """Encode sort key and entity UUID into an opaque base64 cursor token."""
    if isinstance(sort_value, datetime):
        val = sort_value.isoformat()
    elif isinstance(sort_value, Decimal):
        val = str(sort_value)
    else:
        val = str(sort_value)

    payload = {"v": val, "id": str(item_id)}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor_str: str) -> tuple[str, uuid.UUID]:
    """Decode an opaque cursor token into (sort_value_str, item_uuid)."""
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode()).decode()
        data = json.loads(raw)
        return data["v"], uuid.UUID(data["id"])
    except Exception as exc:
        raise ValueError("Malformed pagination cursor") from exc