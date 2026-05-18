"""Hunter.io contact-enrichment service (BL-1212).

Wraps the public Hunter.io v2 endpoints we use for email discovery:

* ``GET /v2/email-finder``    — 1 search credit per call (returns 1 email + confidence)
* ``GET /v2/domain-search``   — 1 search credit per call (returns up to 100 emails)
* ``GET /v2/email-verifier``  — 1 verification credit per call

The service is intentionally small. It owns:

* one ``requests.Session`` per process
* a token-bucket rate limiter (5 req/s by default — Hunter allows 10)
* exponential-backoff retry for 429 + 5xx (other errors fail fast)
* a per-instance credit counter exposed via :py:meth:`get_credits_used`

It does NOT own:

* database persistence (the CLI runner does that)
* contact-selection logic (the CLI runner does that)
* cost accounting in USD (we count credits, not dollars; the upstream
  plan reconciles).

Usage
-----

Reads ``HUNTER_API_KEY`` from the environment by default — set on the
container in ``deploy/docker-compose.api.yml`` (production) and via
``staging/docker-compose.leadgen.yml`` (staging). For local development,
``scripts/init-env.sh`` pulls it into ``.env.dev`` from the
``visionvolve-prod`` 1Password vault.

>>> from api.services.hunter_enrichment import HunterEnrichmentService
>>> svc = HunterEnrichmentService()
>>> result = svc.find_email("stripe.com", "Patrick", "Collison")
>>> result.email, result.score
('patrick@stripe.com', 95)
>>> svc.get_credits_used()
{'email-finder': 1, 'domain-search': 0, 'verify': 0, 'total': 1}

The companion CLI lives at ``scripts/hunter_enrichment_run.py``.

Pattern note
------------

Modelled on :mod:`api.services.anthropic_client` — same retry semantics,
same ``requests``-based shape, no new heavy dependencies. The module
is import-light so unit tests can mock ``requests.get`` without spinning
up a Flask app.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


HUNTER_BASE_URL = "https://api.hunter.io"
DEFAULT_TIMEOUT_SECONDS = 30
# Hunter's documented public limit is 10 req/s. We throttle to 5 to leave
# headroom and to be polite to a shared account.
DEFAULT_REQUESTS_PER_SECOND = 5.0
DEFAULT_MAX_RETRIES_429 = 3
DEFAULT_MAX_RETRIES_5XX = 2
RETRYABLE_5XX = frozenset({500, 502, 503, 504})


class HunterError(RuntimeError):
    """Base exception for Hunter service failures."""


class HunterAuthError(HunterError):
    """Raised on 401/403 — API key missing / invalid / quota-locked."""


class HunterRateLimitError(HunterError):
    """Raised when 429 retries are exhausted."""


class HunterServerError(HunterError):
    """Raised when 5xx retries are exhausted."""


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EmailFinderResult:
    """Outcome of a single ``/v2/email-finder`` call."""

    email: str | None
    score: int | None
    position: str | None
    sources_count: int
    verification_status: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainSearchEmail:
    """One email entry from a domain-search response."""

    value: str
    first_name: str | None
    last_name: str | None
    position: str | None
    confidence: int | None
    verification_status: str | None


@dataclass
class DomainSearchResult:
    """Outcome of a single ``/v2/domain-search`` call."""

    domain: str
    organization: str | None
    emails: list[DomainSearchEmail]
    total: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmailVerifyResult:
    """Outcome of a single ``/v2/email-verifier`` call."""

    email: str
    status: (
        str | None
    )  # 'valid' | 'invalid' | 'accept_all' | 'webmail' | 'disposable' | 'unknown'
    score: int | None
    regexp: bool | None
    gibberish: bool | None
    disposable: bool | None
    webmail: bool | None
    mx_records: bool | None
    smtp_server: bool | None
    smtp_check: bool | None
    accept_all: bool | None
    block: bool | None
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Rate limiter — minimal token bucket
# ---------------------------------------------------------------------------


class _TokenBucket:
    """Thread-safe token bucket: at most ``rate`` requests per second.

    Simple sleep-on-deficit model. Good enough for a single-process CLI
    runner and the Flask in-request usage we care about. Not designed to
    coordinate across multiple processes — Hunter's own server-side
    limiter handles cross-process spillover.
    """

    def __init__(self, rate_per_second: float) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be > 0")
        self.rate = float(rate_per_second)
        self._min_interval = 1.0 / self.rate
        self._lock = threading.Lock()
        self._next_allowed_at: float = 0.0

    def acquire(self, sleep: Any = time.sleep) -> None:
        """Block until a request slot is available.

        ``sleep`` is injectable for tests so we can assert that throttling
        actually happened without burning wall time.
        """
        with self._lock:
            now = time.monotonic()
            if now < self._next_allowed_at:
                wait = self._next_allowed_at - now
                # Release the lock while we sleep so other callers can
                # queue up — but for our small expected concurrency it
                # is fine to hold it.
                sleep(wait)
                now = time.monotonic()
            self._next_allowed_at = max(self._next_allowed_at, now) + self._min_interval


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class HunterEnrichmentService:
    """Thin wrapper around the Hunter.io v2 REST API.

    Parameters
    ----------
    api_key
        Hunter API key. Defaults to ``os.environ["HUNTER_API_KEY"]``. Raise
        :class:`HunterAuthError` lazily on the first call if missing.
    base_url
        Override for tests. Production should leave at default.
    timeout
        Per-request timeout in seconds.
    requests_per_second
        Soft client-side cap. Hunter's own limit is 10/sec; we use 5.
    max_retries_429
        How many times to retry on 429 before raising.
    max_retries_5xx
        How many times to retry on a retryable 5xx before raising.
    retry_base_delay
        Base delay for exponential backoff (`delay = base * 2**attempt`).
    session
        Inject a ``requests.Session``-like object for tests.
    sleep
        Inject the sleep function for tests (defaults to ``time.sleep``).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = HUNTER_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        max_retries_429: int = DEFAULT_MAX_RETRIES_429,
        max_retries_5xx: int = DEFAULT_MAX_RETRIES_5XX,
        retry_base_delay: float = 1.0,
        session: Any = None,
        sleep: Any = None,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.environ.get("HUNTER_API_KEY", "")
        )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries_429 = max_retries_429
        self.max_retries_5xx = max_retries_5xx
        self.retry_base_delay = retry_base_delay
        self._session = session if session is not None else requests.Session()
        self._sleep = sleep if sleep is not None else time.sleep
        self._bucket = _TokenBucket(requests_per_second)
        # Credit counters by method label.
        self._credits: dict[str, int] = {
            "email-finder": 0,
            "domain-search": 0,
            "verify": 0,
        }
        self._credits_lock = threading.Lock()

    # ----- public API ----------------------------------------------------

    def find_email(
        self,
        domain: str,
        first_name: str,
        last_name: str,
    ) -> EmailFinderResult:
        """Look up an email by domain + first + last name. 1 search credit."""
        domain = (domain or "").strip()
        first_name = (first_name or "").strip()
        last_name = (last_name or "").strip()
        if not domain or not first_name or not last_name:
            raise ValueError("find_email requires domain, first_name, and last_name")

        payload = self._get(
            "/v2/email-finder",
            params={
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
            },
            credit_label="email-finder",
        )
        data = payload.get("data") or {}
        return EmailFinderResult(
            email=(data.get("email") or None),
            score=data.get("score"),
            position=data.get("position"),
            sources_count=len(data.get("sources") or []),
            verification_status=(
                (data.get("verification") or {}).get("status")
                if isinstance(data.get("verification"), dict)
                else data.get("verification_status")
            ),
            raw=payload,
        )

    def domain_search(self, domain: str, limit: int = 100) -> DomainSearchResult:
        """Fetch the email roster for a domain. 1 search credit per call.

        Hunter's free tier caps at 25 results; data plans return up to 100
        per page. We do not paginate — the first 100 is enough for our
        contact-hydration use case.
        """
        domain = (domain or "").strip()
        if not domain:
            raise ValueError("domain_search requires a non-empty domain")
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")

        payload = self._get(
            "/v2/domain-search",
            params={"domain": domain, "limit": limit},
            credit_label="domain-search",
        )
        data = payload.get("data") or {}
        emails_raw = data.get("emails") or []
        emails = [
            DomainSearchEmail(
                value=e.get("value") or "",
                first_name=e.get("first_name"),
                last_name=e.get("last_name"),
                position=e.get("position"),
                confidence=e.get("confidence"),
                verification_status=(
                    (e.get("verification") or {}).get("status")
                    if isinstance(e.get("verification"), dict)
                    else None
                ),
            )
            for e in emails_raw
            if isinstance(e, dict) and e.get("value")
        ]
        meta = payload.get("meta") or {}
        total = (meta.get("results") if isinstance(meta, dict) else None) or len(emails)
        return DomainSearchResult(
            domain=domain,
            organization=data.get("organization"),
            emails=emails,
            total=int(total or 0),
            raw=payload,
        )

    def verify_email(self, email: str) -> EmailVerifyResult:
        """Run the deliverability checker. 1 verification credit per call."""
        email = (email or "").strip()
        if "@" not in email:
            raise ValueError("verify_email requires a syntactically valid email")

        payload = self._get(
            "/v2/email-verifier",
            params={"email": email},
            credit_label="verify",
        )
        data = payload.get("data") or {}
        return EmailVerifyResult(
            email=email,
            status=data.get("status"),
            score=data.get("score"),
            regexp=data.get("regexp"),
            gibberish=data.get("gibberish"),
            disposable=data.get("disposable"),
            webmail=data.get("webmail"),
            mx_records=data.get("mx_records"),
            smtp_server=data.get("smtp_server"),
            smtp_check=data.get("smtp_check"),
            accept_all=data.get("accept_all"),
            block=data.get("block"),
            raw=payload,
        )

    def get_credits_used(self) -> dict[str, int]:
        """Return cumulative credit usage for this service instance.

        Returns a fresh dict with the four counters: ``email-finder``,
        ``domain-search``, ``verify``, and ``total``.
        """
        with self._credits_lock:
            snapshot = dict(self._credits)
        snapshot["total"] = sum(snapshot.values())
        return snapshot

    # ----- internals -----------------------------------------------------

    def _require_key(self) -> str:
        if not self._api_key:
            raise HunterAuthError(
                "HUNTER_API_KEY is not set. Configure it in the container "
                "environment (deploy/docker-compose.api.yml) or in .env.dev."
            )
        return self._api_key

    def _get(
        self,
        path: str,
        params: dict[str, Any],
        credit_label: str,
    ) -> dict[str, Any]:
        """Issue a rate-limited, retrying GET against the Hunter API.

        Increments the credit counter on a successful 200, regardless of
        whether the response had useful data (Hunter charges on the
        successful lookup, even if the result is "no email found").

        Raises
        ------
        HunterAuthError
            On 401, 403.
        HunterRateLimitError
            On 429 after exhausting retries.
        HunterServerError
            On a retryable 5xx after exhausting retries.
        HunterError
            On any other non-2xx or on malformed JSON.
        """
        api_key = self._require_key()
        url = f"{self.base_url}{path}"
        # Hunter expects api_key in query-string; never log this value.
        query = dict(params)
        query["api_key"] = api_key

        attempt_429 = 0
        attempt_5xx = 0
        while True:
            self._bucket.acquire(sleep=self._sleep)
            try:
                resp = self._session.get(url, params=query, timeout=self.timeout)
            except requests.RequestException as exc:
                # Network-level errors get the same backoff as 5xx.
                if attempt_5xx >= self.max_retries_5xx:
                    raise HunterServerError(
                        f"Hunter request to {path} failed after "
                        f"{attempt_5xx} retries: {exc}"
                    ) from exc
                delay = self.retry_base_delay * (2**attempt_5xx)
                logger.warning(
                    "Hunter %s network error %s; retrying in %.1fs (attempt %d/%d)",
                    path,
                    exc,
                    delay,
                    attempt_5xx + 1,
                    self.max_retries_5xx,
                )
                self._sleep(delay)
                attempt_5xx += 1
                continue

            status = resp.status_code

            if status == 200:
                try:
                    body = resp.json()
                except ValueError as exc:
                    raise HunterError(
                        f"Hunter {path} returned 200 with non-JSON body"
                    ) from exc
                self._increment_credit(credit_label)
                return body

            if status in (401, 403):
                # Don't leak the key. The body is short and useful.
                raise HunterAuthError(
                    f"Hunter {path} returned {status}: {resp.text[:200]}"
                )

            if status == 429:
                if attempt_429 >= self.max_retries_429:
                    raise HunterRateLimitError(
                        f"Hunter {path} rate-limited after {attempt_429} retries"
                    )
                # Respect Retry-After if present, else exp backoff.
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = float(retry_after)
                else:
                    delay = self.retry_base_delay * (2**attempt_429)
                logger.warning(
                    "Hunter %s 429; retrying in %.1fs (attempt %d/%d)",
                    path,
                    delay,
                    attempt_429 + 1,
                    self.max_retries_429,
                )
                self._sleep(delay)
                attempt_429 += 1
                continue

            if status in RETRYABLE_5XX:
                if attempt_5xx >= self.max_retries_5xx:
                    raise HunterServerError(
                        f"Hunter {path} returned {status} after {attempt_5xx} retries"
                    )
                delay = self.retry_base_delay * (2**attempt_5xx)
                logger.warning(
                    "Hunter %s %d; retrying in %.1fs (attempt %d/%d)",
                    path,
                    status,
                    delay,
                    attempt_5xx + 1,
                    self.max_retries_5xx,
                )
                self._sleep(delay)
                attempt_5xx += 1
                continue

            # Any other non-2xx: fail fast.
            raise HunterError(f"Hunter {path} returned {status}: {resp.text[:200]}")

    def _increment_credit(self, label: str) -> None:
        with self._credits_lock:
            if label not in self._credits:
                self._credits[label] = 0
            self._credits[label] += 1
