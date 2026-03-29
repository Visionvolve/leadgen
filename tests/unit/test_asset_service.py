"""Tests for asset service validation."""

from api.services.asset_service import validate_upload, MAX_FILE_SIZE


class TestAssetValidation:
    def test_valid_jpeg(self):
        assert validate_upload("image/jpeg", 1024) is None

    def test_valid_png(self):
        assert validate_upload("image/png", 5000) is None

    def test_valid_pdf(self):
        assert validate_upload("application/pdf", 1024 * 1024) is None

    def test_invalid_content_type(self):
        err = validate_upload("text/html", 1024)
        assert err is not None
        assert "not allowed" in err

    def test_file_too_large(self):
        err = validate_upload("image/jpeg", MAX_FILE_SIZE + 1)
        assert err is not None
        assert "too large" in err

    def test_exactly_max_size(self):
        assert validate_upload("image/jpeg", MAX_FILE_SIZE) is None
