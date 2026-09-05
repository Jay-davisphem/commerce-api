from fastapi import APIRouter

from app.api.v1 import auth, checkout, orders, products, sellers, users, webhooks

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(products.router)
api_router.include_router(checkout.router)
api_router.include_router(orders.router)
api_router.include_router(sellers.router)
api_router.include_router(users.router)
api_router.include_router(webhooks.router)