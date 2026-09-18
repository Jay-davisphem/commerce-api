from __future__ import annotations

from email.utils import parseaddr
import logging
import httpx

from app.core.config import settings

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


email_service = EmailService()