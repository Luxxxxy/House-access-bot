from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select

from app.domain.models import (
    Account,
    Apartment,
    Building,
    Checkpoint,
    ComplexAdmin,
    GuardCheckpoint,
    GuardProfile,
    GuardShift,
    RegistryEntry,
    ResidentApartment,
    ResidentialComplex,
    VisitRequest,
)
from app.web.db import SessionLocal, engine

DEMO_NS = uuid.UUID("4c948817-8fa3-4e9d-aeb8-8c2f71115d68")
DEMO_ADMIN_ID = 100001
DEMO_GUARD_IDS = (200001, 200002, 200003, 200004)
DEMO_RESIDENT_IDS = tuple(range(300001, 300021))

GUARD_NAMES = (
    "Иван Сергеевич Иванов",
    "Павел Андреевич Смирнов",
    "Олег Викторович Кузнецов",
    "Денис Михайлович Петров",
)

REGISTRY_PEOPLE = (
    ("Иванов Иван Иванович", "101", "1"),
    ("Иванова Мария Петровна", "101", "1"),
    ("Петров Пётр Сергеевич", "102", "1"),
    ("Сидорова Анна Андреевна", "205", "2"),
    ("Кузнецов Алексей Олегович", "206", "2"),
    ("Смирнова Елена Викторовна", "303", "1"),
    ("Васильев Дмитрий Павлович", "304", "1"),
    ("Попова Ольга Игоревна", "401", "2"),
    ("Соколов Михаил Евгеньевич", "402", "2"),
    ("Лебедева Ирина Николаевна", "501", "1"),
    ("Новиков Артём Романович", "502", "1"),
    ("Морозова Дарья Максимовна", "601", "2"),
    ("Фёдоров Никита Андреевич", "602", "2"),
    ("Волкова Софья Денисовна", "701", "1"),
    ("Алексеев Кирилл Ильич", "702", "1"),
    ("Павлова Екатерина Юрьевна", "801", "2"),
    ("Семёнов Роман Викторович", "802", "2"),
    ("Голубева Полина Сергеевна", "901", "1"),
    ("Виноградов Егор Алексеевич", "902", "1"),
    ("Беляева Алина Михайловна", "1001", "2"),
)


def uid(value: str) -> uuid.UUID:
    return uuid.uuid5(DEMO_NS, value)


