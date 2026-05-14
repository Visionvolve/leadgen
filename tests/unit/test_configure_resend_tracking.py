"""Unit tests for ``scripts/configure_resend_tracking.py``.

The script speaks to Resend's HTTP API; tests stub the network layer
(``_http``) and assert that:

1. Domains already configured the right way are *not* re-patched (Resend
   caps ``tracking_subdomain`` mutations to once per 24h — we must not
   waste the quota).
2. Unconfigured domains get a PATCH with
   ``open_tracking/click_tracking/tracking_subdomain`` all set.
3. The resulting summary surfaces the tracking CNAME each domain needs,
   so an operator can paste it into the DNS provider.
4. Unverified domains are skipped (patching them is a no-op on Resend's
   side but would clutter the summary).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "configure_resend_tracking.py"
)
_spec = importlib.util.spec_from_file_location(
    "configure_resend_tracking", _SCRIPT_PATH
)
configure = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(configure)  # type: ignore[union-attr]


def _domain(
    *,
    name: str,
    domain_id: str,
    open_tracking: bool = False,
    click_tracking: bool = False,
    tracking_subdomain: str | None = None,
    status: str = "verified",
    cname_status: str = "pending",
) -> dict[str, Any]:
    records = []
    if tracking_subdomain:
        records.append(
            {
                "record": "Tracking",
                "type": "CNAME",
                "name": tracking_subdomain,
                "value": "links1.resend-dns.com",
                "status": cname_status,
            }
        )
    return {
        "id": domain_id,
        "name": name,
        "status": status,
        "open_tracking": open_tracking,
        "click_tracking": click_tracking,
        "tracking_subdomain": tracking_subdomain,
        "records": records,
    }


class FakeResend:
    """Minimal stand-in for the Resend HTTP API used by the script."""

    def __init__(self, domains: list[dict[str, Any]]):
        self.domains = {d["id"]: dict(d) for d in domains}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(
        self,
        method: str,
        path: str,
        api_key: str,  # noqa: ARG002 — accepted but unused
        body: dict | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, body))
        if method == "GET" and path == "/domains":
            return {"data": list(self.domains.values())}
        if method == "GET" and path.startswith("/domains/"):
            return self.domains[path.rsplit("/", 1)[1]]
        if method == "PATCH" and path.startswith("/domains/"):
            domain_id = path.rsplit("/", 1)[1]
            d = self.domains[domain_id]
            assert body is not None
            d["open_tracking"] = body["open_tracking"]
            d["click_tracking"] = body["click_tracking"]
            d["tracking_subdomain"] = body["tracking_subdomain"]
            d["records"] = [
                {
                    "record": "Tracking",
                    "type": "CNAME",
                    "name": body["tracking_subdomain"],
                    "value": "links1.resend-dns.com",
                    "status": "pending",
                }
            ]
            return {"id": domain_id, "object": "domain"}
        raise AssertionError(f"unexpected {method} {path}")


@pytest.fixture
def patched_http(monkeypatch):
    def _install(domains: list[dict[str, Any]]) -> FakeResend:
        fake = FakeResend(domains)
        monkeypatch.setattr(configure, "_http", fake)
        return fake

    return _install


def test_unconfigured_domain_gets_patched(patched_http):
    """A verified domain with no tracking gets PATCHed and shows up in
    ``cnames_required`` so the operator knows what DNS to add."""
    fake = patched_http([_domain(name="visionvolve.com", domain_id="dom-1")])

    result = configure.configure_all("fake-key", subdomain="track")

    patches = [c for c in fake.calls if c[0] == "PATCH"]
    assert patches == [
        (
            "PATCH",
            "/domains/dom-1",
            {
                "open_tracking": True,
                "click_tracking": True,
                "tracking_subdomain": "track",
            },
        )
    ]
    assert result["domains"][0]["changed"] is True
    assert result["domains"][0]["open_tracking"] is True
    assert result["domains"][0]["click_tracking"] is True
    assert result["domains"][0]["tracking_subdomain"] == "track"
    # CNAME surfaced for DNS handoff
    assert result["cnames_required"] == [
        "track.visionvolve.com  CNAME  links1.resend-dns.com"
    ]


def test_already_configured_domain_is_not_repatched(patched_http):
    """Resend limits tracking_subdomain changes to once per 24h — the
    script must be idempotent and not re-PATCH a correctly-configured
    domain on every run."""
    fake = patched_http(
        [
            _domain(
                name="visionvolve.com",
                domain_id="dom-1",
                open_tracking=True,
                click_tracking=True,
                tracking_subdomain="track",
                cname_status="pending",
            )
        ]
    )

    result = configure.configure_all("fake-key", subdomain="track")

    assert [c for c in fake.calls if c[0] == "PATCH"] == []
    assert result["domains"][0]["changed"] is False
    # CNAME still required until DNS verifies — surface it on every run.
    assert result["cnames_required"] == [
        "track.visionvolve.com  CNAME  links1.resend-dns.com"
    ]


def test_verified_cname_not_listed_in_cnames_required(patched_http):
    """Once Resend reports the tracking CNAME as ``verified``, the
    operator doesn't need to do anything — drop it from the required
    list."""
    patched_http(
        [
            _domain(
                name="visionvolve.com",
                domain_id="dom-1",
                open_tracking=True,
                click_tracking=True,
                tracking_subdomain="track",
                cname_status="verified",
            )
        ]
    )

    result = configure.configure_all("fake-key", subdomain="track")

    assert result["cnames_required"] == []


def test_unverified_domain_is_skipped(patched_http):
    """If a sending domain hasn't completed DKIM/SPF verification we
    can't usefully enable tracking on it — skip it explicitly so the
    operator notices."""
    fake = patched_http(
        [_domain(name="example.com", domain_id="dom-1", status="pending")]
    )

    result = configure.configure_all("fake-key", subdomain="track")

    assert [c for c in fake.calls if c[0] == "PATCH"] == []
    assert result["domains"][0]["skipped"] == "domain_not_verified"
    assert result["domains"][0]["changed"] is False
    assert result["cnames_required"] == []


def test_multiple_domains_all_processed(patched_http):
    """The script handles every domain on the account in a single run."""
    fake = patched_http(
        [
            _domain(name="visionvolve.com", domain_id="dom-1"),
            _domain(
                name="aitransformers.eu",
                domain_id="dom-2",
                open_tracking=True,
                click_tracking=True,
                tracking_subdomain="track",
            ),
            _domain(name="loserscirque.cz", domain_id="dom-3"),
        ]
    )

    result = configure.configure_all("fake-key", subdomain="track")

    # dom-1 and dom-3 patched; dom-2 already configured, untouched
    patched_ids = sorted(c[1].rsplit("/", 1)[1] for c in fake.calls if c[0] == "PATCH")
    assert patched_ids == ["dom-1", "dom-3"]

    changed_flags = {d["name"]: d["changed"] for d in result["domains"]}
    assert changed_flags == {
        "visionvolve.com": True,
        "aitransformers.eu": False,
        "loserscirque.cz": True,
    }
    assert sorted(result["cnames_required"]) == sorted(
        [
            "track.visionvolve.com  CNAME  links1.resend-dns.com",
            "track.aitransformers.eu  CNAME  links1.resend-dns.com",
            "track.loserscirque.cz  CNAME  links1.resend-dns.com",
        ]
    )
