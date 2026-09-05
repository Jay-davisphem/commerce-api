"""Tests for seller dashboard, scoped inventory, and order management endpoints."""

from __future__ import annotations

import pytest

from app.models.user import UserRole

PRODUCT_BODY = {
    "title": "Seller Widget",
    "description": "A widget for testing seller flow",
    "price": "29.99",
    "inventory_count": 5,
}


@pytest.mark.asyncio
async def test_list_my_products_requires_auth(client):
    resp = await client.get("/api/v1/sellers/products")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_seller_lists_only_own_products(client, auth_headers, create_user):
    await create_user("seller-own-list@test.com", "sellerpass", UserRole.SELLER)
    await create_user("seller-other@test.com", "sellerpass", UserRole.SELLER)

    headers_own = await auth_headers("seller-own-list@test.com", "sellerpass")
    resp_own = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_own)
    assert resp_own.status_code == 201

    headers_other = await auth_headers("seller-other@test.com", "sellerpass")
    resp_other = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_other)
    assert resp_other.status_code == 201

    # /sellers/products returns only the caller's products
    resp = await client.get("/api/v1/sellers/products", headers=headers_own)
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    assert len(items) == 1
    assert items[0]["title"] == PRODUCT_BODY["title"]


@pytest.mark.asyncio
async def test_seller_dashboard_metrics(client, auth_headers, create_user):
    seller = await create_user("seller-metrics@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-metrics@test.com", "sellerpass")

    resp = await client.get("/api/v1/sellers/dashboard", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "online_orders_today" in data
    assert "pos_sales_today" in data
    assert "goods_in_escrow" in data
    assert "low_stock_alerts" in data
    assert "recent_orders" in data
    assert "low_stock_items" in data


@pytest.mark.asyncio
async def test_seller_restock_product(client, auth_headers, create_user):
    seller = await create_user("seller-restock@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-restock@test.com", "sellerpass")

    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    assert created.status_code == 201
    pid = created.json()["id"]

    resp = await client.post(
        f"/api/v1/sellers/products/{pid}/restock",
        json={"quantity": 15},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["inventory_count"] == 20  # 5 initial + 15 added


@pytest.mark.asyncio
async def test_seller_cannot_restock_others_product(client, auth_headers, create_user):
    await create_user("seller-owner-rs@test.com", "sellerpass", UserRole.SELLER)
    await create_user("seller-intruder@test.com", "sellerpass", UserRole.SELLER)

    headers_owner = await auth_headers("seller-owner-rs@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_owner)
    assert created.status_code == 201
    pid = created.json()["id"]

    headers_intruder = await auth_headers("seller-intruder@test.com", "sellerpass")
    resp = await client.post(
        f"/api/v1/sellers/products/{pid}/restock",
        json={"quantity": 10},
        headers=headers_intruder,
    )
    assert resp.status_code == 403