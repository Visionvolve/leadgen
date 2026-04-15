"""EventFest HTML email template rendering.

Renders the branded EventFest invitation email with Czech vocative greeting
and per-contact microsite invite links.  The template uses the email copy
specified by Hanka (updated text about nabidka vystoupeni).

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
                hled\u00e1te zaj\u00edmav\u00fd opening pro konferenci, gala ve\u010de\u0159i \u010di spole\u010densk\u00e9 setk\u00e1n\u00ed?
              </p>
              <p style="margin:0 0 16px 0;">
                Losers Cirque Company m\u00e1 pro V\u00e1s n\u011bkolik novinek, kter\u00e9 si m\u016f\u017eete
                prohl\u00e9dnout v\u00a0na\u0161\u00ed aktualizovan\u00e9
                <a href="{{microsite_link}}"
                   target="_blank"
                   style="color:#e63946;text-decoration:underline;">nab\u00eddce vystoupen\u00ed</a>.
              </p>
              <p style="margin:0 0 16px 0;">
                N\u011bkter\u00e1 z\u00a0nich m\u016f\u017eete vid\u011bt i\u00a0na\u017eivo v\u00a0r\u00e1mci akce
                <strong>EVENT FEST</strong> ve st\u0159edu 22.4. na pra\u017esk\u00e9m V\u00fdstavi\u0161ti
                Let\u0148any. Od 12:00 hodin se na Expo stage m\u016f\u017eete t\u011b\u0161it na
                <em>Hat Jazz</em> a\u00a0od 13:00 hodin v\u00a0r\u00e1mci prostoru Experience show
                na <em>Handstand</em>.
              </p>
              <p style="margin:0 0 24px 0;">
                Zastavte se i\u00a0na na\u0161em st\u00e1nku, budeme se na V\u00e1s t\u011b\u0161it.
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

hled\u00e1te zaj\u00edmav\u00fd opening pro konferenci, gala ve\u010de\u0159i \u010di spole\u010densk\u00e9 setk\u00e1n\u00ed?

Losers Cirque Company m\u00e1 pro V\u00e1s n\u011bkolik novinek, kter\u00e9 si m\u016f\u017eete prohl\u00e9dnout v na\u0161\u00ed aktualizovan\u00e9 nab\u00eddce vystoupen\u00ed ({{microsite_link}}).

N\u011bkter\u00e1 z nich m\u016f\u017eete vid\u011bt i na\u017eivo v r\u00e1mci akce EVENT FEST ve st\u0159edu 22.4. na pra\u017esk\u00e9m V\u00fdstavi\u0161ti Let\u0148any. Od 12:00 hodin se na Expo stage m\u016f\u017eete t\u011b\u0161it na Hat Jazz a od 13:00 hodin v r\u00e1mci prostoru Experience show na Handstand.

Zastavte se i na na\u0161em st\u00e1nku, budeme se na V\u00e1s t\u011b\u0161it.

Hanka"""


def _replace_template_variables(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{variable}}`` placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value or "")
    return result


def render_eventfest_email(
    vocative_name: str | None,
    microsite_link: str,
) -> tuple[str, str, str]:
    """Render the EventFest invitation email.

    Args:
        vocative_name: Contact's name already in vocative form (or ``None``).
        microsite_link: Full URL to the contact's personalised microsite invite.

    Returns:
        Tuple of ``(subject, html_body, plain_text_body)``.
    """
    variables = {
        "vocative_name": vocative_name or "",
        "microsite_link": microsite_link,
    }

    # Handle empty name: "Hezky den," with no trailing space before comma
    html = _replace_template_variables(EVENTFEST_HTML_TEMPLATE, variables)
    plain = _replace_template_variables(EVENTFEST_PLAIN_TEMPLATE, variables)

    return (EVENTFEST_SUBJECT, html, plain)
