"""CRUD routes for asset management (file upload, download, delete)."""

import logging
import uuid

from flask import Blueprint, jsonify, request

from ..auth import require_auth, resolve_tenant
from ..models import Asset, db
from ..services.asset_service import (
    delete_asset,
    get_download_url,
    upload_asset,
    validate_upload,
)

logger = logging.getLogger(__name__)

assets_bp = Blueprint("assets", __name__)


@assets_bp.route("/api/assets/upload", methods=["POST"])
@require_auth
def upload():
    """Upload a file asset (multipart form data)."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No filename"}), 400

    # Read file content to get size
    file_data = file.read()
    size_bytes = len(file_data)
    content_type = file.content_type or "application/octet-stream"

    # Validate content type and size
    error = validate_upload(content_type, size_bytes)
    if error:
        return jsonify({"error": error}), 400

    campaign_id = request.form.get("campaign_id") or request.args.get("campaign_id")
    asset_id = str(uuid.uuid4())

    # Reset file pointer for upload
    from io import BytesIO

    file_obj = BytesIO(file_data)

    # Upload to S3
    try:
        storage_path = upload_asset(
            file_obj=file_obj,
            filename=file.filename,
            content_type=content_type,
            tenant_id=str(tenant_id),
            campaign_id=campaign_id,
            asset_id=asset_id,
        )
    except Exception as e:
        logger.error(f"S3 upload failed: {e}")
        return jsonify({"error": "File upload failed"}), 500

    # Create DB record
    asset = Asset(
        id=asset_id,
        tenant_id=str(tenant_id),
        campaign_id=campaign_id,
        filename=file.filename,
        content_type=content_type,
        storage_path=storage_path,
        size_bytes=size_bytes,
        metadata_={},
    )
    db.session.add(asset)
    db.session.commit()

    return jsonify(asset.to_dict()), 201


@assets_bp.route("/api/assets", methods=["GET"])
@require_auth
def list_assets():
    """List assets for the current tenant, optionally filtered by campaign_id."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    query = Asset.query.filter_by(tenant_id=str(tenant_id))

    campaign_id = request.args.get("campaign_id")
    if campaign_id:
        query = query.filter_by(campaign_id=campaign_id)

    assets = query.order_by(Asset.created_at.desc()).all()
    return jsonify({"assets": [a.to_dict() for a in assets]}), 200


@assets_bp.route("/api/assets/<asset_id>/download", methods=["GET"])
@require_auth
def download(asset_id):
    """Generate a presigned S3 download URL for an asset."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    asset = Asset.query.filter_by(id=asset_id, tenant_id=str(tenant_id)).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    try:
        url = get_download_url(asset.storage_path)
    except Exception as e:
        logger.error(f"Failed to generate download URL: {e}")
        return jsonify({"error": "Failed to generate download URL"}), 500

    return jsonify({"url": url}), 200


@assets_bp.route("/api/assets/<asset_id>", methods=["DELETE"])
@require_auth
def delete(asset_id):
    """Delete an asset from S3 and the database."""
    tenant_id = resolve_tenant()
    if not tenant_id:
        return jsonify({"error": "Tenant not found"}), 404

    asset = Asset.query.filter_by(id=asset_id, tenant_id=str(tenant_id)).first()
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    # Delete from S3 (best effort — still remove DB record)
    try:
        delete_asset(asset.storage_path)
    except Exception as e:
        logger.warning(f"S3 delete failed for asset {asset_id}: {e}")

    db.session.delete(asset)
    db.session.commit()

    return jsonify({"ok": True}), 200
