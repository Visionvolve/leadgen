"""Unit tests for campaign attribution URL parameter helper (BL-1036).

Covers the ``?c=<campaign_id>&r=<recipient_id>`` tagging that feeds
PostHog super-properties via the microsite, which in turn feeds
``get_campaign_microsite_metrics`` in BL-1035. Tests the pure helper
(``add_campaign_attribution`` / ``is_microsite_url``) and the
integration point inside ``_build_template_variables``.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from api.services.campaign_attribution import (
    add_campaign_attribution,
    is_microsite_url,
)


MICROSITE_BASE = "https://demo.visionvolve.com"


# ---------------------------------------------------------------------------
# add_campaign_attribution — pure helper
# ---------------------------------------------------------------------------


def test_adds_c_and_r_to_url_without_params():
    """Given a clean microsite link, both params are appended."""
    url = "https://demo.visionvolve.com/invite/abc123"
    out = add_campaign_attribution(
        url,
        campaign_id="camp-uuid-111",
        recipient_id="rcpt-uuid-222",
        microsite_base_url=MICROSITE_BASE,
    )
    parsed = urlparse(out)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "demo.visionvolve.com"
    assert parsed.path == "/invite/abc123"
    assert params["c"] == ["camp-uuid-111"]
    assert params["r"] == ["rcpt-uuid-222"]


def test_preserves_existing_query_params():
    """Existing params (e.g. ?lang=cs) survive; c/r are merged in."""
    url = "https://demo.visionvolve.com/invite/abc?lang=cs&utm_source=email"
    out = add_campaign_attribution(
        url,
        campaign_id="C1",
        recipient_id="R1",
        microsite_base_url=MICROSITE_BASE,
    )
    params = parse_qs(urlparse(out).query)
    assert params["lang"] == ["cs"]
    assert params["utm_source"] == ["email"]
    assert params["c"] == ["C1"]
    assert params["r"] == ["R1"]


def test_idempotent_when_params_already_present():
    """First-write-wins: existing c/r values are not overwritten."""
    url = "https://demo.visionvolve.com/invite/abc?c=OLDC&r=OLDR"
    out = add_campaign_attribution(
        url,
        campaign_id="NEWC",
        recipient_id="NEWR",
        microsite_base_url=MICROSITE_BASE,
    )
    params = parse_qs(urlparse(out).query)
    assert params["c"] == ["OLDC"]
    assert params["r"] == ["OLDR"]
    # No duplicate keys.
    assert len(params["c"]) == 1
    assert len(params["r"]) == 1


def test_does_not_touch_non_microsite_url():
    """External/unsubscribe/mailto links are returned unchanged."""
    cases = [
        "https://leadgen.visionvolve.com/api/unsubscribe/xyz",
        "mailto:hana@unitedarts.cz",
        "tel:+420737853490",
        "https://example.com/somewhere",
    ]
    for url in cases:
        out = add_campaign_attribution(
            url,
            campaign_id="C1",
            recipient_id="R1",
            microsite_base_url=MICROSITE_BASE,
        )
        assert out == url, f"{url} was unexpectedly modified to {out}"


def test_preserves_fragment():
    """URL fragment (#section) survives intact."""
    url = "https://demo.visionvolve.com/#contact"
    out = add_campaign_attribution(
        url,
        campaign_id="C1",
        recipient_id="R1",
        microsite_base_url=MICROSITE_BASE,
    )
    parsed = urlparse(out)
    assert parsed.fragment == "contact"
    assert "c=C1" in parsed.query
    assert "r=R1" in parsed.query


def test_urlencodes_special_characters():
    """IDs with slashes, spaces, ampersands, plus signs are encoded."""
    url = "https://demo.visionvolve.com/"
    out = add_campaign_attribution(
        url,
        # Realistic-but-mean inputs: UUIDs never contain these, but we
        # still must encode in case the id format changes later.
        campaign_id="a/b c&d+e",
        recipient_id="x y+z",
        microsite_base_url=MICROSITE_BASE,
    )
    # Decoded values match originals.
    params = parse_qs(urlparse(out).query)
    assert params["c"] == ["a/b c&d+e"]
    assert params["r"] == ["x y+z"]
    # And the raw query string is properly encoded (no literal & in the
    # value, space is encoded, etc.).
    raw_query = urlparse(out).query
    assert "a/b c&d+e" not in raw_query  # must be encoded


def test_empty_url_is_returned_unchanged():
    assert add_campaign_attribution("", campaign_id="C1", recipient_id="R1") == ""


def test_none_ids_add_nothing():
    url = "https://demo.visionvolve.com/invite/abc"
    out = add_campaign_attribution(
        url,
        campaign_id=None,
        recipient_id=None,
        microsite_base_url=MICROSITE_BASE,
    )
    assert out == url


def test_only_campaign_id_adds_only_c():
    url = "https://demo.visionvolve.com/invite/abc"
    out = add_campaign_attribution(
        url,
        campaign_id="C1",
        recipient_id=None,
        microsite_base_url=MICROSITE_BASE,
    )
    params = parse_qs(urlparse(out).query)
    assert params["c"] == ["C1"]
    assert "r" not in params


def test_only_recipient_id_adds_only_r():
    url = "https://demo.visionvolve.com/invite/abc"
    out = add_campaign_attribution(
        url,
        campaign_id=None,
        recipient_id="R1",
        microsite_base_url=MICROSITE_BASE,
    )
    params = parse_qs(urlparse(out).query)
    assert params["r"] == ["R1"]
    assert "c" not in params


def test_no_base_url_tags_any_http_url():
    """When no microsite_base_url is supplied, any http(s) URL is tagged.

    This matches the helper contract: base-url filtering is opt-in.
    """
    url = "https://example.com/path"
    out = add_campaign_attribution(url, campaign_id="C1", recipient_id="R1")
    params = parse_qs(urlparse(out).query)
    assert params["c"] == ["C1"]
    assert params["r"] == ["R1"]


def test_no_base_url_still_rejects_non_http_schemes():
    """Without base url we still refuse mailto:/tel: etc."""
    for url in ("mailto:a@b.c", "tel:+100", "ftp://x/y"):
        out = add_campaign_attribution(url, campaign_id="C1", recipient_id="R1")
        assert out == url


def test_malformed_url_returned_unchanged():
    """Relative URLs and garbage return unchanged (no crash)."""
    for url in ("/relative/path", "not a url at all", "://no-scheme"):
        out = add_campaign_attribution(
            url, campaign_id="C1", recipient_id="R1", microsite_base_url=MICROSITE_BASE
        )
        assert out == url


def test_case_insensitive_host_match():
    """Microsite base comparison ignores case in scheme + host."""
    url = "https://Demo.VisionVolve.com/invite/abc"
    out = add_campaign_attribution(
        url,
        campaign_id="C1",
        recipient_id="R1",
        microsite_base_url="HTTPS://demo.visionvolve.com",
    )
    params = parse_qs(urlparse(out).query)
    assert params["c"] == ["C1"]
    assert params["r"] == ["R1"]


# ---------------------------------------------------------------------------
# is_microsite_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://demo.visionvolve.com/", True),
        ("https://demo.visionvolve.com/invite/abc?x=1", True),
        ("http://demo.visionvolve.com/", False),  # scheme mismatch
        ("https://leadgen.visionvolve.com/", False),  # host mismatch
        ("mailto:a@b.c", False),
        ("tel:+420", False),
        ("", False),
        ("not a url", False),
    ],
)
def test_is_microsite_url(url, expected):
    assert is_microsite_url(url, MICROSITE_BASE) is expected


