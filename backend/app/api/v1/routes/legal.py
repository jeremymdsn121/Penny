"""Public legal pages (Privacy Policy + SMS Terms & Conditions).

Carrier A2P 10DLC registration requires a publicly reachable privacy policy and
terms-of-service URL. These two GET routes serve self-contained HTML (no auth, no
DB) so they're always loadable by Twilio and the carriers:

  - GET /privacy — privacy policy
  - GET /terms   — SMS program terms & conditions (the carrier-required SMS section
                   lives here: program description, message frequency, rates, and
                   HELP/STOP opt-out instructions)

Plain prose, editable in place. Have an attorney review before relying on these
broadly.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["legal"])

# Business identity — edit here if any of these change.
_COMPANY = "Madison Solutions LLC"
_PRODUCT = "Penny"
_SUPPORT_EMAIL = "support@poweredbypenny.com"
_ADDRESS = "12203 Tapit St, Buda, TX 78610"
_LAST_UPDATED = "June 4, 2026"


def _page(title: str, body: str) -> HTMLResponse:
    """Wrap document body in a minimal, readable shell."""
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} — {_PRODUCT}</title></head>
<body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#F9FAFB;margin:0;padding:48px 16px;color:#1F2937;line-height:1.65;">
  <div style="max-width:720px;margin:0 auto;background:#fff;border-radius:12px;padding:40px 44px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
    <div style="font-size:22px;font-weight:700;color:#7C3AED;margin-bottom:4px;">{_PRODUCT}</div>
    <h1 style="font-size:26px;margin:8px 0 4px;">{title}</h1>
    <p style="color:#6B7280;font-size:14px;margin-top:0;">Last updated: {_LAST_UPDATED}</p>
    {body}
    <hr style="border:none;border-top:1px solid #E5E7EB;margin:32px 0 16px;"/>
    <p style="color:#6B7280;font-size:13px;">{_COMPANY} &middot; {_ADDRESS} &middot;
      <a href="mailto:{_SUPPORT_EMAIL}" style="color:#7C3AED;">{_SUPPORT_EMAIL}</a></p>
  </div>
</body></html>"""
    return HTMLResponse(content=html)


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    body = f"""
<p>{_COMPANY} ("we," "us," or "our") operates {_PRODUCT}, a virtual transaction
coordinator used by real estate brokerages. This Privacy Policy explains what
information we collect, how we use it, and the choices you have. It applies to our
website, application, and our SMS/text-messaging program.</p>

<h2 style="font-size:18px;">Information we collect</h2>
<ul>
  <li><strong>Account &amp; contact information</strong> you or your brokerage provide,
      such as name, email address, and mobile phone number.</li>
  <li><strong>Transaction information</strong> you submit to coordinate real estate
      transactions, including documents, dates, and details about the parties to a deal.</li>
  <li><strong>Message content and metadata</strong> for the text messages and other
      communications you exchange with {_PRODUCT}.</li>
  <li><strong>Usage data</strong> generated as you use the service.</li>
</ul>

<h2 style="font-size:18px;">How we use information</h2>
<ul>
  <li>To provide and operate {_PRODUCT}, including sending and responding to
      transaction-related text messages you have opted in to receive.</li>
  <li>To coordinate deadlines, documents, and communications on your transactions.</li>
  <li>To secure, maintain, support, and improve the service.</li>
  <li>To comply with legal obligations.</li>
</ul>

<h2 style="font-size:18px;">How we share information</h2>
<p>We do <strong>not</strong> sell your information, and we do <strong>not</strong>
share it with third parties for their own marketing purposes. We share information
only with service providers who help us operate {_PRODUCT} (for example, our
messaging, email, and hosting providers) under obligations to protect it, and where
required by law.</p>
<p><strong>SMS consent and phone numbers are never shared with third parties or
sold.</strong> No mobile information is shared with third parties or affiliates for
marketing or promotional purposes.</p>

<h2 style="font-size:18px;">Your choices</h2>
<p>You can opt out of text messages at any time by replying <strong>STOP</strong>.
You can request access to or deletion of your information by contacting us at
<a href="mailto:{_SUPPORT_EMAIL}" style="color:#7C3AED;">{_SUPPORT_EMAIL}</a>.</p>

<h2 style="font-size:18px;">Data retention &amp; security</h2>
<p>We retain information for as long as needed to provide the service and meet legal
requirements, and we use reasonable administrative and technical safeguards to protect
it.</p>

<h2 style="font-size:18px;">Contact us</h2>
<p>Questions about this policy? Contact {_COMPANY} at
<a href="mailto:{_SUPPORT_EMAIL}" style="color:#7C3AED;">{_SUPPORT_EMAIL}</a> or
{_ADDRESS}.</p>
"""
    return _page("Privacy Policy", body)


