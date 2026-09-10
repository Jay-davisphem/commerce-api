from __future__ import annotations

import logging
import aioboto3
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class R2StorageService:
    def __init__(self) -> None:
        self.session = aioboto3.Session()
        self.endpoint_url = f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        self.bucket = settings.R2_BUCKET_NAME
        self.public_domain = settings.R2_PUBLIC_DOMAIN.rstrip("/")

    async def upload_file(self, file_bytes: bytes, filename: str, content_type: str) -> str:
        """Upload raw bytes to R2 bucket and return the public URL."""
        async with self.session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        ) as s3:
            await s3.put_object(
                Bucket=self.bucket,
                Key=filename,
                Body=file_bytes,
                ContentType=content_type,
            )

        return f"{self.public_domain}/{filename}"

    async def delete_file(self, file_url: str | None) -> None:
        """Delete an object from R2 by its public URL."""
        if not file_url or not file_url.startswith(self.public_domain):
            return

        key = file_url.replace(f"{self.public_domain}/", "")
        try:
            async with self.session.client(
                "s3",
                endpoint_url=self.endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                region_name="auto",
            ) as s3:
                await s3.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            logger.warning("Failed to delete orphaned R2 file %s: %s", key, exc)


storage_service = R2StorageService()