"""Tests for the atomic inventory reservation in checkout.

The guarded UPDATE (WHERE inventory_count >= quantity) must prevent overselling
under concurrency: given N units and N+1 simultaneous reservations, exactly N
succeed and the last is rejected with `CheckoutError`. We exercise
`CheckoutService._reserve_inventory` directly against the test DB (the full
checkout endpoint additionally calls Paystack, which needs real keys).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.models import Product
from app.schemas.order import CheckoutItem
from app.services.checkout import CheckoutError, CheckoutService


def _make_helpers(db_session_factory):
    async def new_product(inventory: int):
        async with db_session_factory() as session:
            p = Product(title="Inv Test", price=Decimal("5.00"), inventory_count=inventory)
            session.add(p)
            await session.commit()
            return p.id

    async def try_reserve(product_id, quantity, tag):
        async with db_session_factory() as session:
            svc = CheckoutService(session)
            items = [CheckoutItem(product_id=product_id, quantity=quantity)]
            product = await session.get(Product, product_id)
            by_id = {product_id: product}
            try:
                await svc._reserve_inventory(items, by_id)
                await session.commit()
                return tag, "success"
            except CheckoutError:
                await session.rollback()
                return tag, "blocked"

    async def inventory_of(product_id) -> int:
        async with db_session_factory() as session:
            p = await session.get(Product, product_id)
            return p.inventory_count

    return new_product, try_reserve, inventory_of


@pytest.mark.asyncio
async def test_concurrent_single_unit_not_oversold(db_session_factory):
    """Two requests for the last 1 unit: exactly one succeeds, no negative stock."""
    new_product, try_reserve, inventory_of = _make_helpers(db_session_factory)
    pid = await new_product(inventory=1)

    results = await asyncio.gather(
        try_reserve(pid, 1, "A"),
        try_reserve(pid, 1, "B"),
    )
    outcomes = [o for _, o in results]
    assert outcomes.count("success") == 1
    assert outcomes.count("blocked") == 1
    assert await inventory_of(pid) == 0


@pytest.mark.asyncio
async def test_concurrent_multi_unit_partial_ok(db_session_factory):
    """5 units, 3 concurrent requests of 2 each -> only 2 succeed, 1 remains."""
    new_product, try_reserve, inventory_of = _make_helpers(db_session_factory)
    pid = await new_product(inventory=5)

    results = await asyncio.gather(
        try_reserve(pid, 2, "A"),
        try_reserve(pid, 2, "B"),
        try_reserve(pid, 2, "C"),
    )
    outcomes = [o for _, o in results]
    assert outcomes.count("success") == 2
    assert outcomes.count("blocked") == 1
    assert await inventory_of(pid) == 1


@pytest.mark.asyncio
async def test_over_demand_rejected(db_session_factory):
    """Requesting more than available stock is rejected outright."""
    new_product, try_reserve, inventory_of = _make_helpers(db_session_factory)
    pid = await new_product(inventory=3)
    _, outcome = await try_reserve(pid, 5, "too-much")
    assert outcome == "blocked"
    assert await inventory_of(pid) == 3