async def seed_demo() -> None:
    async with SessionLocal() as session:
        complex_id = uid("complex")
        complex_obj = await session.get(ResidentialComplex, complex_id)
        if complex_obj is None:
            session.add(
                ResidentialComplex(
                    id=complex_id,
                    name="Северный парк",
                    city="Москва",
                    timezone="Europe/Moscow",
                )
            )

        buildings: dict[str, Building] = {}
        for number in ("1", "2"):
            building_id = uid(f"building-{number}")
            building = await session.get(Building, building_id)
            if building is None:
                building = Building(id=building_id, complex_id=complex_id, name=number)
                session.add(building)
            buildings[number] = building

        checkpoints: dict[int, Checkpoint] = {}
        checkpoint_definitions = (
            (1, "КПП №1 — Центральный"),
            (2, "КПП №2 — Автомобильный"),
        )
        for number, name in checkpoint_definitions:
            checkpoint_id = uid(f"checkpoint-{number}")
            checkpoint = await session.get(Checkpoint, checkpoint_id)
            if checkpoint is None:
                checkpoint = Checkpoint(
                    id=checkpoint_id,
                    complex_id=complex_id,
                    name=name,
                    description="Демонстрационный КПП",
                )
                session.add(checkpoint)
            checkpoints[number] = checkpoint

        # Flush all complex-level parents before constructing their children.
        await session.flush()

        apartments: dict[tuple[str, str], Apartment] = {}
        for _, apartment_number, building_number in REGISTRY_PEOPLE:
            key = (building_number, apartment_number)
            if key in apartments:
                continue
            apartment_id = uid(f"apartment-{building_number}-{apartment_number}")
            apartment = await session.get(Apartment, apartment_id)
            if apartment is None:
                apartment = Apartment(
                    id=apartment_id,
                    building_id=buildings[building_number].id,
                    number=apartment_number,
                )
                session.add(apartment)
            apartments[key] = apartment
        await session.flush()

        # MAX user ids are the accounts' external identifiers and primary keys.
        # Every user reference below uses these same ids; there is no second DB id.
        demo_accounts = [
            Account(
                max_user_id=DEMO_ADMIN_ID,
                role="ADMIN",
                full_name="Демо Администратор",
                username="demo_admin",
                is_demo=True,
            )
        ]
        demo_accounts.extend(
            Account(
                max_user_id=user_id,
                role="GUARD",
                full_name=full_name,
                username=f"demo_guard_{index + 1}",
                is_demo=True,
            )
            for index, (user_id, full_name) in enumerate(zip(DEMO_GUARD_IDS, GUARD_NAMES))
        )
        demo_accounts.extend(
            Account(
                max_user_id=user_id,
                role="RESIDENT",
                full_name=full_name,
                username=f"demo_resident_{index + 1:02d}",
                default_contact=f"+7 900 000-{index + 1:02d}-{index + 10:02d}",
                is_demo=True,
            )
            for index, (user_id, (full_name, _, _)) in enumerate(
                zip(DEMO_RESIDENT_IDS, REGISTRY_PEOPLE)
            )
        )
        for account in demo_accounts:
            if await session.get(Account, account.max_user_id) is None:
                session.add(account)
        # Parent accounts must be persisted before any profile or association row.
        await session.flush()

        registry_entries: dict[tuple[str, str, str], RegistryEntry] = {}
        for full_name, apartment_number, building_number in REGISTRY_PEOPLE:
            apt = apartments[(building_number, apartment_number)]
            normalized = " ".join(full_name.casefold().split())
            entry = await session.scalar(
                select(RegistryEntry).where(
                    RegistryEntry.apartment_id == apt.id,
                    RegistryEntry.normalized_name == normalized,
                )
            )
            if entry is None:
                entry = RegistryEntry(
                    apartment_id=apt.id,
                    full_name=full_name,
                    normalized_name=normalized,
                )
                session.add(entry)
            registry_entries[(building_number, apartment_number, normalized)] = entry

        # Ivanov is registered in two apartments in the demo data.
        first_name, _, _ = REGISTRY_PEOPLE[0]
        first_normalized = " ".join(first_name.casefold().split())
        second_apt = apartments[("1", "102")]
        second_entry = await session.scalar(
            select(RegistryEntry).where(
                RegistryEntry.apartment_id == second_apt.id,
                RegistryEntry.normalized_name == first_normalized,
            )
        )
        if second_entry is None:
            second_entry = RegistryEntry(
                apartment_id=second_apt.id,
                full_name=first_name,
                normalized_name=first_normalized,
            )
            session.add(second_entry)
        registry_entries[("1", "102", first_normalized)] = second_entry
        await session.flush()

        # Guard profiles are parent rows of guard_checkpoints and guard_shifts.
        # Flush them separately so association inserts cannot race their creation.
        for user_id in DEMO_GUARD_IDS:
            profile = await session.get(GuardProfile, user_id)
            if profile is None:
                session.add(GuardProfile(user_id=user_id, complex_id=complex_id, status="VERIFIED"))
            else:
                profile.complex_id = complex_id
                profile.status = "VERIFIED"
        await session.flush()

        # Associations are only written after all their parent rows exist.
        if await session.get(ComplexAdmin, (complex_id, DEMO_ADMIN_ID)) is None:
            session.add(ComplexAdmin(complex_id=complex_id, user_id=DEMO_ADMIN_ID))

        for index, (user_id, (full_name, apartment_number, building_number)) in enumerate(
            zip(DEMO_RESIDENT_IDS, REGISTRY_PEOPLE)
        ):
            apt = apartments[(building_number, apartment_number)]
            normalized = " ".join(full_name.casefold().split())
            entry = registry_entries[(building_number, apartment_number, normalized)]
            resident_apartments = [(apt, entry)]
            if index == 0:
                resident_apartments.append(
                    (second_apt, registry_entries[("1", "102", first_normalized)])
                )
            for resident_apt, resident_entry in resident_apartments:
                association = await session.scalar(
                    select(ResidentApartment).where(
                        ResidentApartment.user_id == user_id,
                        ResidentApartment.apartment_id == resident_apt.id,
                    )
                )
                if association is None:
                    session.add(
                        ResidentApartment(
                            user_id=user_id,
                            apartment_id=resident_apt.id,
                            registry_entry_id=resident_entry.id,
                        )
                    )
                elif association.registry_entry_id != resident_entry.id:
                    association.registry_entry_id = resident_entry.id

        guard_checkpoint_numbers = {
            DEMO_GUARD_IDS[0]: (1,),
            DEMO_GUARD_IDS[1]: (1, 2),
            DEMO_GUARD_IDS[2]: (2,),
            DEMO_GUARD_IDS[3]: (1,),
        }
        for user_id, checkpoint_numbers in guard_checkpoint_numbers.items():
            for checkpoint_number in checkpoint_numbers:
                checkpoint_id = checkpoints[checkpoint_number].id
                if await session.get(GuardCheckpoint, (user_id, checkpoint_id)) is None:
                    session.add(GuardCheckpoint(user_id=user_id, checkpoint_id=checkpoint_id))
        await session.flush()

        today = date.today()
        shift_rows = (
            ("shift-day", DEMO_GUARD_IDS[0], 1, time(8), time(20)),
            ("shift-night", DEMO_GUARD_IDS[1], 1, time(20), time(8)),
            ("shift-overlap", DEMO_GUARD_IDS[3], 1, time(9), time(17)),
            ("shift-car", DEMO_GUARD_IDS[2], 2, time(8), time(20)),
        )
        for key, user_id, checkpoint_number, starts, ends in shift_rows:
            for weekday in range(7):
                shift_id = uid(f"{key}-{weekday}")
                if await session.get(GuardShift, shift_id) is None:
                    session.add(
                        GuardShift(
                            id=shift_id,
                            complex_id=complex_id,
                            checkpoint_id=checkpoints[checkpoint_number].id,
                            user_id=user_id,
                            kind="RECURRING",
                            weekday=weekday,
                            starts_on=today - timedelta(days=today.weekday()),
                            start_time=starts,
                            end_time=ends,
                            created_by=DEMO_ADMIN_ID,
                        )
                    )

        now = datetime.now(UTC)
        demo_requests = (
            ("visit-courier", "COURIER", "Курьер Антон Орлов", "А123АА77", "ACTIVE", False),
            ("visit-guest", "GUEST", "Наталья Климова", None, "ACTIVE", True),
            ("visit-repair", "REPAIR", "Мастер Сергей Волков", "М456ММ99", "PASSED", False),
            ("visit-rejected", "GUEST", "Андрей Серов", None, "REJECTED", False),
        )
        demo_apartment = apartments[("1", "101")]
        for key, visitor_type, visitor_name, car, state, pinned in demo_requests:
            request_id = uid(key)
            if await session.get(VisitRequest, request_id) is None:
                session.add(
                    VisitRequest(
                        id=request_id,
                        complex_id=complex_id,
                        resident_id=DEMO_RESIDENT_IDS[0],
                        apartment_id=demo_apartment.id,
                        checkpoint_id=checkpoints[1].id,
                        visitor_type=visitor_type,
                        visitor_name=visitor_name,
                        visitor_car_number=car,
                        resident_contact="+7 900 000-01-10",
                        comment="Демо-заявка для презентации",
                        status=state,
                        is_pinned=pinned,
                        created_at=now - timedelta(hours=3),
                    )
                )
        await session.commit()


async def main() -> None:
    from app.domain.models import Base

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await seed_demo()


if __name__ == "__main__":
    asyncio.run(main())
