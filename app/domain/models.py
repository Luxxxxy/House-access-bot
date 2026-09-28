from __future__ import annotations

import uuid
from datetime import date, datetime, time
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("role IN ('ADMIN','GUARD','RESIDENT')", name="ck_accounts_role"),
        Index("ix_accounts_role_active", "role", "is_active"),
    )

    max_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    username: Mapped[str | None] = mapped_column(String(100))
    default_contact: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResidentialComplex(Base):
    __tablename__ = "residential_complexes"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Europe/Moscow")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComplexAdmin(Base):
    __tablename__ = "complex_admins"

    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.max_user_id", ondelete="CASCADE"), primary_key=True
    )


class Building(Base):
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("complex_id", "name", name="uq_buildings_complex_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class Apartment(Base):
    __tablename__ = "apartments"
    __table_args__ = (UniqueConstraint("building_id", "number", name="uq_apartments_building_number"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    building_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RegistryEntry(Base):
    __tablename__ = "registry_entries"
    __table_args__ = (
        UniqueConstraint("apartment_id", "normalized_name", name="uq_registry_apartment_person"),
        Index("ix_registry_name", "normalized_name"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    apartment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResidentApartment(Base):
    __tablename__ = "resident_apartments"
    __table_args__ = (
        UniqueConstraint("apartment_id", "user_id", name="uq_resident_apartment_pair"),
        UniqueConstraint("registry_entry_id", name="uq_resident_registry_entry"),
        Index("ix_resident_apartments_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.max_user_id", ondelete="CASCADE"), nullable=False
    )
    apartment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("apartments.id", ondelete="CASCADE"), nullable=False
    )
    registry_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("registry_entries.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("complex_id", "name", name="uq_checkpoints_complex_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class GuardProfile(Base):
    __tablename__ = "guard_profiles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INVITED','PENDING','VERIFIED','REJECTED','DEACTIVATED')",
            name="ck_guard_profiles_status",
        ),
        Index("ix_guard_profiles_complex_status", "complex_id", "status"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.max_user_id", ondelete="CASCADE"), primary_key=True
    )
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.max_user_id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuardCheckpoint(Base):
    __tablename__ = "guard_checkpoints"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("guard_profiles.user_id", ondelete="CASCADE"), primary_key=True
    )
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("checkpoints.id", ondelete="CASCADE"), primary_key=True
    )


class GuardInvite(Base):
    __tablename__ = "guard_invites"
    __table_args__ = (Index("ix_guard_invites_expiry", "expires_at", "used_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("checkpoints.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("accounts.max_user_id"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.max_user_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GuardShift(Base):
    __tablename__ = "guard_shifts"
    __table_args__ = (
        CheckConstraint("kind IN ('RECURRING','ONE_TIME','REPLACEMENT')", name="ck_guard_shifts_kind"),
        Index("ix_guard_shifts_guard_checkpoint", "user_id", "checkpoint_id"),
        Index("ix_guard_shifts_dates", "starts_on", "ends_on"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False
    )
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("checkpoints.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("guard_profiles.user_id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    weekday: Mapped[int | None] = mapped_column(Integer)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[int] = mapped_column(ForeignKey("accounts.max_user_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VisitRequest(Base):
    # Keep the legacy bot's visit_requests table intact during the schema transition.
    __tablename__ = "resident_visit_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','PASSED','REJECTED','CANCELLED','EXPIRED','DELETED')",
            name="ck_visit_requests_status",
        ),
        Index("ix_visit_queue", "checkpoint_id", "status", "created_at"),
        Index("ix_visit_resident", "resident_id", "created_at"),
        Index("ix_visit_search_name", "visitor_name"),
        Index("ix_visit_search_car", "visitor_car_number"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False
    )
    resident_id: Mapped[int] = mapped_column(ForeignKey("accounts.max_user_id"), nullable=False)
    apartment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("apartments.id"), nullable=False)
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checkpoints.id"), nullable=False)
    visitor_type: Mapped[str] = mapped_column(String(24), nullable=False)
    visitor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    visitor_car_number: Mapped[str | None] = mapped_column(String(24))
    resident_contact: Mapped[str] = mapped_column(String(80), nullable=False)
    estimated_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("accounts.max_user_id"))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisitEvent(Base):
    __tablename__ = "visit_request_events"
    __table_args__ = (Index("ix_visit_events_request_created", "request_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resident_visit_requests.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.max_user_id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_complex_created", "complex_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.max_user_id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(120))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe"),
        CheckConstraint("status IN ('PENDING','PROCESSING','SENT','FAILED')", name="ck_notifications_status"),
        Index("ix_notifications_delivery", "status", "next_attempt_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    recipient_id: Mapped[int] = mapped_column(ForeignKey("accounts.max_user_id"), nullable=False)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("resident_visit_requests.id", ondelete="SET NULL"), index=True
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    text: Mapped[str] = mapped_column(String(1500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "max_webhook_events"

    event_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegistryImport(Base):
    __tablename__ = "registry_imports"
    __table_args__ = (Index("ix_registry_imports_complex_created", "complex_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    complex_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("residential_complexes.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("accounts.max_user_id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    rows_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
