from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.order import CheckoutRequest, CheckoutResponse
from app.services.checkout import CheckoutService

router = APIRouter(prefix="/checkout", tags=["Checkout"])


@router.post("", response_model=CheckoutResponse, status_code=201)
async def create_checkout(
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """One-shot guest checkout.

    Body: `{ guest_email, delivery, items: [{product_id, quantity}] }`.

    The server recomputes the total from the database, persists a `pending`
    Order, initialises a Paystack transaction, and returns the
    `authorization_url`.
    """
    return await CheckoutService(db).run(payload)
