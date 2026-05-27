"""SendGrid email service.

Thin wrapper around the SendGrid API for transactional emails.

Usage
-----
Call ``send_welcome_email(...)`` from a FastAPI ``BackgroundTasks`` task so it
never blocks or breaks the HTTP response:

    background_tasks.add_task(
        send_welcome_email,
        brokerage_name="Sunrise Realty",
        assistant_name="Penny",
        to_email="broker@example.com",
        state="TX",
    )

If ``SENDGRID_API_KEY`` is absent the call is a no-op (logs + returns). This
keeps dev environments fully functional without SendGrid credentials.
"""

import logging
import textwrap

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def send_welcome_email(
    *,
    brokerage_name: str,
    assistant_name: str,
    to_email: str,
    state: str | None = None,
) -> None:
    """Send the onboarding welcome email to the brokerage owner.

    Args:
        brokerage_name: Display name of the brokerage.
        assistant_name: The AI assistant name chosen during onboarding (e.g. "Penny").
        to_email:       Recipient email address (brokerage owner).
        state:          Two-letter US state code, used for compliance copy.
    """
    if not settings.SENDGRID_API_KEY:
        logger.info(
            "SendGrid not configured — skipping welcome email to %s", to_email
        )
        return

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        logger.error(
            "sendgrid package not installed — run `pip install sendgrid`"
        )
        return

    subject = f"Welcome to Penny — {assistant_name} is ready for your team"
    html_body = _build_html(
        brokerage_name=brokerage_name,
        assistant_name=assistant_name,
        state=state,
    )
    plain_body = _build_plain(
        brokerage_name=brokerage_name,
        assistant_name=assistant_name,
        state=state,
    )

    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=plain_body,
        html_content=html_body,
    )

    try:
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(
            "Welcome email sent to %s (HTTP %s)", to_email, response.status_code
        )
    except Exception as exc:  # noqa: BLE001
        # Never let a failed email crash the caller — log and move on.
        logger.error("Failed to send welcome email to %s: %s", to_email, exc)


# ---------------------------------------------------------------------------
# Email content builders
# ---------------------------------------------------------------------------

_BRAND_VIOLET = "#7C3AED"
_BRAND_VIOLET_DARK = "#6D28D9"
_TEXT_DARK = "#111827"
_TEXT_MUTED = "#6B7280"
_BG = "#F9FAFB"
_WHITE = "#FFFFFF"


