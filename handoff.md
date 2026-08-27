# Handoff — Headless eCommerce API (FastAPI)

> **Purpose:** Comprehensive context for resuming work in a new Copilot session.
> **Project root:** `/home/davisphem/Documents/Codes/external/commerce-api`
> **Last updated:** 2026-08-27

---

## 1. TL;DR

A headless eCommerce API implementing a **one-shot checkout flow**. The frontend owns the cart (localStorage — no server cart, no Redis), submits a single payload, the **server recomputes the total from the DB** (never trusts client prices), persists a `pending` Order + OrderItems, initialises a **Paystack** transaction, returns the `authorization_url`, and a **webhook** flips the order to `paid`.

**Phase 1 (DONE):** Project scaffolded, SQLAlchemy 2.0 models + Pydantic v2 schemas built, checkout service, Paystack client, webhook handler, Alembic scaffolding, and a runnable FastAPI app — all wiring in place.

---

## 2. Tech Stack & Decisions

| Concern | Choice | Notes |
|---|---|---|
| Runtime | Python ≥ 3.11 | venv uses 3.11 (`commerce-api/.venv`) |
| Framework | **FastAPI** (async) | `uvicorn[standard]` |
| ORM | **SQLAlchemy 2.0** (typed `Mapped`/`mapped_column`) | async engine |
| Driver | **asyncpg** | `postgresql+asyncpg://` |
| Validation | **Pydantic v2** | `EmailStr` requires `email-validator` |
| Config | `pydantic-settings` (+ `.env`) | see `app/core/config.py` |
| Payments | **Paystack** API | async via `httpx`; amounts in **kobo** |
| Migrations | **Alembic** | async env configured |
| Testing | `pytest` + `pytest-asyncio`, `ruff` | dev extras |
| **No Redis** | — | cart is frontend localStorage |

### Key invariants (do not break)
- **Never trust client prices.** The server always loads `Product.price` from the DB and computes the total. The `CheckoutItem` schema deliberately has **no price field.**
- **Money = `Decimal` / `Numeric(12,2)`**, never floats. Paystack minor units = kobo = `amount * 100`.
- Order line items **snapshot** `unit_price`/`line_total` so later product price edits never change historical orders.

---

## 3. Project Layout

```
commerce-api/
├── .env.example            # copy to .env (db url + paystack keys)
├── .gitignore
├── pyproject.toml          # deps, scripts, ruff, pytest config
├── README.md
├── alembic.ini
├── alembic/
│   ├── env.py              # async engine config (reads app core.config settings)
│   └── script.py.mako
└── app/
    ├── main.py             # FastAPI app; lifespan auto create_all in dev/test
    ├── core/
    │   ├── config.py       # Settings (pydantic-settings) + cached get_settings()
    │   └── database.py     # async engine, AsyncSessionLocal, get_db dep, init_db; imports Base from models.base
    ├── models/             # SQLAlchemy 2.0 ORM models
    │   ├── base.py         # Base, UUIDPrimaryKeyMixin, TimestampMixin, utcnow()
    │   ├── product.py      # Product
    │   ├── order.py        # Order, OrderStatus, PaymentStatus
    │   └── order_item.py   # OrderItem
    ├── schemas/            # Pydantic v2
    │   ├── product.py      # ProductCreate/Update/Read
    │   ├── order.py        # CheckoutRequest/Response, DeliveryAddress, OrderRead/Item, OrderStatusUpdate
    │   └── paystack.py     # PaystackWebhook, PaystackEventData, PaymentVerification
    ├── services/
    │   ├── paystack.py     # PaystackService: initialize_transaction, to_kobo, verify_webhook_signature
    │   ├── checkout.py     # CheckoutService: recompute total, persist order, init txn
    │   └── webhook.py      # PaystackWebhookHandler: verify sig, mark paid
    └── api/
        └── v1/
            ├── products.py # CRUD
            ├── checkout.py # POST /api/v1/checkout
            └── webhooks.py # POST /api/v1/webhooks/paystack
```

---

## 4. Data Model

All tables use a UUID PK (`UUIDPrimaryKeyMixin`) + `created_at`/`updated_at` (`TimestampMixin`). `Base` is defined in `app/models/base.py`; `app/core/database.py` **imports** it (avoids circular imports).

