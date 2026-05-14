"""AITransformers Meetup #2 invitation email template.

Brand-grounded transactional email announcing the May 20 Prague meetup
("From Pilot to Production"). All design tokens come from the
**AITransformers design system** (``mcp__design-system__ds_get_brand``):

- ``primary``       ``#00BDD6``  cyan -- primary brand color, CTAs, accents
- ``primaryDark``   ``#0090A0``  dark cyan -- gradient ends
- ``secondaryBlue`` ``#0080FF``  blue -- gradient pair
- ``surfaceDark``   ``#080A0C``  dark navy -- hero background
- ``surfaceCard``   ``#111318``  card surface -- secondary panels
- ``border``        ``#272C35``  card border on dark
- ``text``          ``#FFFFFF``  white text on dark
- ``text-muted``    ``#E5E7EB``  light grey for body on dark
- ``text-dim``      ``#6B7280``  dim grey for tertiary copy
- ``font``          Sora (DS title + body family)
- Gradient          ``linear-gradient(135deg, #00BDD6, #0080FF)``
- Logo              shield-white SVG hosted at ds.visionvolve.com

The flyer the user provided (dark navy + subtle pattern + cyan accents +
white Sora wordmark + shield in top-right + Emplifi co-brand + speaker
portraits + white info card with date/venue) is reproduced as a
**designed dark hero** in pure HTML/CSS rather than a hot-linked image.
Reasons:

- Outlook strips background images and CSS gradients on TD elements
  unreliably; many corporate Outlook installs would have shown a blank
  navy box anyway. The shield logo is hosted as a remote SVG.
- Gmail's image proxy can rewrite hot-linked PNGs and trip "via" labels
  that look spammy in B2B inboxes.
- A pure-HTML hero keeps the email under 30KB (well below Gmail's
  102KB clipping threshold) and renders identically in dark-mode and
  light-mode Gmail.

Two placeholders are substituted per-recipient at send time:

- ``{{first_name}}`` -- Contact first name. Substituted in the greeting.
- ``{{unsubscribe_url}}`` -- Per-contact one-click unsubscribe link.

Substitution happens both in ``send_campaign_emails`` (production send
path) and in ``send-test`` / ``generate-preview`` (review path).

Visual choices:
- Dark hero band (``#080A0C``) with the white Sora wordmark
  "AI TRANSFORMERS" on the left and the shield SVG on the right
  (mirrors the flyer layout).
- Hero title "From Pilot to Production" in 34px Sora bold (white) with
  a 17px subtitle and a 64px cyan-to-blue gradient underline.
- White info card with date/venue mimicking the flyer's hero card,
  centered, with a cyan-gradient ``MAY 20 · 17:30`` chip.
- Light content area below (``#F8F9FC``) for high readability of body
  copy on every email client.
- Cyan CTA button rendered both via VML (Outlook) and HTML (rest) at
  18px/36px padding so the click target is comfortable on mobile.
- Speaker list is a compact bulleted list (no portraits in the email --
  the registration page has those); keeps the email scannable.
- Plain-text fallback mirrors the structure with the registration URL
  written out.
- ``Sora`` is declared first in the font stack with system fallbacks
  (``Inter``, ``-apple-system``, ``BlinkMacSystemFont``, ``Segoe UI``);
  Sora is intentionally *not* loaded via webfont because most email
  clients strip ``<link>`` to fonts.googleapis.com -- fallbacks render
  cleanly.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AITRANSFORMERS_MEETUP_TEMPLATE_KEY = "aitransformers_meetup_may2026"

AITRANSFORMERS_MEETUP_SUBJECT = (
    "Meetup 20 May · From Pilot to Production — why most AI projects die"
)

AITRANSFORMERS_MEETUP_REGISTRATION_URL = (
    "https://www.meetup.com/transform-prague-ai/events/314675972/"
)

# Hosted AI Transformers shield mark (white-on-dark) from the design system.
# This is served by ds.visionvolve.com and is the canonical brand logo.
AITRANSFORMERS_LOGO_URL = (
    "https://ds.visionvolve.com/assets/logos/aitransformers-icon-white.svg"
)


# ---------------------------------------------------------------------------
# HTML template (inline CSS for email-client compatibility)
# ---------------------------------------------------------------------------

AITRANSFORMERS_MEETUP_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light dark">
  <meta name="supported-color-schemes" content="light dark">
  <title>AI Transformers Meetup #2 · From Pilot to Production</title>
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
    body { margin:0 !important; padding:0 !important; width:100% !important; background:#080A0C; }
    a { color:#00BDD6; }
    @media only screen and (max-width:620px){
      .container { width:100% !important; }
      .px-32 { padding-left:20px !important; padding-right:20px !important; }
      .hero-title { font-size:28px !important; line-height:1.2 !important; }
      .hero-sub { font-size:15px !important; }
      .cta-btn { display:block !important; width:100% !important; box-sizing:border-box; }
      .info-card-cell { padding-left:16px !important; padding-right:16px !important; }
    }
  </style>
</head>
<body style="margin:0;padding:0;background:#080A0C;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#FFFFFF;">

<!-- Preheader (hidden in body, surfaces in inbox preview) -->
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#080A0C;">
  AI Transformers Meetup #2 · Wed May 20 · 17:30 · Emplifi, Karlín Prague. From Pilot to Production with Ohad Hecht, Petra Lovčinská, Dario Sapienza.
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#080A0C" style="background:#080A0C;">
  <tr>
    <td align="center" style="padding:0;">
      <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background:#080A0C;">

        <!-- ===== DARK HERO BAND (mirrors the flyer's navy + cyan + Sora wordmark) ===== -->
        <tr>
          <td bgcolor="#080A0C" style="background:#080A0C;padding:36px 32px 8px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <!-- Wordmark, top-left -->
                <td align="left" valign="middle" style="font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:700;letter-spacing:0.16em;font-size:13px;line-height:1;color:#FFFFFF;text-transform:uppercase;">
                  AI&nbsp;Transformers
                </td>
                <!-- Shield mark, top-right -->
                <td align="right" valign="middle" width="36">
                  <img src="https://ds.visionvolve.com/assets/logos/aitransformers-icon-white.svg" alt="AI Transformers" width="28" height="28" style="display:inline-block;width:28px;height:28px;border:0;">
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Hero title -->
        <tr>
          <td class="px-32" bgcolor="#080A0C" style="background:#080A0C;padding:28px 32px 8px 32px;">
            <div style="font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:600;font-size:12px;letter-spacing:0.18em;color:#00BDD6;text-transform:uppercase;margin-bottom:18px;">
              Meetup #2 · Prague
            </div>
            <h1 class="hero-title" style="margin:0 0 12px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:34px;line-height:1.15;font-weight:700;color:#FFFFFF;letter-spacing:-0.01em;">
              From Pilot to Production
            </h1>
            <p class="hero-sub" style="margin:0 0 4px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:17px;line-height:1.45;font-weight:500;color:#E5E7EB;">
              Why Most AI Projects Die — and What the 10% Do Differently
            </p>
            <div style="height:3px;width:64px;background-color:#00BDD6;background-image:linear-gradient(90deg,#00BDD6 0%,#0080FF 100%);margin:22px 0 0 0;line-height:3px;font-size:0;">&nbsp;</div>
          </td>
        </tr>

        <!-- White info card (date + venue), centered, mimics flyer hero card -->
        <tr>
          <td class="px-32 info-card-cell" bgcolor="#080A0C" style="background:#080A0C;padding:28px 32px 36px 32px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#FFFFFF;border-radius:12px;">
              <tr>
                <td align="center" style="padding:22px 20px 22px 20px;">
                  <div style="display:inline-block;background-color:#00BDD6;background-image:linear-gradient(135deg,#00BDD6 0%,#0080FF 100%);color:#FFFFFF;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:700;font-size:11px;letter-spacing:0.2em;text-transform:uppercase;padding:6px 12px;border-radius:999px;">
                    May 20 · 17:30
                  </div>
                  <div style="margin-top:14px;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:700;font-size:18px;line-height:1.3;color:#080A0C;">
                    Wednesday, May 20
                  </div>
                  <div style="margin-top:4px;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#404B5C;">
                    5:30 – 8:00 PM · Emplifi, Pernerova 51, Karlín
                  </div>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- ===== LIGHT CONTENT AREA (body, speakers, CTA, signature) ===== -->
        <tr>
          <td bgcolor="#F8F9FC" style="background:#F8F9FC;padding:0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">

              <!-- Greeting + intro paragraphs -->
              <tr>
                <td class="px-32" style="padding:36px 32px 0 32px;">
                  <p style="margin:0 0 20px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:16px;line-height:1.6;color:#111318;">
                    Hello {{first_name}},
                  </p>
                  <p style="margin:0 0 18px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.65;color:#111318;">
                    Everyone is running AI pilots. Almost nobody&rsquo;s getting them to production. This second AI Transformers meetup, in cooperation with Emplifi, focuses on what actually happens between &ldquo;we tried it&rdquo; and &ldquo;it runs our business&rdquo; — the organizational blockers, data gaps, budget battles, and change-management challenges that determine whether AI initiatives succeed or stall.
                  </p>
                  <p style="margin:0 0 28px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.65;color:#111318;">
                    We&rsquo;ll bring together real stories from people who shipped and people who failed, to explore what separates the few AI projects that make it to production from the many that don&rsquo;t.
                  </p>
                </td>
              </tr>

              <!-- CTA button -->
              <tr>
                <td class="px-32" align="center" style="padding:4px 32px 28px 32px;">
                  <!--[if mso]>
                  <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="https://www.meetup.com/transform-prague-ai/events/314675972/" style="height:56px;v-text-anchor:middle;width:280px;" arcsize="14%" stroke="f" fillcolor="#00BDD6">
                    <w:anchorlock/>
                    <center style="color:#FFFFFF;font-family:Arial,sans-serif;font-size:16px;font-weight:700;">Register on Meetup</center>
                  </v:roundrect>
                  <![endif]-->
                  <!--[if !mso]><!-- -->
                  <a class="cta-btn" href="https://www.meetup.com/transform-prague-ai/events/314675972/"
                     style="display:inline-block;background-color:#00BDD6;background-image:linear-gradient(135deg,#00BDD6 0%,#0080FF 100%);color:#FFFFFF;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:700;font-size:16px;letter-spacing:0.02em;text-decoration:none;padding:18px 36px;border-radius:8px;mso-hide:all;">
                    Register on Meetup →
                  </a>
                  <!--<![endif]-->
                </td>
              </tr>

              <!-- Event details (small repeat below CTA for scannability) -->
              <tr>
                <td class="px-32" align="center" style="padding:0 32px 8px 32px;">
                  <p style="margin:0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;color:#6B7280;">
                    Wednesday, May 20 · 5:30&nbsp;PM · Emplifi, Pernerova 51, Karlín
                  </p>
                </td>
              </tr>

              <!-- Speakers -->
              <tr>
                <td class="px-32" style="padding:28px 32px 0 32px;">
                  <div style="font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:12px;font-weight:700;letter-spacing:0.16em;color:#0090A0;text-transform:uppercase;margin-bottom:14px;">
                    Speakers
                  </div>
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                    <tr><td style="padding:0 0 10px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#111318;">
                      <strong style="color:#080A0C;">Ohad Hecht</strong> — <span style="color:#6B7280;">CEO, Emplifi</span>
                    </td></tr>
                    <tr><td style="padding:0 0 10px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#111318;">
                      <strong style="color:#080A0C;">Petra Lovčinská</strong> — <span style="color:#6B7280;">AI Business Implementation Lead, Raiffeisenbank Czech Republic</span>
                    </td></tr>
                    <tr><td style="padding:0 0 14px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#111318;">
                      <strong style="color:#080A0C;">Dario Sapienza</strong> — <span style="color:#6B7280;">Principal Group Software Engineering Manager, Microsoft</span>
                    </td></tr>
                  </table>
                  <div style="margin:6px 0 0 0;padding-top:14px;border-top:1px solid #E5E7EB;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:14px;line-height:1.5;color:#111318;">
                    <span style="color:#6B7280;">Moderator:</span> <strong style="color:#080A0C;">Michal Ličko</strong> — <span style="color:#6B7280;">CEO, Visionvolve</span>
                  </div>
                </td>
              </tr>

              <!-- Sign-off -->
              <tr>
                <td class="px-32" style="padding:28px 32px 0 32px;">
                  <p style="margin:0 0 4px 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#111318;">
                    Looking forward to seeing you,
                  </p>
                  <p style="margin:0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.6;color:#111318;">
                    — Barbora
                  </p>
                </td>
              </tr>

              <!-- Signature block -->
              <tr>
                <td class="px-32" style="padding:18px 32px 32px 32px;">
                  <div style="padding-top:16px;border-top:1px solid #E5E7EB;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;color:#6B7280;">
                    <div style="color:#080A0C;font-weight:600;">Barbora Maroto</div>
                    <div>AI Transformers · Visionvolve</div>
                    <div><a href="mailto:barbora.maroto@aitransformers.eu" style="color:#0090A0;text-decoration:none;">barbora.maroto@aitransformers.eu</a></div>
                  </div>
                </td>
              </tr>

            </table>
          </td>
        </tr>

        <!-- Footer (dark) -->
        <tr>
          <td bgcolor="#080A0C" style="background:#080A0C;padding:20px 32px 28px 32px;border-top:1px solid #272C35;">
            <p style="margin:0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:11px;line-height:1.5;color:#6B7280;text-align:center;">
              You received this because you signed up for AI Transformers updates.
              <a href="{{unsubscribe_url}}" style="color:#6B7280;text-decoration:underline;">Unsubscribe</a>.
            </p>
            <p style="margin:8px 0 0 0;font-family:'Sora','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:10px;line-height:1.5;color:#404B5C;text-align:center;letter-spacing:0.1em;text-transform:uppercase;">
              AI Transformers · Visionvolve
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
# Plain-text fallback (mirrors the HTML content)
# ---------------------------------------------------------------------------

AITRANSFORMERS_MEETUP_PLAIN = """\
AI TRANSFORMERS · MEETUP #2
Wednesday, May 20 · 5:30 – 8:00 PM
Emplifi, Pernerova 51, Karlín, Prague

