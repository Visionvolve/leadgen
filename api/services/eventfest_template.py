"""EventFest HTML email template rendering.

Renders the v4-approved branded EventFest invitation email with Czech
vocative greeting and per-contact microsite invite links.

The template follows Hana's v4 approved design:
- Deep-blue header band with circular logo + "LOSERS CIRQUE" wordmark
- Red 4px accent bar
- Greeting + body paragraphs (EVENT FEST invite, Hat Jazz + Handstand,
  booth visit)
- 2x2 thumbnail grid for 4 featured acts (Complicité, Glamour in Red,
  Aerial Hoop — Armagedon, Onyx) — all thumbnails link to the partner
  home (``{{microsite_link}}``) to keep the template simple and avoid
  per-slug URL complexity.
- Red "Prohlédněte si celou nabídku" CTA button
- Warm "Hanka" closer + formal signature block with live tel/mailto/3
  web URLs
- Footer with unsubscribe

The template supports two address-style (tone) registers via placeholders
substituted at send time by ``send_service._build_template_variables``
based on ``contact.address_style`` (``vykat`` | ``tykat``):

- ``{{vocative_name}}`` — Czech vocative form of the recipient's first name.
- ``{{microsite_link}}`` — per-recipient UA microsite invite URL. Appears
  in 10 places (logo, wordmark, 4 thumbnail links, CTA button mso+non-mso,
  signature follow-up) so every CTA-level click carries the partner token.
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
# HTML template (inline CSS for email-client compatibility — v4 approved)
#
# Hardcoded assets:
# - Logo:     https://booking.loserscirque.cz/images/lcc-logo-2025.png
# - Thumb 1 (Complicité):          /api/media/file/01-2-768x512.jpg
# - Thumb 2 (Glamour in Red):      /api/media/file/01-11-768x512.jpg
# - Thumb 3 (Aerial Hoop Armagedon): /api/media/file/40_1-768x512.jpg
# - Thumb 4 (Onyx):                /api/media/file/01-17-768x512.jpg
#
# All 4 thumbnails link to ``{{microsite_link}}`` (partner home) — NOT
# per-slug detail pages — to keep the template simple and reliable for
# the 357-partner send. The partner cookie is set by the invite-token
# redemption on the landing page, then the partner can navigate.
# ---------------------------------------------------------------------------

EVENTFEST_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <title>Pozv\u00e1nka na EVENT FEST | Losers Cirque Company</title>
  <!--[if mso]>
  <noscript>
    <xml>
      <o:OfficeDocumentSettings>
        <o:PixelsPerInch>96</o:PixelsPerInch>
      </o:OfficeDocumentSettings>
    </xml>
  </noscript>
  <![endif]-->
  <style>
    body,table,td,a { -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }
    table,td { mso-table-lspace:0pt; mso-table-rspace:0pt; }
    img { -ms-interpolation-mode:bicubic; border:0; outline:none; text-decoration:none; display:block; }
    body { margin:0 !important; padding:0 !important; width:100% !important; background:#f4f4f7; }
    a { color:#1A0DAB; }
    @media only screen and (max-width:600px){
      .container { width:100% !important; }
      .px-32 { padding-left:20px !important; padding-right:20px !important; }
      .hero-h1 { font-size:26px !important; line-height:1.15 !important; }
      .card-cell { display:block !important; width:100% !important; padding:0 0 16px 0 !important; }
      .card-img { width:100% !important; height:auto !important; max-width:100% !important; }
      .cta-btn { display:block !important; width:100% !important; box-sizing:border-box; }
      .wordmark-text { font-size:22px !important; }
      .header-logo { width:80px !important; max-width:80px !important; }
    }
  </style>
</head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0A0066;max-width:600px;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#f4f4f7;">
  \u010cty\u0159i p\u0159edstaven\u00ed pro Va\u0161i sez\u00f3nu 2026 \u2014 Complicit\u00e9, Glamour in Red, Aerial Hoop a Onyx.
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f4f4f7;">
  <tr>
    <td align="center" style="padding:24px 12px;">
      <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background:#FFFFFF;border-radius:8px;overflow:hidden;box-shadow:0 1px 2px rgba(10,0,102,0.04);">

        <!-- Header band (deep blue) -->
        <tr>
          <td align="center" bgcolor="#0A0066" style="background-color:#0A0066;padding:24px 24px;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0" align="center">
              <tr>
                <td valign="middle" style="padding-right:16px;">
                  <a href="{{microsite_link}}" style="text-decoration:none;display:inline-block;">
                    <img class="header-logo"
                         src="https://booking.loserscirque.cz/images/lcc-logo-2025.png"
                         alt="LOSERS CIRQUE COMPANY"
                         width="96" height="96"
                         style="display:block;border:0;width:96px;max-width:96px;height:auto;">
                  </a>
                </td>
                <td valign="middle">
                  <a href="{{microsite_link}}"
                     class="wordmark-text"
                     style="text-decoration:none;color:#FFFFFF;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-weight:900;letter-spacing:0.08em;font-size:26px;line-height:1.1;text-transform:uppercase;">
                    LOSERS<br>CIRQUE
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Red accent stripe -->
        <tr><td style="background:#FF0000;height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>

        <!-- Greeting + body (Hana's v4 approved copy) -->
        <tr>
          <td class="px-32" style="padding:40px 32px 8px 32px;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            <h1 class="hero-h1" style="margin:0 0 16px 0;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:30px;line-height:1.15;font-weight:800;color:#0A0066;letter-spacing:-0.01em;">
              Hezk\u00fd den, {{vocative_name}},
            </h1>
            <p style="margin:0 0 14px 0;font-size:16px;line-height:1.6;color:#222;">
              {{you_look_verb}} zaj\u00edmav\u00fd opening pro konferenci, gala ve\u010de\u0159i \u010di spole\u010densk\u00e9 setk\u00e1n\u00ed?
            </p>
            <p style="margin:0 0 14px 0;font-size:16px;line-height:1.6;color:#222;">
              Losers Cirque Company m\u00e1 pro {{you_acc}} n\u011bkolik novinek, kter\u00e9 si {{you_can_verb}} prohl\u00e9dnout v\u00a0na\u0161\u00ed aktualizovan\u00e9 <a href="{{microsite_link}}" style="color:#1A0DAB;text-decoration:underline;">nab\u00eddce vystoupen\u00ed</a>.
            </p>
            <p style="margin:0 0 14px 0;font-size:16px;line-height:1.6;color:#222;">
              N\u011bkter\u00e1 z\u00a0nich {{you_can_verb}} vid\u011bt i\u00a0na\u017eivo v\u00a0r\u00e1mci akce <strong style="color:#0A0066;">EVENT FEST</strong> ve st\u0159edu <strong style="color:#0A0066;">22.4.2026</strong> na pra\u017esk\u00e9m V\u00fdstavi\u0161ti Let\u0148any. Od 12:00 hodin na Expo stage {{you_can_verb}} t\u011b\u0161it na <strong style="color:#0A0066;">Hat Jazz</strong> a od 13:00 hodin v\u00a0r\u00e1mci prostoru Experience show na <strong style="color:#0A0066;">Handstand</strong>.
            </p>
            <p style="margin:0 0 28px 0;font-size:16px;line-height:1.6;color:#222;">
              {{stop_by_imper}} i\u00a0na na\u0161em st\u00e1nku, budeme se na {{you_acc}} t\u011b\u0161it.
            </p>
          </td>
        </tr>

        <!-- Section heading -->
        <tr>
          <td class="px-32" style="padding:0 32px 20px 32px;">
            <h2 style="margin:0;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:20px;line-height:1.25;font-weight:700;color:#0A0066;">
              Vybrali jsme pro {{you_acc}} \u010dty\u0159i p\u0159edstaven\u00ed, kter\u00e1 stoj\u00ed za pozornost
            </h2>
            <div style="height:3px;width:48px;background:#FF0000;margin:10px 0 0 0;line-height:3px;font-size:0;">&nbsp;</div>
          </td>
        </tr>

        <!-- 2x2 Grid: row 1 -->
        <tr>
          <td class="px-32" style="padding:8px 32px 0 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <!-- Complicité -->
                <td class="card-cell" width="50%" valign="top" style="padding:8px 8px 16px 0;">
                  <a href="{{microsite_link}}" style="text-decoration:none;color:#0A0066;display:block;">
                    <img class="card-img" src="https://booking.loserscirque.cz/api/media/file/01-2-768x512.jpg"
                         alt="Complicit\u00e9 \u2014 skupinov\u00e1 akrobacie"
                         width="260"
                         style="display:block;border:0;width:100%;max-width:260px;height:auto;border-radius:6px;background:#e6e6f0;">
                    <div style="padding:12px 2px 0 2px;">
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:17px;line-height:1.2;font-weight:700;color:#0A0066;">Complicit\u00e9</div>
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#555;margin-top:4px;">P\u011bt akrobat\u016f, s\u00edla a d\u016fv\u011bra ve vizu\u00e1ln\u011b strhuj\u00edc\u00ed choreografii.</div>
                    </div>
                  </a>
                </td>
                <!-- Glamour in Red -->
                <td class="card-cell" width="50%" valign="top" style="padding:8px 0 16px 8px;">
                  <a href="{{microsite_link}}" style="text-decoration:none;color:#0A0066;display:block;">
                    <img class="card-img" src="https://booking.loserscirque.cz/api/media/file/01-11-768x512.jpg"
                         alt="Glamour in Red \u2014 anima\u010dn\u00ed program"
                         width="260"
                         style="display:block;border:0;width:100%;max-width:260px;height:auto;border-radius:6px;background:#e6e6f0;">
                    <div style="padding:12px 2px 0 2px;">
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:17px;line-height:1.2;font-weight:700;color:#0A0066;">Glamour in Red</div>
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#555;margin-top:4px;">\u017div\u00e9 sochy v \u010derven\u00e9 \u2014 smysln\u00e1, elegantn\u00ed animace pro V\u00e1\u0161 prostor.</div>
                    </div>
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- 2x2 Grid: row 2 -->
        <tr>
          <td class="px-32" style="padding:0 32px 8px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <!-- Aerial Hoop — Armagedon -->
                <td class="card-cell" width="50%" valign="top" style="padding:8px 8px 16px 0;">
                  <a href="{{microsite_link}}" style="text-decoration:none;color:#0A0066;display:block;">
                    <img class="card-img" src="https://booking.loserscirque.cz/api/media/file/40_1-768x512.jpg"
                         alt="Aerial Hoop \u2014 Armagedon"
                         width="260"
                         style="display:block;border:0;width:100%;max-width:260px;height:auto;border-radius:6px;background:#e6e6f0;">
                    <div style="padding:12px 2px 0 2px;">
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:17px;line-height:1.2;font-weight:700;color:#0A0066;">Aerial Hoop \u2014 Armagedon</div>
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#555;margin-top:4px;">S\u00f3lo na z\u00e1v\u011bsn\u00e9m kruhu \u2014 poetick\u00e9 a atraktivn\u00ed, ide\u00e1ln\u00ed pro gala ve\u010dery.</div>
                    </div>
                  </a>
                </td>
                <!-- Onyx -->
                <td class="card-cell" width="50%" valign="top" style="padding:8px 0 16px 8px;">
                  <a href="{{microsite_link}}" style="text-decoration:none;color:#0A0066;display:block;">
                    <img class="card-img" src="https://booking.loserscirque.cz/api/media/file/01-17-768x512.jpg"
                         alt="Onyx \u2014 skupinov\u00e1 akrobacie"
                         width="260"
                         style="display:block;border:0;width:100%;max-width:260px;height:auto;border-radius:6px;background:#e6e6f0;">
                    <div style="padding:12px 2px 0 2px;">
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:17px;line-height:1.2;font-weight:700;color:#0A0066;">Onyx</div>
                      <div style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#555;margin-top:4px;">P\u00e1rov\u00e1 i skupinov\u00e1 akrobacie s handstandem \u2014 p\u0159esnost a s\u00edla v\u00a0ka\u017ed\u00e9m gestu.</div>
                    </div>
                  </a>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- CTA button -->
        <tr>
          <td class="px-32" align="center" style="padding:24px 32px 8px 32px;">
            <!--[if mso]>
            <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{{microsite_link}}" style="height:52px;v-text-anchor:middle;width:320px;" arcsize="10%" stroke="f" fillcolor="#FF0000">
              <w:anchorlock/>
              <center style="color:#FFFFFF;font-family:Arial,sans-serif;font-size:16px;font-weight:700;">Prohl\u00e9dn\u011bte si celou nab\u00eddku</center>
            </v:roundrect>
            <![endif]-->
            <!--[if !mso]><!-- -->
            <a class="cta-btn" href="{{microsite_link}}"
               style="display:inline-block;background:#FF0000;color:#FFFFFF;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-weight:700;font-size:16px;letter-spacing:0.02em;text-decoration:none;padding:16px 32px;border-radius:6px;mso-hide:all;">
              Prohl\u00e9dn\u011bte si celou nab\u00eddku \u2192
            </a>
            <!--<![endif]-->
          </td>
        </tr>

        <!-- Warm closer -->
        <tr>
          <td class="px-32" style="padding:32px 32px 0 32px;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            <div style="font-size:18px;font-weight:800;color:#0A0066;line-height:1.2;">Hanka</div>
          </td>
        </tr>

        <!-- Thin divider above formal signature -->
        <tr>
          <td class="px-32" style="padding:24px 32px 0 32px;">
            <div style="height:1px;background-color:#E5E5E5;line-height:1px;font-size:0;">&nbsp;</div>
          </td>
        </tr>

        <!-- Formal signature block -->
        <tr>
          <td class="px-32" style="padding:16px 32px 32px 32px;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr>
                <td style="font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                  <div style="font-size:16px;font-weight:700;color:#0A0066;line-height:1.3;">Hana Fakov\u00e1</div>
                  <div style="font-size:14px;font-weight:400;color:#555555;line-height:1.4;margin-top:2px;">Event Producer</div>
                  <div style="font-size:13px;font-weight:500;color:#0A0066;line-height:1.5;margin-top:8px;">United Arts s.r.o. | Losers Cirque Company | Divadlo BRAVO!</div>
                  <div style="font-size:13px;font-weight:400;color:#333333;line-height:1.6;margin-top:12px;">
                    M:&nbsp;&nbsp;<a href="tel:+420737853490" style="color:#333333;text-decoration:none;">+420 737 853 490</a>
                  </div>
                  <div style="font-size:13px;font-weight:400;color:#333333;line-height:1.6;">
                    E:&nbsp;&nbsp;<a href="mailto:hana@unitedarts.cz" style="color:#1A0DAB;text-decoration:none;">hana@unitedarts.cz</a>
                  </div>
                  <div style="font-size:13px;font-weight:400;color:#1A0DAB;line-height:1.6;margin-top:8px;">
                    <a href="https://www.unitedarts.cz" style="color:#1A0DAB;text-decoration:none;">www.unitedarts.cz</a> | <a href="https://www.loserscirque.cz" style="color:#1A0DAB;text-decoration:none;">www.loserscirque.cz</a> | <a href="https://www.divadlobravo.cz" style="color:#1A0DAB;text-decoration:none;">www.divadlobravo.cz</a>
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f4f4f7;padding:20px 32px;border-top:1px solid #e6e6ec;">
            <p style="margin:0 0 4px 0;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;line-height:1.5;color:#888;text-align:center;">
              United Arts s.r.o. \u00b7 Praha \u00b7 \u010cesk\u00e1 republika
            </p>
            <p style="margin:0;font-family:Barlow,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;line-height:1.5;color:#888;text-align:center;">
              Tento e-mail jste obdr\u017eel jako partner Losers Cirque Company pro sez\u00f3nu 2026. Pokud si nep\u0159ejete dal\u0161\u00ed zpr\u00e1vy, <a href="mailto:hana@unitedarts.cz?subject=unsubscribe" style="color:#888;text-decoration:underline;">odhla\u0161te se</a>.
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Plain text version (richer than before — mirrors HTML structure)
# ---------------------------------------------------------------------------

EVENTFEST_PLAIN_TEMPLATE = """\
LOSERS CIRQUE COMPANY
---------------------

