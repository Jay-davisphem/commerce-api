#!/usr/bin/env python3
from __future__ import annotations

import os
import httpx

# ==============================================================================
# CONFIGURATION & TOGGLES
# ==============================================================================
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")

# Set to False to skip seeding and only run checkout on existing products
SEED_PRODUCTS = True

SELLER_EMAIL = "davidoluwafemi178@gmail.com"
SELLER_PASSWORD = "Password123!"

# ==============================================================================
# SEEDING DATA
# ==============================================================================
PRODUCTS_TO_SEED = [
    {
        "title": "Salmon Oil 1000mg",
        "description": "Pure wild Alaskan salmon oil rich in Omega-3 EPA/DHA for cardiovascular wellness.",
        "price": 15000.00,
        "original_price": 20000.00,
        "discount_percentage": 25,
        "inventory_count": 120,
        "category": "Heart Health",
        "tag": "hot_deal",
        "image_url": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=600",
    },
    {
        "title": "Turmeric Curcumin Extract",
        "description": "High potency joint and anti-inflammatory support complex with BioPerine.",
        "price": 18000.00,
        "original_price": 22500.00,
        "discount_percentage": 20,
        "inventory_count": 85,
        "category": "Joint Support",
        "tag": "special_offer",
        "image_url": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=600",
    },
    {
        "title": "Vitamin C 1000mg Zinc Gummies",
        "description": "Immune support antioxidant chewables for daily defense.",
        "price": 8500.00,
        "inventory_count": 200,
        "category": "Immune Support",
        "tag": "recommended",
        "image_url": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=600",
    },
    {
        "title": "Organic Ashwagandha KSM-66",
        "description": "Stress relief and vitality optimizer with standardized black pepper extract.",
        "price": 12000.00,
        "inventory_count": 14,
        "category": "Stress Management",
        "image_url": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=600",
    },
]


def get_seller_token(client: httpx.Client) -> str:
    """Log in the seller or register if the account does not exist yet."""
    login_res = client.post(
        "/auth/login",
        json={"email": SELLER_EMAIL, "password": SELLER_PASSWORD},
    )

    if login_res.status_code == 200:
        return login_res.json()["access_token"]

    reg_res = client.post(
        "/auth/register",
        json={
            "email": SELLER_EMAIL,
            "password": SELLER_PASSWORD,
            "full_name": "David Oluwafemi",
        },
    )
    if reg_res.status_code == 201:
        print(f"   Created new seller account for {SELLER_EMAIL}")
        return reg_res.json()["access_token"]

    raise RuntimeError(f"Failed to authenticate seller: {login_res.text} / {reg_res.text}")


def seed_catalog(client: httpx.Client, token: str) -> None:
    """Post configured items to the canonical /products endpoint."""
    headers = {"Authorization": f"Bearer {token}"}
    print(f"\n--- Seeding Products for {SELLER_EMAIL} ---")

    for item in PRODUCTS_TO_SEED:
        res = client.post("/products", json=item, headers=headers)
        if res.status_code == 201:
            data = res.json()
            print(f"   Created: '{data['title']}' (ID: {data['id']}) | Stock: {data['inventory_count']}")
        else:
            print(f"   Failed to create '{item['title']}': {res.status_code} - {res.text}")


def main():
    with httpx.Client(base_url=API_BASE_URL, timeout=30.0) as client:
        # 1. OPTIONAL PRODUCT SEEDING
        if SEED_PRODUCTS:
            try:
                seller_token = get_seller_token(client)
                seed_catalog(client, seller_token)
            except Exception as exc:
                print(f"❌ Seeding error: {exc}")
                return

        # 2. SELECT PRODUCT FOR CHECKOUT (Updated for Keyset Pagination)
        print("\n--- Initiating Storefront Checkout ---")
        prod_res = client.get("/products?sort_by=newest&limit=1")
        if prod_res.status_code != 200 or not prod_res.json().get("items"):
            print("❌ No products available in the database to test checkout.")
            return

        product = prod_res.json()["items"][0]
        product_id = product["id"]
        print(f"Selected Product : {product['title']}")
        print(f"Product ID       : {product_id}")
        print(f"Authoritative DB : NGN {product['price']}")

        # 3. RUN ONE-SHOT GUEST CHECKOUT
        checkout_payload = {
            "guest_email": "davidoluwafemi00@gmail.com",
            "delivery": {
                "recipient_name": "Amina Bello",
                "phone": "08116585993",
                "address_line1": "Plot 14 Admiralty Way",
                "city": "Lekki",
                "state": "Lagos",
                "country": "Nigeria",
            },
            "items": [{"product_id": product_id, "quantity": 1}],
        }

        checkout_res = client.post("/checkout", json=checkout_payload)
        if checkout_res.status_code != 201:
            print(f"❌ Checkout failed ({checkout_res.status_code}):", checkout_res.text)
            return

        checkout_data = checkout_res.json()
        paystack_url = checkout_data["authorization_url"]
        reference = checkout_data["reference"]
        order = checkout_data["order"]

        print(f"✅ Order Created   : {order['id']}")
        print(f"✅ Paystack Ref    : {reference}")
        print(f"✅ Order Total     : NGN {order['total_amount']}")
        print(f"✅ Order Status    : {order['status']} (Payment: {order['payment_status']})")
        print("\n" + "=" * 70)
        print("🔗 PAYSTACK PAYMENT LINK (Open in browser to complete live test):")
        print(paystack_url)
        print("=" * 70)
        print("\nWaiting for real Paystack webhook callback via ngrok. Check your server logs.")


if __name__ == "__main__":
    main()