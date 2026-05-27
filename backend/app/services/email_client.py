"""SendGrid email service.

Thin wrapper around the SendGrid API plus the **intro email** — the
introduction Penny sends to everyone on a transaction (buyer, seller, agents,
lender, title) once a deal is underway, presenting herself as the coordinator
(PRD task ``intro-email``).

``send_email`` is a logged no-op when ``SENDGRID_API_KEY`` is absent, so dev
environments work without SendGrid credentials, and it never raises — callers
can treat email as best-effort.
"""

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Parties on a transaction that can receive the intro email, in roster order.
# (role label, name column, email column)
_INTRO_PARTY_FIELDS: list[tuple[str, str, str]] = [
    ("Buyer", "buyer_name", "buyer_email"),
    ("Seller", "seller_name", "seller_email"),
    ("Listing agent", "listing_agent_name", "listing_agent_email"),
    ("Selling agent", "selling_agent_name", "selling_agent_email"),
    ("Lender", "lender_name", "lender_email"),
    ("Title company", "title_company", "title_email"),
    ("Transaction coordinator", "tc_name", "tc_email"),
]


# --------------------------------------------------------------------------- #
# Intro-email party gathering
# --------------------------------------------------------------------------- #

def gather_intro_parties(tx: dict[str, Any]) -> list[dict[str, str]]:
    """Return the transaction's parties that have an email address on file.

    Each entry is ``{"role", "name", "email"}``. Parties without an email are
    omitted (you can't introduce someone you can't reach).
    """
    parties: list[dict[str, str]] = []
    for role, name_col, email_col in _INTRO_PARTY_FIELDS:
        email = (tx.get(email_col) or "").strip()
        if not email:
            continue
        name = (tx.get(name_col) or "").strip() or role
        parties.append({"role": role, "name": name, "email": email})
    return parties


def _dedupe_emails(emails: list[str]) -> list[str]:
    """Drop duplicate addresses (case-insensitive) while preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for e in emails:
        key = e.lower()
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# --------------------------------------------------------------------------- #
# Core sender
# --------------------------------------------------------------------------- #

def send_email(*, to_emails: list[str], subject: str, html: str, plain: str) -> bool:
    """Send a single email to one or more recipients.

    Returns True if SendGrid accepted the message, False otherwise. A single
    message is sent with all addresses on the To line, so recipients can see and
    reply-all to each other — exactly what an introduction should do.

    No-op (returns False) when ``SENDGRID_API_KEY`` is unset. Never raises.
    """
    recipients = _dedupe_emails([e for e in (to_emails or []) if e and e.strip()])
    if not recipients:
        logger.warning("send_email called with no recipients — skipping '%s'", subject)
        return False

    if not settings.SENDGRID_API_KEY:
        logger.info(
            "SendGrid not configured — skipping email '%s' to %s",
            subject,
            ", ".join(recipients),
        )
        return False

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        logger.error("sendgrid package not installed — run `pip install sendgrid`")
        return False

    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=recipients,
        subject=subject,
        plain_text_content=plain,
        html_content=html,
    )
    try:
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        logger.info(
            "Email '%s' sent to %d recipient(s) (HTTP %s)",
            subject,
            len(recipients),
            response.status_code,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email '%s': %s", subject, exc)
        return False


# --------------------------------------------------------------------------- #
# Intro-email orchestration
# --------------------------------------------------------------------------- #

def send_intro_email(tx: dict[str, Any], brokerage_name: str) -> dict[str, Any]:
    """Build and send the intro email to every party with an email on file.

    Returns ``{"sent": bool, "recipients": [...], "reason": str | None}`` so the
    caller can report what happened and decide whether to flag the transaction
    as ``intro_email_sent``.
    """
    parties = gather_intro_parties(tx)
    if not parties:
        return {
            "sent": False,
            "recipients": [],
            "reason": "no parties have email addresses on file",
        }

    subject, html, plain = build_intro_content(tx, brokerage_name)
    sent = send_email(
        to_emails=[p["email"] for p in parties],
        subject=subject,
        html=html,
        plain=plain,
    )
    return {
        "sent": sent,
        "recipients": parties,
        "reason": None if sent else "SendGrid not configured or the send failed",
    }


# --------------------------------------------------------------------------- #
# Intro-email content
# --------------------------------------------------------------------------- #

_BRAND_VIOLET = "#7C3AED"
_TEXT_DARK = "#111827"
_TEXT_MUTED = "#6B7280"
_BG = "#F9FAFB"
_WHITE = "#FFFFFF"


def _intro_dates(tx: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (label, value) pairs for the key dates present on the deal."""
    pairs: list[tuple[str, str]] = []
    if tx.get("contract_date"):
        pairs.append(("Contract date", str(tx["contract_date"])))
    if tx.get("closing_date"):
        pairs.append(("Closing date", str(tx["closing_date"])))
    return pairs


