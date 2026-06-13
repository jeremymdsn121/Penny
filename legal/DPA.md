# Data Processing Addendum (DPA) — DRAFT

> **DRAFT FOR ATTORNEY REVIEW — NOT LEGAL ADVICE.** This is a starting template assembled
> from how Penny actually processes data. A licensed attorney must review and tailor it
> (liability, indemnity, warranties, governing law, breach-notice window, audit rights)
> before it is used or signed. Bracketed `[…]` items are placeholders.

This Data Processing Addendum ("DPA") forms part of the agreement ("Agreement") between
**Madison Solutions LLC**, a Texas limited liability company, operating the **Penny**
service ("Processor," "we," "us") and the customer brokerage identified in the Agreement
("Controller," "Customer," "you"). It governs Processor's processing of Personal Data on
Customer's behalf in connection with the Penny service.

If there is a conflict between this DPA and the Agreement on the subject of personal-data
processing, this DPA controls.

## 1. Definitions

- **Personal Data** — information relating to an identified or identifiable natural person
  that Processor processes on Customer's behalf under the Agreement. For this service it
  includes real-estate transaction parties' contact details and the contents of uploaded
  documents, which may contain **nonpublic personal information ("NPI")** such as Social
  Security numbers, financial-account details, and income information.
- **Processing**, **Controller**, **Processor**, **Data Subject** — as commonly defined in
  applicable data-protection law.
- **Subprocessor** — a third party engaged by Processor to process Personal Data.
- **Applicable Data Protection Law** — privacy/data-protection laws applicable to the
  processing, which may include state laws such as the [Texas Data Privacy and Security
  Act] and the California Consumer Privacy Act ("CCPA") as amended.

## 2. Roles and scope of processing

2.1 Customer is the Controller and Processor is the Processor of the Personal Data. Where
CCPA applies, Processor acts as Customer's **service provider** and will not sell or share
Personal Data, or retain/use/disclose it for any purpose other than performing the service
(or as permitted by law).

2.2 Processor processes Personal Data only on Customer's **documented instructions** —
including the instructions embodied in Customer's use of the service — unless required by
law (in which case Processor will, where lawful, notify Customer first).

2.3 The subject matter, duration, nature, purpose, data types, and categories of Data
Subjects are set out in **Schedule A**.

## 3. Confidentiality

Processor ensures that personnel authorized to process Personal Data are bound by
confidentiality obligations and access Personal Data only as needed to provide the service
(least-privilege).

## 4. Security

4.1 Processor implements appropriate technical and organizational measures to protect
Personal Data, described in **Schedule B**. These include encryption in transit and at
rest, tenant isolation, access controls, and use of an infrastructure provider that
maintains SOC 2 / ISO 27001 attestations.

4.2 Processor is pursuing its own SOC 2 readiness; until that attestation exists, the
security baseline is the measures in Schedule B plus the subprocessors' own certifications.
Customer acknowledges this status. [Confirm how this should be represented.]

## 5. Subprocessors

5.1 Customer provides **general authorization** for Processor to engage the Subprocessors
listed in **Schedule C** to process Personal Data, each under a written contract imposing
data-protection obligations no less protective than this DPA.

5.2 Processor will give Customer **at least [30] days' notice** of any intended addition or
replacement of a Subprocessor, giving Customer the opportunity to object on reasonable
data-protection grounds. [Define the notice mechanism — e.g., email to the brokerage admin
+ a published list — and the objection/termination remedy.]

5.3 Processor remains liable for its Subprocessors' acts and omissions in respect of
Personal Data to the same extent as for its own.

## 6. Assistance to Customer

6.1 **Data-subject requests.** Taking into account the nature of the processing, Processor
will assist Customer by appropriate technical and organizational measures, insofar as
possible, to respond to Data-Subject requests (access, correction, deletion, etc.).

6.2 **Security, breach, and DPIAs.** Processor will assist Customer in ensuring compliance
with its security, breach-notification, and (where applicable) data-protection-impact-
assessment obligations, taking into account the information available to Processor.

## 7. Personal Data breach

Processor will notify Customer **without undue delay, and in any event within [72] hours**,
after becoming aware of a Personal Data breach affecting Customer's Personal Data, and will
provide information reasonably available to help Customer meet its own notification duties.
[Confirm the window against insurer/contract requirements.]

