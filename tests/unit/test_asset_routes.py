"""Unit tests for asset CRUD routes (upload, list, download, delete)."""

import uuid
from io import BytesIO
from unittest.mock import patch

from tests.conftest import auth_header


def _headers(client):
    headers = auth_header(client)
    headers["X-Namespace"] = "test-corp"
    return headers


def _upload_asset(
    client,
    headers,
    filename="test.jpg",
    content_type="image/jpeg",
    content=b"fake jpeg content",
    campaign_id=None,
):
    """Helper: upload an asset and return the response."""
    data = {"file": (BytesIO(content), filename, content_type)}
    if campaign_id:
        data["campaign_id"] = campaign_id
    return client.post(
        "/api/assets/upload",
        headers=headers,
        data=data,
        content_type="multipart/form-data",
    )


class TestUploadAsset:
    @patch(
        "api.routes.asset_routes.upload_asset", return_value="tenant/shared/id/test.jpg"
    )
    def test_upload_valid_jpeg(self, mock_upload, client, seed_companies_contacts):
        headers = _headers(client)
        resp = _upload_asset(client, headers)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["filename"] == "test.jpg"
        assert data["content_type"] == "image/jpeg"
        assert data["size_bytes"] > 0
        assert data["id"] is not None
        assert data["storage_path"] == "tenant/shared/id/test.jpg"
        mock_upload.assert_called_once()

    @patch(
        "api.routes.asset_routes.upload_asset", return_value="tenant/camp/id/test.pdf"
    )
    def test_upload_with_campaign_id(
        self, mock_upload, client, seed_companies_contacts
    ):
        headers = _headers(client)
        campaign_id = str(uuid.uuid4())
        resp = _upload_asset(
            client,
            headers,
            filename="doc.pdf",
            content_type="application/pdf",
            campaign_id=campaign_id,
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["campaign_id"] == campaign_id

    def test_upload_invalid_content_type(self, client, seed_companies_contacts):
        headers = _headers(client)
        resp = _upload_asset(
            client,
            headers,
            filename="test.exe",
            content_type="application/x-msdownload",
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.get_json()["error"]

    def test_upload_no_file(self, client, seed_companies_contacts):
        headers = _headers(client)
        resp = client.post("/api/assets/upload", headers=headers)
        assert resp.status_code == 400
        assert "No file" in resp.get_json()["error"]

    @patch("api.routes.asset_routes.upload_asset", side_effect=Exception("S3 error"))
    def test_upload_s3_failure(self, mock_upload, client, seed_companies_contacts):
        headers = _headers(client)
        resp = _upload_asset(client, headers)
        assert resp.status_code == 500
        assert "upload failed" in resp.get_json()["error"]


class TestListAssets:
    def test_list_empty(self, client, seed_companies_contacts):
        headers = _headers(client)
        resp = client.get("/api/assets", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["assets"] == []

    @patch("api.routes.asset_routes.upload_asset", return_value="t/shared/id/a.jpg")
    def test_list_with_assets(self, mock_upload, client, seed_companies_contacts):
        headers = _headers(client)
        _upload_asset(client, headers, filename="a.jpg")
        _upload_asset(client, headers, filename="b.png", content_type="image/png")

        resp = client.get("/api/assets", headers=headers)
        assert resp.status_code == 200
        assets = resp.get_json()["assets"]
        assert len(assets) == 2

    @patch("api.routes.asset_routes.upload_asset", return_value="t/camp/id/a.jpg")
    def test_list_filter_by_campaign(
        self, mock_upload, client, seed_companies_contacts
    ):
        headers = _headers(client)
        campaign_id = str(uuid.uuid4())
        _upload_asset(client, headers, filename="camp.jpg", campaign_id=campaign_id)
        _upload_asset(client, headers, filename="no_camp.jpg")

        # Filter by campaign_id
        resp = client.get(f"/api/assets?campaign_id={campaign_id}", headers=headers)
        assert resp.status_code == 200
        assets = resp.get_json()["assets"]
        assert len(assets) == 1
        assert assets[0]["campaign_id"] == campaign_id


class TestDownloadAsset:
    @patch(
        "api.routes.asset_routes.get_download_url",
        return_value="https://s3.example.com/presigned",
    )
    @patch("api.routes.asset_routes.upload_asset", return_value="t/shared/id/dl.jpg")
    def test_download_url(
        self, mock_upload, mock_download, client, seed_companies_contacts
    ):
        headers = _headers(client)
        resp = _upload_asset(client, headers, filename="dl.jpg")
        asset_id = resp.get_json()["id"]

        resp = client.get(f"/api/assets/{asset_id}/download", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["url"] == "https://s3.example.com/presigned"
        mock_download.assert_called_once()

    def test_download_not_found(self, client, seed_companies_contacts):
        headers = _headers(client)
        fake_id = str(uuid.uuid4())
        resp = client.get(f"/api/assets/{fake_id}/download", headers=headers)
        assert resp.status_code == 404


class TestDeleteAsset:
    @patch("api.routes.asset_routes.delete_asset", return_value=True)
    @patch("api.routes.asset_routes.upload_asset", return_value="t/shared/id/del.jpg")
    def test_delete_asset(
        self, mock_upload, mock_delete, client, seed_companies_contacts
    ):
        headers = _headers(client)
        resp = _upload_asset(client, headers, filename="del.jpg")
        asset_id = resp.get_json()["id"]

        resp = client.delete(f"/api/assets/{asset_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        mock_delete.assert_called_once()

        # Verify it's gone from DB
        resp = client.get("/api/assets", headers=headers)
        assert len(resp.get_json()["assets"]) == 0

    def test_delete_not_found(self, client, seed_companies_contacts):
        headers = _headers(client)
        fake_id = str(uuid.uuid4())
        resp = client.delete(f"/api/assets/{fake_id}", headers=headers)
        assert resp.status_code == 404


class TestTenantIsolation:
    @patch("api.routes.asset_routes.upload_asset", return_value="t/shared/id/iso.jpg")
    def test_cannot_access_other_tenant_asset(
        self, mock_upload, client, db, seed_companies_contacts
    ):
        """Assets created by one tenant are invisible to another."""
        headers = _headers(client)
        resp = _upload_asset(client, headers, filename="iso.jpg")
        asset_id = resp.get_json()["id"]

        # Directly modify the asset's tenant_id to simulate another tenant
        from api.models import Asset

        asset = Asset.query.get(asset_id)
        asset.tenant_id = str(uuid.uuid4())
        db.session.commit()

        # Original tenant can no longer see it
        resp = client.get("/api/assets", headers=headers)
        assert len(resp.get_json()["assets"]) == 0

        # Original tenant can't download it
        resp = client.get(f"/api/assets/{asset_id}/download", headers=headers)
        assert resp.status_code == 404

        # Original tenant can't delete it
        resp = client.delete(f"/api/assets/{asset_id}", headers=headers)
        assert resp.status_code == 404
