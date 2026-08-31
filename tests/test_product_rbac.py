"""Tests for product RBAC and ownership enforcement.

Covers the shared `/products` write routes (seller + super admin) plus the
seller dashboard namespace under `/sellers/products`. Public browsing stays
open to anyone.
"""

from __future__ import annotations

import pytest

from app.models.user import UserRole

PRODUCT_BODY = {
    "title": "Test Widget",
    "description": "A widget",
    "price": "19.99",
    "inventory_count": 10,
}


@pytest.mark.asyncio
async def test_create_product_requires_auth(client):
    resp = await client.post("/api/v1/products", json=PRODUCT_BODY)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_buyer_cannot_create_product(client, auth_headers, create_user):
    await create_user("buyer-rbac@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-rbac@test.com", "buyerpass")
    resp = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_seller_create_product_sets_owner(client, auth_headers, create_user):
    seller = await create_user("seller-rbac@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-rbac@test.com", "sellerpass")
    resp = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["owner_id"] == str(seller.id)


@pytest.mark.asyncio
async def test_seller_cannot_edit_others_product(client, auth_headers, create_user):
    await create_user("seller-a@test.com", "sellerpass", UserRole.SELLER)
    await create_user("seller-b@test.com", "sellerpass", UserRole.SELLER)

    # seller A creates a product
    headers_a = await auth_headers("seller-a@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_a)
    product_id = created.json()["id"]

    # seller B tries to edit it -> 403
    headers_b = await auth_headers("seller-b@test.com", "sellerpass")
    resp = await client.patch(
        f"/api/v1/products/{product_id}", json={"price": "1.00"}, headers=headers_b
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_seller_can_edit_own_product(client, auth_headers, create_user):
    await create_user("seller-own@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-own@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    product_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/products/{product_id}", json={"price": "29.99"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["price"] == "29.99"


@pytest.mark.asyncio
async def test_superadmin_can_edit_any_product(client, auth_headers, create_user):
    await create_user("seller-admin@test.com", "sellerpass", UserRole.SELLER)
    await create_user("root@test.com", "rootpass", UserRole.SUPER_ADMIN)

    headers_s = await auth_headers("seller-admin@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_s)
    product_id = created.json()["id"]

    headers_root = await auth_headers("root@test.com", "rootpass")
    resp = await client.patch(
        f"/api/v1/products/{product_id}", json={"inventory_count": 3}, headers=headers_root
    )
    assert resp.status_code == 200
    assert resp.json()["inventory_count"] == 3


@pytest.mark.asyncio
async def test_public_list_products(client, auth_headers, create_user):
    await create_user("seller-pub@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-pub@test.com", "sellerpass")
    await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)

    resp = await client.get("/api/v1/products")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
