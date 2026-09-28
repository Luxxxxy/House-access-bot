"""Сценарий визита, /cancel и защита от повторного approve/reject."""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.db.models import (
    GuardAccessRequest,
    GuardAccessStatus,
    Role,
    User,
    VisitRequest,
    VisitStatus,
)
from app.db.session import async_session_maker
from app.fsm.states import AdminForm, GuardDecision, VisitForm
from app.fsm.storage import fsm
from app.handlers.common import cmd_cancel
from app.keyboards.menus import (
    BACK,
    CHANGE_ROLE,
    CHOOSE_ADMIN,
    CHOOSE_GUARD,
    CHOOSE_USER,
    GUARD_APPLY_APPROVE_PREFIX,
    GUARD_APPLY_REJECT_PREFIX,
    GUARD_PENDING,
    RESIDENT_CONFIRM,
    RESIDENT_VISIT,
    VISIT_APPROVE_PREFIX,
    VISIT_REJECT_PREFIX,
    VISIT_REJECT_SKIP_PREFIX,
    admin_menu,
)
from tests.helpers import FakeBot, callback_update, make_dispatcher, message_update

RESIDENT_ID = 10
GUARD_ID = 20
GUARD2_ID = 21


async def _seed_users() -> None:
    async with async_session_maker() as session:
        session.add_all(
            [
                User(
                    id=RESIDENT_ID,
                    full_name="Жилец Иванов",
                    role=Role.RESIDENT,
                    is_active=True,
                ),
                User(
                    id=GUARD_ID,
                    full_name="Охранник Петров",
                    role=Role.GUARD,
                    is_active=True,
                ),
                User(
                    id=GUARD2_ID,
                    full_name="Охранник Сидоров",
                    role=Role.GUARD,
                    is_active=True,
                ),
            ]
        )
        await session.commit()


async def _latest_visit() -> VisitRequest:
    async with async_session_maker() as session:
        visit = await session.scalar(
            select(VisitRequest).order_by(VisitRequest.id.desc())
        )
        assert visit is not None
        return visit


async def test_resident_creates_visit_guard_approves_and_notifies(db: object) -> None:
    await _seed_users()
    bot = FakeBot()
    dp = make_dispatcher()

    fsm.set_state(
        RESIDENT_ID,
        VisitForm.WAITING_CONFIRM,
        guest_name="Иван",
        apartment="15",
        purpose="доставка",
    )
    await dp.feed_update(bot, callback_update(RESIDENT_ID, RESIDENT_CONFIRM))

    visit = await _latest_visit()
    assert visit.status == VisitStatus.PENDING
    assert visit.guest_name == "Иван"
    assert visit.apartment == "15"
    assert visit.purpose == "доставка"
    assert any(
        item["user_id"] == GUARD_ID and item["text"] and "Иван" in item["text"]
        for item in bot.sent
    )

    await dp.feed_update(
        bot,
        callback_update(GUARD_ID, f"{VISIT_APPROVE_PREFIX}{visit.id}", name="Охранник"),
    )

    async with async_session_maker() as session:
        updated = await session.get(VisitRequest, visit.id)
        assert updated is not None
        assert updated.status == VisitStatus.APPROVED
        assert updated.guard_id == GUARD_ID
        assert updated.resolved_at is not None

    notify = [
        item
        for item in bot.sent
        if item["user_id"] == RESIDENT_ID and item["text"] and "одобрен" in item["text"]
    ]
    assert notify, bot.sent
    assert "Иван" in (notify[-1]["text"] or "")
    assert "Петров" in (notify[-1]["text"] or "")


