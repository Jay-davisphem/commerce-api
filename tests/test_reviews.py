"""Tests for reviews, ratings, and seller review management."""

from __future__ import annotations

from decimal import Decimal
import pytest

from app.models.user import UserRole


@pytest.mark.asyncio
async def test_product_rating_defaults_to_max(client, auth_headers, create_user):
    seller = await create_user("seller-rate@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-rate@test.com", "sellerpass")

    # Create new product with no reviews
    prod = {"title": "Omega 3 Ultra", "price": "6000.00"}
    res = await client.post("/api/v1/products", json=prod, headers=headers)
    assert res.status_code == 201
    data = res.json()

    # Must default to 5.0 rating with 0 reviews
    assert Decimal(str(data["rating"])) == Decimal("5.0")
    assert data["reviews_count"] == 0


@pytest.mark.asyncio
async def test_submit_review_updates_product_average(client, auth_headers, create_user):
    seller = await create_user("seller-item@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-item@test.com", "sellerpass")

    prod = {"title": "Vitamin D3", "price": "4000.00"}
    prod_res = await client.post("/api/v1/products", json=prod, headers=headers)
    pid = prod_res.json()["id"]

    # First review: 4 stars
    r1 = await client.post(
        f"/api/v1/products/{pid}/reviews",
        json={"rating": 4, "comment": "Good quality", "reviewer_name": "Alice"},
    )
    assert r1.status_code == 201

    updated_prod = (await client.get(f"/api/v1/products/{pid}")).json()
    assert Decimal(str(updated_prod["rating"])) == Decimal("4.0")
    assert updated_prod["reviews_count"] == 1

    # Second review: 5 stars (Average = 4.5)
    r2 = await client.post(
        f"/api/v1/products/{pid}/reviews",
        json={"rating": 5, "comment": "Excellent!", "reviewer_name": "Bob"},
    )
    assert r2.status_code == 201

    updated_prod2 = (await client.get(f"/api/v1/products/{pid}")).json()
    assert Decimal(str(updated_prod2["rating"])) == Decimal("4.5")
    assert updated_prod2["reviews_count"] == 2


@pytest.mark.asyncio
async def test_seller_reviews_list(client, auth_headers, create_user):
    seller = await create_user("seller-rev@test.com", "sellerpass", UserRole.SELLER)
    headers = await auth_headers("seller-rev@test.com", "sellerpass")

    prod = {"title": "CoQ10 Heart Support", "price": "12000.00"}
    prod_res = await client.post("/api/v1/products", json=prod, headers=headers)
    pid = prod_res.json()["id"]

    await client.post(
        f"/api/v1/products/{pid}/reviews",
        json={"rating": 5, "comment": "Loved it", "reviewer_name": "Chidi"},
    )

    # Seller checks their review tab
    rev_res = await client.get("/api/v1/sellers/reviews", headers=headers)
    assert rev_res.status_code == 200
    rev_data = rev_res.json()
    assert rev_data["total"] == 1
    assert rev_data["items"][0]["reviewer_name"] == "Chidi"
    assert rev_data["items"][0]["product_title"] == "CoQ10 Heart Support"