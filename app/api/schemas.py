from datetime import date, datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResidentRegistration(StrictModel):
    full_name: str = Field(min_length=5, max_length=200)
    building: str = Field(min_length=1, max_length=80)
    apartment: str = Field(min_length=1, max_length=32)
    default_contact: str = Field(min_length=3, max_length=80)


class GuardRegistration(StrictModel):
    invite_code: str = Field(min_length=24, max_length=128)
    full_name: str = Field(min_length=5, max_length=200)


class VisitCreate(StrictModel):
    apartment_id: UUID
    checkpoint_id: UUID
    visitor_type: Literal["COURIER", "GUEST", "REPAIR", "OTHER"]
    visitor_name: str = Field(min_length=2, max_length=200)
    visitor_car_number: str | None = Field(default=None, max_length=24)
    resident_contact: str | None = Field(default=None, max_length=80)
    estimated_arrival_at: datetime | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("visitor_name", "resident_contact", "comment", mode="before")
    @classmethod
    def trim_optional_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class Decision(StrictModel):
    status: Literal["PASSED", "REJECTED"]
    reason: str | None = Field(default=None, max_length=500)


class PinUpdate(StrictModel):
    is_pinned: bool


class InviteCreate(StrictModel):
    checkpoint_id: UUID
    expires_in_minutes: int = Field(default=15, ge=1, le=10080)


class GuardReview(StrictModel):
    approve: bool
    checkpoint_ids: list[UUID] | None = None


class GuardActive(StrictModel):
    active: bool


class CheckpointCreate(StrictModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=300)


class ShiftCreate(StrictModel):
    checkpoint_id: UUID
    guard_user_id: int
    kind: Literal["RECURRING", "ONE_TIME", "REPLACEMENT"]
    weekday: int | None = Field(default=None, ge=0, le=6)
    starts_on: date | None = None
    ends_on: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    note: str | None = Field(default=None, max_length=300)


class RegistryConfirm(StrictModel):
    deactivate_missing: bool = False