Hello {{first_name}},

FROM PILOT TO PRODUCTION
Why Most AI Projects Die — and What the 10% Do Differently

Everyone is running AI pilots. Almost nobody's getting them to production. This second AI Transformers meetup, in cooperation with Emplifi, focuses on what actually happens between "we tried it" and "it runs our business" — the organizational blockers, data gaps, budget battles, and change-management challenges that determine whether AI initiatives succeed or stall.

We'll bring together real stories from people who shipped and people who failed, to explore what separates the few AI projects that make it to production from the many that don't.

REGISTER ON MEETUP:
https://www.meetup.com/transform-prague-ai/events/314675972/

SPEAKERS
- Ohad Hecht — CEO, Emplifi
- Petra Lovčinská — AI Business Implementation Lead, Raiffeisenbank Czech Republic
- Dario Sapienza — Principal Group Software Engineering Manager, Microsoft

Moderator: Michal Ličko — CEO, Visionvolve

Looking forward to seeing you,
— Barbora

--
Barbora Maroto
AI Transformers · Visionvolve
barbora.maroto@aitransformers.eu

To unsubscribe: {{unsubscribe_url}}"""


def render_aitransformers_meetup() -> dict[str, str]:
    """Return the meetup invitation as a placeholder-bearing payload.

    The returned ``html`` and ``text`` strings contain ``{{first_name}}`` and
    ``{{unsubscribe_url}}`` placeholders that are substituted per-recipient
    by the send-service (and by ``send-test`` / ``generate-preview``) at
    render time. This function exists so the route handler and any test
    helpers can pull the canonical body from one place.
    """
    return {
        "subject": AITRANSFORMERS_MEETUP_SUBJECT,
        "html": AITRANSFORMERS_MEETUP_HTML,
        "text": AITRANSFORMERS_MEETUP_PLAIN,
    }
