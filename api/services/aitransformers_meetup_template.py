"""AITransformers Meetup #2 invitation email template.

A fixed, transactional-style email body announcing the May 20 Prague meetup
("From Pilot to Production"). The body is plain HTML with inline CSS, max
600px wide, branded in AITransformers cyan-gradient palette (``#00BDD6``
→ ``#0080FF``), and intentionally minimal: no images required, no
JavaScript, table-based layout for Gmail/Outlook/Apple Mail
compatibility.

Two placeholders are substituted per-recipient at send time:

- ``{{first_name}}`` — Contact first name. Substituted in the greeting.
- ``{{unsubscribe_url}}`` — Per-contact one-click unsubscribe link.
  Substituted in the footer (falls back to a mailto when unsubscribe
  infrastructure is unavailable).

Substitution happens both in ``send_campaign_emails`` (production send
path) and in ``send-test`` / ``generate-preview`` (review path). The
HTML is stored verbatim in ``Message.body`` by the
``POST /api/campaigns/<id>/set-template-body`` endpoint and substituted
each time the body is rendered.

Brand palette is mirrored from the live AITransformers site
(``aitransformers-platform/site/src/components/theme/tokens.css``):

- Primary cyan: ``#0097a7``
- Primary glow: ``#00BDD6``
- Header gradient: ``#00BDD6 → #0080FF`` (matches the wordmark SVG)
- Body text: ``#111318``
- Muted text: ``#6b7280``
- Surface: ``#FFFFFF`` card on ``#F8F9FC`` page

Visual choices:
- Compact 600px transactional layout — no hero image (Outlook strips
  bg-images), wordmark rendered as styled text to avoid hot-linking.
- CTA button rendered both via VML (Outlook) and HTML (rest) at a
  generous 16px / 32px padding so the click target is large.
- Speaker list is a compact bulleted list, not heavy cards — keeps the
  email scannable on mobile.
- Plain-text fallback mirrors the structure with the registration URL
  written out.
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

# ---------------------------------------------------------------------------
# HTML template (inline CSS for email-client compatibility)
# ---------------------------------------------------------------------------

AITRANSFORMERS_MEETUP_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>Meetup 20 May · From Pilot to Production</title>
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
    body { margin:0 !important; padding:0 !important; width:100% !important; background:#F8F9FC; }
    a { color:#0097a7; }
    @media only screen and (max-width:600px){
      .container { width:100% !important; }
      .px-32 { padding-left:20px !important; padding-right:20px !important; }
      .hero-h1 { font-size:22px !important; line-height:1.25 !important; }
      .cta-btn { display:block !important; width:100% !important; box-sizing:border-box; }
    }
  </style>
</head>
<body style="margin:0;padding:0;background:#F8F9FC;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#111318;">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#F8F9FC;">
  AI Transformers Meetup #2 · Wednesday May 20 · 17:30 · Prague. From Pilot to Production with speakers from Emplifi, Raiffeisenbank, Microsoft.
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#F8F9FC;">
  <tr>
    <td align="center" style="padding:24px 12px;">
      <table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="width:600px;max-width:600px;background:#FFFFFF;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(17,19,24,0.06);">

        <!-- Header band: cyan gradient with AI TRANSFORMERS wordmark -->
        <tr>
          <td align="center" bgcolor="#0097a7" style="background:#0097a7;background-image:linear-gradient(135deg,#00BDD6 0%,#0080FF 100%);padding:32px 24px;">
            <div style="font-family:'Sora',Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:800;letter-spacing:0.08em;font-size:22px;line-height:1.1;color:#FFFFFF;text-transform:uppercase;">
              AI&nbsp;Transformers
            </div>
            <div style="margin-top:8px;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:13px;letter-spacing:0.04em;color:#E8FBFF;text-transform:uppercase;">
              Meetup #2 · Wed, May 20 · 17:30 · Prague
            </div>
          </td>
        </tr>

        <!-- Greeting + hero topic -->
        <tr>
          <td class="px-32" style="padding:36px 32px 8px 32px;">
            <p style="margin:0 0 24px 0;font-size:16px;line-height:1.6;color:#111318;">
              Hello {{first_name}},
            </p>
            <h1 class="hero-h1" style="margin:0 0 8px 0;font-family:'Sora',Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:26px;line-height:1.2;font-weight:700;color:#111318;letter-spacing:-0.01em;">
              From Pilot to Production: Why Most AI Projects Die — and What the 10% Do Differently
            </h1>
            <div style="height:3px;width:56px;background-image:linear-gradient(90deg,#00BDD6 0%,#0080FF 100%);margin:14px 0 24px 0;line-height:3px;font-size:0;">&nbsp;</div>
          </td>
        </tr>

        <!-- Body copy (verbatim, two paragraphs) -->
        <tr>
          <td class="px-32" style="padding:0 32px 8px 32px;">
            <p style="margin:0 0 16px 0;font-size:15px;line-height:1.65;color:#111318;">
              Everyone is running AI pilots. Almost nobody&rsquo;s getting them to production. This second AI Transformers meetup, in cooperation with Emplifi, focuses on what actually happens between &ldquo;we tried it&rdquo; and &ldquo;it runs our business&rdquo; — the organizational blockers, data gaps, budget battles, and change-management challenges that determine whether AI initiatives succeed or stall.
            </p>
            <p style="margin:0 0 28px 0;font-size:15px;line-height:1.65;color:#111318;">
              We&rsquo;ll bring together real stories from people who shipped and people who failed, to explore what separates the few AI projects that make it to production from the many that don&rsquo;t.
            </p>
          </td>
        </tr>

        <!-- Speakers -->
        <tr>
          <td class="px-32" style="padding:0 32px 8px 32px;">
            <div style="font-family:'Sora',Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:13px;font-weight:700;letter-spacing:0.08em;color:#0097a7;text-transform:uppercase;margin-bottom:12px;">
              Speakers
            </div>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr><td style="padding:0 0 10px 0;font-size:15px;line-height:1.5;color:#111318;">
                <strong>Ohad Hecht</strong> — <span style="color:#6b7280;">CEO, Emplifi</span>
              </td></tr>
              <tr><td style="padding:0 0 10px 0;font-size:15px;line-height:1.5;color:#111318;">
                <strong>Petra Lovčinská</strong> — <span style="color:#6b7280;">AI Business Implementation Lead, Raiffeisenbank Czech Republic</span>
              </td></tr>
              <tr><td style="padding:0 0 14px 0;font-size:15px;line-height:1.5;color:#111318;">
                <strong>Dario Sapienza</strong> — <span style="color:#6b7280;">Principal Group Software Engineering Manager, Microsoft</span>
              </td></tr>
            </table>
            <div style="margin:6px 0 0 0;padding-top:14px;border-top:1px solid #E5E7EB;font-size:14px;line-height:1.5;color:#111318;">
              <span style="color:#6b7280;">Moderator:</span> <strong>Michal Ličko</strong> — <span style="color:#6b7280;">CEO, Visionvolve</span>
            </div>
          </td>
        </tr>

        <!-- CTA button -->
        <tr>
          <td class="px-32" align="center" style="padding:32px 32px 8px 32px;">
            <!--[if mso]>
            <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="https://www.meetup.com/transform-prague-ai/events/314675972/" style="height:52px;v-text-anchor:middle;width:260px;" arcsize="12%" stroke="f" fillcolor="#0080FF">
              <w:anchorlock/>
              <center style="color:#FFFFFF;font-family:Arial,sans-serif;font-size:16px;font-weight:700;">Register on Meetup</center>
            </v:roundrect>
            <![endif]-->
            <!--[if !mso]><!-- -->
            <a class="cta-btn" href="https://www.meetup.com/transform-prague-ai/events/314675972/"
               style="display:inline-block;background:#0080FF;background-image:linear-gradient(135deg,#00BDD6 0%,#0080FF 100%);color:#FFFFFF;font-family:'Sora',Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-weight:700;font-size:16px;letter-spacing:0.02em;text-decoration:none;padding:16px 32px;border-radius:8px;mso-hide:all;">
              Register on Meetup →
            </a>
            <!--<![endif]-->
          </td>
        </tr>

        <!-- Closer -->
        <tr>
          <td class="px-32" style="padding:28px 32px 0 32px;">
            <p style="margin:0 0 6px 0;font-size:15px;line-height:1.6;color:#111318;">
              See you there.
            </p>
            <p style="margin:0;font-size:15px;line-height:1.6;color:#111318;">
              — Michal
            </p>
          </td>
        </tr>

        <!-- Signature -->
        <tr>
          <td class="px-32" style="padding:24px 32px 32px 32px;">
            <div style="padding-top:16px;border-top:1px solid #E5E7EB;font-size:13px;line-height:1.5;color:#6b7280;">
              <div style="color:#111318;font-weight:600;">Michal Ličko</div>
              <div>Visionvolve</div>
              <div><a href="mailto:michal@visionvolve.ai" style="color:#0097a7;text-decoration:none;">michal@visionvolve.ai</a></div>
            </div>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#F8F9FC;padding:18px 32px;border-top:1px solid #E5E7EB;">
            <p style="margin:0;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:11px;line-height:1.5;color:#9ca3af;text-align:center;">
              You received this because you signed up for AI Transformers updates.
              <a href="{{unsubscribe_url}}" style="color:#9ca3af;text-decoration:underline;">Unsubscribe</a>.
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
Wednesday, May 20 · 17:30 · Prague

Hello {{first_name}},

From Pilot to Production: Why Most AI Projects Die — and What the 10% Do Differently

Everyone is running AI pilots. Almost nobody's getting them to production. This second AI Transformers meetup, in cooperation with Emplifi, focuses on what actually happens between "we tried it" and "it runs our business" — the organizational blockers, data gaps, budget battles, and change-management challenges that determine whether AI initiatives succeed or stall.

We'll bring together real stories from people who shipped and people who failed, to explore what separates the few AI projects that make it to production from the many that don't.

SPEAKERS
- Ohad Hecht — CEO, Emplifi
- Petra Lovčinská — AI Business Implementation Lead, Raiffeisenbank Czech Republic
- Dario Sapienza — Principal Group Software Engineering Manager, Microsoft

Moderator: Michal Ličko — CEO, Visionvolve

Register on Meetup: https://www.meetup.com/transform-prague-ai/events/314675972/

See you there.
— Michal

--
Michal Ličko
Visionvolve
michal@visionvolve.ai

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
