# Headless eCommerce API

A headless one-shot-checkout eCommerce API built with:

- **FastAPI** (async)
- **PostgreSQL** + **SQLAlchemy 2.0** (async via `asyncpg`)
- **Pydantic v2**
- **Paystack** payment gateway

## Architecture (One-Shot Checkout)

- No server-side cart. The frontend owns the cart (localStorage).
- The frontend sends a single checkout payload: guest email, delivery address, and items.
- The backend **recomputes** the total from the DB (never trusts frontend prices).
- Order is persisted as `pending`, then a Paystack webhook flips it to `paid`.

```
Frontend (localStorage cart)
        │  POST /api/checkout  { email, address, items: [{product_id, qty}] }
        ▼
   FastAPI CheckoutService
        │ 1. Load products, compute server-side total
        │ 2. Create Order (status=pending) + OrderItems
        │ 3. Initialize transaction @ Paystack API
        ▼
   returns { authorization_url }
        │
Frontend redirects user to Paystack
        │  Paystack POSTs charge.success event
        ▼
   POST /api/webhooks/paystack  (signature verified)
        │  Order.status = "paid"
```

## Project layout

```
commerce-api/
├── app/
│   ├── main.py              # FastAPI app entrypoint
│   ├── core/                # config, db session
│   ├── models/              # SQLAlchemy 2.0 ORM models
│   ├── schemas/             # Pydantic v2 schemas
│   ├── services/            # business logic (checkout, payments)
│   └── api/                 # routers
├──.env.example
├── pyproject.toml
└── README.md
```

## Run

See the "Scaffold commands" section in the task or run:

```bash
cd commerce-api
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # set DATABASE_URL + PAYSTACK keys
uvicorn app.main:app --reload
```
