"""Tests for authentication and user roles."""

from __future__ import annotations

import pytest

from app.models.user import UserRole


@pytest.mark.asyncio
async def test_register_seller(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "seller-new@test.com", "password": "sellerpass123"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["role"] == "seller"
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    # login with the new account works
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "seller-new@test.com", "password": "sellerpass123"},
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_register_duplicate_email_conflicts(client, create_user):
    await create_user("dup@test.com", "password123", UserRole.SELLER)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "dup@test.com", "password": "password123"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_register_buyer_role(client):
    resp = await client.post(
        "/api/v1/auth/register-buyer",
        json={"email": "buyer@test.com", "password": "buyerpass123"},
    )
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "buyer"


@pytest.mark.asyncio
async def test_login_wrong_password(client, create_user):
    await create_user("who@test.com", "correctpass", UserRole.SELLER)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "who@test.com", "password": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_current_user(client, auth_headers, create_user):
    await create_user("me@test.com", "mepass123", UserRole.SUPER_ADMIN)
    headers = await auth_headers("me@test.com", "mepass123")
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "me@test.com"
    assert resp.json()["role"] == "super_admin"
