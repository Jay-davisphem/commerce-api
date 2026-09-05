"""Tests for Storefront Search, Categories, Seller Dashboard, and Restock."""

from __future__ import annotations

import pytest

from app.models.user import UserRole


@pytest.mark.asyncio
async def test_search_and_filter_products(client, auth_headers, create_user):
    await create_user("seller-search@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-search@test.com", "sellerpass")

    # Seed test products
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

    # 1. Search keyword
    res = await client.get("/api/v1/products?q=salmon")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Salmon Oil Omega-3"

    # 2. Filter category
    res = await client.get("/api/v1/products?category=Immune Support")
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["title"] == "Vitamin C Gummies"

    # 3. Filter tag
    res = await client.get("/api/v1/products?tag=hot_deal")
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["tag"] == "hot_deal"

    # 4. Aggregated categories
    cat_res = await client.get("/api/v1/products/categories")
    assert cat_res.status_code == 200
    categories = {c["name"]: c["count"] for c in cat_res.json()}
    assert categories["Heart Health"] >= 1
    assert categories["Immune Support"] >= 1


@pytest.mark.asyncio
async def test_seller_dashboard_and_restock(client, auth_headers, create_user):
    seller = await create_user("seller-dash@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-dash@test.com", "sellerpass")

    # Create an item below threshold via the canonical product creation route
    low_stock_item = {
        "title": "Zinc Picolinate",
        "price": "2500.00",
        "inventory_count": 5,
        "low_stock_threshold": 15,
    }
    create_res = await client.post("/api/v1/products", json=low_stock_item, headers=headers)
    assert create_res.status_code == 201
    product_id = create_res.json()["id"]

    # Check dashboard stats
    dash_res = await client.get("/api/v1/sellers/dashboard", headers=headers)
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert dash_data["low_stock_alerts"] >= 1
    alert_ids = [item["product_id"] for item in dash_data["low_stock_items"]]
    assert product_id in alert_ids

    # Restock product
    restock_res = await client.post(
        f"/api/v1/sellers/products/{product_id}/restock",
        json={"quantity": 20},
        headers=headers,
    )
    assert restock_res.status_code == 200
    assert restock_res.json()["inventory_count"] == 25

    # Check that it is no longer in low stock
    dash_res_after = await client.get("/api/v1/sellers/dashboard", headers=headers)
    assert dash_res_after.status_code == 200
    updated_alerts = [item["product_id"] for item in dash_res_after.json()["low_stock_items"]]
    assert product_id not in updated_alerts
    
@pytest.mark.asyncio
async def test_new_arrivals_pure_date_sorting(client, auth_headers, create_user):
    seller = await create_user("seller-datesort@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-datesort@test.com", "sellerpass")

    # Create two items sequentially
    await client.post("/api/v1/products", json={"title": "Older Item", "price": "1000.00"}, headers=headers)
    await client.post("/api/v1/products", json={"title": "Newer Item", "price": "2000.00"}, headers=headers)

    # Fetch New Arrivals using date sorting (new to old)
    res = await client.get("/api/v1/products?sort_by=newest&page_size=2")
    assert res.status_code == 200
    items = res.json()["items"]
    assert items[0]["title"] == "Newer Item"
    assert items[1]["title"] == "Older Item"