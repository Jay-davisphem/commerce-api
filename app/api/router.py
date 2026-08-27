from fastapi import APIRouter

from app.api.v1 import checkout, products, webhooks

api_router = APIRouter()
api_router.include_router(checkout.router)
api_router.include_router(products.router)
api_router.include_router(webhooks.router)