@router.get("/terms", response_class=HTMLResponse)
async def terms_and_conditions() -> HTMLResponse:
    body = f"""
<p>These Terms &amp; Conditions govern your use of {_PRODUCT}, a virtual transaction
coordinator operated by {_COMPANY}, including our SMS/text-messaging program.</p>

<h2 style="font-size:18px;">Messaging program (SMS)</h2>
<p><strong>Program name:</strong> {_PRODUCT}.</p>
<p><strong>Program description:</strong> When you provide your mobile number to your
brokerage to be contacted by {_PRODUCT}, you agree to receive operational and
transactional text messages related to your real estate transactions. These include
deadline and contingency reminders, transaction status updates, earnest-money and
document confirmations, requests for missing paperwork, showing and appointment
coordination, and replies to questions you send about your active deals. This is not a
marketing program.</p>
<p><strong>How you opt in:</strong> {_PRODUCT} uses a double opt-in process. When your
brokerage adds you to {_PRODUCT}, an administrator enters your mobile number in the
{_PRODUCT} web application after confirming you have agreed to be contacted about your
transactions. {_PRODUCT} then sends you a single confirmation text:</p>
<p style="background:#F3F4F6;border-radius:8px;padding:12px 16px;font-style:italic;">
"[Your brokerage] set up Penny, your transaction assistant, to text you. Reply YES to
get deal updates &amp; reminders. Msg frequency varies; msg &amp; data rates may apply.
Reply STOP to opt out, HELP for help. Terms: poweredbypenny.com/terms.html"</p>
<p>You must reply <strong>YES</strong> to activate messaging. If you do not reply YES,
you will not receive any further messages. You can reply <strong>STOP</strong> at any
time to opt out.</p>
<p><strong>Message frequency:</strong> Message frequency varies based on your
transaction activity.</p>
<p><strong>Message and data rates:</strong> <strong>Message and data rates may
apply.</strong> These charges come from your mobile carrier and are your
responsibility.</p>
<p><strong>To get help:</strong> Reply <strong>HELP</strong> at any time, or contact us
at <a href="mailto:{_SUPPORT_EMAIL}" style="color:#7C3AED;">{_SUPPORT_EMAIL}</a>.</p>
<p><strong>To opt out:</strong> Reply <strong>STOP</strong> at any time to cancel. After
you send STOP, we will send one confirmation message and then stop sending messages to
you. To rejoin, contact your brokerage or
<a href="mailto:{_SUPPORT_EMAIL}" style="color:#7C3AED;">{_SUPPORT_EMAIL}</a>.</p>
<p><strong>Carriers are not liable for delayed or undelivered messages.</strong>
Message delivery is subject to effective transmission by your mobile carrier and is not
guaranteed.</p>

<h2 style="font-size:18px;">Consent</h2>
<p>By providing your mobile number to be contacted by {_PRODUCT} and replying YES to the
confirmation text described above, you consent to receive the text messages described
above. Consent is not a condition of any purchase. We do not share or sell your mobile
number or SMS consent to third parties.</p>

<h2 style="font-size:18px;">Acceptable use</h2>
<p>You agree to use {_PRODUCT} only for lawful purposes and in connection with genuine
real estate transactions you are authorized to coordinate.</p>

<h2 style="font-size:18px;">No legal or professional advice</h2>
<p>{_PRODUCT} assists with transaction coordination and does not provide legal,
financial, tax, or brokerage advice. You remain responsible for your professional and
legal obligations.</p>

<h2 style="font-size:18px;">Privacy</h2>
<p>Your use of {_PRODUCT} is also governed by our
<a href="https://poweredbypenny.com/privacy.html" style="color:#7C3AED;">Privacy Policy</a>.</p>

<h2 style="font-size:18px;">Contact us</h2>
<p>{_COMPANY} &middot; {_ADDRESS} &middot;
<a href="mailto:{_SUPPORT_EMAIL}" style="color:#7C3AED;">{_SUPPORT_EMAIL}</a></p>
"""
    return _page("Terms & Conditions", body)