def build_intro_content(
    tx: dict[str, Any], brokerage_name: str
) -> tuple[str, str, str]:
    """Build ``(subject, html, plain)`` for the intro email."""
    address = (tx.get("address") or "your transaction").strip()
    parties = gather_intro_parties(tx)
    dates = _intro_dates(tx)
    subject = f"Introductions — {address}"

    return subject, _intro_html(address, brokerage_name, parties, dates), _intro_plain(
        address, brokerage_name, parties, dates
    )


def _intro_html(
    address: str,
    brokerage_name: str,
    parties: list[dict[str, str]],
    dates: list[tuple[str, str]],
) -> str:
    roster = "".join(
        f'<li style="margin-bottom:4px;"><strong>{p["role"]}:</strong> {p["name"]}</li>'
        for p in parties
    )
    date_rows = "".join(
        f'<li style="margin-bottom:4px;"><strong>{label}:</strong> {value}</li>'
        for label, value in dates
    )
    date_block = (
        f'<p style="margin:0 0 8px;font-size:14px;font-weight:600;color:{_TEXT_DARK};">Key dates</p>'
        f'<ul style="margin:0 0 24px;padding-left:18px;font-size:14px;color:{_TEXT_DARK};line-height:1.7;">{date_rows}</ul>'
        if date_rows
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Introductions — {address}</title>
</head>
<body style="margin:0;padding:0;background:{_BG};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{_BG};padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{_WHITE};border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08);">
          <tr>
            <td style="background:{_BRAND_VIOLET};padding:28px 40px;text-align:center;">
              <p style="margin:0;color:{_WHITE};font-size:24px;font-weight:700;letter-spacing:-0.5px;">Penny</p>
              <p style="margin:6px 0 0;color:rgba(255,255,255,.85);font-size:13px;font-weight:500;">Transaction Coordinator · {brokerage_name}</p>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 40px 32px;">
              <h1 style="margin:0 0 16px;font-size:20px;font-weight:700;color:{_TEXT_DARK};">
                Introductions for {address}
              </h1>
              <p style="margin:0 0 20px;font-size:15px;color:{_TEXT_DARK};line-height:1.6;">
                Hi everyone — I'm Penny, the transaction coordinator working with
                <strong>{brokerage_name}</strong> on the transaction at <strong>{address}</strong>.
                I'll be helping keep everyone aligned through closing. I've put you all on this
                thread so you have each other's contact details in one place.
              </p>
              <p style="margin:0 0 8px;font-size:14px;font-weight:600;color:{_TEXT_DARK};">Who's involved</p>
              <ul style="margin:0 0 24px;padding-left:18px;font-size:14px;color:{_TEXT_DARK};line-height:1.7;">
                {roster}
              </ul>
              {date_block}
              <p style="margin:0;font-size:14px;color:{_TEXT_MUTED};line-height:1.6;">
                Please reply all if you have questions or need anything — I'll keep this thread
                updated as we move toward closing.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:{_BG};padding:18px 40px;border-top:1px solid #E5E7EB;text-align:center;">
              <p style="margin:0;font-size:12px;color:{_TEXT_MUTED};">
                Sent by Penny on behalf of {brokerage_name}
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _intro_plain(
    address: str,
    brokerage_name: str,
    parties: list[dict[str, str]],
    dates: list[tuple[str, str]],
) -> str:
    lines = [
        f"Introductions for {address}",
        "=" * 40,
        "",
        f"Hi everyone — I'm Penny, the transaction coordinator working with "
        f"{brokerage_name} on the transaction at {address}. I'll be helping keep "
        f"everyone aligned through closing. I've put you all on this thread so you "
        f"have each other's contact details in one place.",
        "",
        "WHO'S INVOLVED",
        "--------------",
    ]
    lines += [f"  • {p['role']}: {p['name']}" for p in parties]
    if dates:
        lines += ["", "KEY DATES", "---------"]
        lines += [f"  • {label}: {value}" for label, value in dates]
    lines += [
        "",
        "Please reply all if you have questions or need anything — I'll keep this "
        "thread updated as we move toward closing.",
        "",
        "—",
        f"Sent by Penny on behalf of {brokerage_name}",
    ]
    return "\n".join(lines)
