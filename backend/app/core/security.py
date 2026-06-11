"""Auth dependencies. The bearer token is a Supabase-issued JWT; we validate it
by asking Supabase who it belongs to, then resolve the brokerage it is scoped to
via the `app_metadata.brokerage_id` claim.
"""

from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import supabase_client as sb

bearer_scheme = HTTPBearer(auto_error=False)


def _token_from(creds: HTTPAuthorizationCredentials | None) -> str:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return creds.credentials


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    token = _token_from(creds)
    try:
        return await sb.get_user(token)
    except sb.SupabaseError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_admin(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """The caller must hold the brokerage-admin role.

    Today every login IS the admin (signup stamps app_metadata.role =
    'broker_in_charge' and agents have no logins), so this changes nothing
    functionally — it exists so that the day a second seat type is added,
    the admin-only surfaces (review queue, reports, autonomy, settings)
    don't silently open up. Legacy accounts created before the role stamp
    are treated as admins (single-login era ⇒ they are the broker).
    """
    role = (user.get("app_metadata") or {}).get("role")
    if role not in (None, "broker_in_charge"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This area is for the broker-in-charge.",
        )
    return user


async def get_current_brokerage(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    brokerage_id = (user.get("app_metadata") or {}).get("brokerage_id")
    if not brokerage_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not linked to a brokerage",
        )
    brokerage = await sb.get_brokerage(brokerage_id)
    if brokerage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Brokerage not found"
        )
    return brokerage