async def test_approve_and_reject_cannot_change_visit_twice(db: object) -> None:
    await _seed_users()
    bot = FakeBot()
    dp = make_dispatcher()

    async with async_session_maker() as session:
        visit = VisitRequest(
            resident_id=RESIDENT_ID,
            guest_name="Гость",
            apartment="10",
            purpose="встреча",
            status=VisitStatus.PENDING,
        )
        session.add(visit)
        await session.commit()
        await session.refresh(visit)
        visit_id = visit.id

    await dp.feed_update(bot, callback_update(GUARD_ID, f"{VISIT_APPROVE_PREFIX}{visit_id}"))
    await dp.feed_update(bot, callback_update(GUARD2_ID, f"{VISIT_APPROVE_PREFIX}{visit_id}"))
    await dp.feed_update(
        bot,
        callback_update(GUARD2_ID, f"{VISIT_REJECT_SKIP_PREFIX}{visit_id}"),
    )

    async with async_session_maker() as session:
        updated = await session.get(VisitRequest, visit_id)
        assert updated is not None
        assert updated.status == VisitStatus.APPROVED
        assert updated.guard_id == GUARD_ID

    already = [item for item in bot.sent if item["text"] == "Заявка уже обработана."]
    assert already


async def test_cancel_clears_all_fsm_states(db: object) -> None:
    bot = FakeBot()
    cases = (
        (101, VisitForm.WAITING_GUEST_NAME),
        (108, VisitForm.WAITING_APARTMENT),
        (102, VisitForm.WAITING_PURPOSE),
        (103, VisitForm.WAITING_CONFIRM),
        (104, GuardDecision.WAITING_REJECT_COMMENT),
        (105, AdminForm.WAITING_GUARD_CODE),
        (106, AdminForm.WAITING_ADMIN_CODE),
        (107, GuardDecision.WAITING_VISIT_ID),
    )
    for user_id, state in cases:
        fsm.set_state(user_id, state, leftover=True)
        assert fsm.get_state(user_id) == state
        await cmd_cancel(bot, message_update(user_id, "/cancel"))
        assert fsm.get_state(user_id) is None
        assert fsm.get_data(user_id) == {}

    cancelled = [item for item in bot.sent if item["text"] == "Действие отменено."]
    assert len(cancelled) == len(cases)


async def test_start_allows_user_or_explicitly_configured_admin_code(db: object, monkeypatch) -> None:
    bot = FakeBot()
    dp = make_dispatcher()
    user_id = 77

    await dp.feed_update(bot, message_update(user_id, "/start", name="Егор"))
    assert any("Кем вы хотите войти" in (item["text"] or "") for item in bot.sent)

    await dp.feed_update(bot, callback_update(user_id, CHOOSE_USER, name="Егор"))
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.role == Role.RESIDENT

    await dp.feed_update(bot, callback_update(user_id, CHOOSE_ADMIN, name="Егор"))
    settings.admin_max_user_id = None
    await dp.feed_update(bot, message_update(user_id, "0000", name="Егор"))
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.role == Role.RESIDENT

    monkeypatch.setattr(settings, "admin_access_code", "3407")
    await dp.feed_update(bot, message_update(user_id, "3407", name="Егор"))
    async with async_session_maker() as session:
        user = await session.get(User, user_id)
        assert user is not None
        assert user.role == Role.ADMIN
    assert settings.admin_max_user_id == user_id
    menu = admin_menu()
    payloads = [
        btn.payload
        for row in menu.payload.buttons
        for btn in row
    ]
    assert "admin:add_guard" not in payloads
    assert any(payload == RESIDENT_VISIT for payload in payloads)


