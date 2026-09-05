"""Tests for product role-based access control (RBAC)."""

from __future__ import annotations

import pytest

from app.models.user import UserRole

PRODUCT_BODY = {
    "title": "RBAC Widget",
    "description": "A widget for testing RBAC",
    "price": "49.99",
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
    data = resp.json()
    assert data["owner_id"] == str(seller.id)


@pytest.mark.asyncio
async def test_seller_cannot_edit_others_product(client, auth_headers, create_user):
    await create_user("seller-a@test.com", "sellerpass", UserRole.SELLER)
    await create_user("seller-b@test.com", "sellerpass", UserRole.SELLER)

    headers_a = await auth_headers("seller-a@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_a)
    assert created.status_code == 201
    product_id = created.json()["id"]

    headers_b = await auth_headers("seller-b@test.com", "sellerpass")
    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"title": "Hacked Title"},
        headers=headers_b,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_seller_can_edit_own_product(client, auth_headers, create_user):
    await create_user("seller-own@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-own@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    assert created.status_code == 201
    product_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"title": "Updated Title"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"


@pytest.mark.asyncio
async def test_superadmin_can_edit_any_product(client, auth_headers, create_user):
    await create_user("seller-admin@test.com", "sellerpass", UserRole.SELLER)
    await create_user("root@test.com", "rootpass", UserRole.SUPER_ADMIN)

    headers_s = await auth_headers("seller-admin@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_s)
    assert created.status_code == 201
    product_id = created.json()["id"]

    headers_root = await auth_headers("root@test.com", "rootpass")
    resp = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"title": "Admin Override"},
        headers=headers_root,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Admin Override"


@pytest.mark.asyncio
async def test_seller_delete_own_product(client, auth_headers, create_user):
    await create_user("seller-del-prod@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-del-prod@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    assert created.status_code == 201
    product_id = created.json()["id"]

    resp = await client.delete(f"/api/v1/products/{product_id}", headers=headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_seller_cannot_delete_others_product(client, auth_headers, create_user):
    await create_user("seller-owner@test.com", "sellerpass", UserRole.SELLER)
    await create_user("seller-other-del@test.com", "sellerpass", UserRole.SELLER)

    headers_owner = await auth_headers("seller-owner@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers_owner)
    assert created.status_code == 201
    product_id = created.json()["id"]

    headers_other = await auth_headers("seller-other-del@test.com", "sellerpass")
    resp = await client.delete(f"/api/v1/products/{product_id}", headers=headers_other)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_public_list_products(client, auth_headers, create_user):
    await create_user("seller-pub@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-pub@test.com", "sellerpass")
    created = await client.post("/api/v1/products", json=PRODUCT_BODY, headers=headers)
    assert created.status_code == 201

    resp = await client.get("/api/v1/products")
    assert resp.status_code == 200
    data = resp.json()
    items = data["items"] if isinstance(data, dict) and "items" in data else data
    assert len(items) == 1
    assert items[0]["title"] == PRODUCT_BODY["title"]