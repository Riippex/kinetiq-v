from __future__ import annotations

import logging
from typing import Any

from kinetiq.modules.media.application.ports import MediaStoragePort

logger = logging.getLogger(__name__)


class InMemoryMediaStorageAdapter(MediaStoragePort):
    """In-memory storage adapter for unit tests and local development."""

    def __init__(self, bucket_name: str = "kinetiq-media-test") -> None:
        self._bucket = bucket_name
        self._objects: dict[str, bytes] = {}

    def generate_upload_url(
        self, *, s3_key: str, content_type: str, ttl_seconds: int = 900
    ) -> str:
        return f"https://mock-s3.local/{self._bucket}/{s3_key}?action=put&ttl={ttl_seconds}&type={content_type}"

    def generate_download_url(self, *, s3_key: str, ttl_seconds: int = 900) -> str:
        return f"https://mock-s3.local/{self._bucket}/{s3_key}?action=get&ttl={ttl_seconds}"

    def object_exists(self, *, s3_key: str) -> bool:
        return s3_key in self._objects

    def delete_object(self, *, s3_key: str) -> None:
        self._objects.pop(s3_key, None)

    # Test helper
    def put_object_data(self, *, s3_key: str, data: bytes = b"mock-image-data") -> None:
        self._objects[s3_key] = data


class S3MediaStorageAdapter(MediaStoragePort):
    """Real S3 storage adapter generating pre-signed URLs and managing objects."""

    def __init__(
        self,
        bucket_name: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket_name
        self._region = region
        self._endpoint_url = endpoint_url
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # type: ignore[import-not-found]

            self._client = boto3.client(
                "s3",
                region_name=self._region,
                endpoint_url=self._endpoint_url,
            )
        return self._client

    def generate_upload_url(
        self, *, s3_key: str, content_type: str, ttl_seconds: int = 900
    ) -> str:
        client = self._get_client()
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._bucket,
                "Key": s3_key,
                "ContentType": content_type,
            },
            ExpiresIn=ttl_seconds,
        )
        return str(url)

    def generate_download_url(self, *, s3_key: str, ttl_seconds: int = 900) -> str:
        client = self._get_client()
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": s3_key},
            ExpiresIn=ttl_seconds,
        )
        return str(url)

    def object_exists(self, *, s3_key: str) -> bool:
        client = self._get_client()
        try:
            from botocore.exceptions import ClientError  # type: ignore[import-not-found]
        except ImportError:
            ClientError = Exception

        try:
            client.head_object(Bucket=self._bucket, Key=s3_key)
            return True
        except ClientError as exc:
            error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchKey", "NotFound"):
                return False
            if type(exc) is Exception:
                return False
            raise

    def delete_object(self, *, s3_key: str) -> None:
        client = self._get_client()
        try:
            client.delete_object(Bucket=self._bucket, Key=s3_key)
        except Exception:
            logger.exception("Failed to delete S3 object '%s' from '%s'", s3_key, self._bucket)
