"""EventFest HTML email template rendering.

Renders the branded EventFest invitation email with Czech vocative greeting
and per-contact microsite invite links.  The template uses the email copy
specified by Hanka (updated text about nabidka vystoupeni).

The template supports two address-style (tone) registers via placeholders
substituted at send time by ``send_service._build_template_variables``
based on ``contact.address_style`` (``vykat`` | ``tykat``):

- ``{{vocative_name}}`` — Czech vocative form of the recipient's first name.
- ``{{microsite_link}}`` — per-recipient UA microsite invite URL.
- ``{{recipient_token}}`` — per-recipient partner token baked into each
  featured-act thumbnail href.
- ``{{you_acc}}`` — accusative personal pronoun (Vás | Tebe).
- ``{{you_look_verb}}`` — 2nd-person verb "to look for" (hledáte | hledáš).
- ``{{you_can_verb}}`` — 2nd-person verb "can" (můžete | můžeš).
- ``{{stop_by_imper}}`` — imperative "stop by" (Zastavte se | Zastav se).

If future copy additions introduce other Vy/Vás/Váš/Vám forms, add a new
placeholder here AND populate it in ``send_service._build_template_variables``.

Usage::

    from api.services.eventfest_template import render_eventfest_email

    subject, html, plain = render_eventfest_email(
        "Jano", "https://demo.visionvolve.com/invite/abc123"
    )
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENTFEST_SUBJECT = "Pozvánka na EVENT FEST | Losers Cirque Company"

# ---------------------------------------------------------------------------
# HTML template (inline CSS for email client compatibility)
# ---------------------------------------------------------------------------

EVENTFEST_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nab\u00eddka vystoupen\u00ed</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
</head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f4;">
    <tr>
      <td align="center" style="padding:24px 16px;">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0"
               style="background-color:#ffffff;border-radius:8px;overflow:hidden;max-width:600px;width:100%;">

          <!-- BODY -->
          <tr>
            <td style="padding:32px 32px 16px 32px;color:#333333;font-size:15px;line-height:1.6;">
              <p style="margin:0 0 16px 0;">
                Hezk\u00fd den, {{vocative_name}},
              </p>
              <p style="margin:0 0 16px 0;">
                {{you_look_verb}} zaj\u00edmav\u00fd opening pro konferenci, gala ve\u010de\u0159i \u010di spole\u010densk\u00e9 setk\u00e1n\u00ed?
              </p>
              <p style="margin:0 0 16px 0;">
                Losers Cirque Company m\u00e1 pro {{you_acc}} n\u011bkolik novinek, kter\u00e9 si {{you_can_verb}}
                prohl\u00e9dnout v\u00a0na\u0161\u00ed aktualizovan\u00e9
                <a href="{{microsite_link}}"
                   target="_blank"
                   style="color:#e63946;text-decoration:underline;">nab\u00eddce vystoupen\u00ed</a>.
              </p>
{{featured_acts_section}}
              <p style="margin:0 0 16px 0;">
                N\u011bkter\u00e1 z\u00a0nich {{you_can_verb}} vid\u011bt i\u00a0na\u017eivo v\u00a0r\u00e1mci akce
                <strong>EVENT FEST</strong> ve st\u0159edu 22.4. na pra\u017esk\u00e9m V\u00fdstavi\u0161ti
                Let\u0148any. Od 12:00 hodin se na Expo stage {{you_can_verb}} t\u011b\u0161it na
                <em>Hat Jazz</em> a\u00a0od 13:00 hodin v\u00a0r\u00e1mci prostoru Experience show
                na <em>Handstand</em>.
              </p>
              <p style="margin:0 0 24px 0;">
                {{stop_by_imper}} i\u00a0na na\u0161em st\u00e1nku, budeme se na {{you_acc}} t\u011b\u0161it.
              </p>
              <p style="margin:0 0 0 0;">
                Hanka
              </p>
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="background-color:#f8f8f8;padding:16px 32px;
                       font-size:11px;color:#999999;text-align:center;
                       border-top:1px solid #eeeeee;">
              United Arts s.r.o. | Praha, \u010cesk\u00e1 republika<br>
              <a href="mailto:hana@unitedarts.cz?subject=unsubscribe"
                 style="color:#999999;text-decoration:underline;">Odhl\u00e1sit se</a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Plain text version
# ---------------------------------------------------------------------------

EVENTFEST_PLAIN_TEMPLATE = """\
Hezk\u00fd den, {{vocative_name}},

{{you_look_verb}} zaj\u00edmav\u00fd opening pro konferenci, gala ve\u010de\u0159i \u010di spole\u010densk\u00e9 setk\u00e1n\u00ed?

