"""add buyer role

Revision ID: 95eba297a277
Revises: 9ed4e7477971
Create Date: 2026-08-29 07:26:54.139620

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '95eba297a277'
down_revision = '9ed4e7477971'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic autogenerate does not detect enum *value* additions, so we add the
    # new BUYER value to the existing `user_role` Postgres enum type directly.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'BUYER'")


def downgrade() -> None:
    # PostgreSQL does not support removing a value from an enum type without
    # recreating the type. BUYER is a safe addition (no rows depend on it being
    # removed for downgrade correctness in normal use), so downgrade is a no-op
    # here. Recreating the type to drop the value is only necessary if we need
    # a strict rollback.
    pass