def test_is_microsite_url_empty_base_is_false():
    assert is_microsite_url("https://demo.visionvolve.com/", "") is False


# ---------------------------------------------------------------------------
# Integration — _build_template_variables in send_service
# ---------------------------------------------------------------------------


def _make_stub_campaign_and_contact(session, tenant_id):
    """Create a minimal EventFest campaign + contact + CC, return all three.

    Avoids the conftest seed fixture complexity; we just need the IDs
    and generation_config on the campaign row.
    """
    from api.models import Campaign, CampaignContact, Contact

    contact = Contact(
        tenant_id=tenant_id,
        first_name="Jana",
        last_name="Nováková",
        email_address="jana@example.com",
    )
    session.add(contact)
    session.flush()

    campaign = Campaign(
        tenant_id=tenant_id,
        name="BL-1036 Attribution Test",
        status="review",
        generation_config={"template_type": "eventfest"},
    )
    session.add(campaign)
    session.flush()

    cc = CampaignContact(
        campaign_id=campaign.id,
        contact_id=contact.id,
        tenant_id=tenant_id,
        status="pending",
    )
    session.add(cc)
    session.flush()

    return campaign, cc, contact


def test_build_template_variables_tags_microsite_link(
    app, db, seed_tenant, monkeypatch
):
    """Rendering a template campaign tags the microsite link with c+r."""
    from api.services.send_service import _build_template_variables

    monkeypatch.setenv("UA_MICROSITE_URL", "https://demo.visionvolve.com")
    monkeypatch.setenv("UA_INVITE_API_KEY", "test-key")

    tenant_id = seed_tenant.id
    campaign, cc, contact = _make_stub_campaign_and_contact(db.session, tenant_id)

    with patch(
        "api.services.microsite_invites.get_or_create_invite",
        return_value="https://demo.visionvolve.com/invite/abc123",
    ):
        variables = _build_template_variables(contact, cc, campaign)

    assert "microsite_link" in variables
    parsed = urlparse(variables["microsite_link"])
    params = parse_qs(parsed.query)
    assert params["c"] == [str(campaign.id)]
    assert params["r"] == [str(cc.id)]
    assert parsed.path == "/invite/abc123"


