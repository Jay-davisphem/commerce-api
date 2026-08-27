"""ORM models.

Importing this package registers every model on `Base.metadata`, which is
required before `create_all`/Alembic autogenerate can see the tables.
"""

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow
from app.models.order import Order, OrderStatus, PaymentStatus
from app.models.order_item import OrderItem
from app.models.product import Product

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "utcnow",
    "Product",
    "Order",
    "OrderItem",
    "OrderStatus",
    "PaymentStatus",
]
