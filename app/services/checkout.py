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
from app.services.paystack import paystack


class CheckoutError(HTTPException):
    """Business-rule error surfaced to the client as an HTTP 400."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class CheckoutService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run(self, payload: CheckoutRequest, user: User | None = None) -> CheckoutResponse:
        """Execute the full one-shot checkout flow for the given payload.

        `user` is optional — a logged-in buyer's order is linked to their
        account (and may reuse their saved delivery details); guests
        (user=None) remain pure guest orders and must supply delivery.
        """
        # 1 + 2. Load products and compute the server-side total.
        products = await self._fetch_products([i.product_id for i in payload.items])
        by_id = {p.id: p for p in products}

        if len(by_id) != len(payload.items):
            missing = [str(i.product_id) for i in payload.items if i.product_id not in by_id]
            raise CheckoutError(f"Unknown product ids: {', '.join(missing)}")

        # 3. Atomically reserve inventory BEFORE building the order. This uses a
        #    guarded UPDATE so concurrent checkouts cannot oversell: the DB only
        #    decrements while `inventory_count >= quantity`, and we abort if any
        #    row was not affected.
        await self._reserve_inventory(payload.items, by_id)

        # Build order items with *DB* prices.
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
                    unit_price=product.price,  # snapshot: authoritative DB price
                    line_total=line_total,
                )
            )

        # Resolve the buyer's email: for a logged-in user, use their account
        # email (never trust a re-typed payload email). Guests must supply one.
        order_email = user.email if user is not None else payload.guest_email
        if not order_email:
            raise CheckoutError("guest_email is required for guest checkout")

        # Resolve delivery details: a logged-in buyer either uses their saved
        # address or submits a new one (buyer picks source). Guests must supply
        # one. Submitting a new address also saves it as the buyer's default.
        delivery = await self._resolve_delivery(payload, user)

        # 4. Persist the pending Order + items.
        order = Order(
            guest_email=order_email,
            # Link to the account only if the buyer is authenticated (guest = None).
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
        await self.db.flush()  # assign order.id before generating the reference

        # 5. Initialise the Paystack transaction with the server-computed total.
        reference = f"ORDER-{order.id}"
        result = await paystack.initialize_transaction(
            email=order_email,
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

    async def _reserve_inventory(
        self,
        items: list,
        products_by_id: dict[uuid.UUID, Product],
    ) -> None:
        """Atomically reserve stock for each requested line.

        Uses a single guarded UPDATE per product:
            SET inventory_count = inventory_count - :qty
            WHERE id = :id AND inventory_count >= :qty

        The `inventory_count >= :qty` predicate makes the decrement atomic and
        safe under concurrency: only one of two simultaneous checkouts for the
        last unit can succeed (rowcount == 1). If a row is *not* affected, the
        stock ran out and we abort the whole checkout. The caller then never
        persists the order (the transaction rolls back).
        """
        for item in items:
            product = products_by_id[item.product_id]
            result = await self.db.execute(
                update(Product)
                .where(Product.id == item.product_id, Product.inventory_count >= item.quantity)
                .values(inventory_count=Product.inventory_count - item.quantity)
                .execution_options(synchronize_session=False)
            )
            # rowcount == 1 means exactly one product row was decremented.
            # 0 means the guarded predicate failed (insufficient stock).
            if result.rowcount != 1:
                raise CheckoutError(
                    f"Insufficient stock for '{product.title}' "
                    f"(requested={item.quantity})"
                )

    async def _resolve_delivery(
        self,
        payload: CheckoutRequest,
        user: User | None,
    ) -> DeliveryAddress:
        """Decide which delivery details to use and return a populated schema.

        Rules ("buyer picks source"):
        - Guest (no user): the payload must include `delivery`.
        - Logged-in buyer with `use_saved_address=True` or no `delivery` in the
          payload: use the account's saved details; error if none were saved.
        - Logged-in buyer who submits `delivery`: use it AND save it back as
          their default (so future checkouts can be prefilled).
        """
        # Guest checkout always requires explicit delivery details.
        if user is None:
            if payload.delivery is None:
                raise CheckoutError(
                    "Delivery details are required for guest checkout"
                )
            return payload.delivery

        use_saved = payload.use_saved_address or payload.delivery is None

        if not use_saved:
            # Buyer explicitly entered a new address — use it and save it as default.
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
        """Persist a submitted delivery address as the user's default."""
        user.default_recipient_name = delivery.recipient_name
        user.default_phone = delivery.phone
        user.default_address_line1 = delivery.address_line1
        user.default_address_line2 = delivery.address_line2
        user.default_city = delivery.city
        user.default_state = delivery.state
        user.default_postal_code = delivery.postal_code
        user.default_country = delivery.country
        user.default_notes = delivery.notes
        # Flushed/committed as part of the same transaction as the order.
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
