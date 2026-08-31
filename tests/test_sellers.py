"""Tests for the /sellers namespace: seller manages their OWN products only."""

from __future__ import annotations

import pytest

from app.models.user import UserRole

PRODUCT_BODY = {
    "title": "Seller Widget",
    "price": "9.99",
    "inventory_count": 5,
}


@pytest.mark.asyncio
async def test_sellers_requires_auth(client):
    resp = await client.get("/api/v1/sellers/products")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_seller_lists_only_own_products(client, auth_headers, create_user):
    seller = await create_user("seller-own-list@test.com", "sellerpass", UserRole.SELLER)
    other = await create_user("seller-other@test.com", "sellerpass", UserRole.SELLER)

    headers_own = await auth_headers("seller-own-list@test.com", "sellerpass")

    # own product via the /sellers namespace
    await client.post("/api/v1/sellers/products", json=PRODUCT_BODY, headers=headers_own)

    # another seller's product via shared /products
    headers_other = await auth_headers("seller-other@test.com", "sellerpass")
    await client.post("/api/v1/sellers/products", json=PRODUCT_BODY, headers=headers_other)

    # seller lists own -> only their product
    resp = await client.get("/api/v1/sellers/products", headers=headers_own)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["owner_id"] == str(seller.id)
    assert items[0]["owner_id"] != str(other.id)


@pytest.mark.asyncio
async def test_seller_create_product_owner_is_self(client, auth_headers, create_user):
    seller = await create_user("seller-create@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-create@test.com", "sellerpass")
    resp = await client.post("/api/v1/sellers/products", json=PRODUCT_BODY, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["owner_id"] == str(seller.id)


@pytest.mark.asyncio
async def test_seller_cannot_edit_others_via_sellers(client, auth_headers, create_user):
    await create_user("seller-x@test.com", "sellerpass", UserRole.SELLER)
    await create_user("seller-y@test.com", "sellerpass", UserRole.SELLER)

    headers_x = await auth_headers("seller-x@test.com", "sellerpass")
    created = await client.post("/api/v1/sellers/products", json=PRODUCT_BODY, headers=headers_x)
    product_id = created.json()["id"]

    headers_y = await auth_headers("seller-y@test.com", "sellerpass")
    resp = await client.patch(
        f"/api/v1/sellers/products/{product_id}", json={"price": "1.00"}, headers=headers_y
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_seller_can_edit_own_via_sellers(client, auth_headers, create_user):
    await create_user("seller-edit@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-edit@test.com", "sellerpass")
    created = await client.post("/api/v1/sellers/products", json=PRODUCT_BODY, headers=headers)
    product_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/sellers/products/{product_id}", json={"price": "14.99"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["price"] == "14.99"


@pytest.mark.asyncio
async def test_buyer_cannot_access_sellers(client, auth_headers, create_user):
    await create_user("buyer-sellers@test.com", "buyerpass", UserRole.BUYER)
    headers = await auth_headers("buyer-sellers@test.com", "buyerpass")
    resp = await client.post("/api/v1/sellers/products", json=PRODUCT_BODY, headers=headers)
    assert resp.status_code == 403
