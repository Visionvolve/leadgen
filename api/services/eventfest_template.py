"""EventFest HTML email template rendering.

Renders the branded EventFest invitation email with a vocative greeting
and per-contact microsite invite links. The Czech (cs) variant is the
production-tested template used since the LCC partnership launch; the
English (en) variant is a literal translation registered alongside CS so
contacts with ``language='en'`` receive the EN copy automatically (see
``api.services.template_registry``).

Legacy usage (still supported)::

    from api.services.eventfest_template import render_eventfest_email

    subject, html, plain = render_eventfest_email(
        "Jano", "https://demo.visionvolve.com/invite/abc123"
    )

Preferred usage via the registry::

    from api.services import template_registry

    payload = template_registry.render(
        "eventfest_invitation",
        contact.language,
        vocative_name="Jano",
        microsite_link="https://demo.visionvolve.com/invite/abc123",
    )
"""

from __future__ import annotations

from .template_registry import register

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVENTFEST_TEMPLATE_KEY = "eventfest_invitation"

EVENTFEST_SUBJECT = "Pozvánka na EVENT FEST | Losers Cirque Company"
"""Czech subject line (production)."""

EVENTFEST_SUBJECT_EN = "Invitation to EVENT FEST | Losers Cirque Company"
"""English subject line."""

# ---------------------------------------------------------------------------
# Czech HTML template (inline CSS for email client compatibility)
# ---------------------------------------------------------------------------

EVENTFEST_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Nabídka vystoupení</title>
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
                Hezký den, {{vocative_name}},
              </p>
              <p style="margin:0 0 16px 0;">
                hledáte zajímavý opening pro konferenci, gala večeři či společenské setkání?
              </p>
              <p style="margin:0 0 16px 0;">
                Losers Cirque Company má pro Vás několik novinek, které si můžete
                prohlédnout v naší aktualizované
                <a href="{{microsite_link}}"
                   target="_blank"
                   style="color:#e63946;text-decoration:underline;">nabídce vystoupení</a>.
              </p>
              <p style="margin:0 0 16px 0;">
                Některá z nich můžete vidět i naživo v rámci akce
                <strong>EVENT FEST</strong> ve středu 22.4. na pražském Výstavišti
                Letňany. Od 12:00 hodin se na Expo stage můžete těšit na
                <em>Hat Jazz</em> a od 13:00 hodin v rámci prostoru Experience show
                na <em>Handstand</em>.
              </p>
              <p style="margin:0 0 24px 0;">
                Zastavte se i na našem stánku, budeme se na Vás těšit.
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
              United Arts s.r.o. | Praha, Česká republika<br>
              <a href="mailto:hana@unitedarts.cz?subject=unsubscribe"
                 style="color:#999999;text-decoration:underline;">Odhlásit se</a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Czech plain text version
# ---------------------------------------------------------------------------

EVENTFEST_PLAIN_TEMPLATE = """\
Hezký den, {{vocative_name}},

hledáte zajímavý opening pro konferenci, gala večeři či společenské setkání?

Losers Cirque Company má pro Vás několik novinek, které si můžete prohlédnout v naší aktualizované nabídce vystoupení ({{microsite_link}}).

Některá z nich můžete vidět i naživo v rámci akce EVENT FEST ve středu 22.4. na pražském Výstavišti Letňany. Od 12:00 hodin se na Expo stage můžete těšit na Hat Jazz a od 13:00 hodin v rámci prostoru Experience show na Handstand.

Zastavte se i na našem stánku, budeme se na Vás těšit.

Hanka"""

# ---------------------------------------------------------------------------
# English HTML template
# ---------------------------------------------------------------------------

