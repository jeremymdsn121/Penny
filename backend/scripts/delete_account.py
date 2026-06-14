"""Dev cleanup: delete a brokerage account by email.

One signup == one Supabase auth user (carrying app_metadata.brokerage_id) + one
brokerage row + that brokerage's scoped data. This removes all three so the email
frees up and signup/onboarding can be re-tested.

NOT wired into the API — deleting accounts is a destructive surface we keep off
HTTP. Run it manually from ``backend/`` (so ``.env`` + the service-role key load),
using the project venv:

    .venv/Scripts/python.exe scripts/delete_account.py someone@example.com
    .venv/Scripts/python.exe scripts/delete_account.py someone@example.com --yes

It prompts for confirmation (retype the email) unless ``--yes`` is passed.
"""

import argparse
import asyncio
import os
import sys

# Allow running as `python scripts/delete_account.py` (not just `-m`): put the
# backend dir (this file's parent's parent) on the path so `app` imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import supabase_client as sb  # noqa: E402

# Brokerage-scoped tables to sweep, best-effort, before deleting the brokerage.
# `transactions` goes first: its children (deadlines, tasks, emails, appointments,
# checklist items, EMD, events, …) cascade via their FKs. The rest are scoped
# directly by brokerage_id. Missing tables / already-empty sweeps are ignored.
BROKERAGE_TABLES = [
    "transactions",
    "agent_channels",
    "agents",
    "knowledge_rules",
    "knowledge_documents",
    "task_autonomy",
    "listings",
    "compliance_templates",
    "workflow_templates",
    "doc_routing_rules",
    "whatsapp_messages",
    "pending_whatsapp_transactions",
    "ai_usage",
]


async def run(email: str, assume_yes: bool) -> int:
    try:
        user = await sb.admin_get_user_by_email(email)
    except sb.SupabaseError as exc:
        print(f"Lookup failed: {exc}", file=sys.stderr)
        return 1
    if not user:
        print(f"No auth user found for {email!r}. Nothing to do.")
        return 1

    user_id = user["id"]
    brokerage_id = (user.get("app_metadata") or {}).get("brokerage_id")
    print(f"User:      {email}  ({user_id})")
    print(f"Brokerage: {brokerage_id or '(none stamped on the user)'}")

    if not assume_yes:
        typed = input("Delete this account and ALL its data? Retype the email to confirm: ").strip()
        if typed != email:
            print("Aborted — input did not match.")
            return 1

    # 1. Sweep brokerage-scoped data (best-effort; keep going on per-table errors).
    if brokerage_id:
        for table in BROKERAGE_TABLES:
            try:
                await sb.delete_rows_by_brokerage(table, brokerage_id)
                print(f"  - {table}: cleared")
            except sb.SupabaseError as exc:
                print(f"  - {table}: skipped ({exc.status_code})")
        # 2. The brokerage row itself.
        try:
            await sb.delete_brokerage(brokerage_id)
            print("  - brokerages: deleted")
        except sb.SupabaseError as exc:
            print(f"  - brokerages: FAILED ({exc}) — leftover scoped rows may block it", file=sys.stderr)
            return 1

    # 3. The auth user (last, so a failure above doesn't orphan the brokerage).
    try:
        await sb.admin_delete_user(user_id)
        print("  - auth user: deleted")
    except sb.SupabaseError as exc:
        print(f"  - auth user: FAILED ({exc})", file=sys.stderr)
        return 1

    print(f"Done. {email} is free to sign up again.")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Delete a brokerage account by email (dev cleanup).")
    p.add_argument("email", help="the account's login email")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = p.parse_args()
    sys.exit(asyncio.run(run(args.email, args.yes)))


if __name__ == "__main__":
    main()