Hezk\u00fd den, {{vocative_name}},

{{you_look_verb}} zaj\u00edmav\u00fd opening pro konferenci, gala ve\u010de\u0159i \u010di spole\u010densk\u00e9 setk\u00e1n\u00ed?

Losers Cirque Company m\u00e1 pro {{you_acc}} n\u011bkolik novinek, kter\u00e9 si {{you_can_verb}} prohl\u00e9dnout v na\u0161\u00ed aktualizovan\u00e9 nab\u00eddce vystoupen\u00ed ({{microsite_link}}).

N\u011bkter\u00e1 z nich {{you_can_verb}} vid\u011bt i na\u017eivo v r\u00e1mci akce EVENT FEST ve st\u0159edu 22.4.2026 na pra\u017esk\u00e9m V\u00fdstavi\u0161ti Let\u0148any. Od 12:00 hodin na Expo stage {{you_can_verb}} t\u011b\u0161it na Hat Jazz a od 13:00 hodin v r\u00e1mci prostoru Experience show na Handstand.

{{stop_by_imper}} i na na\u0161em st\u00e1nku, budeme se na {{you_acc}} t\u011b\u0161it.

Vybrali jsme pro {{you_acc}} \u010dty\u0159i p\u0159edstaven\u00ed, kter\u00e1 stoj\u00ed za pozornost:
- Complicit\u00e9 \u2014 P\u011bt akrobat\u016f, s\u00edla a d\u016fv\u011bra ve vizu\u00e1ln\u011b strhuj\u00edc\u00ed choreografii.
- Glamour in Red \u2014 \u017div\u00e9 sochy v \u010derven\u00e9, smysln\u00e1 a elegantn\u00ed animace.
- Aerial Hoop \u2014 Armagedon \u2014 S\u00f3lo na z\u00e1v\u011bsn\u00e9m kruhu, ide\u00e1ln\u00ed pro gala ve\u010dery.
- Onyx \u2014 P\u00e1rov\u00e1 i skupinov\u00e1 akrobacie s handstandem.

