from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class TaskAutonomyItem(BaseModel):
    task_id: str
    autonomous: bool = False


class OnboardingSubmit(BaseModel):
    # Step 1 — State
    state: str = Field(min_length=2, max_length=2)

    # Step 2 — Identity
    assistant_name: str = Field(min_length=1, default="Penny")
    name: str = Field(min_length=1)  # brokerage name
    email: EmailStr | None = None
    phone: str | None = None

    # Step 3 — Email handling
    email_mode: Literal["own", "monitor"] = "own"
    monitor_email: EmailStr | None = None

    # Step 4 — Calendar / scheduling
    calendar_provider: Literal["google", "outlook"] | None = None
    work_start: str = "09:00"
    work_end: str = "17:00"
    buffer_minutes: int = Field(default=15, ge=0, le=240)
    showing_method: Literal["email", "showingtime"] = "email"

    # Step 5 — Task autonomy
    tasks: list[TaskAutonomyItem] = []


class OnboardingOptions(BaseModel):
    states: list[dict]
    detailed_ruleset_states: list[str]
    tasks: list[dict]
