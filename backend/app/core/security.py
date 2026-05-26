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
