"""Tests for guest-order -> account linkage.

When a guest places an order and later creates an account with the same email,
the past guest order must be linked to the new user (Order.user_id set).
Uses the shared `db_session_factory` to seed orders directly (the full checkout
endpoint additionally needs Paystack).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import Order, OrderStatus, User, UserRole


async def _seed_guest_order(db_session_factory, email: str, total: str = "100.00"):
    """Insert a pending guest order (user_id=NULL) directly and return its id."""
    async with db_session_factory() as session:
        order = Order(
            guest_email=email,
            delivery_recipient_name="Guest",
            delivery_address_line1="12 Main St",
            delivery_city="Lagos",
            delivery_country="NG",
            total_amount=Decimal(total),
            status=OrderStatus.PENDING,
        )
        session.add(order)
        await session.commit()
        return order.id


async def _get_order_user_id(db_session_factory, order_id):
    async with db_session_factory() as session:
        order = await session.get(Order, order_id)
        return order.user_id


@pytest.mark.asyncio
async def test_register_seller_links_past_guest_orders(client, db_session_factory):
    email = "link-seller@test.com"
    order_id = await _seed_guest_order(db_session_factory, email)

    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "sellerpass123"},
    )
    assert resp.status_code == 201

    linked_user_id = await _get_order_user_id(db_session_factory, order_id)
    assert linked_user_id is not None


@pytest.mark.asyncio
async def test_register_buyer_links_past_guest_orders(client, db_session_factory):
    email = "link-buyer@test.com"
    order_id = await _seed_guest_order(db_session_factory, email)

    resp = await client.post(
        "/api/v1/auth/register-buyer",
        json={"email": email, "password": "buyerpass123"},
    )
    assert resp.status_code == 201

    linked_user_id = await _get_order_user_id(db_session_factory, order_id)
    assert linked_user_id is not None


@pytest.mark.asyncio
async def test_register_does_not_link_orders_of_other_email(client, db_session_factory):
    # Two guest orders: one with the registering email, one with a different email.
    email = "link-mine@test.com"
    other_email = "someone-else@test.com"
    my_order_id = await _seed_guest_order(db_session_factory, email)
    other_order_id = await _seed_guest_order(db_session_factory, other_email)

    await client.post(
        "/api/v1/auth/register-buyer",
        json={"email": email, "password": "buyerpass123"},
    )

    assert await _get_order_user_id(db_session_factory, my_order_id) is not None
    assert await _get_order_user_id(db_session_factory, other_order_id) is None


@pytest.mark.asyncio
async def test_linked_user_role_is_buyer_for_register_buyer(client, db_session_factory):
    email = "link-role@test.com"
    await client.post(
        "/api/v1/auth/register-buyer",
        json={"email": email, "password": "buyerpass123"},
    )
    async with db_session_factory() as session:
        from sqlalchemy import select

        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        assert user.role == UserRole.BUYER
