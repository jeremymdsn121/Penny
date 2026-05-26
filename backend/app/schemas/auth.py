from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    brokerage_name: str = Field(min_length=1)
    assistant_name: str = "Penny"
    state: str | None = None
    phone: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class BrokerageOut(BaseModel):
    id: str
    name: str
    assistant_name: str | None = None
    state: str | None = None
    email: str | None = None
    phone: str | None = None
    subscription_tier: str | None = None


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int | None = None
    brokerage: BrokerageOut
