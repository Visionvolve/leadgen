"""Unit tests for api.services.hunter_enrichment (BL-1212).

These tests never touch the real Hunter.io API — every test injects a
fake ``requests.Session`` so we burn zero live credits. A single
``@pytest.mark.live_api`` integration check is provided for manual
staging validation; it is skipped by default.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pytest
import requests

from api.services.hunter_enrichment import (
    DEFAULT_REQUESTS_PER_SECOND,
    HunterAuthError,
    HunterEnrichmentService,
    HunterError,
    HunterRateLimitError,
    HunterServerError,
    _TokenBucket,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stand-in for ``requests.Response`` with the minimum surface we use."""

    def __init__(
        self,
        status_code: int = 200,
        json_body: dict[str, Any] | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
        raise_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}
        self.text = text or (json.dumps(json_body) if json_body else "")
        self.headers = headers or {}
        self._raise_json = raise_json

    def json(self) -> Any:
        if self._raise_json:
            raise ValueError("not json")
        return self._json_body


class _FakeSession:
    """Replays a queued list of responses (or callables) per .get()."""

    def __init__(self, responses: Iterable[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, params: dict[str, Any], timeout: float) -> _FakeResponse:
        self.calls.append({"url": url, "params": dict(params), "timeout": timeout})
        if not self._responses:
            raise AssertionError("FakeSession exhausted")
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        if callable(nxt):
            return nxt()
        return nxt


def _make_service(
    responses: Iterable[Any],
    *,
    api_key: str = "test-key",
    rps: float = 1000.0,  # effectively no client-side throttling
    max_retries_429: int = 3,
    max_retries_5xx: int = 2,
) -> tuple[HunterEnrichmentService, _FakeSession, list[float]]:
    """Build a service wired to fakes and a sleep-spy."""
    sleeps: list[float] = []

    def fake_sleep(delay: float) -> None:
        sleeps.append(float(delay))

    session = _FakeSession(responses)
    svc = HunterEnrichmentService(
        api_key=api_key,
        session=session,
        sleep=fake_sleep,
        requests_per_second=rps,
        max_retries_429=max_retries_429,
        max_retries_5xx=max_retries_5xx,
        retry_base_delay=0.5,
    )
    return svc, session, sleeps


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_find_email_happy_path() -> None:
    body = {
        "data": {
            "email": "patrick@stripe.com",
            "score": 95,
            "position": "CEO",
            "sources": [{"uri": "x"}, {"uri": "y"}],
            "verification": {"status": "valid"},
        }
    }
    svc, session, _ = _make_service([_FakeResponse(200, body)])

    result = svc.find_email("stripe.com", "Patrick", "Collison")

    assert result.email == "patrick@stripe.com"
    assert result.score == 95
    assert result.position == "CEO"
    assert result.sources_count == 2
    assert result.verification_status == "valid"
    assert svc.get_credits_used() == {
        "email-finder": 1,
        "domain-search": 0,
        "verify": 0,
        "total": 1,
    }

    # api_key MUST be in querystring (Hunter convention).
    call = session.calls[0]
    assert call["url"].endswith("/v2/email-finder")
    assert call["params"]["api_key"] == "test-key"
    assert call["params"]["domain"] == "stripe.com"


def test_domain_search_parses_email_list() -> None:
    body = {
        "data": {
            "organization": "Stripe Inc.",
            "emails": [
                {
                    "value": "patrick@stripe.com",
                    "first_name": "Patrick",
                    "last_name": "Collison",
                    "position": "CEO",
                    "confidence": 92,
                    "verification": {"status": "valid"},
                },
                {
                    "value": "john@stripe.com",
                    "first_name": "John",
                    "last_name": "Collison",
                    "position": "President",
                    "confidence": 88,
                    "verification": None,
                },
                # Malformed entries should be filtered out.
                {"value": None, "first_name": "X"},
                "not-a-dict",
            ],
        },
        "meta": {"results": 3},
    }
    svc, _, _ = _make_service([_FakeResponse(200, body)])

    result = svc.domain_search("stripe.com", limit=50)

    assert result.domain == "stripe.com"
    assert result.organization == "Stripe Inc."
    assert len(result.emails) == 2
    assert result.emails[0].value == "patrick@stripe.com"
    assert result.emails[0].verification_status == "valid"
    assert result.emails[1].verification_status is None
    assert result.total == 3
    assert svc.get_credits_used()["domain-search"] == 1


def test_verify_email_happy_path() -> None:
    body = {
        "data": {
            "status": "valid",
            "score": 90,
            "regexp": True,
            "gibberish": False,
            "disposable": False,
            "webmail": False,
            "mx_records": True,
            "smtp_server": True,
            "smtp_check": True,
            "accept_all": False,
            "block": False,
        }
    }
    svc, _, _ = _make_service([_FakeResponse(200, body)])

    result = svc.verify_email("Patrick@stripe.com")

    assert result.email == "Patrick@stripe.com"
    assert result.status == "valid"
    assert result.score == 90
    assert result.accept_all is False
    assert svc.get_credits_used()["verify"] == 1


def test_empty_domain_search_result() -> None:
    body = {"data": {"organization": None, "emails": []}, "meta": {"results": 0}}
    svc, _, _ = _make_service([_FakeResponse(200, body)])

    result = svc.domain_search("noemails.example")
    assert result.emails == []
    assert result.total == 0
    # Empty result still costs a credit on Hunter.
    assert svc.get_credits_used()["domain-search"] == 1


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_api_key_raises_auth_error_lazily() -> None:
    # Construction must not raise; the first call does.
    svc = HunterEnrichmentService(
        api_key="", session=_FakeSession([]), sleep=lambda _d: None
    )
    with pytest.raises(HunterAuthError):
        svc.find_email("stripe.com", "P", "C")


def test_invalid_api_key_returns_401() -> None:
    svc, _, _ = _make_service(
        [_FakeResponse(401, {}, text='{"errors":[{"id":"invalid_key"}]}')]
    )
    with pytest.raises(HunterAuthError) as exc_info:
        svc.find_email("stripe.com", "Patrick", "Collison")
    assert "401" in str(exc_info.value)
    # No credit charged on auth failure.
    assert svc.get_credits_used()["total"] == 0


def test_429_retries_then_succeeds() -> None:
    body = {"data": {"email": "p@stripe.com", "score": 80}}
    svc, session, sleeps = _make_service(
        [
            _FakeResponse(429, {}, headers={"Retry-After": "1"}),
            _FakeResponse(429, {}, headers={"Retry-After": "1"}),
            _FakeResponse(200, body),
        ],
        max_retries_429=3,
    )

    result = svc.find_email("stripe.com", "Patrick", "Collison")

    assert result.email == "p@stripe.com"
    assert len(session.calls) == 3
    # Retry-After=1 was honoured for both 429 retries.
    assert sleeps.count(1.0) >= 2
    assert svc.get_credits_used()["total"] == 1


def test_429_exhausts_retries_raises() -> None:
    svc, session, _ = _make_service(
        [
            _FakeResponse(429, {}),
            _FakeResponse(429, {}),
            _FakeResponse(429, {}),
            _FakeResponse(429, {}),
        ],
        max_retries_429=3,
    )
    with pytest.raises(HunterRateLimitError):
        svc.find_email("stripe.com", "Patrick", "Collison")
    # 3 retries on top of the original attempt = 4 calls.
    assert len(session.calls) == 4
    assert svc.get_credits_used()["total"] == 0


def test_5xx_retries_then_succeeds() -> None:
    body = {"data": {"email": "p@stripe.com", "score": 70}}
    svc, session, sleeps = _make_service(
        [
            _FakeResponse(503, {}),
            _FakeResponse(502, {}),
            _FakeResponse(200, body),
        ],
        max_retries_5xx=2,
    )

    result = svc.find_email("stripe.com", "Patrick", "Collison")

    assert result.email == "p@stripe.com"
    assert len(session.calls) == 3
    # Exponential backoff: 0.5, 1.0 — both should have been slept.
    assert any(abs(s - 0.5) < 1e-6 for s in sleeps)
    assert any(abs(s - 1.0) < 1e-6 for s in sleeps)


def test_5xx_exhausts_retries_raises() -> None:
    svc, _, _ = _make_service(
        [_FakeResponse(500, {}), _FakeResponse(500, {}), _FakeResponse(500, {})],
        max_retries_5xx=2,
    )
    with pytest.raises(HunterServerError):
        svc.find_email("stripe.com", "Patrick", "Collison")


def test_network_error_retries_then_raises() -> None:
    svc, _, _ = _make_service(
        [
            requests.ConnectionError("boom1"),
            requests.ConnectionError("boom2"),
            requests.ConnectionError("boom3"),
        ],
        max_retries_5xx=2,
    )
    with pytest.raises(HunterServerError):
        svc.find_email("stripe.com", "Patrick", "Collison")


def test_malformed_json_on_200_raises_hunter_error() -> None:
    svc, _, _ = _make_service(
        [_FakeResponse(200, {}, raise_json=True, text="not json")]
    )
    with pytest.raises(HunterError):
        svc.find_email("stripe.com", "Patrick", "Collison")
    # No credit charged when we couldn't parse the response.
    assert svc.get_credits_used()["total"] == 0


def test_404_fails_fast_no_retry() -> None:
    svc, session, _ = _make_service([_FakeResponse(404, {}, text="not found")])
    with pytest.raises(HunterError) as exc_info:
        svc.find_email("stripe.com", "Patrick", "Collison")
    assert "404" in str(exc_info.value)
    # Only one call — no retry on 4xx other than 429.
    assert len(session.calls) == 1


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def test_find_email_validates_required_args() -> None:
    svc, _, _ = _make_service([])
    with pytest.raises(ValueError):
        svc.find_email("", "Patrick", "Collison")
    with pytest.raises(ValueError):
        svc.find_email("stripe.com", "", "Collison")
    with pytest.raises(ValueError):
        svc.find_email("stripe.com", "Patrick", "")


def test_domain_search_validates_limit() -> None:
    svc, _, _ = _make_service([])
    with pytest.raises(ValueError):
        svc.domain_search("stripe.com", limit=0)
    with pytest.raises(ValueError):
        svc.domain_search("stripe.com", limit=101)


def test_verify_email_rejects_invalid_shape() -> None:
    svc, _, _ = _make_service([])
    with pytest.raises(ValueError):
        svc.verify_email("not-an-email")


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


def test_token_bucket_throttles_back_to_back_calls() -> None:
    sleeps: list[float] = []

    def fake_sleep(d: float) -> None:
        sleeps.append(float(d))

    bucket = _TokenBucket(rate_per_second=5.0)  # 0.2s min interval
    bucket.acquire(sleep=fake_sleep)  # first call — no wait
    bucket.acquire(sleep=fake_sleep)  # second call — must wait ~0.2s

    assert sleeps, "second acquire should have triggered a sleep"
    assert sleeps[0] > 0.0
    assert sleeps[0] <= 0.21  # ~0.2 with a tiny margin


def test_service_default_rps_is_5() -> None:
    # Guard the documented default — we throttle to 5 even though Hunter
    # allows 10, to leave headroom.
    assert DEFAULT_REQUESTS_PER_SECOND == 5.0


def test_throttling_invokes_sleep_between_requests() -> None:
    body = {"data": {"email": "p@x.com", "score": 50}}
    svc, _, sleeps = _make_service(
        [_FakeResponse(200, body), _FakeResponse(200, body)],
        rps=10.0,  # 0.1s spacing
    )
    svc.find_email("x.com", "A", "B")
    svc.find_email("x.com", "C", "D")
    # At least one sleep call should have happened for the second request.
    assert any(s > 0 for s in sleeps)


# ---------------------------------------------------------------------------
# Live-API smoke test — manual only.
# ---------------------------------------------------------------------------


@pytest.mark.live_api
def test_live_account_endpoint_returns_200() -> None:
    """Hit Hunter's /v2/account using the real env-supplied API key.

    Skipped by default. Run manually during staging validation with:

        pytest -m live_api tests/unit/test_hunter_enrichment.py
    """
    import os as _os

    key = _os.environ.get("HUNTER_API_KEY")
    if not key:
        pytest.skip("HUNTER_API_KEY not set")
    resp = requests.get(
        "https://api.hunter.io/v2/account",
        params={"api_key": key},
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
