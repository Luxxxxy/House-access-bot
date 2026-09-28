from __future__ import annotations

import hashlib
import hmac
import json
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.domain.models import AuditEvent
from app.domain.models import (
    Account,
    Apartment,
    Building,
    Checkpoint,
    ComplexAdmin,
    GuardCheckpoint,
    GuardProfile,
    GuardShift,
    Notification,
    RegistryEntry,
    ResidentApartment,
    ResidentialComplex,
    Base,
)
from app.domain.schedules import shift_covers_instant
from app.security.auth import verify_max_init_data
from app.web.db import get_session
from app.web.main import app
from app.web.start import bootstrap_production_admin


def test_recurring_night_shift_crosses_midnight() -> None:
    tz = ZoneInfo("Europe/Moscow")
    instant = datetime(2026, 9, 24, 2, 30, tzinfo=tz)  # Thu
    assert shift_covers_instant(
        kind="RECURRING",
        weekday=2,
        starts_on=date(2026, 9, 21),
        ends_on=None,
        start_time=time(20),
        end_time=time(8),
        starts_at=None,
        ends_at=None,
        at=instant,
        timezone="Europe/Moscow",
    )


def test_explicit_overlapping_shift_is_active() -> None:
    now = datetime.now(timezone.utc)
    assert shift_covers_instant(
        kind="REPLACEMENT",
        weekday=None,
        starts_on=None,
        ends_on=None,
        start_time=None,
        end_time=None,
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(minutes=5),
        at=now,
        timezone="Europe/Moscow",
    )


