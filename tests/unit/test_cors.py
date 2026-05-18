"""CORS preflight tests — BL-1208.

Production at leadgen.visionvolve.com was returning OPTIONS preflight responses
without any Access-Control-* headers for `chrome-extension://*` origins,
which blocked the LinkedIn Sales Navigator extension from making
authenticated requests. The fix in api/__init__.py unconditionally appends a
compiled regex matching real Chrome extension IDs to the flask_cors origin
list so a stricter prod CORS_ORIGINS env can never lock the extension out.

These tests probe the app via OPTIONS preflight (no auth needed — preflight
is browser-driven and never authenticated) and assert the response carries
the headers a real browser needs to allow the follow-up request.
"""

from api import _CHROME_EXTENSION_ORIGIN_RE


# A realistic 32-char Chrome extension ID (a-z0-9). Matches the regex used
# for the spec's curl probe example.
_EXT_ORIGIN = "chrome-extension://abcdefghijklmnopqrstuvwxyz123456"


def _preflight(client, path, origin, method="POST"):
    """Issue an OPTIONS preflight as a browser would."""
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "Authorization, Content-Type, X-Namespace",
        },
    )


def test_chrome_extension_origin_regex_matches_real_id():
    """The compiled regex must match a realistic 32-char extension ID."""
    assert _CHROME_EXTENSION_ORIGIN_RE.match(_EXT_ORIGIN) is not None


def test_chrome_extension_origin_regex_rejects_too_short():
    """Anchored regex must reject obviously malformed origins."""
    assert _CHROME_EXTENSION_ORIGIN_RE.match("chrome-extension://abc") is None


def test_chrome_extension_origin_regex_rejects_prefix_attack():
    """End anchor prevents prefix-based bypass attempts."""
    suffix_attack = f"{_EXT_ORIGIN}.evil.com"
    assert _CHROME_EXTENSION_ORIGIN_RE.match(suffix_attack) is None


def test_preflight_from_chrome_extension_returns_cors_headers(client):
    """OPTIONS preflight from a chrome-extension://* origin must yield the
    Access-Control-* headers the browser needs to permit the follow-up POST.
    """
    resp = _preflight(client, "/api/extension/leads", _EXT_ORIGIN, method="POST")

    # Preflight responses are 200 or 204 — either is valid; flask_cors uses 200.
    assert resp.status_code in (200, 204), (
        f"Preflight returned {resp.status_code} — expected 200/204"
    )

    # The browser checks Access-Control-Allow-Origin against the requesting
    # Origin. flask_cors echoes the origin (or returns "*"); either is
    # acceptable for the extension to proceed.
    allow_origin = resp.headers.get("Access-Control-Allow-Origin", "")
    assert allow_origin in (_EXT_ORIGIN, "*"), (
        f"Access-Control-Allow-Origin was {allow_origin!r}, "
        f"expected {_EXT_ORIGIN!r} or '*'"
    )

    # Methods header must permit POST (the extension's primary verb).
    allow_methods = resp.headers.get("Access-Control-Allow-Methods", "")
    assert "POST" in allow_methods.upper(), (
        f"Access-Control-Allow-Methods missing POST: {allow_methods!r}"
    )

    # Headers list must permit the extension's request headers.
    allow_headers = resp.headers.get("Access-Control-Allow-Headers", "")
    # Header values come back as a comma-separated, often lowercase string.
    allow_headers_lc = allow_headers.lower()
    assert "authorization" in allow_headers_lc, (
        f"Access-Control-Allow-Headers missing Authorization: {allow_headers!r}"
    )


def test_preflight_includes_vary_origin_header(client):
    """flask_cors should set Vary: Origin so caches don't poison cross-origin
    responses. Important for CDN/edge-cache correctness."""
    resp = _preflight(client, "/api/extension/leads", _EXT_ORIGIN, method="POST")
    vary = resp.headers.get("Vary", "")
    assert "Origin" in vary, f"Vary header missing Origin: {vary!r}"


def test_preflight_from_unknown_origin_with_restrictive_config(monkeypatch):
    """When CORS_ORIGINS is locked down to specific origins (mimicking prod),
    the chrome-extension regex must STILL allow the extension through. This
    is the regression test for the bug — prod's CORS_ORIGINS excluded the
    extension, and the fix must be defense-in-depth so env config alone
    cannot break it.
    """
    # Build a fresh app with a restrictive CORS_ORIGINS so we exercise the
    # "regex augments env" path independent of the session-scoped fixture.
    monkeypatch.setenv("CORS_ORIGINS", "https://leadgen.visionvolve.com")

    from api import create_app

    fresh_app = create_app()
    fresh_app.config["TESTING"] = True

    with fresh_app.test_client() as fresh_client:
        resp = _preflight(
            fresh_client, "/api/extension/leads", _EXT_ORIGIN, method="POST"
        )
        allow_origin = resp.headers.get("Access-Control-Allow-Origin", "")
        assert allow_origin in (_EXT_ORIGIN, "*"), (
            "Restrictive CORS_ORIGINS must NOT block the extension regex; "
            f"got Access-Control-Allow-Origin={allow_origin!r}"
        )