Losers Cirque Company m\u00e1 pro {{you_acc}} n\u011bkolik novinek, kter\u00e9 si {{you_can_verb}} prohl\u00e9dnout v na\u0161\u00ed aktualizovan\u00e9 nab\u00eddce vystoupen\u00ed ({{microsite_link}}).
{{featured_acts_plain}}
N\u011bkter\u00e1 z nich {{you_can_verb}} vid\u011bt i na\u017eivo v r\u00e1mci akce EVENT FEST ve st\u0159edu 22.4. na pra\u017esk\u00e9m V\u00fdstavi\u0161ti Let\u0148any. Od 12:00 hodin se na Expo stage {{you_can_verb}} t\u011b\u0161it na Hat Jazz a od 13:00 hodin v r\u00e1mci prostoru Experience show na Handstand.

{{stop_by_imper}} i na na\u0161em st\u00e1nku, budeme se na {{you_acc}} t\u011b\u0161it.

Hanka"""


def _replace_template_variables(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{variable}}`` placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value or "")
    return result


def _escape_html_attr(value: str) -> str:
    """Minimal HTML attribute escaping for trusted-but-unsafe input."""
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_html_text(value: str) -> str:
    """Minimal HTML text-node escaping."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _build_featured_acts_html(
    featured_acts: list[dict] | None,
    site_url: str,
    recipient_token: str,
) -> str:
    """Build the 2x2 (or shorter) thumbnail grid HTML block.

    Returns an empty string when ``featured_acts`` is falsy so the
    surrounding template renders without any placeholder artefacts.
    """
    if not featured_acts:
        return ""

    acts = list(featured_acts)[:4]
    site_url_clean = site_url.rstrip("/")

    # Two-column nested table; wraps after the second cell. Nested tables
    # instead of grid/flex because Outlook only renders tables reliably.
    cells: list[str] = []
    for act in acts:
        name = _escape_html_text(str(act.get("name", "")))
        slug = str(act.get("slug", ""))
        image_url = str(act.get("image_url", ""))
        category = str(act.get("category", "performances"))

        href = (
            f"{site_url_clean}/cs/{category}/{slug}"
            f"?t={_escape_html_attr(recipient_token)}"
        )

        cell = (
            '<td width="290" valign="top" '
            'style="padding:8px;width:290px;">'
            f'<a href="{_escape_html_attr(href)}" target="_blank" '
            'style="text-decoration:none;color:inherit;display:block;">'
            f'<img src="{_escape_html_attr(image_url)}" '
            f'alt="{_escape_html_attr(name)}" '
            'width="290" '
            'style="display:block;width:100%;max-width:290px;height:auto;'
            'border:0;outline:none;text-decoration:none;" />'
            '<p style="margin:8px 0 0 0;font-family:Arial,Helvetica,sans-serif;'
            'font-size:14px;font-weight:bold;color:#0A0066;text-align:center;">'
            f"{name}</p>"
            "</a></td>"
        )
        cells.append(cell)

    # Group cells into rows of 2 (1x1, 1x2, 2x1, 2x2 all valid).
    rows_html: list[str] = []
    for i in range(0, len(cells), 2):
        row_cells = "".join(cells[i : i + 2])
        rows_html.append(f"<tr>{row_cells}</tr>")

    return (
        '              <table role="presentation" width="100%" cellpadding="0" '
        'cellspacing="0" '
        'style="margin:8px 0 24px 0;border-collapse:separate;">'
        + "".join(rows_html)
        + "</table>\n"
    )


