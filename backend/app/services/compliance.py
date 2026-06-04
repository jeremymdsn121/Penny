"""Compliance review (PRD task ``compliance`` — locked, human-confirmed).

Penny reviews a transaction for compliance gaps and **surfaces findings for a
human to act on** — it never approves anything itself. Per the hard rule,
compliance review can never run autonomously.

Two layers:
  * **Structural checks** (deterministic, always run): missing required fields,
    date sanity, no contract on file, etc. Reliable guardrails over the
    transaction record.
  * **Contract review** (AI, when a contract PDF + ANTHROPIC_API_KEY are
    available): the contract PDF is sent to the model as a native document and
    assessed against the state's compliance checklist, mirroring ai_extract.

Per-state checklists are verification prompts, **not legal advice** — they tell
the agent what to confirm, and current state requirements are the agent's
responsibility. ``review_transaction`` returns findings + the annotated
checklist + a *suggested* status; it persists nothing.
"""

import base64
import json
import re
from datetime import date
from typing import Any

from anthropic import AsyncAnthropic

from app.config import settings
from app.constants import DETAILED_RULESET_STATES

MODEL = "claude-sonnet-4-5-20250929"
MAX_TOKENS = 2000

DISCLAIMER = (
    "These are checklist prompts to verify, not legal advice. Confirm current "
    "state and local requirements; Penny surfaces issues but never approves "
    "compliance — a human must review and sign off."
)

ALLOWED_STATUSES = {"not_reviewed", "needs_attention", "approved"}


class ComplianceNotConfigured(Exception):
    """Raised when AI contract review is requested without an API key."""


class ComplianceError(Exception):
    """Raised when the model response can't be parsed."""


# --------------------------------------------------------------------------- #
# State rulesets — (id, category, requirement). Verification prompts.
# --------------------------------------------------------------------------- #

_DEFAULT_RULES: list[dict[str, str]] = [
    {"id": "agency_disclosure", "category": "Disclosure",
     "requirement": "Brokerage/agency relationship disclosure was provided and signed by the parties."},
    {"id": "property_condition", "category": "Disclosure",
     "requirement": "Seller's property condition disclosure was provided where required."},
    {"id": "lead_paint", "category": "Disclosure",
     "requirement": "Lead-based paint disclosure is included for any dwelling built before 1978."},
    {"id": "addenda_attached", "category": "Documents",
     "requirement": "Every addendum referenced in the contract is attached and signed."},
    {"id": "signatures", "category": "Execution",
     "requirement": "All required signatures, initials, and dates are present from every party."},
    {"id": "earnest_money", "category": "Funds",
     "requirement": "Earnest money amount, receipt, and handling are documented."},
    {"id": "contingency_dates", "category": "Dates",
     "requirement": "Financing, appraisal, and inspection contingency dates are specified."},
]

_STATE_RULES: dict[str, list[dict[str, str]]] = {
    "TX": [
        {"id": "tx_trec_form", "category": "Forms",
         "requirement": "A current TREC-promulgated contract form is used."},
        {"id": "tx_sellers_disclosure", "category": "Disclosure",
         "requirement": "Seller's Disclosure Notice (Tex. Prop. Code §5.008) is provided where required."},
        {"id": "tx_iabs", "category": "Disclosure",
         "requirement": "Information About Brokerage Services (IABS) form was provided."},
        {"id": "tx_financing_addendum", "category": "Documents",
         "requirement": "Third Party Financing Addendum is attached when the sale is financed."},
        {"id": "tx_hoa_addendum", "category": "Documents",
         "requirement": "HOA Addendum and required subdivision information are included if the property is in an HOA."},
        {"id": "tx_lead_paint", "category": "Disclosure",
         "requirement": "Lead-based paint disclosure is included for dwellings built before 1978."},
    ],
    "FL": [
        {"id": "fl_approved_form", "category": "Forms",
         "requirement": "An approved contract form (e.g. FR/BAR) is used and fully completed."},
        {"id": "fl_property_tax", "category": "Disclosure",
         "requirement": "Property tax disclosure summary is provided to the buyer."},
        {"id": "fl_hoa_condo", "category": "Disclosure",
         "requirement": "HOA/condominium disclosure and any 3-day rescission rights are addressed where applicable."},
        {"id": "fl_radon", "category": "Disclosure",
         "requirement": "Radon gas disclosure is included."},
        {"id": "fl_flood", "category": "Disclosure",
         "requirement": "Flood-zone / coastal construction disclosures are addressed if applicable."},
        {"id": "fl_lead_paint", "category": "Disclosure",
         "requirement": "Lead-based paint disclosure is included for dwellings built before 1978."},
    ],
    "CA": [
        {"id": "ca_tds", "category": "Disclosure",
         "requirement": "Transfer Disclosure Statement (TDS) is provided where required."},
        {"id": "ca_nhd", "category": "Disclosure",
         "requirement": "Natural Hazard Disclosure (NHD) statement is provided."},
        {"id": "ca_megans_law", "category": "Disclosure",
         "requirement": "Megan's Law database disclosure is included in the contract."},
        {"id": "ca_agency", "category": "Disclosure",
         "requirement": "Agency disclosure (Disclosure Regarding Real Estate Agency Relationship) was provided."},
        {"id": "ca_safety", "category": "Compliance",
         "requirement": "Water-conserving fixtures, smoke detector, and CO detector compliance is addressed."},
        {"id": "ca_lead_paint", "category": "Disclosure",
         "requirement": "Lead-based paint disclosure is included for dwellings built before 1978."},
    ],
    "NY": [
        {"id": "ny_property_condition", "category": "Disclosure",
         "requirement": "Property Condition Disclosure Statement is provided (or the $500 credit is given at closing)."},
        {"id": "ny_agency", "category": "Disclosure",
         "requirement": "Agency disclosure form was provided and acknowledged."},
        {"id": "ny_attorney_review", "category": "Process",
         "requirement": "Attorney review/approval has occurred per local custom."},
        {"id": "ny_smoke_co", "category": "Compliance",
         "requirement": "Smoke/CO detector affidavit will be provided at closing."},
        {"id": "ny_lead_paint", "category": "Disclosure",
         "requirement": "Lead-based paint disclosure is included for dwellings built before 1978."},
    ],
    "SC": [
        {"id": "sc_property_condition", "category": "Disclosure",
         "requirement": "SC Residential Property Condition Disclosure Statement is provided."},
        {"id": "sc_agency", "category": "Disclosure",
         "requirement": "Disclosure of Real Estate Brokerage Relationships was provided."},
        {"id": "sc_coastal", "category": "Disclosure",
         "requirement": "Coastal/beachfront (SCDHEC) disclosures are addressed if applicable."},
        {"id": "sc_vacant_land", "category": "Disclosure",
         "requirement": "Percolation/soil disclosures are addressed for vacant land if applicable."},
        {"id": "sc_lead_paint", "category": "Disclosure",
         "requirement": "Lead-based paint disclosure is included for dwellings built before 1978."},
    ],
}