async def test_guard_applies_admin_approves_with_explicit_code(db: object, monkeypatch) -> None:
    admin_id = 1
    applicant_id = 88
    async with async_session_maker() as session:
        session.add(
            User(
                id=admin_id,
                full_name="Админ",
                role=Role.ADMIN,
                is_active=True,
            )
        )
        await session.commit()

    bot = FakeBot()
    dp = make_dispatcher()

    await dp.feed_update(bot, message_update(applicant_id, "/start", name="Олег"))
    await dp.feed_update(bot, callback_update(applicant_id, CHOOSE_GUARD, name="Олег"))
    await dp.feed_update(bot, message_update(applicant_id, "0000", name="Олег"))
    async with async_session_maker() as session:
        user = await session.get(User, applicant_id)
        assert user is not None
        assert user.role == Role.RESIDENT

    monkeypatch.setattr(settings, "guard_access_code", "6767")
    await dp.feed_update(bot, message_update(applicant_id, "6767", name="Олег"))
    async with async_session_maker() as session:
        user = await session.get(User, applicant_id)
        assert user is not None
        assert user.role == Role.RESIDENT
        request = await session.scalar(
            select(GuardAccessRequest).where(GuardAccessRequest.user_id == applicant_id)
        )
        assert request is not None
        assert request.status == GuardAccessStatus.PENDING
        request_id = request.id

    notice = [
        item
        for item in bot.sent
        if item["user_id"] == admin_id and item["text"] and "охранника" in item["text"]
    ]
    assert notice, bot.sent

    await dp.feed_update(
        bot,
        callback_update(admin_id, f"{GUARD_APPLY_APPROVE_PREFIX}{request_id}", name="Админ"),
    )
    async with async_session_maker() as session:
        user = await session.get(User, applicant_id)
        assert user is not None
        assert user.role == Role.GUARD
        assert user.is_active is True
        assert user.guard_approved is True
        request = await session.get(GuardAccessRequest, request_id)
        assert request is not None
        assert request.status == GuardAccessStatus.APPROVED

    granted = [
        item
        for item in bot.sent
        if item["user_id"] == applicant_id
        and item["text"]
        and "доступ охранника" in item["text"]
    ]
    assert granted
    assert granted[-1]["attachments"]
    assert "Выберите действие" in (granted[-1]["text"] or "")
    assert "Нажмите /start" not in (granted[-1]["text"] or "")

    admin_notices_before = len(notice)
    await dp.feed_update(bot, callback_update(applicant_id, CHANGE_ROLE, name="Олег"))
    await dp.feed_update(bot, callback_update(applicant_id, CHOOSE_USER, name="Олег"))
    async with async_session_maker() as session:
        user = await session.get(User, applicant_id)
        assert user is not None
        assert user.role == Role.RESIDENT
        assert user.guard_approved is True

    await dp.feed_update(bot, callback_update(applicant_id, CHOOSE_GUARD, name="Олег"))
    await dp.feed_update(bot, message_update(applicant_id, "6767", name="Олег"))
    async with async_session_maker() as session:
        user = await session.get(User, applicant_id)
        assert user is not None
        assert user.role == Role.GUARD
        pending = (
            await session.scalars(
                select(GuardAccessRequest).where(
                    GuardAccessRequest.user_id == applicant_id,
                    GuardAccessRequest.status == GuardAccessStatus.PENDING,
                )
            )
        ).all()
        assert pending == []

    admin_notices_after = [
        item
        for item in bot.sent
        if item["user_id"] == admin_id and item["text"] and "Новая заявка" in item["text"]
    ]
    assert len(admin_notices_after) == admin_notices_before

    await dp.feed_update(bot, callback_update(applicant_id, BACK, name="Олег"))
    assert any("Вы вошли как охранник" in (item["text"] or "") for item in bot.sent)


async def test_admin_can_create_visit_request(db: object) -> None:
    admin_id = 1
    async with async_session_maker() as session:
        session.add_all(
            [
                User(
                    id=admin_id,
                    full_name="Админ",
                    role=Role.ADMIN,
                    is_active=True,
                ),
                User(
                    id=GUARD_ID,
                    full_name="Охранник Петров",
                    role=Role.GUARD,
                    is_active=True,
                ),
            ]
        )
        await session.commit()

    bot = FakeBot()
    dp = make_dispatcher()
    fsm.set_state(
        admin_id,
        VisitForm.WAITING_CONFIRM,
        guest_name="Гость админа",
        apartment="7А",
        purpose="проверка",
    )
    await dp.feed_update(bot, callback_update(admin_id, RESIDENT_CONFIRM, name="Админ"))

    visit = await _latest_visit()
    assert visit.resident_id == admin_id
    assert visit.guest_name == "Гость админа"
    assert visit.apartment == "7А"
    assert visit.status == VisitStatus.PENDING
    assert any(
        item["user_id"] == GUARD_ID and item["text"] and "Гость админа" in item["text"]
        for item in bot.sent
    )