### `products`
| Column | Type | Notes |
|---|---|---|
| id | UUID pk | |
| title | String(255) not null | |
| description | Text nullable | |
| price | Numeric(12,2) not null | CHECK `>= 0` |
| inventory_count | BigInteger not null | CHECK `>= 0` |
| image_url | String(1024) nullable | |

### `orders`
| Column | Type | Notes |
|---|---|---|
| id | UUID pk | |
| guest_email | String(255) not null, indexed | guest checkout, no auth |
| delivery_recipient_name / delivery_phone | nullable | |
| delivery_address_line1 | String(255) not null | |
| delivery_address_line2 / state / postal_code / notes | nullable | |
| delivery_city / delivery_country | not null | |
| total_amount | Numeric(12,2) not null | server-computed, CHECK `>= 0` |
| status | enum `OrderStatus` | `pending` (default) / `paid` / `failed` / `cancelled` |
| payment_status | enum `PaymentStatus` | `unpaid` / `paid` / `failed` |
| paystack_reference | String(255) nullable, indexed | set at init |
| paystack_access_code | String(255) nullable | |
| paystack_authorization_url | String(1024) nullable | |
| paid_at | timestamptz nullable | set by webhook |

Relationships: `Order.items` → `OrderItem` (cascade delete-orphan, `lazy="selectin"`), items loaded via `db.refresh(order, ["items"])`.

### `order_items`
| Column | Type | Notes |
|---|---|---|
| id | UUID pk | |
| order_id | FK `orders.id` CASCADE, indexed | |
| product_id | FK `products.id` RESTRICT, indexed | |
| quantity | BigInteger not null | CHECK `> 0` |
| unit_price | Numeric(12,2) not null | **snapshot** of product price |
| line_total | Numeric(12,2) not null | unit_price × quantity |
| | | UNIQUE(order_id, product_id) |

---

## 5. API Surface (Phase 1 implemented)

All under `/api/v1`.

- `GET  /api/v1/products` → `list[ProductRead]`
- `GET  /api/v1/products/{id}` → `ProductRead`
- `POST /api/v1/products` → `ProductRead` (ProductCreate)
- `PATCH /api/v1/products/{id}` → `ProductRead`
- `DELETE /api/v1/products/{id}` → 204
- `POST /api/v1/checkout` → `CheckoutResponse` (see flow below)
- `POST /api/v1/webhooks/paystack` → verifies HMAC, marks order paid
- `GET  /health` → `{status, app}`

### Checkout flow (`POST /api/v1/checkout`)
Request body:
```json
{
  "guest_email": "buyer@example.com",
  "delivery": {
    "address_line1": "12 Main St",
    "city": "Lagos",
    "country": "NG"
  },
  "items": [ { "product_id": "<uuid>", "quantity": 2 } ]
}
```
`app/services/checkout.py::CheckoutService.run()`:
1. Load products by id from DB.
2. Reject unknown product ids.
3. Validate stock; compute each `line_total` + total from **DB prices**; decrement inventory (best-effort).
4. Persist `Order(status=pending)` + OrderItems (flush for id).
5. `paystack.initialize_transaction(...)` with server total (in kobo) + `reference="ORDER-<id>"`.
6. Store `paystack_reference/access_code/authorization_url`, commit.
7. Return `CheckoutResponse{order, authorization_url, access_code, reference}`.

### Webhook flow (`POST /api/v1/webhooks/paystack`)
`app/services/webhook.py`:
1. Read raw body, verify `x-paystack-signature` (HMAC-SHA512 of body with secret) — 401 if bad.
2. On `event == "charge.success"`, find order by `paystack_reference`, set `status=paid`, `payment_status=paid`, `paid_at`.
3. Returns `{"status": "ok"}` (Paystack expects 200).

---

## 6. Environment & Setup

`.env` (copy from `.env.example`):
```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/commerce
PAYSTACK_SECRET_KEY=sk_test_...
PAYSTACK_PUBLIC_KEY=pk_test_...
PAYSTACK_BASE_URL=https://api.paystack.co
CORS_ORIGINS=["http://localhost:3000"]
```