def get_ruleset(state: str | None) -> tuple[str, list[dict[str, str]]]:
    """Return ``(ruleset_state, rules)`` — the detailed ruleset for a covered
    state, otherwise the DEFAULT checklist."""
    code = (state or "").strip().upper()
    if code in DETAILED_RULESET_STATES and code in _STATE_RULES:
        return code, _STATE_RULES[code]
    return "DEFAULT", _DEFAULT_RULES


# --------------------------------------------------------------------------- #
# Structural checks (deterministic)
# --------------------------------------------------------------------------- #

def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def run_structural_checks(tx: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic findings from the transaction record alone."""
    findings: list[dict[str, Any]] = []

    def add(severity: str, category: str, message: str) -> None:
        findings.append({
            "severity": severity,
            "category": category,
            "message": message,
            "source": "structural",
        })

    if not (tx.get("address") or "").strip():
        add("issue", "Property", "No property address on file.")
    if not (tx.get("state") or "").strip():
        add("warning", "Property", "No state set — using the default compliance checklist.")
    if not (tx.get("buyer_name") or "").strip():
        add("issue", "Parties", "Buyer name is missing.")
    if not (tx.get("seller_name") or "").strip():
        add("issue", "Parties", "Seller name is missing.")
    if tx.get("sale_price") in (None, "", 0):
        add("warning", "Deal", "Sale price is not recorded.")

    contract_date = _parse_date(tx.get("contract_date"))
    closing_date = _parse_date(tx.get("closing_date"))
    if contract_date is None:
        add("warning", "Dates", "Contract date is missing.")
    if closing_date is None:
        add("warning", "Dates", "Closing date is missing.")
    if contract_date and closing_date and closing_date < contract_date:
        add("issue", "Dates", "Closing date is before the contract date.")
    stage = (tx.get("stage") or "").lower()
    if closing_date and closing_date < date.today() and stage not in ("closed", "cancelled"):
        add("warning", "Dates", "Closing date has passed but the deal isn't marked closed.")

    if not (tx.get("contract_pdf_url") or "").strip():
        add("warning", "Documents",
            "No contract PDF on file — the contract couldn't be reviewed against the state ruleset.")

    return findings


# --------------------------------------------------------------------------- #
# AI contract review
# --------------------------------------------------------------------------- #

def _client() -> AsyncAnthropic:
    if not settings.ANTHROPIC_API_KEY:
        raise ComplianceNotConfigured("ANTHROPIC_API_KEY is not set")
    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _build_system(ruleset_state: str, rules: list[dict[str, str]]) -> str:
    rule_lines = "\n".join(f'- {r["id"]}: {r["requirement"]}' for r in rules)
    return (
        "You are Penny, a real estate transaction coordinator assistant performing a "
        "COMPLIANCE REVIEW of a purchase contract. You surface possible issues for a "
        "human to verify — you do NOT approve anything and you never give legal advice.\n\n"
        f"Compliance checklist for {ruleset_state}:\n{rule_lines}\n\n"
        "Read the attached contract document and assess each checklist item.\n"
        "Return ONLY a JSON object: {\"assessments\": [{\"rule_id\": <id>, "
        "\"status\": \"satisfied\"|\"missing\"|\"unclear\", "
        "\"confidence\": \"high\"|\"medium\"|\"low\", \"note\": <short reason>}]}.\n"
        "Rules:\n"
        "- Use the exact rule_id values from the checklist.\n"
        "- \"satisfied\" only when the document clearly shows the item is met.\n"
        "- \"missing\" when the document indicates the item is absent or not done.\n"
        "- \"unclear\" when you cannot tell from the document — never guess.\n"
        "- \"confidence\" is how sure you are this assessment is right from the "
        "document alone: \"high\" = the document states it plainly; \"medium\" = "
        "implied or needs interpretation; \"low\" = a weak inference. Be honest — "
        "a human double-checks low-confidence items first.\n"
        "- Keep each note under 25 words and specific to the document.\n"
        "- Return only the JSON object, no prose, no markdown fences."
    )


def _parse_assessments(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ComplianceError("Model did not return JSON.")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ComplianceError(f"Could not parse model JSON: {exc}") from exc
    assessments = data.get("assessments") if isinstance(data, dict) else None
    if not isinstance(assessments, list):
        raise ComplianceError("Model response missing an 'assessments' list.")
    return assessments


async def ai_review_contract(
    pdf_bytes: bytes, ruleset_state: str, rules: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Assess the contract PDF against the checklist. Returns a list of
    ``{rule_id, status, note}``. Raises ComplianceNotConfigured / ComplianceError."""
    client = _client()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
    try:
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_build_system(ruleset_state, rules),
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {"type": "text", "text": "Review this contract against the compliance checklist."},
                ],
            }],
        )
    except Exception as exc:
        raise ComplianceError(f"Anthropic API error: {exc}") from exc
    raw = "".join(block.text for block in response.content if block.type == "text")
    return _parse_assessments(raw)


