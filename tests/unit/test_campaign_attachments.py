"""Unit tests for campaign PDF attachment upload/list/delete and test email sending.

Covers:
- POST /api/campaigns/<id>/attachments (upload)
- GET /api/campaigns/<id>/attachments (list)
- DELETE /api/campaigns/<id>/attachments/<attachment_id> (delete)
- POST /api/campaigns/<id>/send-test (test email)
"""

import io
import json
from unittest.mock import MagicMock, patch

from tests.conftest import auth_header


def _create_campaign(db, seed, **overrides):
    """Create a campaign for testing."""
    from api.models import Campaign

    defaults = {
        "tenant_id": seed["tenant"].id,
        "name": "Attachment Test Campaign",
        "status": "draft",
    }
    defaults.update(overrides)
    campaign = Campaign(**defaults)
    db.session.add(campaign)
    db.session.commit()
    return campaign


def _create_asset(db, seed, campaign_id, filename="test.pdf"):
    """Create an asset record linked to a campaign."""
    from api.models import Asset

    import uuid

    asset = Asset(
        id=str(uuid.uuid4()),
        tenant_id=seed["tenant"].id,
        campaign_id=campaign_id,
        filename=filename,
        content_type="application/pdf",
        storage_path=f"{seed['tenant'].id}/{campaign_id}/fake/{filename}",
        size_bytes=1024,
        metadata_={},
    )
    db.session.add(asset)
    db.session.commit()
    return asset