def _build_featured_acts_plain(
    featured_acts: list[dict] | None,
    site_url: str,
    recipient_token: str,
) -> str:
    """Build the plain-text bullet list of featured acts.

    Returns an empty string when there are no acts so the surrounding
    template has no stray blank line.
    """
    if not featured_acts:
        return ""

    acts = list(featured_acts)[:4]
    site_url_clean = site_url.rstrip("/")

    lines = ["", "Vybraná vystoupení:"]
    for act in acts:
        name = str(act.get("name", ""))
        slug = str(act.get("slug", ""))
        category = str(act.get("category", "performances"))
        url = f"{site_url_clean}/cs/{category}/{slug}?t={recipient_token}"
        lines.append(f"- {name}: {url}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tone (vykání / tykání) pronoun and verb variants
# ---------------------------------------------------------------------------
#
# The EventFest template is authored in Czech with Vy/Ty register switching.
# Each key below is a template placeholder; each value is the substitution
# for that tone. Add new placeholders here AND ensure they are referenced in
# the template body above — a placeholder defined here but absent from the
# template is a no-op; one referenced in the template but missing here leaks
# the literal ``{{...}}`` into the rendered email.
#
# Keep in sync with ``send_service._build_template_variables`` — that helper
# is the runtime authority for what ends up in the final message body.

_TONE_VARIANTS: dict[str, dict[str, str]] = {
    # Formal "Vy" register — default for 351/357 EventFest contacts.
    "vykat": {
        "you_acc": "V\u00e1s",          # accusative: "pro V\u00e1s" / "na V\u00e1s"
        "you_look_verb": "hled\u00e1te",  # 2pl: are you looking for
        "you_can_verb": "m\u016f\u017eete",  # 2pl: you can
        "stop_by_imper": "Zastavte se",  # 2pl imperative: stop by
    },
    # Informal "Ty" register — 6/357 EventFest contacts flagged in DB.
    "tykat": {
        "you_acc": "Tebe",               # accusative: "pro Tebe" / "na Tebe"
        "you_look_verb": "hled\u00e1\u0161",  # 2sg: are you looking for
        "you_can_verb": "m\u016f\u017ee\u0161",  # 2sg: you can
        "stop_by_imper": "Zastav se",    # 2sg imperative: stop by
    },
}


def tone_variables(tone: str | None) -> dict[str, str]:
    """Return the pronoun/verb substitution dict for a given tone.

    Falls back to ``vykat`` (formal) when ``tone`` is ``None``, empty, or
    an unrecognised value — matches the DB default on ``contacts.address_style``.
    """
    key = (tone or "").strip().lower()
    if key not in _TONE_VARIANTS:
        key = "vykat"
    return dict(_TONE_VARIANTS[key])


def _tone_passthrough_variables() -> dict[str, str]:
    """Return a dict mapping each tone key to its own ``{{key}}`` placeholder.

    Used by the provisioner (``_render_storable_body``) so the stored body
    keeps tone placeholders intact for per-recipient substitution at send
    time, the same way ``{{vocative_name}}`` and ``{{microsite_link}}`` do.
    """
    # Both tone dicts share the same keys (asserted in tests) — pick either.
    return {key: "{{" + key + "}}" for key in _TONE_VARIANTS["vykat"]}


#: Sentinel value for ``tone`` param: leaves tone placeholders intact in the
#: rendered body so a downstream step (``send_service``) can substitute
#: them per-recipient from ``contact.address_style``. The provisioner uses
#: this when pre-rendering the storable body.
TONE_PASSTHROUGH = "passthrough"


def render_eventfest_email(
    vocative_name: str | None,
    microsite_link: str,
    recipient_token: str = "",
    site_url: str = "",
    featured_acts: list[dict] | None = None,
    tone: str | None = "vykat",
) -> tuple[str, str, str]:
    """Render the EventFest invitation email.

    Args:
        vocative_name: Contact's name already in vocative form (or ``None``).
        microsite_link: Full URL to the contact's personalised microsite invite.
        recipient_token: The UA microsite partner token (appended as ``?t=``
            to each featured-act detail-page link so arrival sets the
            ``ua_partner`` cookie).
        site_url: Absolute origin for the UA microsite (e.g.
            ``https://booking.loserscirque.cz``). Used to build absolute
            detail-page URLs. Caller-provided -- template never hardcodes.
        featured_acts: Optional list of dicts with keys ``name``, ``slug``,
            ``image_url``, and optional ``category`` (``performances`` --
            default -- or ``animations``). Up to 4 items are rendered as a
            2x2 thumbnail grid. If empty or ``None`` the section is omitted.
        tone: Address style — ``"vykat"`` (formal, default), ``"tykat"``
            (informal), or ``TONE_PASSTHROUGH`` to keep tone placeholders
            unsubstituted for later per-recipient rendering. Any other
            value (including ``None`` and ``""``) falls back to ``vykat``
            so a missing ``address_style`` still produces a valid email.

    Returns:
        Tuple of ``(subject, html_body, plain_text_body)``.
    """
    featured_html = _build_featured_acts_html(
        featured_acts, site_url, recipient_token
    )
    featured_plain = _build_featured_acts_plain(
        featured_acts, site_url, recipient_token
    )

    variables: dict[str, str] = {
        "vocative_name": vocative_name or "",
        "microsite_link": microsite_link,
        "featured_acts_section": featured_html,
        "featured_acts_plain": featured_plain,
    }
    # Tone overlay: normal tones produce the final pronoun strings; the
    # passthrough sentinel keeps ``{{you_acc}}`` etc. literal so the
    # provisioner's stored body survives re-rendering at send time.
    if tone == TONE_PASSTHROUGH:
        variables.update(_tone_passthrough_variables())
    else:
        variables.update(tone_variables(tone))

    # Handle empty name: "Hezky den," with no trailing space before comma
    html = _replace_template_variables(EVENTFEST_HTML_TEMPLATE, variables)
    plain = _replace_template_variables(EVENTFEST_PLAIN_TEMPLATE, variables)

    return (EVENTFEST_SUBJECT, html, plain)
