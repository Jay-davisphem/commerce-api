# BLHMI Commerce API

A high-performance, asynchronous headless eCommerce API built with FastAPI, SQLAlchemy 2.0, PostgreSQL (asyncpg), and Paystack. Designed to power the BLHMI Supplements storefront and seller administrative dashboard.

---

## Features

* **Storefront API (`/api/v1/products`)**:
  * Paginated product catalog with text search (`q`), category filters, and price ranges.
  * Promotional tagging (`hot_deal`, `special_offer`, `new_arrival`, `recommended`).
  * Dynamic category list with product count aggregations for category pills.
  * Safe UUID product retrieval with dual `title`/`name` compatibility.
* **Seller Dashboard (`/api/v1/sellers`)**:
  * Real-time KPI analytics: Online Orders Today, POS Sales Today, Goods in Escrow, and Low-Stock Alert counts.
  * Low-stock monitoring with one-click inventory restock (`POST /products/{id}/restock`).
  * Paginated seller order fulfillment queue with status transitions (`in_escrow`, `in_transit`, `delivered`).
  * Role-enforced product CRUD (sellers only manage their own inventory).
* **Checkout & Paystack Integration (`/api/v1/checkout`, `/api/v1/webhooks`)**:
  * Guest-first or authenticated checkout.
  * **Server-Authoritative Pricing**: Total amounts are recalculated strictly from the database; client-submitted prices are discarded.
  * **Concurrency-Safe Stock Reservation**: Guarded SQL decrements (`WHERE inventory_count >= quantity`) prevent race conditions and overselling.
  * Paystack inline/redirect initialization with HMAC-SHA512 webhook verification for payment settlement.
* **Buyer Order Tracking (`/api/v1/orders`)**:
  * Authenticated buyer order history (`GET /orders/me`) with paginated line items and delivery address snapshots.
  * Automatic retroactive linking of guest purchases when creating an account with matching email.
* **Security & RBAC (`/api/v1/auth`, `/api/v1/users`)**:
  * JWT Bearer token authentication with PyJWT and bcrypt password hashing.
  * Three-tier role-based access control: `BUYER`, `SELLER`, and `SUPER_ADMIN`.
  * Saved customer delivery profiles with auto-update on checkout.

---

## Tech Stack

* **Framework**: FastAPI (Python 3.11+)
* **Database**: PostgreSQL
* **ORM**: SQLAlchemy 2.0 (AsyncIO with `asyncpg`)
* **Migrations**: Alembic
* **Validation**: Pydantic v2
* **Payment Gateway**: Paystack REST API & Webhooks
* **Testing**: Pytest, HTTPX (AsyncClient)

---

## Project Structure

```text
├── alembic/                 # Database migration scripts and environment
├── app/
│   ├── api/
│   │   ├── router.py        # Central v1 route aggregator
│   │   └── v1/
│   │       ├── auth.py      # Registration, login, profile, delivery address
│   │       ├── checkout.py  # One-shot checkout orchestration
│   │       ├── orders.py    # Buyer order history
│   │       ├── products.py  # Storefront browsing, search, categories
│   │       ├── sellers.py   # Seller dashboard, metrics, restock, order queue
│   │       ├── users.py     # Super-admin user management
│   │       └── webhooks.py  # Paystack event intake
│   ├── core/
│   │   ├── config.py        # Environment variables & Pydantic settings
│   │   ├── database.py      # Async engine, sessionmaker, and get_db dependency
│   │   └── init_superadmin.py # Idempotent startup superadmin bootstrap
│   ├── models/              # SQLAlchemy 2.0 ORM models (UUID PKs)
│   ├── schemas/             # Pydantic v2 request/response schemas
│   └── services/            # Business logic (Paystack, Checkout, Auth, Security)
├── tests/                   # Pytest suite covering auth, RBAC, checkout, inventory
├── pyproject.toml           # Project dependencies and tool configurations
└── README.md