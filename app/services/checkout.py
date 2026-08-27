"""Checkout orchestration for the one-shot (guest) checkout flow.

Responsibilities:
1. Load products from the DB using the ids in the payload.
2. Compute the *authoritative* total server-side — never trust client prices
   or client totals.
3. Validate inventory availability.
4. Persist the Order (status=pending) + OrderItems with price snapshots.
5. Initialise a Paystack transaction and return the authorization_url.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem, OrderStatus, Product
from app.schemas.order import (
    CheckoutRequest,
    CheckoutResponse,
    DeliveryAddress,
    OrderItemRead,
    OrderRead,
)
from app.services.paystack import paystack


class CheckoutError(HTTPException):
    """Business-rule error surfaced to the client as an HTTP 400."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class CheckoutService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run(self, payload: CheckoutRequest) -> CheckoutResponse:
        """Execute the full one-shot checkout flow for the given payload."""
        # 1 + 2. Load products and compute the server-side total.
        products = await self._fetch_products([i.product_id for i in payload.items])
        by_id = {p.id: p for p in products}

        if len(by_id) != len(payload.items):
            missing = [str(i.product_id) for i in payload.items if i.product_id not in by_id]
            raise CheckoutError(f"Unknown product ids: {', '.join(missing)}")

        # 3. Validate inventory + build order items with *DB* prices.
        order_items: list[OrderItem] = []
        total = Decimal("0.00")
        for item in payload.items:
            product = by_id[item.product_id]
            if product.inventory_count < item.quantity:
                raise CheckoutError(
                    f"Insufficient stock for '{product.title}' "
                    f"(available={product.inventory_count}, requested={item.quantity})"
                )
            line_total = (product.price * item.quantity).quantize(Decimal("0.01"))
            total += line_total
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price=product.price,  # snapshot: authoritative DB price
                    line_total=line_total,
                )
            )

        # Decrement inventory (best-effort reserve at order time).
        for item in payload.items:
            by_id[item.product_id].inventory_count -= item.quantity

        # 4. Persist the pending Order + items.
        order = Order(
            guest_email=payload.guest_email,
            delivery_recipient_name=payload.delivery.recipient_name,
            delivery_phone=payload.delivery.phone,
            delivery_address_line1=payload.delivery.address_line1,
            delivery_address_line2=payload.delivery.address_line2,
            delivery_city=payload.delivery.city,
            delivery_state=payload.delivery.state,
            delivery_postal_code=payload.delivery.postal_code,
            delivery_country=payload.delivery.country,
            delivery_notes=payload.delivery.notes,
            total_amount=total,
            status=OrderStatus.PENDING,
        )
        order.items = order_items
        self.db.add(order)
        await self.db.flush()  # assign order.id before generating the reference

        # 5. Initialise the Paystack transaction with the server-computed total.
        reference = f"ORDER-{order.id}"
        result = await paystack.initialize_transaction(
            email=payload.guest_email,
            amount=total,
            reference=reference,
            metadata={"order_id": str(order.id)},
        )
        order.paystack_reference = reference
        order.paystack_access_code = result.get("access_code")
        order.paystack_authorization_url = result.get("authorization_url")

        # Commit everything (order + payment init) atomically.
        await self.db.commit()
        await self.db.refresh(order, attribute_names=["items"])

        return CheckoutResponse(
            order=OrderRead(
                id=order.id,
                guest_email=order.guest_email,
                delivery=self._delivery_schema(order),
                total_amount=order.total_amount,
                status=order.status,
                payment_status=order.payment_status,
                paystack_reference=order.paystack_reference,
                paid_at=order.paid_at,
                created_at=order.created_at,
                items=[
                    OrderItemRead(
                        id=it.id,
                        product_id=it.product_id,
                        quantity=it.quantity,
                        unit_price=it.unit_price,
                        line_total=it.line_total,
                    )
                    for it in order.items
                ],
            ),
            authorization_url=result.get("authorization_url", ""),
            access_code=result.get("access_code"),
            reference=reference,
        )

    async def _fetch_products(self, ids: list[uuid.UUID]) -> list[Product]:
        stmt = select(Product).where(Product.id.in_(ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _delivery_schema(order: Order) -> DeliveryAddress:
        return DeliveryAddress(
            recipient_name=order.delivery_recipient_name,
            phone=order.delivery_phone,
            address_line1=order.delivery_address_line1,
            address_line2=order.delivery_address_line2,
            city=order.delivery_city,
            state=order.delivery_state,
            postal_code=order.delivery_postal_code,
            country=order.delivery_country,
            notes=order.delivery_notes,
        )


def checkout_service(db: AsyncSession) -> CheckoutService:
    return CheckoutService(db)
