# Legal drafts — for attorney review

These are **drafts**, prepared as a starting point for a licensed attorney to review,
tailor, and finalize. **They are not legal advice and must not be relied on or published
as-is.** They were assembled from how Penny actually processes data (subprocessors,
storage, security posture) so counsel has an accurate factual base, but the legal terms
(liability, indemnity, warranties, governing law, breach-notice windows, audit rights)
need professional review before use.

Context: these close the **business follow-ups** under `BLOCKERS.md` Hard Limit 6 (SOC 2 /
NPI data handling) and the NPI/data-posture decision in `TIER2_DECISIONS.md` § 1 —
onboarding design-partner brokerages under a written DPA + Privacy Policy.

| File | Purpose |
|------|---------|
| `DPA.md` | Data Processing Addendum — Madison Solutions LLC (processor) ↔ brokerage (controller). The document a broker-owner will ask for before signing. Names subprocessors, security measures, breach notice, data return/deletion. |
| `PRIVACY_POLICY.md` | B2B-oriented privacy policy covering NPI processing, AI use, subprocessors, retention, and data-subject rights. Complements (does not replace) the existing A2P/SMS consumer copy in `marketing/privacy.html` + `app/api/v1/routes/legal.py`. |

**Business identity used in the drafts** (keep in sync with `legal.py` constants):
Madison Solutions LLC · Penny · support@poweredbypenny.com · 12203 Tapit St, Buda, TX 78610.

## Before these go live — counsel checklist
- [ ] Attorney review of both documents (liability, indemnity, warranties, governing law).
- [ ] Confirm the **subprocessor list** matches what's actually enabled in production
      (Schedule C / the Privacy Policy "Sharing" section) and set up a change-notice
      mechanism.
- [ ] Decide **breach-notification window** and whatever your insurer/contracts require.
- [ ] If any brokerage operates in California (CCPA) or you take EU data (unlikely),
      confirm the service-provider / SCC language is right.
- [ ] Publish the Privacy Policy (and link it from the app + marketing site); attach the
      DPA to the brokerage MSA/order form.