## 8. Return and deletion

8.1 On termination or expiry of the Agreement, Processor will, at Customer's choice, return
or delete the Personal Data, and delete existing copies, except to the extent retention is
required by law.

8.2 The service provides a **configurable document-retention policy** (default 7 years,
broker-configurable) governing how long uploaded documents are kept; automated deletion is
opt-in and is never performed without configuration. [Confirm interaction between this
retention setting and the return/deletion obligation above.]

## 9. Audit

Processor will make available to Customer information reasonably necessary to demonstrate
compliance with this DPA and will allow for and contribute to audits, including inspections,
conducted by Customer or its mandated auditor, **subject to reasonable notice,
confidentiality, frequency limits, and [Processor's then-current audit/security
documentation satisfying this obligation where adequate]**. [Counsel to scope audit rights.]

## 10. International transfers

Processor processes and stores Personal Data in the **United States**. Processor does not
intend to transfer Personal Data internationally; if that changes, the parties will put an
appropriate transfer mechanism in place. [Confirm — relevant only if EU/UK data is ever
involved, which is not expected for US brokerages.]

## 11. Liability and precedence

This DPA is subject to the limitations and exclusions of liability in the Agreement.
[Counsel to confirm liability cap, indemnities, and order of precedence.]

## 12. Governing law

This DPA is governed by the law specified in the Agreement [e.g., the State of Texas],
except where Applicable Data Protection Law requires otherwise.

---

## Schedule A — Details of processing

- **Subject matter:** provision of the Penny virtual transaction-coordination service.
- **Duration:** the term of the Agreement, plus any legally required retention period.
- **Nature and purpose:** coordinating real-estate transactions — extracting fields from
  uploaded contracts, generating correspondence, tracking deadlines/checklists/EMD,
  surfacing compliance findings, scheduling, and messaging parties over WhatsApp/SMS/email
  on Customer's behalf.
- **Types of Personal Data:** names, email addresses, mobile phone numbers, and the
  contents of uploaded transaction documents, which may include **NPI** (e.g., Social
  Security numbers, financial-account and income information).
- **Categories of Data Subjects:** Customer's agents and staff; and transaction parties
  (buyers, sellers, and their representatives such as lenders and title/escrow contacts).
- **Special-category data:** not intentionally processed; Customer should avoid uploading
  documents containing special categories of data.

## Schedule B — Technical and organizational measures (summary)

> Counsel/security to confirm and expand; this summarizes the implemented posture.

- **Encryption:** TLS for data in transit; encryption at rest at the infrastructure layer.
- **Tenant isolation:** every record is scoped to a brokerage ID and enforced by database
  row-level security; application queries are scoped server-side as well.
- **Access control:** the privileged service credential is server-side only; least-privilege
  access for personnel; authentication via a managed identity provider.
- **Secrets:** API keys and credentials stored as managed secrets, never in client code.
- **Storage:** uploaded documents held in **private** object-storage buckets.
- **Infrastructure:** hosted on providers maintaining SOC 2 / ISO 27001 attestations.
- **Retention:** configurable per brokerage (default 7 years); deletion is opt-in.
- **Logging/audit:** application-level audit trail of key actions per transaction.

## Schedule C — Authorized Subprocessors

> Confirm this list matches production before signing; keep it current.

| Subprocessor | Purpose | Data exposed | Region |
|---|---|---|---|
| Supabase | Database, authentication, file storage (primary data store) | All categories above | US |
| Render | Application/API hosting | Transient processing of all categories | US |
| Anthropic | AI: contract extraction, assistant, compliance review, document drafting | Document contents + transaction data sent for processing | US |
| OpenAI | AI: voice-memo transcription (Whisper) | Audio of inbound voice memos | US |
| Twilio | WhatsApp + SMS messaging | Party names, phone numbers, message contents | US |
| SendGrid (Twilio) | Outbound + inbound email | Party names, email addresses, message contents | US |
| Rentcast | Comparable-sales / property lookups | Property **address** only (no NPI) | US |
| Google | Optional calendar sync (only if a brokerage/agent connects it) | Appointment metadata | US |

[Verify each subprocessor's current DPA/sub-processing terms and certifications, and note
any that should be flagged as optional/feature-gated.]
