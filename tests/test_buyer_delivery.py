"""Tests for buyer login, saved delivery details, and checkout prefilling."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models import Product
from app.models.user import UserRole


async def _new_product(db_session_factory, price="25.00", inventory=10):
    async with db_session_factory() as session:
        p = Product(title="Buyer Widget", price=Decimal(price), inventory_count=inventory)
        session.add(p)
        await session.commit()
        return p.id


def _payload(email, product_id, quantity=1, **overrides):
    body = {
        "guest_email": email,
        "items": [{"product_id": str(product_id), "quantity": quantity}],
    }
    body.update(overrides)
    return body


def _delivery():
    return {
        "recipient_name": "Ada",
        "phone": "08011111111",
        "address_line1": "1 Test St",
        "city": "Lagos",
        "country": "NG",
    }


@pytest.fixture
def mock_paystack(monkeypatch):
    async def fake_initialize(*, email, amount, reference, metadata=None, callback_url=None):
        return {
            "authorization_url": "https://checkout.paystack.com/fake-link",
            "access_code": "FAKE",
            "reference": reference,
        }

    from app.services import paystack

    monkeypatch.setattr(paystack.paystack, "initialize_transaction", fake_initialize)
    return paystack.paystack


@pytest.mark.asyncio
async def test_buyer_can_login_and_me(client, create_user, auth_headers):
    await create_user("buyer-login@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-login@test.com", "buyerpass")
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "buyer"


@pytest.mark.asyncio
async def test_guest_checkout_without_delivery_is_rejected(client, db_session_factory, mock_paystack):
    pid = await _new_product(db_session_factory)
    resp = await client.post("/api/v1/checkout", json=_payload("guest-x@test.com", pid))
    assert resp.status_code == 400
    assert "Delivery details are required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_save_delivery_via_profile(client, create_user, auth_headers):
    await create_user("save-delivery@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("save-delivery@test.com", "buyerpass")

    resp = await client.put(
        "/api/v1/auth/me/delivery",
        json=_delivery(),
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_address_line1"] == "1 Test St"
    assert body["default_city"] == "Lagos"
    assert body["default_country"] == "NG"

    # /auth/me reflects the saved details too
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["default_city"] == "Lagos"


@pytest.mark.asyncio
async def test_checkout_uses_saved_address(client, db_session_factory, auth_headers, create_user, mock_paystack):
    await create_user("buyer-saved@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-saved@test.com", "buyerpass")

    # Save default delivery first.
    await client.put("/api/v1/auth/me/delivery", json=_delivery(), headers=headers)

    pid = await _new_product(db_session_factory)
    # No delivery in payload — buyer relies on saved address.
    resp = await client.post(
        "/api/v1/checkout",
        json=_payload("buyer-saved@test.com", pid, use_saved_address=True),
        headers=headers,
    )
    assert resp.status_code == 201
    order_delivery = resp.json()["order"]["delivery"]
    # Delivered OrderRead serializes delivery via _delivery_schema (flat fields).
    # Confirm the saved address was used (address_line1 present).
    assert order_delivery["address_line1"] == "1 Test St"
    assert order_delivery["city"] == "Lagos"


@pytest.mark.asyncio
async def test_checkout_saved_address_not_saved_returns_400(
    client, db_session_factory, auth_headers, create_user, mock_paystack
):
    await create_user("buyer-nosaved@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-nosaved@test.com", "buyerpass")

    pid = await _new_product(db_session_factory)
    resp = await client.post(
        "/api/v1/checkout",
        json=_payload("buyer-nosaved@test.com", pid, use_saved_address=True),
        headers=headers,
    )
    assert resp.status_code == 400
    assert "No saved delivery details" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_checkout_with_new_delivery_saves_as_default(
    client, db_session_factory, auth_headers, create_user, mock_paystack
):
    await create_user("buyer-new@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-new@test.com", "buyerpass")

    pid = await _new_product(db_session_factory)
    resp = await client.post(
        "/api/v1/checkout",
        json={**_payload("buyer-new@test.com", pid), "delivery": _delivery()},
        headers=headers,
    )
    assert resp.status_code == 201

    # The submitted address was saved as the buyer's default.
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["default_address_line1"] == "1 Test St"


@pytest.mark.asyncio
async def test_logged_in_buyer_order_uses_account_email(
    client, db_session_factory, auth_headers, create_user, mock_paystack
):
    """A logged-in buyer's order email comes from their account, not the payload."""
    await create_user("buyer-email@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-email@test.com", "buyerpass")

    pid = await _new_product(db_session_factory)
    # Submit a DIFFERENT email in the payload — the account email must win.
    resp = await client.post(
        "/api/v1/checkout",
        json={
            **_payload("fake-other@test.com", pid),
            "delivery": _delivery(),
        },
        headers=headers,
    )
    assert resp.status_code == 201
    # The order carries the account email, not the payload's.
    assert resp.json()["order"]["guest_email"] == "buyer-email@test.com"


@pytest.mark.asyncio
async def test_logged_in_buyer_order_email_without_payload_email(
    client, db_session_factory, auth_headers, create_user, mock_paystack
):
    """A logged-in buyer can check out WITHOUT sending guest_email — derived from account."""
    await create_user("buyer-noemail@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-noemail@test.com", "buyerpass")

    pid = await _new_product(db_session_factory)
    # No guest_email in payload at all.
    body = {
        "items": [{"product_id": str(pid), "quantity": 1}],
        "delivery": _delivery(),
    }
    resp = await client.post("/api/v1/checkout", json=body, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["order"]["guest_email"] == "buyer-noemail@test.com"


@pytest.mark.asyncio
async def test_guest_checkout_requires_email(
    client, db_session_factory, mock_paystack
):
    """A guest without an email in the payload is rejected."""
    pid = await _new_product(db_session_factory)
    body = {
        "items": [{"product_id": str(pid), "quantity": 1}],
        "delivery": _delivery(),
    }
    resp = await client.post("/api/v1/checkout", json=body)
    assert resp.status_code == 400
    assert "guest_email is required" in resp.json()["detail"]
