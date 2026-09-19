"""Checkout orchestration for the one-shot (guest and authenticated) checkout flow.

Responsibilities:
1. Load products from the DB using the ids in the payload.
2. Compute the authoritative total server-side.
3. Validate inventory availability.
4. Persist the Order (status=pending) + OrderItems with price snapshots.
5. Initialize configured payment gateway (Paystack or Stripe) and return the checkout URL.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Order, OrderItem, OrderStatus, Product, User
from app.schemas.order import (
    CheckoutRequest,
    CheckoutResponse,
    DeliveryAddress,
    OrderItemRead,
    OrderRead,
)
from app.services.payment import payment_gateway


class CheckoutError(HTTPException):
    """Business-rule error surfaced to the client as an HTTP 400."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class CheckoutService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run(self, payload: CheckoutRequest, user: User | None = None) -> CheckoutResponse:
        # 1. Fetch products & validate ids
        products = await self._fetch_products([i.product_id for i in payload.items])
        by_id = {p.id: p for p in products}
        if len(by_id) != len(payload.items):
            missing = [str(i.product_id) for i in payload.items if i.product_id not in by_id]
            raise CheckoutError(f"Unknown product ids: {', '.join(missing)}")

        # 2. Atomically reserve inventory
        await self._reserve_inventory(payload.items, by_id)

        # 3. Compute server-side authoritative total
        order_items: list[OrderItem] = []
        total = Decimal("0.00")
        for item in payload.items:
            product = by_id[item.product_id]
            line_total = (product.price * item.quantity).quantize(Decimal("0.01"))
            total += line_total
            order_items.append(
                OrderItem(
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price=product.price,
                    line_total=line_total,
                )
            )

        order_email = user.email if user is not None else payload.guest_email
        if not order_email:
            raise CheckoutError("guest_email is required for guest checkout")

        delivery = await self._resolve_delivery(payload, user)

        # 4. Create pending Order
        order = Order(
            guest_email=order_email,
            user_id=user.id if user is not None else None,
            delivery_recipient_name=delivery.recipient_name,
            delivery_phone=delivery.phone,
            delivery_address_line1=delivery.address_line1,
            delivery_address_line2=delivery.address_line2,
            delivery_city=delivery.city,
            delivery_state=delivery.state,
            delivery_postal_code=delivery.postal_code,
            delivery_country=delivery.country,
            delivery_notes=delivery.notes,
            total_amount=total,
            status=OrderStatus.PENDING,
        )
        order.items = order_items
        self.db.add(order)
        await self.db.flush()

        # 5. Initialize configured payment provider (Paystack or Stripe)
        reference = f"ORDER-{order.id}"
        result = await payment_gateway.initialize_payment(
            email=order_email,
            amount=total,
            reference=reference,
            order_id=str(order.id),
        )

        order.paystack_reference = reference
        order.paystack_access_code = result.get("access_code")
        order.paystack_authorization_url = result.get("authorization_url")

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
                        product_title=it.product.title if it.product else "Item",
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

    async def _reserve_inventory(
        self,
        items: list,
        products_by_id: dict[uuid.UUID, Product],
    ) -> None:
        for item in items:
            product = products_by_id[item.product_id]
            result = await self.db.execute(
                update(Product)
                .where(Product.id == item.product_id, Product.inventory_count >= item.quantity)
                .values(inventory_count=Product.inventory_count - item.quantity)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                raise CheckoutError(
                    f"Insufficient stock for '{product.title}' (requested={item.quantity})"
                )

    async def _resolve_delivery(
        self,
        payload: CheckoutRequest,
        user: User | None,
    ) -> DeliveryAddress:
        if user is None:
            if payload.delivery is None:
                raise CheckoutError("Delivery details are required for guest checkout")
            return payload.delivery

        use_saved = payload.use_saved_address or payload.delivery is None
        if not use_saved:
            await self._save_default_delivery(user, payload.delivery)
            return payload.delivery

        missing = (
            not user.default_address_line1
            or not user.default_city
            or not user.default_country
        )
        if missing:
            raise CheckoutError(
                "No saved delivery details on this account. "
                "Provide delivery in the request or save an address first."
            )

        return DeliveryAddress(
            recipient_name=user.default_recipient_name,
            phone=user.default_phone,
            address_line1=user.default_address_line1,
            address_line2=user.default_address_line2,
            city=user.default_city,
            state=user.default_state,
            postal_code=user.default_postal_code,
            country=user.default_country,
            notes=user.default_notes,
        )

    async def _save_default_delivery(self, user: User, delivery: DeliveryAddress) -> None:
        user.default_recipient_name = delivery.recipient_name
        user.default_phone = delivery.phone
        user.default_address_line1 = delivery.address_line1
        user.default_address_line2 = delivery.address_line2
        user.default_city = delivery.city
        user.default_state = delivery.state
        user.default_postal_code = delivery.postal_code
        user.default_country = delivery.country
        user.default_notes = delivery.notes
        self.db.add(user)

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