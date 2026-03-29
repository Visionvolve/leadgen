"""Asset storage service using S3."""

from __future__ import annotations

import os
import logging
import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _get_s3_client():
    """Get boto3 S3 client. Uses AWS credentials from environment."""
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "eu-central-1"),
    )


def _get_bucket():
    """Get S3 bucket name from environment."""
    env = os.getenv("FLASK_ENV", "staging")
    return os.getenv("ASSET_S3_BUCKET", f"leadgen-assets-{env}")


def upload_asset(
    file_obj,
    filename: str,
    content_type: str,
    tenant_id: str,
    campaign_id: str | None,
    asset_id: str,
) -> str:
    """Upload file to S3. Returns the storage path (S3 key)."""
    bucket = _get_bucket()
    if campaign_id:
        key = f"{tenant_id}/{campaign_id}/{asset_id}/{filename}"
    else:
        key = f"{tenant_id}/shared/{asset_id}/{filename}"

    s3 = _get_s3_client()
    s3.upload_fileobj(
        file_obj,
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    log.info(f"Uploaded asset {asset_id} to s3://{bucket}/{key}")
    return key


def get_download_url(storage_path: str, expires_in: int = 3600) -> str:
    """Generate presigned download URL for an asset."""
    bucket = _get_bucket()
    s3 = _get_s3_client()
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": storage_path},
        ExpiresIn=expires_in,
    )
    return url


def delete_asset(storage_path: str) -> bool:
    """Delete asset from S3. Returns True if deleted."""
    bucket = _get_bucket()
    s3 = _get_s3_client()
    try:
        s3.delete_object(Bucket=bucket, Key=storage_path)
        log.info(f"Deleted asset from s3://{bucket}/{storage_path}")
        return True
    except ClientError as e:
        log.error(f"Failed to delete asset: {e}")
        return False


def validate_upload(content_type: str, size_bytes: int) -> str | None:
    """Validate file upload. Returns error message or None if valid."""
    if content_type not in ALLOWED_CONTENT_TYPES:
        return f"File type {content_type} not allowed. Allowed: {', '.join(ALLOWED_CONTENT_TYPES)}"
    if size_bytes > MAX_FILE_SIZE:
        return f"File too large ({size_bytes} bytes). Max: {MAX_FILE_SIZE} bytes (10MB)"
    return None
