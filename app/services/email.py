from __future__ import annotations

from decimal import Decimal
from email.utils import parseaddr
import logging
from typing import TYPE_CHECKING
import httpx

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.order import Order

logger = logging.getLogger(__name__)


class EmailService:
    RESEND_URL = "https://api.resend.com/emails"
    ENSEND_URL = "https://api.ensend.co/send/mail"

    @classmethod
    async def _send_via_resend(cls, to: str, subject: str, html_content: str) -> bool:
        if not settings.RESEND_API_KEY:
            logger.warning("RESEND_API_KEY is not configured in .env")
            return False

        headers = {
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "from": settings.EMAILS_FROM,
            "to": [to],
            "subject": subject,
            "html": html_content,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(cls.RESEND_URL, json=payload, headers=headers)
                if res.is_success:
                    logger.info("Email delivered via Resend to %s", to)
                    return True
                logger.error("Resend API error (HTTP %s): %s", res.status_code, res.text)
                return False
        except Exception as exc:
            logger.error("Resend delivery failed: %s", exc)
            return False

    @classmethod
    async def _send_via_ensend(
        cls, to: str, subject: str, html_content: str, recipient_name: str
    ) -> bool:
        if not settings.ENSEND_PROJECT_SECRET:
            logger.warning("ENSEND_PROJECT_SECRET is not configured in .env")
            return False

        parsed_name, parsed_address = parseaddr(settings.EMAILS_FROM)
        sender_name = settings.ENSEND_SENDER_NAME or parsed_name or "BLHMI Supplements"
        sender_address = settings.ENSEND_SENDER_ADDRESS or parsed_address or settings.EMAILS_FROM

        headers = {
            "Authorization": f"Bearer {settings.ENSEND_PROJECT_SECRET}",
            "Content-Type": "application/json",
        }
        payload = {
            "subject": subject,
            "message": html_content,
            "sender": {
                "name": sender_name,
                "address": sender_address,
            },
            "recipients": {
                "name": recipient_name or to.split("@")[0],
                "address": to,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(cls.ENSEND_URL, json=payload, headers=headers)
                if res.is_success:
                    logger.info("Email delivered via Ensend to %s", to)
                    return True
                logger.error("Ensend API error (HTTP %s): %s", res.status_code, res.text)
                return False
        except Exception as exc:
            logger.error("Ensend delivery failed: %s", exc)
            return False

    @classmethod
    async def send_email(
        cls,
        to: str,
        subject: str,
        html_content: str,
        recipient_name: str = "Customer",
    ) -> bool:
        """Route email dispatch based on the EMAIL_PROVIDER environment setting."""
        provider = (settings.EMAIL_PROVIDER or "resend").lower().strip()

        if provider == "ensend":
            return await cls._send_via_ensend(
                to=to,
                subject=subject,
                html_content=html_content,
                recipient_name=recipient_name,
            )

        return await cls._send_via_resend(
            to=to,
            subject=subject,
            html_content=html_content,
        )

    @classmethod
    async def send_otp_email(
        cls,
        to: str,
        otp: str,
        purpose: str = "Verification",
        recipient_name: str = "Customer",
    ) -> bool:
        subject = f"{purpose} Code: {otp}"
        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 500px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
            <h2 style="color: #1e3a8a; margin-bottom: 8px;">BLHMI Supplements</h2>
            <p style="color: #475569; font-size: 15px;">Use the code below to complete your <strong>{purpose.lower()}</strong>. This code is valid for 10 minutes.</p>
            <div style="margin: 24px 0; text-align: center;">
                <span style="display: inline-block; font-size: 32px; font-weight: bold; letter-spacing: 6px; color: #1e293b; background: #f1f5f9; padding: 12px 24px; border-radius: 6px;">{otp}</span>
            </div>
            <p style="color: #94a3b8; font-size: 13px;">If you didn't request this code, you can safely ignore this email.</p>
        </div>
        """
        return await cls.send_email(
            to=to,
            subject=subject,
            html_content=html_content,
            recipient_name=recipient_name,
        )

    @classmethod
    async def send_order_status_email(
        cls,
        order: Order,
        new_status: str,
    ) -> bool:
        """Sends transactional order update emails to order.guest_email upon state transitions."""
        normalized = new_status.lower().strip().replace(" ", "_")
        order_ref = order.order_reference
        customer_name = order.customer_name
        formatted_total = f"NGN {order.total_amount:,.2f}"

        items_li = "".join([
            f"<li style='margin-bottom: 6px;'>{it.product.title if it.product else 'Item'} &times; {it.quantity} "
            f"&mdash; <strong>NGN {it.line_total:,.2f}</strong></li>"
            for it in order.items
        ])

        if normalized in ("paid", "in_escrow"):
            subject = f"Payment Secured in Escrow: Order {order_ref}"
            badge_color = "#2563eb"
            badge_label = "Payment Secured (Escrow)"
            headline = "Your Payment is Safely Held in Escrow"
            message = (
                f"We have received your payment of <strong>{formatted_total}</strong>. "
                "Your funds are secured in escrow and will only be released after you confirm "
                "safe delivery of your items."
            )
        elif normalized == "in_transit":
            subject = f"Order In Transit: {order_ref}"
            badge_color = "#0891b2"
            badge_label = "In Transit"
            headline = "Your Order is on the Way!"
            message = (
                f"Your order <strong>{order_ref}</strong> is currently in transit. "
                "Once you receive your package, please log into your account and click "
                "<strong>'Mark as received'</strong> to release the escrow payment."
            )
        elif normalized == "delivered":
            subject = f"Order Delivered & Escrow Released: {order_ref}"
            badge_color = "#16a34a"
            badge_label = "Delivered"
            headline = "Delivery Confirmed"
            message = (
                f"Order <strong>{order_ref}</strong> has been marked as delivered. "
                "Escrow funds have been successfully released to complete the order. "
                "Thank you for choosing BLHMI Supplements!"
            )
        elif normalized in ("cancelled", "failed"):
            subject = f"Order Status Update: Cancelled ({order_ref})"
            badge_color = "#dc2626"
            badge_label = "Cancelled"
            headline = "Order Cancelled"
            message = (
                f"Your order <strong>{order_ref}</strong> has been cancelled. "
                "If you made a payment or have questions regarding escrow release, "
                "please contact support immediately."
            )
        else:
            subject = f"Order Status Update: {order_ref}"
            badge_color = "#475569"
            badge_label = normalized.replace("_", " ").title()
            headline = f"Order Status: {badge_label}"
            message = f"Your order <strong>{order_ref}</strong> has been updated to <strong>{badge_label}</strong>."

        delivery_info = (
            f"<p style='color: #64748b; font-size: 14px; margin-top: 16px;'>"
            f"<strong>Delivery Address:</strong> {order.delivery_address_line1}, {order.delivery_city}, {order.delivery_country}"
            f"</p>"
        )

        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 540px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 8px; background-color: #ffffff;">
            <div style="border-bottom: 2px solid #f1f5f9; padding-bottom: 16px; margin-bottom: 20px;">
                <h2 style="color: #1e3a8a; margin: 0; font-size: 20px;">BLHMI Supplements</h2>
                <span style="display: inline-block; margin-top: 8px; font-size: 12px; font-weight: bold; text-transform: uppercase; color: #ffffff; background-color: {badge_color}; padding: 4px 10px; border-radius: 4px;">
                    {badge_label}
                </span>
            </div>

            <p style="color: #334155; font-size: 15px;">Hello {customer_name},</p>
            <h3 style="color: #0f172a; margin-top: 8px;">{headline}</h3>
            <p style="color: #475569; font-size: 14px; line-height: 1.6;">{message}</p>

            <div style="margin: 20px 0; padding: 16px; background-color: #f8fafc; border-radius: 6px;">
                <div style="font-size: 13px; font-weight: bold; color: #475569; margin-bottom: 8px; text-transform: uppercase;">
                    Order Summary ({order_ref})
                </div>
                <ul style="padding-left: 20px; margin: 0 0 12px 0; color: #334155; font-size: 14px;">
                    {items_li}
                </ul>
                <div style="border-top: 1px solid #e2e8f0; padding-top: 8px; font-size: 15px; font-weight: bold; color: #0f172a; display: flex; justify-content: space-between;">
                    <span>Total Amount:</span>
                    <span>{formatted_total}</span>
                </div>
            </div>

            {delivery_info}

            <p style="color: #94a3b8; font-size: 12px; margin-top: 24px; border-top: 1px solid #f1f5f9; padding-top: 12px;">
                If you have any questions, reach out to our team at support@blhmisupplement.com.
            </p>
        </div>
        """

        return await cls.send_email(
            to=order.guest_email,
            subject=subject,
            html_content=html_content,
            recipient_name=customer_name,
        )


email_service = EmailService()