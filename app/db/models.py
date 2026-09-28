"""Модели: User, Role, VisitRequest, GuardAccessRequest."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Role(StrEnum):
    ADMIN = "ADMIN"
    GUARD = "GUARD"
    RESIDENT = "RESIDENT"


class VisitStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class GuardAccessStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[Role] = mapped_column(
        SAEnum(Role, native_enum=False, length=32),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    guard_approved: Mapped[bool] = mapped_column(default=False, nullable=False)
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    approved_by: Mapped["User | None"] = relationship(
        remote_side=[id],
        foreign_keys=[approved_by_id],
    )
    visit_requests: Mapped[list["VisitRequest"]] = relationship(
        back_populates="resident",
        foreign_keys="VisitRequest.resident_id",
    )
    resolved_visits: Mapped[list["VisitRequest"]] = relationship(
        back_populates="guard",
        foreign_keys="VisitRequest.guard_id",
    )
    guard_access_requests: Mapped[list["GuardAccessRequest"]] = relationship(
        back_populates="applicant",
        foreign_keys="GuardAccessRequest.user_id",
    )


class VisitRequest(Base):
    __tablename__ = "visit_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    resident_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
    )
    guest_name: Mapped[str] = mapped_column(String(255), nullable=False)
    apartment: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[VisitStatus] = mapped_column(
        SAEnum(VisitStatus, native_enum=False, length=32),
        default=VisitStatus.PENDING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    guard_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=True,
    )
    comment: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    resident: Mapped[User] = relationship(
        back_populates="visit_requests",
        foreign_keys=[resident_id],
    )
    guard: Mapped[User | None] = relationship(
        back_populates="resolved_visits",
        foreign_keys=[guard_id],
    )


class GuardAccessRequest(Base):
    __tablename__ = "guard_access_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False,
    )
    status: Mapped[GuardAccessStatus] = mapped_column(
        SAEnum(GuardAccessStatus, native_enum=False, length=32),
        default=GuardAccessStatus.PENDING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    admin_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=True,
    )

    applicant: Mapped[User] = relationship(
        back_populates="guard_access_requests",
        foreign_keys=[user_id],
    )
    resolved_by: Mapped[User | None] = relationship(
        foreign_keys=[admin_id],
    )
