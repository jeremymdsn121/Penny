from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials

from app.core import supabase_client as sb
from app.core.security import bearer_scheme, get_current_brokerage
from app.schemas.auth import AuthResponse, BrokerageOut, LoginRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _brokerage_out(row: dict[str, Any]) -> BrokerageOut:
    return BrokerageOut(**{k: row.get(k) for k in BrokerageOut.model_fields})


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest) -> AuthResponse:
    # 1. Create the Supabase auth user. email_confirm=True so the brokerage can
    #    log in immediately (swap to the email-verification flow for production).
    try:
        user = await sb.admin_create_user(body.email, body.password, email_confirm=True)
    except sb.SupabaseError as exc:
        # 422/400 here usually means the email is already registered.
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    user_id = user["id"]

    # 2. Create the brokerage row.
    try:
        brokerage = await sb.insert_brokerage(
            {
                "name": body.brokerage_name,
                "assistant_name": "Sloane",
                "email": body.email,
                "subscription_tier": "starter",
            }
        )
    except sb.SupabaseError as exc:
        await sb.admin_delete_user(user_id, suppress=True)
        raise HTTPException(
            status_code=exc.status_code, detail=f"Could not create brokerage: {exc.detail}"
        )

    # 3. Stamp the brokerage id into app_metadata so it rides in the JWT and
    #    drives row-level security.
    try:
        await sb.update_app_metadata(
            user_id, {"brokerage_id": brokerage["id"], "role": "broker_in_charge"}
        )
    except sb.SupabaseError as exc:
        await sb.admin_delete_user(user_id, suppress=True)
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    # 4. Sign in to mint a JWT that now carries app_metadata.brokerage_id.
    tokens = await sb.sign_in(body.email, body.password)
    return AuthResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens.get("expires_in"),
        brokerage=_brokerage_out(brokerage),
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest) -> AuthResponse:
    try:
        tokens = await sb.sign_in(body.email, body.password)
    except sb.SupabaseError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )

    user = tokens.get("user") or {}
    brokerage_id = (user.get("app_metadata") or {}).get("brokerage_id")
    brokerage = await sb.get_brokerage(brokerage_id) if brokerage_id else None
    if brokerage is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account is not linked to a brokerage",
        )

    return AuthResponse(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_in=tokens.get("expires_in"),
        brokerage=_brokerage_out(brokerage),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    if creds and creds.credentials:
        await sb.sign_out(creds.credentials)


@router.get("/me", response_model=BrokerageOut)
async def me(brokerage: dict[str, Any] = Depends(get_current_brokerage)) -> BrokerageOut:
    return _brokerage_out(brokerage)