Prohl\u00e9dn\u011bte si celou nab\u00eddku: {{microsite_link}}

Hanka

--
Hana Fakov\u00e1
Event Producer
United Arts s.r.o. | Losers Cirque Company | Divadlo BRAVO!
M: +420 737 853 490
E: hana@unitedarts.cz
www.unitedarts.cz | www.loserscirque.cz | www.divadlobravo.cz

United Arts s.r.o. \u00b7 Praha \u00b7 \u010cesk\u00e1 republika
Pokud si nep\u0159ejete dal\u0161\u00ed zpr\u00e1vy, odpov\u011bzte na tento e-mail (hana@unitedarts.cz) s p\u0159edm\u011btem "unsubscribe"."""


def _replace_template_variables(template: str, variables: dict[str, str]) -> str:
    """Replace ``{{variable}}`` placeholders in a template string."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value or "")
    return result


def _escape_html_attr(value: str) -> str:
    """Minimal HTML attribute escaping for trusted-but-unsafe input.

    Retained for backwards compatibility with the dynamic featured-acts
    helper below (kept only so downstream imports don't break — the v4
    template hardcodes its 4 thumbnails).
    """
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_html_text(value: str) -> str:
    """Minimal HTML text-node escaping. See ``_escape_html_attr`` note."""
    return (
        value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _build_featured_acts_html(
    featured_acts: list[dict] | None,
    site_url: str,
    recipient_token: str,
) -> str:
    """Dynamic thumbnail grid builder (legacy path — kept for callers).

    The v4 approved template hardcodes its 4 thumbnails inline and does
    not reference the ``{{featured_acts_section}}`` placeholder, so this
    helper's output is not threaded through ``render_eventfest_email``
    anymore. Retained so any external caller that imported this symbol
    still resolves, and because ``_build_featured_acts_plain`` callers
    may still invoke it during tests.

    Returns an empty string when ``featured_acts`` is falsy so the
    surrounding template renders without any placeholder artefacts.
    """
    if not featured_acts:
        return ""

    acts = list(featured_acts)[:4]
    site_url_clean = site_url.rstrip("/")

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
    """Plain-text featured-acts list (legacy — see ``_build_featured_acts_html``).

    The v4 template inlines its own featured-acts bullet list; callers
    that still invoke this helper (or import it) get identical behaviour
    to the previous releases.
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
    """Render the EventFest invitation email (v4 approved design).

    Args:
        vocative_name: Contact's name already in vocative form (or ``None``).
        microsite_link: Full URL to the contact's personalised microsite invite.
        recipient_token: Accepted for backwards compatibility — the v4
            template hardcodes its thumbnails and links all CTAs to
            ``microsite_link``, so this value is no longer baked into
            detail-page query strings.
        site_url: Accepted for backwards compatibility — the v4 template
            hardcodes asset URLs to ``https://booking.loserscirque.cz``.
        featured_acts: Accepted for backwards compatibility — the v4
            template hardcodes its 4 thumbnails (Complicité,
            Glamour in Red, Aerial Hoop — Armagedon, Onyx). Passing a
            list is a no-op; the legacy ``_build_featured_acts_html``
            helper is retained only for external callers.
        tone: Address style — ``"vykat"`` (formal, default), ``"tykat"``
            (informal), or ``TONE_PASSTHROUGH`` to keep tone placeholders
            unsubstituted for later per-recipient rendering. Any other
            value (including ``None`` and ``""``) falls back to ``vykat``
            so a missing ``address_style`` still produces a valid email.

    Returns:
        Tuple of ``(subject, html_body, plain_text_body)``.
    """
    # recipient_token, site_url, featured_acts accepted for API stability
    # but the v4 template doesn't consume them (hardcoded thumbnails).
    del recipient_token, site_url, featured_acts  # silence unused warnings

    variables: dict[str, str] = {
        "vocative_name": vocative_name or "",
        "microsite_link": microsite_link,
    }
    # Tone overlay: normal tones produce the final pronoun strings; the
    # passthrough sentinel keeps ``{{you_acc}}`` etc. literal so the
    # provisioner's stored body survives re-rendering at send time.
    if tone == TONE_PASSTHROUGH:
        variables.update(_tone_passthrough_variables())
    else:
        variables.update(tone_variables(tone))

    html = _replace_template_variables(EVENTFEST_HTML_TEMPLATE, variables)
    plain = _replace_template_variables(EVENTFEST_PLAIN_TEMPLATE, variables)

    return (EVENTFEST_SUBJECT, html, plain)