Commands (run from project root):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then edit
uvicorn app.main:app --reload # http://127.0.0.1:8000/docs
```

Alembic:
```bash
alembic revision --autogenerate -m "init product order orderitem"
alembic upgrade head
```

> In `development`/`test` env, `app.main` lifespan calls `init_db()` (auto `create_all`) for convenience. Use Alembic for production.

---

## 7. Current State & Known Gaps (Phase 2 candidates)

### Implemented ✅
- Product CRUD, Order + OrderItem models, checkout service, Paystack init, webhook signature verification + paid-marking, Alembic scaffolding, settings/db wiring.

### Gaps / next steps ⚠️
1. **Concurrency / overselling:** `inventory_count` decrement is not atomic. Add `SELECT ... FOR UPDATE` (row lock) or an atomic `UPDATE products SET inventory_count = inventory_count - :q WHERE id=:id AND inventory_count >= :q` guarded by rowcount check.
2. **Idempotency:** Webhook can fire multiple times; currently re-marks paid (should be idempotent — skip if already paid). Also no retry/dedupe for the same Paystack `reference` (UNIQUE constraint not enforced at DB level — only an index exists on `paystack_reference`; consider a unique partial index or a dedicated `payments` table).
3. **`db.refresh(order, ["items"])`** after commit currently relies on `lazy="selectin"` and `expire_on_commit=False`; verify items load reliably across sessions (may want `awaitable_attrs` or explicit selectinload).
4. **Rollback on Paystack failure:** if `initialize_transaction` throws, the pending Order was flushed but not committed — current code raises after flush; confirm no partial state. Consider marking order `failed`/`cancelled` on txn error instead of leaving an orphan.
5. **`get_db` rollback** is fine, but the transaction boundary around "persist order + init paystack" should be deliberate (commit only on success; rollback + mark failed on error).
6. **Tests:** no tests exist yet. Add fixtures using a test Postgres (or `aiosqlite`) + mocked `httpx` for Paystack.
7. **Alembic versions folder** is empty — first migration not yet generated/committed.
8. **Auth:** none yet. Add admin auth (e.g. Bearer token / JWT) for product write ops if required.
9. **Paystack verify fallback:** add `GET /payments/verify?reference=` calling `GET /transaction/verify` (schema `PaymentVerification` already exists but no endpoint/service yet).
10. **`delivery` field on `OrderRead`** is flattened in the service mapper (not a real column relation); keep it consistent if schema changes.
11. **CORS + env** not wired to real frontend host; update `CORS_ORIGINS` in `.env`.
12. **`payment.cryptography`** dependency is declared ("for HMAC") but Paystack HMAC uses stdlib `hmac`/`hashlib`; the dep can be dropped unless needed later for encryption.

---

## 8. Pitfalls / Gotchas

- **`.venv` is NOT relocatable.** It bakes absolute paths. If you move the project folder, recreate the venv (`rm -rf .venv && python3 -m venv .venv && pip install -e ".[dev]"`). Do NOT try to move it.
- **`EmailStr` needs `email-validator`** — it's now in `pyproject.toml`; if missing you'll get an ImportError at import time.
- **Circular imports** between models (Order ↔ OrderItem ↔ Product): handled by defining `Base` in `models/base.py` and using bottom-of-module imports for relationship classes. Keep that pattern.
- **SQLite vs Postgres:** target DB is Postgres/asyncpg. If you ever test with SQLite, `DateTime(timezone=True)` + `Enum` behave differently — keep prod on Postgres.
- **Paystack amounts are integer kobo** — always `to_kobo()` (×100, quantized) before sending.
- The system Python is **3.14**, the venv is **3.11** (`requires-python = ">=3.11"`). Stray `cpython-314` `__pycache__` files exist from the system interpreter compile-check; harmless but don't run the app with the system 3.14 unless you recreate the venv.

---

## 9. Suggested Next Session Start

1. Read this file, `pyproject.toml`, `app/core/config.py`, `app/core/database.py`.
2. Review `app/models/*` and `app/schemas/*`.
3. Read `app/services/checkout.py`, `app/services/paystack.py`, `app/services/webhook.py`.
4. Decide Phase 2 priority (recommended: **#1 concurrency/atomic inventory** + **#2 webhook idempotency**).
5. Confirm DB is up and run `uvicorn app.main:app --reload`, hit `/docs`.
