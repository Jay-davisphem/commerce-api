---

### `handoff.md`

```markdown
# Engineering Handoff: BLHMI Commerce API

This document details the architecture, data models, business rules, and UI-to-API mapping for frontend engineers and backend maintainers.

---

## 1. System Invariants & Design Principles

* **Async-First Execution**: The service runs entirely on `async/await` utilizing SQLAlchemy 2.0 with the `asyncpg` dialect. Synchronous ORM calls (`db.query()`, `session.commit()`) are prohibited.
* **Server-Authoritative Financials**: The frontend provides only `product_id` and `quantity` at checkout. Prices sent from the client are completely ignored. All line totals, taxes, and Paystack kobo values are derived server-side from database snapshots.
* **Race-Condition-Free Inventory**: Decrementing inventory during checkout is executed using guarded atomic SQL updates (`UPDATE products SET inventory_count = inventory_count - :qty WHERE id = :id AND inventory_count >= :qty`). If `rowcount == 0`, checkout rolls back immediately, preventing overselling under high concurrency.
* **UUID Primary Keys**: All records (`Product`, `Order`, `OrderItem`, `User`) utilize UUIDv4 identifiers.
* **Dual-Field Compatibility**: The `Product` model defines `title` internally, but exposes `name` as a synonym at both the ORM and Pydantic schema layers to eliminate naming drift between frontend conventions and database schema.

---

## 2. Frontend Screen Mapping

### Storefront Home (`design1.jpg`)

| UI Element | API Endpoint & Parameters | Notes |
| :--- | :--- | :--- |
| **Global Search** | `GET /api/v1/products?q={term}` | Searches product titles and descriptions case-insensitively. |
| **Hot Deals Carousel** | `GET /api/v1/products?tag=hot_deal&page_size=5` | Returns flagged promotion cards. |
| **Special Offers Grid** | `GET /api/v1/products?tag=special_offer&page_size=6` | Includes `original_price` and `discount_percentage` for badge rendering. |
| **Shop by Category** | `GET /api/v1/products/categories` | Populates category pills with active item counts. |
| **Category Click** | `GET /api/v1/products?category={category_name}` | Filters the catalog by the selected category slug. |
| **Recommended / New Arrivals** | `GET /api/v1/products?tag=recommended` or `?tag=new_arrival` | Curated product listings for lower sections. |
| **Add to Cart / Buy Now** | `POST /api/v1/checkout` | Accepts `{ guest_email, delivery, items: [{ product_id, quantity }] }`. Returns Paystack `authorization_url` and `reference`. |

### Seller Admin Dashboard (`Sellers Dashboard-design2.png`)

| UI Element | API Endpoint & Parameters | Notes |
| :--- | :--- | :--- |
| **Dashboard Metrics** | `GET /api/v1/sellers/dashboard` | Returns `online_orders_today`, `pos_sales_today`, `goods_in_escrow`, and `low_stock_alerts`. |
| **Recent Orders Widget** | `GET /api/v1/sellers/dashboard` (`recent_orders` array) | Contains order reference, customer name, total amount, and human-readable status. |
| **Low Stock Items Widget** | `GET /api/v1/sellers/dashboard` (`low_stock_items` array) | Returns products where `inventory_count <= low_stock_threshold`. |
| **Restock Now Action** | `POST /api/v1/sellers/products/{id}/restock` | Payload: `{"quantity": 50}`. Atomically increments inventory count. |
| **View All Orders (Table)** | `GET /api/v1/sellers/orders?page=1&page_size=10` | Filterable by `status` (`in_escrow`, `in_transit`, `delivered`) and `search`. |
| **Update Order Status** | `PATCH /api/v1/sellers/orders/{id}/status` | Payload: `{"status": "in_transit"}`. Updates delivery lifecycle state. |
| **Manage Inventory** | `GET /api/v1/sellers/products` | Paginated product table for the authenticated seller. |

---

## 3. Database Schema Overview

### `products`
* `id` (`UUID`, Primary Key)
* `title` / `name` (`VARCHAR(255)`, Indexed)
* `description` (`TEXT`, Nullable)
* `price` (`NUMERIC(12,2)`, Non-negative)
* `original_price` (`NUMERIC(12,2)`, Nullable)
* `discount_percentage` (`INTEGER`, Default `0`)
* `inventory_count` (`BIGINT`, Default `0`)
* `low_stock_threshold` (`INTEGER`, Default `15`)
* `category` (`VARCHAR(100)`, Indexed, Nullable)
* `tag` (`VARCHAR(50)`, Indexed, Nullable)
* `image_url` (`VARCHAR(1024)`, Nullable)
* `owner_id` (`UUID`, Foreign Key -> `users.id`)
* `created_at`, `updated_at` (Timestamps with timezone)

### `orders`
* `id` (`UUID`, Primary Key)
* `guest_email` (`VARCHAR(255)`, Indexed)
* `user_id` (`UUID`, Nullable, Foreign Key -> `users.id`)
* `total_amount` (`NUMERIC(12,2)`)
* `status` (`order_status` Enum: `pending`, `paid`, `in_escrow`, `in_transit`, `delivered`, `failed`, `cancelled`)
* `payment_status` (`payment_status` Enum: `unpaid`, `paid`, `failed`)
* `order_source` (`VARCHAR(20)`, Default `'ONLINE'`)
* `paystack_reference` (`VARCHAR(255)`, Indexed)
* `paystack_access_code` (`VARCHAR(255)`, Nullable)
* `paystack_authorization_url` (`VARCHAR(1024)`, Nullable)
* `paid_at` (`TIMESTAMPTZ`, Nullable)
* `delivery_*` (Snapshot columns for address, phone, and recipient)

---

## 4. Payment & Checkout Lifecycle

```text
[Frontend Cart]
       │  POST /api/v1/checkout
       ▼
[Checkout Service]
       ├─► 1. Query products & verify stock
       ├─► 2. Guarded SQL: UPDATE inventory_count - quantity
       ├─► 3. Create Order (status=pending, payment_status=unpaid)
       ├─► 4. Paystack API: initialize_transaction (total in kobo)
       └─► 5. Return authorization_url & reference
       │
[Customer Completes Payment on Paystack]
       │
       ▼
[Paystack Webhook POST /api/v1/webhooks/paystack]
       ├─► 1. Verify HMAC header (x-paystack-signature)
       ├─► 2. Match order by paystack_reference
       ├─► 3. Mark status = paid / in_escrow, payment_status = paid
       └─► 4. Save paid_at timestamp