# --------------------------------------------------------------------------- #
# Orchestration — surface only, never persists.
# --------------------------------------------------------------------------- #

_AI_SEVERITY = {"missing": "issue", "unclear": "warning"}
_CONFIDENCE_LEVELS = {"high", "medium", "low"}


def normalize_confidence(value: Any) -> str:
    """Coerce a model-reported confidence to high/medium/low.

    Anything missing or unrecognized becomes ``low`` — we'd rather over-surface an
    uncertain finding for a human to check than quietly treat it as reliable.
    """
    v = str(value or "").strip().lower()
    return v if v in _CONFIDENCE_LEVELS else "low"


async def review_transaction(
    tx: dict[str, Any], pdf_bytes: bytes | None = None
) -> dict[str, Any]:
    """Run structural + (when possible) AI contract review and surface findings.

    Never writes to the database. Returns findings, the annotated state
    checklist, and a *suggested* status (the human still decides).
    """
    ruleset_state, rules = get_ruleset(tx.get("state"))
    findings = run_structural_checks(tx)

    # Start the checklist as "not_reviewed"; AI annotates it if it runs.
    checklist = [
        {**r, "ai_status": "not_reviewed", "ai_note": None, "ai_confidence": None}
        for r in rules
    ]
    by_id = {item["id"]: item for item in checklist}

    contract_reviewed = False
    ai_error: str | None = None
    if pdf_bytes:
        try:
            assessments = await ai_review_contract(pdf_bytes, ruleset_state, rules)
            contract_reviewed = True
            for a in assessments:
                rid = a.get("rule_id")
                item = by_id.get(rid)
                if not item:
                    continue
                status = a.get("status")
                note = (a.get("note") or "").strip() or None
                confidence = normalize_confidence(a.get("confidence"))
                item["ai_status"] = status if status in ("satisfied", "missing", "unclear") else "unclear"
                item["ai_note"] = note
                item["ai_confidence"] = confidence
                severity = _AI_SEVERITY.get(item["ai_status"])
                if severity:
                    findings.append({
                        "severity": severity,
                        "category": item["category"],
                        "message": f"{item['requirement']}"
                                   + (f" — {note}" if note else ""),
                        "source": "contract",
                        "rule_id": rid,
                        "confidence": confidence,
                    })
        except ComplianceNotConfigured:
            ai_error = "AI contract review unavailable (ANTHROPIC_API_KEY not set)."
        except ComplianceError as exc:
            ai_error = str(exc)

    has_issue = any(f["severity"] == "issue" for f in findings)
    suggested_status = "needs_attention" if has_issue else "approved"

    return {
        "ruleset_state": ruleset_state,
        "state": tx.get("state"),
        "contract_reviewed": contract_reviewed,
        "ai_error": ai_error,
        "findings": findings,
        "checklist": checklist,
        "counts": {
            "issue": sum(1 for f in findings if f["severity"] == "issue"),
            "warning": sum(1 for f in findings if f["severity"] == "warning"),
        },
        "suggested_status": suggested_status,
        "disclaimer": DISCLAIMER,
    }
