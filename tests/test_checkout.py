"""Full checkout endpoint tests with Paystack mocked.

The checkout flow recomputes totals from DB prices, decrements inventory, and
initialises a Paystack transaction. Since a real Paystack secret key is not
used in tests, we patch the shared `paystack.initialize_transaction` so the
endpoint completes and returns an `authorization_url`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.models import Product
from app.models.user import UserRole


async def _new_product(db_session_factory, title="Checkout Widget", price="25.00", inventory=10):
    async with db_session_factory() as session:
        p = Product(title=title, price=Decimal(price), inventory_count=inventory)
        session.add(p)
        await session.commit()
        return p.id


def _checkout_payload(guest_email, product_id, quantity=2):
    return {
        "guest_email": guest_email,
        "delivery": {
            "recipient_name": "Grace",
            "phone": "08000000000",
            "address_line1": "12 Main St",
            "city": "Lagos",
            "country": "NG",
        },
        "items": [{"product_id": str(product_id), "quantity": quantity}],
    }


@pytest.fixture
def mock_paystack(monkeypatch):
    """Replace `initialize_transaction` on the shared paystack client."""

    async def fake_initialize_transaction(*, email, amount, reference, metadata=None, callback_url=None):
        return {
            "authorization_url": "https://checkout.paystack.com/fake-link",
            "access_code": "FAKE_ACCESS_CODE",
            "reference": reference,
        }

    from app.services import paystack

    monkeypatch.setattr(paystack.paystack, "initialize_transaction", fake_initialize_transaction)
    return paystack.paystack


@pytest.mark.asyncio
async def test_checkout_computes_total_from_db_and_creates_pending_order(
    client, db_session_factory, mock_paystack
):
    pid = await _new_product(db_session_factory, price="25.00", inventory=10)

    resp = await client.post(
        "/api/v1/checkout", json=_checkout_payload("guest@test.com", pid, quantity=2)
    )
    assert resp.status_code == 201
    body = resp.json()

    # total = 25.00 * 2 = 50.00
    assert body["order"]["total_amount"] == "50.00"
    assert body["order"]["status"] == "pending"
    assert body["authorization_url"].startswith("https://checkout.paystack.com/")
    assert body["access_code"] == "FAKE_ACCESS_CODE"
    assert body["reference"].startswith("ORDER-")

    # inventory decremented 10 -> 8
    async with db_session_factory() as session:
        p = await session.get(Product, uuid.UUID(str(pid)))
        assert p.inventory_count == 8


@pytest.mark.asyncio
async def test_checkout_does_not_trust_client_total(client, db_session_factory, mock_paystack):
    # The payload has NO price/total field; server must use DB price regardless.
    pid = await _new_product(db_session_factory, price="100.00", inventory=5)

    payload = _checkout_payload("guest2@test.com", pid, quantity=3)
    resp = await client.post("/api/v1/checkout", json=payload)
    assert resp.status_code == 201
    assert resp.json()["order"]["total_amount"] == "300.00"  # 100 * 3


@pytest.mark.asyncio
async def test_checkout_links_order_to_authenticated_buyer(
    client, db_session_factory, auth_headers, create_user, mock_paystack
):
    await create_user("buyer-checkout@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-checkout@test.com", "buyerpass")
    pid = await _new_product(db_session_factory, price="10.00", inventory=5)

    resp = await client.post(
        "/api/v1/checkout",
        json=_checkout_payload("buyer-checkout@test.com", pid, quantity=1),
        headers=headers,
    )
    assert resp.status_code == 201
    order_id = uuid.UUID(resp.json()["order"]["id"])

    async with db_session_factory() as session:
        from sqlalchemy import select

        from app.models import Order

        order = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one()
        assert order.user_id is not None


@pytest.mark.asyncio
async def test_checkout_rejects_unknown_product(client, mock_paystack):
    resp = await client.post(
        "/api/v1/checkout",
        json=_checkout_payload("guest3@test.com", uuid.uuid4(), quantity=1),
    )
    assert resp.status_code == 400