class TestUploadAttachment:
    """Tests for POST /api/campaigns/<id>/attachments."""

    @patch("api.routes.campaign_routes.upload_asset")
    def test_upload_pdf_success(self, mock_upload, client, db, seed_companies_contacts):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)

        mock_upload.return_value = f"{seed['tenant'].id}/{campaign.id}/fake/doc.pdf"

        data = {
            "file": (io.BytesIO(b"%PDF-1.4 test content"), "doc.pdf", "application/pdf")
        }
        resp = client.post(
            f"/api/campaigns/{campaign.id}/attachments",
            headers=headers,
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 201
        body = resp.get_json()
        assert body["filename"] == "doc.pdf"
        assert body["content_type"] == "application/pdf"
        assert body["campaign_id"] == str(campaign.id)
        mock_upload.assert_called_once()

    def test_upload_no_file(self, client, db, seed_companies_contacts):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)

        resp = client.post(
            f"/api/campaigns/{campaign.id}/attachments",
            headers=headers,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "no file" in resp.get_json()["error"].lower()

    @patch("api.routes.campaign_routes.validate_upload")
    def test_upload_invalid_type_rejected(
        self, mock_validate, client, db, seed_companies_contacts
    ):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)

        mock_validate.return_value = "File type text/plain not allowed"

        data = {"file": (io.BytesIO(b"not a pdf"), "readme.txt", "text/plain")}
        resp = client.post(
            f"/api/campaigns/{campaign.id}/attachments",
            headers=headers,
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.get_json()["error"]

    def test_upload_campaign_not_found(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        data = {"file": (io.BytesIO(b"%PDF-1.4"), "doc.pdf", "application/pdf")}
        resp = client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000099/attachments",
            headers=headers,
            data=data,
            content_type="multipart/form-data",
        )
        assert resp.status_code == 404

    def test_upload_requires_auth(self, client, db):
        resp = client.post("/api/campaigns/some-id/attachments")
        assert resp.status_code == 401


class TestListAttachments:
    """Tests for GET /api/campaigns/<id>/attachments."""

    @patch("api.routes.campaign_routes.get_download_url")
    def test_list_returns_campaign_attachments(
        self, mock_url, client, db, seed_companies_contacts
    ):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)

        _create_asset(db, seed, str(campaign.id), "doc1.pdf")
        _create_asset(db, seed, str(campaign.id), "doc2.pdf")

        mock_url.return_value = "https://s3.example.com/presigned"

        resp = client.get(
            f"/api/campaigns/{campaign.id}/attachments",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["attachments"]) == 2
        filenames = {a["filename"] for a in data["attachments"]}
        assert filenames == {"doc1.pdf", "doc2.pdf"}
        # Each should have a download_url
        for a in data["attachments"]:
            assert a["download_url"] == "https://s3.example.com/presigned"

    def test_list_empty_campaign(self, client, db, seed_companies_contacts):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)

        resp = client.get(
            f"/api/campaigns/{campaign.id}/attachments",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["attachments"] == []

    def test_list_campaign_not_found(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.get(
            "/api/campaigns/00000000-0000-0000-0000-000000000099/attachments",
            headers=headers,
        )
        assert resp.status_code == 404


class TestDeleteAttachment:
    """Tests for DELETE /api/campaigns/<id>/attachments/<attachment_id>."""

    @patch("api.routes.campaign_routes.delete_asset")
    def test_delete_success(self, mock_delete, client, db, seed_companies_contacts):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)
        asset = _create_asset(db, seed, str(campaign.id))

        mock_delete.return_value = True

        resp = client.delete(
            f"/api/campaigns/{campaign.id}/attachments/{asset.id}",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        mock_delete.assert_called_once()

        # Verify DB record is gone
        from api.models import Asset

        assert Asset.query.get(asset.id) is None

    def test_delete_not_found(self, client, db, seed_companies_contacts):
        seed = seed_companies_contacts
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"
        campaign = _create_campaign(db, seed)

        resp = client.delete(
            f"/api/campaigns/{campaign.id}/attachments/00000000-0000-0000-0000-000000000099",
            headers=headers,
        )
        assert resp.status_code == 404


class TestSendTestEmail:
    """Tests for POST /api/campaigns/<id>/send-test."""

    def _setup_campaign_with_message(self, db, seed):
        """Create a campaign with sender_config and a message."""
        from api.models import Campaign, CampaignContact, Message

        tenant_id = seed["tenant"].id
        owner = seed["owners"][0]

        campaign = Campaign(
            tenant_id=tenant_id,
            name="Test Email Campaign",
            status="review",
            sender_config=json.dumps(
                {
                    "from_email": "outreach@test.com",
                    "from_name": "Test Outreach",
                    "reply_to": "replies@test.com",
                }
            ),
        )
        db.session.add(campaign)
        db.session.flush()

        contact = seed["contacts"][0]
        cc = CampaignContact(
            campaign_id=campaign.id,
            contact_id=contact.id,
            tenant_id=tenant_id,
            status="generated",
        )
        db.session.add(cc)
        db.session.flush()

        message = Message(
            tenant_id=tenant_id,
            contact_id=contact.id,
            owner_id=owner.id,
            channel="email",
            sequence_step=1,
            variant="a",
            subject="Hello from campaign",
            body="Dear contact, this is a test.",
            status="approved",
            campaign_contact_id=cc.id,
        )
        db.session.add(message)
        db.session.commit()
        return campaign, message, contact

    def _setup_tenant_with_resend_key(self, db, seed):
        from api.models import Tenant

        tenant = db.session.get(Tenant, seed["tenant"].id)
        tenant.settings = json.dumps({"resend_api_key": "re_test_key_123"})
        db.session.commit()

    @patch("resend.Emails.send")
    def test_send_test_email_success(
        self, mock_resend_send, client, db, seed_companies_contacts
    ):
        seed = seed_companies_contacts
        self._setup_tenant_with_resend_key(db, seed)
        campaign, message, contact = self._setup_campaign_with_message(db, seed)

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        mock_result = MagicMock()
        mock_result.id = "resend_test_001"
        mock_resend_send.return_value = mock_result

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-test",
            headers=headers,
            json={"message_id": str(message.id)},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["sent_to"] == "admin@test.com"
        assert data["resend_id"] == "resend_test_001"

        # Verify the email was sent with [TEST] prefix
        call_args = mock_resend_send.call_args
        params = call_args[0][0]
        assert params["subject"].startswith("[TEST] ")
        assert "test email" in params["html"].lower()

    def test_send_test_missing_message_id(self, client, db, seed_companies_contacts):
        seed = seed_companies_contacts
        self._setup_tenant_with_resend_key(db, seed)
        campaign, _, _ = self._setup_campaign_with_message(db, seed)

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-test",
            headers=headers,
            json={},
        )
        assert resp.status_code == 400
        assert "message_id" in resp.get_json()["error"]

    def test_send_test_missing_sender_config(self, client, db, seed_companies_contacts):
        from api.models import Campaign, Message

        seed = seed_companies_contacts
        self._setup_tenant_with_resend_key(db, seed)
        tenant_id = seed["tenant"].id

        campaign = Campaign(
            tenant_id=tenant_id,
            name="No Sender",
            status="draft",
            sender_config=json.dumps({}),
        )
        db.session.add(campaign)
        db.session.flush()

        # Create a minimal message
        message = Message(
            tenant_id=tenant_id,
            contact_id=seed["contacts"][0].id,
            owner_id=seed["owners"][0].id,
            channel="email",
            sequence_step=1,
            variant="a",
            subject="Test",
            body="Body",
            status="approved",
        )
        db.session.add(message)
        db.session.commit()

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-test",
            headers=headers,
            json={"message_id": str(message.id)},
        )
        assert resp.status_code == 400
        assert "from_email" in resp.get_json()["error"]

    def test_send_test_campaign_not_found(self, client, db, seed_companies_contacts):
        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            "/api/campaigns/00000000-0000-0000-0000-000000000099/send-test",
            headers=headers,
            json={"message_id": "anything"},
        )
        assert resp.status_code == 404

    def test_send_test_requires_auth(self, client, db):
        resp = client.post("/api/campaigns/some-id/send-test")
        assert resp.status_code == 401

    @patch("api.routes.campaign_routes.download_asset_bytes")
    @patch("resend.Emails.send")
    def test_send_test_includes_pdf_attachments(
        self, mock_resend_send, mock_download, client, db, seed_companies_contacts
    ):
        seed = seed_companies_contacts
        self._setup_tenant_with_resend_key(db, seed)
        campaign, message, _ = self._setup_campaign_with_message(db, seed)

        # Add a PDF attachment to the campaign
        _create_asset(db, seed, str(campaign.id), "brochure.pdf")

        mock_download.return_value = b"%PDF-1.4 fake pdf content"

        mock_result = MagicMock()
        mock_result.id = "resend_test_002"
        mock_resend_send.return_value = mock_result

        headers = auth_header(client)
        headers["X-Namespace"] = "test-corp"

        resp = client.post(
            f"/api/campaigns/{campaign.id}/send-test",
            headers=headers,
            json={"message_id": str(message.id)},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["attachments_included"] == 1

        # Verify the Resend call included the attachment
        call_args = mock_resend_send.call_args
        params = call_args[0][0]
        assert len(params["attachments"]) == 1
        assert params["attachments"][0]["filename"] == "brochure.pdf"
        assert params["attachments"][0]["type"] == "application/pdf"