EVENTFEST_HTML_TEMPLATE_EN = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Performance offer</title>
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
                Hello {{vocative_name}},
              </p>
              <p style="margin:0 0 16px 0;">
                are you looking for an engaging opening act for a conference,
                gala dinner, or corporate event?
              </p>
              <p style="margin:0 0 16px 0;">
                Losers Cirque Company has several new pieces for you to
                explore in our updated
                <a href="{{microsite_link}}"
                   target="_blank"
                   style="color:#e63946;text-decoration:underline;">performance offer</a>.
              </p>
              <p style="margin:0 0 16px 0;">
                You can also see some of them live at
                <strong>EVENT FEST</strong> on Wednesday, April 22nd at
                Prague Exhibition Grounds Letňany. From 12:00 on the
                Expo stage you can enjoy <em>Hat Jazz</em>, and from 13:00
                in the Experience show area look forward to <em>Handstand</em>.
              </p>
              <p style="margin:0 0 24px 0;">
                Stop by our booth too — we look forward to meeting you.
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
              United Arts s.r.o. | Prague, Czech Republic<br>
              <a href="mailto:hana@unitedarts.cz?subject=unsubscribe"
                 style="color:#999999;text-decoration:underline;">Unsubscribe</a>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# English plain text version
# ---------------------------------------------------------------------------

EVENTFEST_PLAIN_TEMPLATE_EN = """\
Hello {{vocative_name}},

are you looking for an engaging opening act for a conference, gala dinner, or corporate event?

Losers Cirque Company has several new pieces for you to explore in our updated performance offer ({{microsite_link}}).

You can also see some of them live at EVENT FEST on Wednesday, April 22nd at Prague Exhibition Grounds Letňany. From 12:00 on the Expo stage you can enjoy Hat Jazz, and from 13:00 in the Experience show area look forward to Handstand.

Stop by our booth too — we look forward to meeting you.

Hanka"""


def _replace_template_variables(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{variable}}`` placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value or "")
    return result


# ---------------------------------------------------------------------------
# Language-specific renderers (registry-compatible signatures)
# ---------------------------------------------------------------------------


def render_eventfest_cs(
    vocative_name: str | None = None,
    microsite_link: str = "",
    **_: object,
) -> dict:
    """Render the Czech EventFest invitation.

    Returns a dict with ``subject``, ``html`` and ``text`` keys. Extra
    kwargs are accepted (and ignored) so the registry can pass arbitrary
    template context without each renderer caring.
    """
    variables = {
        "vocative_name": vocative_name or "",
        "microsite_link": microsite_link or "",
    }
    return {
        "subject": EVENTFEST_SUBJECT,
        "html": _replace_template_variables(EVENTFEST_HTML_TEMPLATE, variables),
        "text": _replace_template_variables(EVENTFEST_PLAIN_TEMPLATE, variables),
    }


def render_eventfest_en(
    vocative_name: str | None = None,
    microsite_link: str = "",
    **_: object,
) -> dict:
    """Render the English EventFest invitation."""
    variables = {
        "vocative_name": vocative_name or "",
        "microsite_link": microsite_link or "",
    }
    return {
        "subject": EVENTFEST_SUBJECT_EN,
        "html": _replace_template_variables(EVENTFEST_HTML_TEMPLATE_EN, variables),
        "text": _replace_template_variables(EVENTFEST_PLAIN_TEMPLATE_EN, variables),
    }


# ---------------------------------------------------------------------------
# Legacy API — preserved for existing callers / tests
# ---------------------------------------------------------------------------


def render_eventfest_email(
    vocative_name: str | None,
    microsite_link: str,
) -> tuple[str, str, str]:
    """Render the Czech EventFest invitation (legacy 3-tuple API).

    Equivalent to ``render_eventfest_cs`` but returns a tuple of
    ``(subject, html, plain_text)`` for backward compatibility with
    existing callers (the campaign provisioning service and pre-existing
    tests). New code should call :func:`render_eventfest_cs`/`_en` or go
    through :mod:`api.services.template_registry`.
    """
    payload = render_eventfest_cs(
        vocative_name=vocative_name,
        microsite_link=microsite_link,
    )
    return (payload["subject"], payload["html"], payload["text"])


# ---------------------------------------------------------------------------
# Registry wiring — runs at import time
# ---------------------------------------------------------------------------

register(EVENTFEST_TEMPLATE_KEY, "cs", render_eventfest_cs)
register(EVENTFEST_TEMPLATE_KEY, "en", render_eventfest_en)
