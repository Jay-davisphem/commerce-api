"""Shared test fixtures.

Uses a dedicated `commerce_test` Postgres database (created out-of-band) so
tests never touch the dev `commerce` database. The `DATABASE_URL` env var is
set BEFORE any app module is imported so `app.core.database` builds its engine
against the test database.
"""

from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/commerce_test",
)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-long-enough-4-pyjwt")
os.environ.setdefault("SUPER_ADMIN_EMAIL", "admin@test.com")
os.environ.setdefault("SUPER_ADMIN_PASSWORD", "test-admin-password")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Force model registration on Base.metadata (imported after env is configured).
from app import models  # noqa: F401
from app.core.database import get_db
from app.main import app
from app.models.base import Base

TEST_DATABASE_URL = os.environ["DATABASE_URL"]

test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session", autouse=True)
async def _create_schema():
    """Create (and later drop) the schema in the test DB once per session."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


async def override_get_db():
    """Yield an isolated session per request, rolled back on error."""
    async with TestSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture
async def client():
    """FastAPI test client with the DB dependency overridden to the test DB.

    The override is registered at import time and intentionally NOT cleared so
    it applies to every test in the session.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _clean_tables():
    """Truncate all data between tests so each test starts from a clean state."""
    from sqlalchemy import text

    async with test_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE order_items, orders, products, users RESTART IDENTITY CASCADE")
        )
    yield


@pytest.fixture
async def create_user():
    """Factory: insert a user directly into the test DB and return the ORM user."""

    from app.models.user import User
    from app.services.security import hash_password

    async def _factory(email: str, password: str, role, full_name: str | None = None):
        async with TestSessionLocal() as session:
            user = User(
                email=email,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=role,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _factory


@pytest.fixture
def db_session_factory():
    """Provide the test sessionmaker so helpers can open their own sessions."""
    return TestSessionLocal


@pytest.fixture
async def auth_headers(client):
    """Return a helper that logs in via the API and yields Bearer headers."""

    async def _login(email: str, password: str) -> dict[str, str]:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _login