def _build_html(
    *,
    brokerage_name: str,
    assistant_name: str,
    state: str | None,
) -> str:
    state_line = ""
    if state:
        state_line = (
            f"<li>✅ <strong>Compliance-ready</strong> — "
            f"Built for {state} real estate regulations, with human review on every flag.</li>"
        )

    dashboard_url = settings.FRONTEND_URL.rstrip("/")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Welcome to Penny</title>
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{_WHITE};border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">

          <!-- Header -->
          <tr>
            <td style="background:{_BRAND_VIOLET};padding:32px 40px;text-align:center;">
              <p style="margin:0;color:{_WHITE};font-size:28px;font-weight:700;letter-spacing:-0.5px;">Penny</p>
              <p style="margin:6px 0 0;color:rgba(255,255,255,.8);font-size:14px;font-weight:500;">Virtual Transaction Coordinator</p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:{_TEXT_DARK};">
                Your AI transaction coordinator is live 🎉
              </h1>
              <p style="margin:0 0 24px;font-size:15px;color:{_TEXT_MUTED};line-height:1.6;">
                Hi <strong style="color:{_TEXT_DARK};">{brokerage_name}</strong>,
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:{_TEXT_DARK};line-height:1.6;">
                <strong>{assistant_name}</strong> is ready to help your team manage real estate
                transactions from contract to close — 24 hours a day, 7 days a week.
              </p>

              <!-- Capabilities -->
              <table width="100%" cellpadding="0" cellspacing="0"
                     style="background:#F5F3FF;border-radius:8px;padding:0;margin-bottom:28px;">
                <tr>
                  <td style="padding:20px 24px;">
                    <p style="margin:0 0 12px;font-size:13px;font-weight:600;color:{_BRAND_VIOLET};text-transform:uppercase;letter-spacing:.5px;">
                      What {assistant_name} can do
                    </p>
                    <ul style="margin:0;padding-left:18px;font-size:14px;color:{_TEXT_DARK};line-height:1.8;">
                      <li>📋 <strong>Transaction tracking</strong> — Upload contracts and {assistant_name} auto-extracts the key deal details.</li>
                      <li>📱 <strong>WhatsApp access</strong> — Agents can text or voice-memo {assistant_name} anytime to get updates or make changes.</li>
                      {state_line}
                      <li>🔔 <strong>Deadline reminders</strong> — Coming soon: automated reminders for contingency and closing deadlines.</li>
                    </ul>
                  </td>
                </tr>
              </table>

              <!-- CTA -->
              <table cellpadding="0" cellspacing="0" style="margin-bottom:32px;">
                <tr>
                  <td align="center"
                      style="background:{_BRAND_VIOLET};border-radius:8px;">
                    <a href="{dashboard_url}"
                       style="display:inline-block;padding:14px 32px;font-size:15px;font-weight:600;color:{_WHITE};text-decoration:none;letter-spacing:.2px;">
                      Open Your Dashboard →
                    </a>
                  </td>
                </tr>
              </table>

              <!-- Quick-start tips -->
              <p style="margin:0 0 8px;font-size:14px;font-weight:600;color:{_TEXT_DARK};">Quick-start tips</p>
              <ol style="margin:0 0 24px;padding-left:18px;font-size:14px;color:{_TEXT_DARK};line-height:1.8;">
                <li>Go to <strong>Transactions → New</strong> and upload a contract PDF — {assistant_name} will fill in the details.</li>
                <li>Register your WhatsApp number in <strong>Settings → WhatsApp</strong> to start texting {assistant_name}.</li>
                <li>Invite your agents from the <strong>Team</strong> page (coming soon in Phase 2).</li>
              </ol>

              <p style="margin:0;font-size:14px;color:{_TEXT_MUTED};line-height:1.6;">
                Questions? Just reply to this email — we're here to help.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:{_BG};padding:20px 40px;border-top:1px solid #E5E7EB;text-align:center;">
              <p style="margin:0;font-size:12px;color:{_TEXT_MUTED};">
                © 2026 Penny &nbsp;·&nbsp; Virtual Brokerage Assistant
              </p>
              <p style="margin:4px 0 0;font-size:12px;color:{_TEXT_MUTED};">
                You're receiving this because you signed up for a Penny account.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _build_plain(
    *,
    brokerage_name: str,
    assistant_name: str,
    state: str | None,
) -> str:
    state_line = ""
    if state:
        state_line = (
            f"  • Compliance-ready — Built for {state} real estate regulations.\n"
        )

    dashboard_url = settings.FRONTEND_URL.rstrip("/")

    return textwrap.dedent(f"""\
        Welcome to Penny — {assistant_name} is ready for your team
        ============================================================

        Hi {brokerage_name},

        {assistant_name} is your AI-powered transaction coordinator, available
        24/7 to help your team manage real estate transactions from contract to close.

        WHAT {assistant_name.upper()} CAN DO
        -------------------------
          • Transaction tracking — Upload contracts and {assistant_name} auto-extracts deal details.
          • WhatsApp access — Agents can text or voice-memo {assistant_name} anytime.
        {state_line}  • Deadline reminders — Coming soon: automated reminders for key dates.

        OPEN YOUR DASHBOARD
        -------------------
        {dashboard_url}

        QUICK-START TIPS
        ----------------
        1. Go to Transactions → New and upload a contract PDF.
        2. Register your WhatsApp number in Settings → WhatsApp.
        3. Invite your agents from the Team page (coming soon).

        Questions? Reply to this email — we're here to help.

        —
        Penny · Virtual Brokerage Assistant
        You received this because you signed up for a Penny account.
    """)
