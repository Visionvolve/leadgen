"""Tests for GET /api/extension/download (BL-1209).

Covers:
    AC-3: unauthenticated → 401
    AC-4: non-super_admin requesting env=staging → 403
    AC-5: zip contains the required extension files
    Plus: invalid env, missing build directory, super_admin staging download,
          authenticated regular user prod download, and Content-Disposition format.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from tests.conftest import auth_header

# Files the CI smoke test expects to find in the produced zip (AC-5).
EXPECTED_FILES = {
    "manifest.json",
    "service-worker.js",
    "sales-navigator.js",
    "activity-monitor.js",
    "linkedin-validator.js",
    "sidepanel.html",
}


@pytest.fixture
def fake_extension_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Materialise a fake extension/dist tree under tmp_path and point the
    endpoint at it via the EXTENSION_DIST_DIR override.

    Layout:
        tmp/
          prod/
            manifest.json (with version=9.9.9)
            service-worker.js
            sales-navigator.js
            activity-monitor.js
            linkedin-validator.js
            sidepanel.html
            icons/prod/16.png   (extra file to verify recursive packing)
          staging/
            manifest.json (with version=9.9.9-staging)
            ... (same as prod)
    """
    for env, version in (("prod", "9.9.9"), ("staging", "9.9.9-staging")):
        env_dir = tmp_path / env
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / "manifest.json").write_text(
            json.dumps({"manifest_version": 3, "version": version, "name": "Test"}),
            encoding="utf-8",
        )
        (env_dir / "service-worker.js").write_text("// sw", encoding="utf-8")
        (env_dir / "sales-navigator.js").write_text("// sn", encoding="utf-8")
        (env_dir / "activity-monitor.js").write_text("// am", encoding="utf-8")
        (env_dir / "linkedin-validator.js").write_text("// lv", encoding="utf-8")
        (env_dir / "sidepanel.html").write_text("<html></html>", encoding="utf-8")
        icons_dir = env_dir / "icons" / env
        icons_dir.mkdir(parents=True, exist_ok=True)
        (icons_dir / "16.png").write_bytes(b"\x89PNG\r\n")

    monkeypatch.setenv("EXTENSION_DIST_DIR", str(tmp_path))
    return tmp_path


class TestDownloadAuth:
    """Authentication and authorization gates."""

    def test_requires_auth(self, client, db, fake_extension_dist):
        """AC-3: unauthenticated request → 401."""
        resp = client.get("/api/extension/download")
        assert resp.status_code == 401

    def test_super_admin_can_download_prod(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """Super admin can download prod build."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 200

    def test_regular_user_can_download_prod(
        self, client, seed_user_with_role, fake_extension_dist
    ):
        """Regular (non-super_admin) user can download the prod build."""
        headers = auth_header(client, email="user@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 200

    def test_regular_user_cannot_download_staging(
        self, client, seed_user_with_role, fake_extension_dist
    ):
        """AC-4: regular user requesting env=staging → 403."""
        headers = auth_header(client, email="user@test.com")
        resp = client.get("/api/extension/download?env=staging", headers=headers)
        assert resp.status_code == 403

    def test_super_admin_can_download_staging(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """Super admin can download the staging build."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=staging", headers=headers)
        assert resp.status_code == 200


class TestDownloadValidation:
    """Input validation."""

    def test_invalid_env_returns_400(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """Unknown env value → 400."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=dev", headers=headers)
        assert resp.status_code == 400

    def test_missing_build_returns_404(
        self, client, seed_super_admin, tmp_path, monkeypatch
    ):
        """If the dist dir is not present → 404."""
        # Point override at an empty directory (no prod/ subdir).
        monkeypatch.setenv("EXTENSION_DIST_DIR", str(tmp_path / "nope"))
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 404

    def test_default_env_is_prod(
        self, client, seed_user_with_role, fake_extension_dist
    ):
        """Omitting the env query param defaults to prod."""
        headers = auth_header(client, email="user@test.com")
        resp = client.get("/api/extension/download", headers=headers)
        assert resp.status_code == 200
        # Filename should reflect the default env.
        cd = resp.headers.get("Content-Disposition", "")
        assert "visionvolve-leads-prod-v9.9.9.zip" in cd


class TestDownloadPayload:
    """Response payload correctness (AC-1, AC-5)."""

    def test_response_headers(self, client, seed_super_admin, fake_extension_dist):
        """AC-1: zip mimetype + Content-Disposition with versioned filename."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 200
        assert resp.mimetype == "application/zip"
        cd = resp.headers.get("Content-Disposition", "")
        assert 'filename="visionvolve-leads-prod-v9.9.9.zip"' in cd

    def test_zip_contains_all_required_files(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """AC-5: smoke test that the zip contains all required files."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 200

        with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
            names = set(zf.namelist())

        missing = EXPECTED_FILES - names
        assert not missing, f"zip is missing required files: {missing}"

    def test_zip_preserves_nested_paths(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """Nested icon files are included with their relative paths intact."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 200

        with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
            names = set(zf.namelist())

        assert "icons/prod/16.png" in names

    def test_zip_manifest_has_correct_version(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """Manifest inside the zip carries the build's version string."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=prod", headers=headers)
        assert resp.status_code == 200

        with zipfile.ZipFile(io.BytesIO(resp.data), "r") as zf:
            manifest_bytes = zf.read("manifest.json")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        assert manifest["version"] == "9.9.9"

    def test_staging_filename_includes_staging_env(
        self, client, seed_super_admin, fake_extension_dist
    ):
        """Staging build uses staging in filename + reflects staging version."""
        headers = auth_header(client, email="admin@test.com")
        resp = client.get("/api/extension/download?env=staging", headers=headers)
        assert resp.status_code == 200
        cd = resp.headers.get("Content-Disposition", "")
        assert 'filename="visionvolve-leads-staging-v9.9.9-staging.zip"' in cd
