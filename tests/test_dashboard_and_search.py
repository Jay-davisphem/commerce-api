"""Tests for Storefront Search, Categories, Seller Dashboard, and Restock."""

from __future__ import annotations

import pytest

from app.models.user import UserRole


@pytest.mark.asyncio
async def test_search_and_filter_products(client, auth_headers, create_user):
    await create_user("seller-search@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-search@test.com", "sellerpass")

    p1 = {
        "title": "Salmon Oil Omega-3",
        "description": "High potency heart health supplement",
        "price": "5000.00",
        "inventory_count": 50,
        "category": "Heart Health",
        "tag": "hot_deal",
    }
    p2 = {
        "title": "Vitamin C Gummies",
        "description": "Immune support daily chewables",
        "price": "3000.00",
        "inventory_count": 10,
        "category": "Immune Support",
        "tag": "special_offer",
    }

    await client.post("/api/v1/products", json=p1, headers=headers)
    await client.post("/api/v1/products", json=p2, headers=headers)

    # Search keyword via GIN Trigram
    res = await client.get("/api/v1/products?q=salmon")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "Salmon Oil Omega-3"

    # Filter category
    res = await client.get("/api/v1/products?category=Immune Support")
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["items"][0]["title"] == "Vitamin C Gummies"

    # Filter tag
    res = await client.get("/api/v1/products?tag=hot_deal")
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1
    assert res.json()["items"][0]["tag"] == "hot_deal"

    # Cached aggregated categories
    cat_res = await client.get("/api/v1/products/categories")
    assert cat_res.status_code == 200
    categories = {c["name"]: c["count"] for c in cat_res.json()}
    assert categories["Heart Health"] >= 1
    assert categories["Immune Support"] >= 1


@pytest.mark.asyncio
async def test_new_arrivals_pure_date_sorting(client, auth_headers, create_user):
    seller = await create_user("seller-datesort@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-datesort@test.com", "sellerpass")

    # Create two items sequentially
    await client.post("/api/v1/products", json={"title": "Older Item", "price": "1000.00"}, headers=headers)
    await client.post("/api/v1/products", json={"title": "Newer Item", "price": "2000.00"}, headers=headers)

    # Fetch New Arrivals using date sorting (new to old)
    res = await client.get("/api/v1/products?sort_by=newest&limit=2")
    assert res.status_code == 200
    items = res.json()["items"]
    assert items[0]["title"] == "Newer Item"
    assert items[1]["title"] == "Older Item"


@pytest.mark.asyncio
async def test_cursor_pagination_forward_seek(client, auth_headers, create_user):
    seller = await create_user("seller-cursor@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-cursor@test.com", "sellerpass")

    for i in range(1, 4):
        await client.post(
            "/api/v1/products",
            json={"title": f"Product {i}", "price": "1000.00"},
            headers=headers,
        )

    # Page 1 (limit 2)
    p1 = await client.get("/api/v1/products?limit=2&sort_by=newest")
    assert p1.status_code == 200
    d1 = p1.json()
    assert len(d1["items"]) == 2
    assert d1["has_next"] is True
    assert d1["has_more"] is True
    assert d1["next_cursor"] is not None

    # Page 2 (seek forward with after cursor)
    p2 = await client.get(f"/api/v1/products?limit=2&sort_by=newest&after={d1['next_cursor']}")
    assert p2.status_code == 200
    d2 = p2.json()
    assert len(d2["items"]) == 1
    assert d2["has_next"] is False
    assert d2["has_more"] is False
    assert d2["next_cursor"] is None


@pytest.mark.asyncio
async def test_bidirectional_cursor_pagination(client, auth_headers, create_user):
    seller = await create_user("seller-bidir@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-bidir@test.com", "sellerpass")

    for i in range(1, 6):
        await client.post(
            "/api/v1/products",
            json={"title": f"Item {i}", "price": "500.00"},
            headers=headers,
        )

    # Page 1: limit 2
    r1 = await client.get("/api/v1/products?limit=2&sort_by=newest")
    assert r1.status_code == 200
    d1 = r1.json()
    assert len(d1["items"]) == 2
    assert d1["has_next"] is True
    assert d1["has_prev"] is False

    # Page 2: forward
    r2 = await client.get(f"/api/v1/products?limit=2&sort_by=newest&after={d1['next_cursor']}")
    assert r2.status_code == 200
    d2 = r2.json()
    assert len(d2["items"]) == 2
    assert d2["has_next"] is True
    assert d2["has_prev"] is True

    # Page 1: backward using before
    r3 = await client.get(f"/api/v1/products?limit=2&sort_by=newest&before={d2['prev_cursor']}")
    assert r3.status_code == 200
    d3 = r3.json()
    assert len(d3["items"]) == 2
    assert d3["items"][0]["title"] == d1["items"][0]["title"]
    assert d3["items"][1]["title"] == d1["items"][1]["title"]


@pytest.mark.asyncio
async def test_seller_dashboard_and_restock(client, auth_headers, create_user):
    seller = await create_user("seller-dash@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-dash@test.com", "sellerpass")

    low_stock_item = {
        "title": "Zinc Picolinate",
        "price": "2500.00",
        "inventory_count": 5,
        "low_stock_threshold": 15,
    }
    create_res = await client.post("/api/v1/products", json=low_stock_item, headers=headers)
    assert create_res.status_code == 201
    product_id = create_res.json()["id"]

    dash_res = await client.get("/api/v1/sellers/dashboard", headers=headers)
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["low_stock_alerts"] >= 1
    alert_ids = [item["product_id"] for item in dash_data["low_stock_items"]]
    assert product_id in alert_ids

    restock_res = await client.post(
        f"/api/v1/sellers/products/{product_id}/restock",
        json={"quantity": 20},
        headers=headers,
    )
    assert restock_res.status_code == 200
    assert restock_res.json()["inventory_count"] == 25

    dash_res_after = await client.get("/api/v1/sellers/dashboard", headers=headers)
    assert dash_res_after.status_code == 200
    updated_alerts = [item["product_id"] for item in dash_res_after.json()["low_stock_items"]]
    assert product_id not in updated_alerts