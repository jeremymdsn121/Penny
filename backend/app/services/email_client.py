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

# Parties on a transaction, keyed by a stable role id. Used by the intro email
# (whole roster) and by deadline reminders (responsible_parties stores these
# keys). (key -> (role label, name column, email column))
_PARTY_BY_KEY: dict[str, tuple[str, str, str]] = {
    "buyer": ("Buyer", "buyer_name", "buyer_email"),
    "seller": ("Seller", "seller_name", "seller_email"),
    "listing_agent": ("Listing agent", "listing_agent_name", "listing_agent_email"),
    "selling_agent": ("Selling agent", "selling_agent_name", "selling_agent_email"),
    "lender": ("Lender", "lender_name", "lender_email"),
    "title": ("Title company", "title_company", "title_email"),
    "tc": ("Transaction coordinator", "tc_name", "tc_email"),
}

# Stable ordering for the intro-email roster (all parties).
_INTRO_PARTY_FIELDS: list[tuple[str, str, str]] = list(_PARTY_BY_KEY.values())

# Exposed so routes/agent can validate responsible_parties keys.
PARTY_KEYS: list[str] = list(_PARTY_BY_KEY.keys())


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


def gather_parties_by_keys(
    tx: dict[str, Any], keys: list[str]
) -> list[dict[str, str]]:
    """Resolve responsible-party role keys to contactable parties.

    Each entry is ``{"role", "name", "email"}`` for keys that map to a known
    party with an email on file. Unknown keys and parties without an email are
    skipped (you can't notify someone you can't reach).
    """
    parties: list[dict[str, str]] = []
    for key in keys or []:
        spec = _PARTY_BY_KEY.get(key)
        if not spec:
            continue
        role, name_col, email_col = spec
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

def from_email() -> str:
    """The configured outbound 'From' address (for logging outbound emails)."""
    return settings.SENDGRID_FROM_EMAIL


_DEFAULT_DISCLOSURE = (
    "Communications from this office may be drafted or assisted by artificial "
    "intelligence. All communications are reviewed and authorized by a licensed "
    "real estate professional before sending."
)


def disclosure_text(brokerage: dict[str, Any] | None) -> str | None:
    """The brokerage's AI-disclosure text, or None when disclosure is disabled.

    Defaults to enabled (the safe choice) when the brokerage row predates the
    setting columns.
    """
    if brokerage is None:
        return None
    enabled = brokerage.get("ai_disclosure_enabled")
    if enabled is False:
        return None
    return (brokerage.get("ai_disclosure_text") or _DEFAULT_DISCLOSURE).strip()


def reply_to_address(transaction_id: str | None) -> str | None:
    """Per-transaction Reply-To so inbound replies route back to this deal.

    Returns ``tx-{id}@<REPLY_EMAIL_DOMAIN>`` when a reply domain is configured,
    else None (reply threading disabled).
    """
    domain = (settings.REPLY_EMAIL_DOMAIN or "").strip()
    if not domain or not transaction_id:
        return None
    return f"tx-{transaction_id}@{domain}"


def _append_disclosure(html: str, plain: str, disclosure: str | None) -> tuple[str, str]:
    """Append a small, muted AI-disclosure footer to the email bodies."""
    if not disclosure:
        return html, plain
    import html as _html

    footer_html = (
        f'<div style="margin-top:24px;padding-top:12px;border-top:1px solid #E5E7EB;'
        f'font-size:11px;color:{_TEXT_MUTED};line-height:1.5;">{_html.escape(disclosure)}</div>'
    )
    # Insert before </body> when present, else just append.
    if "</body>" in html:
        html = html.replace("</body>", f"{footer_html}</body>", 1)
    else:
        html = f"{html}{footer_html}"
    plain = f"{plain}\n\n---\n{disclosure}"
    return html, plain


def send_email(
    *,
    to_emails: list[str],
    subject: str,
    html: str,
    plain: str,
    reply_to: str | None = None,
    disclosure: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> bool:
    """Send a single email to one or more recipients.

    Returns True if SendGrid accepted the message, False otherwise. A single
    message is sent with all addresses on the To line, so recipients can see and
    reply-all to each other — exactly what an introduction should do. ``reply_to``
    sets the Reply-To header (used for per-transaction inbound reply threading).

    ``attachments`` is an optional list of ``{"content": bytes, "filename": str,
    "type": str}`` dicts — used by document routing to attach the contract PDF.

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

    html, plain = _append_disclosure(html, plain, disclosure)
    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=recipients,
        subject=subject,
        plain_text_content=plain,
        html_content=html,
    )
    if reply_to:
        message.reply_to = reply_to
    for att in attachments or []:
        content = att.get("content")
        if not content:
            continue
        from sendgrid.helpers.mail import (
            Attachment,
            Disposition,
            FileContent,
            FileName,
            FileType,
        )

        message.add_attachment(
            Attachment(
                FileContent(base64.b64encode(content).decode()),
                FileName(att.get("filename") or "attachment"),
                FileType(att.get("type") or "application/octet-stream"),
                Disposition("attachment"),
            )
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

def send_intro_email(
    tx: dict[str, Any], brokerage_name: str, brokerage: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build and send the intro email to every party with an email on file.

    Returns ``{"sent": bool, "recipients": [...], "reason": str | None}`` so the
    caller can report what happened and decide whether to flag the transaction
    as ``intro_email_sent``. When ``brokerage`` is supplied, the AI-disclosure
    footer and (if enabled) per-party consent links are added.
    """
    parties = gather_intro_parties(tx)
    if not parties:
        return {
            "sent": False,
            "recipients": [],
            "reason": "no parties have email addresses on file",
        }

    subject, html, plain = build_intro_content(tx, brokerage_name)

    # Optional explicit-consent acknowledgment links, one per party.
    if brokerage and brokerage.get("request_ai_consent") and tx.get("id"):
        from app.services import consent

        links = [
            (p["role"], consent.consent_link(tx["id"], p["role"], p["email"]))
            for p in parties
        ]
        link_html = "".join(
            f'<li><a href="{url}">Acknowledge AI disclosure ({role})</a></li>'
            for role, url in links
        )
        html = html.replace(
            "</body>",
            f'<div style="font-size:12px;color:{_TEXT_MUTED};padding:0 40px 24px;">'
            f"<p>If applicable, acknowledge below:</p><ul>{link_html}</ul></div></body>",
            1,
        )
        plain += "\n\nAcknowledge AI disclosure:\n" + "\n".join(
            f"  - {role}: {url}" for role, url in links
        )

    sent = send_email(
        to_emails=[p["email"] for p in parties],
        subject=subject,
        html=html,
        plain=plain,
        reply_to=reply_to_address(tx.get("id")),
        disclosure=disclosure_text(brokerage),
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