async def test_admin_can_reject_guard_application(db: object) -> None:
    admin_id = 1
    applicant_id = 89
    async with async_session_maker() as session:
        session.add(
            User(
                id=admin_id,
                full_name="Админ",
                role=Role.ADMIN,
                is_active=True,
            )
        )
        session.add(
            User(
                id=applicant_id,
                full_name="Кандидат",
                role=Role.RESIDENT,
                is_active=True,
            )
        )
        request = GuardAccessRequest(
            user_id=applicant_id,
            status=GuardAccessStatus.PENDING,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)
        request_id = request.id

    bot = FakeBot()
    dp = make_dispatcher()
    await dp.feed_update(
        bot,
        callback_update(admin_id, f"{GUARD_APPLY_REJECT_PREFIX}{request_id}", name="Админ"),
    )
    async with async_session_maker() as session:
        user = await session.get(User, applicant_id)
        assert user is not None
        assert user.role == Role.RESIDENT
        stored = await session.get(GuardAccessRequest, request_id)
        assert stored is not None
        assert stored.status == GuardAccessStatus.REJECTED


async def test_guard_approves_visit_by_number_from_pending_list(db: object) -> None:
    await _seed_users()
    bot = FakeBot()
    dp = make_dispatcher()

    async with async_session_maker() as session:
        visit = VisitRequest(
            resident_id=RESIDENT_ID,
            guest_name="Курьер",
            apartment="22",
            purpose="доставка",
            status=VisitStatus.PENDING,
        )
        session.add(visit)
        await session.commit()
        await session.refresh(visit)
        visit_id = visit.id

    await dp.feed_update(bot, callback_update(GUARD_ID, GUARD_PENDING, name="Охранник"))
    assert fsm.get_state(GUARD_ID) == GuardDecision.WAITING_VISIT_ID

    await dp.feed_update(bot, message_update(GUARD_ID, f"#{visit_id}", name="Охранник"))
    offered = [
        item
        for item in bot.sent
        if item["text"] and "Курьер" in item["text"] and item["attachments"]
    ]
    assert offered

    await dp.feed_update(
        bot,
        callback_update(GUARD_ID, f"{VISIT_APPROVE_PREFIX}{visit_id}", name="Охранник"),
    )
    async with async_session_maker() as session:
        updated = await session.get(VisitRequest, visit_id)
        assert updated is not None
        assert updated.status == VisitStatus.APPROVED
        assert updated.guard_id == GUARD_ID
    assert fsm.get_state(GUARD_ID) == GuardDecision.WAITING_VISIT_ID
    assert any(
        item["user_id"] == RESIDENT_ID and item["text"] and "одобрен" in item["text"]
        for item in bot.sent
    )


async def test_guard_rejects_visit_by_number_from_pending_list(db: object) -> None:
    await _seed_users()
    bot = FakeBot()
    dp = make_dispatcher()

    async with async_session_maker() as session:
        visit = VisitRequest(
            resident_id=RESIDENT_ID,
            guest_name="Гость",
            apartment="10",
            purpose="встреча",
            status=VisitStatus.PENDING,
        )
        session.add(visit)
        await session.commit()
        await session.refresh(visit)
        visit_id = visit.id

    await dp.feed_update(bot, callback_update(GUARD_ID, GUARD_PENDING, name="Охранник"))
    await dp.feed_update(bot, message_update(GUARD_ID, str(visit_id), name="Охранник"))
    await dp.feed_update(
        bot,
        callback_update(GUARD_ID, f"{VISIT_REJECT_PREFIX}{visit_id}", name="Охранник"),
    )
    await dp.feed_update(
        bot,
        callback_update(GUARD_ID, f"{VISIT_REJECT_SKIP_PREFIX}{visit_id}", name="Охранник"),
    )
    async with async_session_maker() as session:
        updated = await session.get(VisitRequest, visit_id)
        assert updated is not None
        assert updated.status == VisitStatus.REJECTED
        assert updated.guard_id == GUARD_ID
    assert fsm.get_state(GUARD_ID) == GuardDecision.WAITING_VISIT_ID