def _signed_init_data(token: str, *, user_id: int, auth_date: int) -> str:
    values = {"auth_date": str(auth_date), "user": json.dumps({"id": user_id}, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_max_init_data_signature_and_expiration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_bot_token", "test-token")
    now = 1_800_000_000
    signed = _signed_init_data("test-token", user_id=12345, auth_date=now)
    assert verify_max_init_data(signed, now=now) == 12345
    with pytest.raises(Exception, match="signature"):
        verify_max_init_data(signed.replace("12345", "54321"), now=now)
    stale = _signed_init_data("test-token", user_id=12345, auth_date=now - 3601)
    with pytest.raises(Exception, match="expired"):
        verify_max_init_data(stale, now=now)


@pytest_asyncio.fixture
async def product_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    complex_id = uuid4()
    other_complex_id = uuid4()
    apartment_id = uuid4()
    other_apartment_id = uuid4()
    checkpoint_id = uuid4()
    other_checkpoint_id = uuid4()
    now = datetime.now(timezone.utc)
    async with factory() as session:
        session.add_all(
            [
                ResidentialComplex(id=complex_id, name="Тестовый дом", city="Москва", timezone="Europe/Moscow"),
                ResidentialComplex(id=other_complex_id, name="Другой дом", city="Москва", timezone="Europe/Moscow"),
                Account(max_user_id=70001, role="ADMIN", full_name="Администратор Тестов", is_demo=True),
                Account(max_user_id=70002, role="RESIDENT", full_name="Иванов Иван Иванович", default_contact="+7 900 000-00-01", is_demo=True),
                Account(max_user_id=70003, role="GUARD", full_name="Охранник Первый", is_demo=True),
                Account(max_user_id=70004, role="GUARD", full_name="Охранник Второй", is_demo=True),
            ]
        )
        session.add(ComplexAdmin(complex_id=complex_id, user_id=70001))
        building = Building(id=uuid4(), complex_id=complex_id, name="1")
        other_building = Building(id=uuid4(), complex_id=complex_id, name="2")
        session.add_all([building, other_building])
        await session.flush()
        apartment = Apartment(id=apartment_id, building_id=building.id, number="101")
        other_apartment = Apartment(id=other_apartment_id, building_id=other_building.id, number="202")
        checkpoint = Checkpoint(id=checkpoint_id, complex_id=complex_id, name="КПП Тест")
        other_checkpoint = Checkpoint(id=other_checkpoint_id, complex_id=other_complex_id, name="КПП Чужого дома")
        session.add_all([apartment, other_apartment, checkpoint, other_checkpoint])
        await session.flush()
        resident_entry = RegistryEntry(
            apartment_id=apartment.id,
            full_name="Иванов Иван Иванович",
            normalized_name="иванов иван иванович",
        )
        another_resident_entry = RegistryEntry(
            apartment_id=apartment.id,
            full_name="Иванова Мария Петровна",
            normalized_name="иванова мария петровна",
        )
        second_apartment_entry = RegistryEntry(
            apartment_id=other_apartment.id,
            full_name="Иванов Иван Иванович",
            normalized_name="иванов иван иванович",
        )
        session.add_all([resident_entry, another_resident_entry, second_apartment_entry])
        await session.flush()
        session.add(
            ResidentApartment(
                user_id=70002,
                apartment_id=apartment.id,
                registry_entry_id=resident_entry.id,
            )
        )
        # A second resident record in the same apartment remains available for registration.
        session.add_all(
            [
                GuardProfile(user_id=70003, complex_id=complex_id, status="VERIFIED"),
                GuardProfile(user_id=70004, complex_id=complex_id, status="VERIFIED"),
                GuardCheckpoint(user_id=70003, checkpoint_id=checkpoint.id),
                GuardCheckpoint(user_id=70004, checkpoint_id=checkpoint.id),
                GuardShift(
                    complex_id=complex_id,
                    checkpoint_id=checkpoint.id,
                    user_id=70003,
                    kind="ONE_TIME",
                    starts_at=now - timedelta(hours=1),
                    ends_at=now + timedelta(hours=1),
                    created_by=70001,
                ),
                GuardShift(
                    complex_id=complex_id,
                    checkpoint_id=checkpoint.id,
                    user_id=70004,
                    kind="ONE_TIME",
                    starts_at=now - timedelta(hours=1),
                    ends_at=now + timedelta(hours=1),
                    created_by=70001,
                ),
            ]
        )
        await session.commit()

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield client, factory, apartment_id, other_apartment_id, checkpoint_id, other_checkpoint_id
        finally:
            app.dependency_overrides.pop(get_session, None)
            await engine.dispose()


@pytest.mark.asyncio
async def test_resident_visit_atomic_decision_and_outbox(product_client) -> None:
    client, factory, apartment_id, _, checkpoint_id, _ = product_client
    resident = {"X-Demo-User": "70002"}
    guard_a = {"X-Demo-User": "70003"}
    guard_b = {"X-Demo-User": "70004"}
    created = await client.post(
        "/api/v1/visit-requests",
        headers=resident,
        json={
            "apartment_id": str(apartment_id),
            "checkpoint_id": str(checkpoint_id),
            "visitor_type": "COURIER",
            "visitor_name": "Курьер Алексей Орлов",
            "resident_contact": "+7 900 000-00-01",
            "comment": "Демо",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    assert created.json()["notified_guards"] == 2

    queue = await client.get("/api/v1/guards/queue?q=Орлов", headers=guard_a)
    assert queue.status_code == 200
    assert len(queue.json()["items"]) == 1

    passed = await client.post(
        f"/api/v1/guards/{request_id}/decision",
        headers=guard_a,
        json={"status": "PASSED"},
    )
    assert passed.status_code == 200, passed.text
    duplicate = await client.post(
        f"/api/v1/guards/{request_id}/decision",
        headers=guard_b,
        json={"status": "PASSED"},
    )
    assert duplicate.status_code == 409

    history = await client.get("/api/v1/visit-requests?history=true", headers=resident)
    assert [item["status"] for item in history.json()] == ["PASSED"]
    async with factory() as session:
        assert await session.scalar(select(func.count(Notification.id))) == 3


@pytest.mark.asyncio
async def test_cross_apartment_and_cross_checkpoint_are_rejected(product_client) -> None:
    client, _, apartment_id, other_apartment_id, checkpoint_id, other_checkpoint_id = product_client
    resident = {"X-Demo-User": "70002"}
    body = {
        "apartment_id": str(other_apartment_id),
        "checkpoint_id": str(checkpoint_id),
        "visitor_type": "GUEST",
        "visitor_name": "Елена Смирнова",
    }
    forbidden_apartment = await client.post("/api/v1/visit-requests", headers=resident, json=body)
    assert forbidden_apartment.status_code == 403

    body["apartment_id"] = str(apartment_id)
    body["checkpoint_id"] = str(other_checkpoint_id)
    foreign_checkpoint = await client.post("/api/v1/visit-requests", headers=resident, json=body)
    assert foreign_checkpoint.status_code == 422


@pytest.mark.asyncio
async def test_cancelled_request_is_kept_in_resident_history(product_client) -> None:
    client, _, apartment_id, _, checkpoint_id, _ = product_client
    resident = {"X-Demo-User": "70002"}
    created = await client.post(
        "/api/v1/visit-requests",
        headers=resident,
        json={
            "apartment_id": str(apartment_id),
            "checkpoint_id": str(checkpoint_id),
            "visitor_type": "GUEST",
            "visitor_name": "Гость Тестовый",
            "resident_contact": "+7 900 000-00-01",
        },
    )
    assert created.status_code == 201, created.text
    cancelled = await client.post(
        f"/api/v1/visit-requests/{created.json()['id']}/cancel",
        headers=resident,
    )
    assert cancelled.status_code == 200
    history = await client.get("/api/v1/visit-requests?history=true", headers=resident)
    assert [item["status"] for item in history.json()] == ["CANCELLED"]


@pytest.mark.asyncio
async def test_two_registry_members_can_live_in_one_apartment(product_client) -> None:
    client, factory, *_ = product_client
    second_user = {"X-Demo-User": "70005"}
    response = await client.post(
        "/api/v1/auth/resident/register",
        headers=second_user,
        json={
            "full_name": "Иванова Мария Петровна",
            "building": "1",
            "apartment": "101",
            "default_contact": "+7 900 000-00-02",
        },
    )
    assert response.status_code == 201, response.text
    async with factory() as session:
        member = await session.scalar(select(ResidentApartment).where(ResidentApartment.user_id == 70005))
        assert member is not None


@pytest.mark.asyncio
async def test_resident_can_link_second_registry_apartment(product_client) -> None:
    client, factory, _, _, _, _ = product_client
    response = await client.post(
        "/api/v1/auth/resident/register",
        headers={"X-Demo-User": "70002"},
        json={
            "full_name": "Иванов Иван Иванович",
            "building": "2",
            "apartment": "202",
            "default_contact": "+7 900 000-00-01",
        },
    )
    assert response.status_code == 201, response.text
    async with factory() as session:
        memberships = await session.scalars(
            select(ResidentApartment).where(ResidentApartment.user_id == 70002)
        )
        assert len(list(memberships)) == 2


@pytest.mark.asyncio
async def test_max_demo_profile_uses_seeded_identity_and_role_permissions(product_client, monkeypatch) -> None:
    client, *_ = product_client
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "max_bot_token", "test-token")

    profiles = await client.get("/api/v1/demo/users-public")
    assert profiles.status_code == 200
    assert {profile["role"] for profile in profiles.json()} == {"ADMIN", "GUARD", "RESIDENT"}

    max_auth = f"tma {_signed_init_data('test-token', user_id=90001, auth_date=int(datetime.now(timezone.utc).timestamp()))}"
    resident_headers = {"Authorization": max_auth, "X-Demo-User": "70002"}
    resident = await client.get("/api/v1/auth/me", headers=resident_headers)
    assert resident.status_code == 200
    assert resident.json()["user_id"] == 70002
    assert resident.json()["role"] == "RESIDENT"
    assert resident.json()["demo"] is True
    assert resident.json()["apartments"]

    admin = await client.get("/api/v1/admin/dashboard", headers={"X-Demo-User": "70001"})
    resident_as_admin = await client.get("/api/v1/admin/dashboard", headers=resident_headers)
    guard_as_admin = await client.get(
        "/api/v1/admin/dashboard", headers={"X-Demo-User": "70003"}
    )
    assert admin.status_code == 200
    assert resident_as_admin.status_code == 403
    assert guard_as_admin.status_code == 403


@pytest.mark.asyncio
async def test_production_ignores_demo_profile_and_hides_picker(product_client, monkeypatch) -> None:
    client, factory, *_ = product_client
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "max_bot_token", "test-token")
    async with factory() as session:
        session.add(Account(max_user_id=90001, role="RESIDENT", full_name="Пользователь MAX"))
        await session.commit()

    demo_profiles = await client.get("/api/v1/demo/users-public")
    assert demo_profiles.status_code == 404

    without_max_auth = await client.get(
        "/api/v1/auth/me", headers={"X-Demo-User": "70001"}
    )
    assert without_max_auth.status_code == 401

    max_auth = f"tma {_signed_init_data('test-token', user_id=90001, auth_date=int(datetime.now(timezone.utc).timestamp()))}"
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": max_auth, "X-Demo-User": "70001"},
    )
    assert response.status_code == 200
    assert response.json()["user_id"] == 90001
    assert response.json()["role"] == "RESIDENT"
    assert response.json()["demo"] is False


@pytest.mark.asyncio
async def test_production_bootstrap_creates_initial_admin_once(product_client, monkeypatch) -> None:
    _, factory, *_ = product_client
    monkeypatch.setattr("app.web.start.SessionLocal", factory)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_max_user_id", 70006)
    monkeypatch.setattr(settings, "initial_complex_name", "Пилотный комплекс")
    monkeypatch.setattr(settings, "initial_complex_city", "Казань")

    await bootstrap_production_admin()
    await bootstrap_production_admin()

    async with factory() as session:
        admin = await session.get(Account, 70006)
        complex_admin = await session.scalar(select(ComplexAdmin).where(ComplexAdmin.user_id == 70006))
        events = await session.scalars(
            select(AuditEvent).where(AuditEvent.actor_id == 70006, AuditEvent.action == "ADMIN_BOOTSTRAPPED")
        )
        assert admin is not None and admin.role == "ADMIN"
        assert complex_admin is not None
        assert len(list(events)) == 1