def test_build_template_variables_tags_fallback_link_when_invite_fails(
    app, db, seed_tenant, monkeypatch
):
    """When invite API fails, the fallback microsite URL is still tagged."""
    from api.services.send_service import _build_template_variables

    monkeypatch.setenv("UA_MICROSITE_URL", "https://demo.visionvolve.com")
    monkeypatch.setenv("UA_INVITE_API_KEY", "test-key")

    tenant_id = seed_tenant.id
    campaign, cc, contact = _make_stub_campaign_and_contact(db.session, tenant_id)

    with patch(
        "api.services.microsite_invites.get_or_create_invite",
        side_effect=RuntimeError("boom"),
    ):
        variables = _build_template_variables(contact, cc, campaign)

    params = parse_qs(urlparse(variables["microsite_link"]).query)
    assert params["c"] == [str(campaign.id)]
    assert params["r"] == [str(cc.id)]


def test_build_template_variables_noop_for_non_template_campaigns(app, db, seed_tenant):
    """Campaigns without a template_type return an empty variables dict."""
    from api.models import Campaign, CampaignContact, Contact
    from api.services.send_service import _build_template_variables

    tenant_id = seed_tenant.id
    contact = Contact(
        tenant_id=tenant_id, first_name="x", last_name="y", email_address="x@y.com"
    )
    db.session.add(contact)
    db.session.flush()
    campaign = Campaign(
        tenant_id=tenant_id,
        name="Plain",
        status="review",
        generation_config={},
    )
    db.session.add(campaign)
    db.session.flush()
    cc = CampaignContact(
        campaign_id=campaign.id,
        contact_id=contact.id,
        tenant_id=tenant_id,
        status="pending",
    )
    db.session.add(cc)
    db.session.flush()

    assert _build_template_variables(contact, cc, campaign) == {}
