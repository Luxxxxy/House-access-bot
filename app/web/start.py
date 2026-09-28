from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid

import uvicorn
from sqlalchemy import select

from app.config import settings
from app.domain.models import Account, AuditEvent, ComplexAdmin, ResidentialComplex
from app.domain.seed import seed_demo
from app.web.db import SessionLocal

BOOTSTRAP_NS = uuid.UUID("645324c7-ef2e-44f1-9708-3a7c7580e98a")


async def bootstrap_production_admin() -> None:
    """Provision the explicitly configured first admin and its initial complex."""
    if settings.environment.lower() != "production":
        return
    if settings.admin_max_user_id is None:
        raise RuntimeError("Set ADMIN_MAX_USER_ID to the initial administrator's MAX user ID")
    if settings.initial_complex_city.strip().casefold() in {"", "укажите город"}:
        raise RuntimeError("Set INITIAL_COMPLEX_CITY before bootstrapping the production administrator")

    user_id = settings.admin_max_user_id
    async with SessionLocal() as session:
        account = await session.get(Account, user_id)
        if account is not None and account.role != "ADMIN":
            raise RuntimeError("ADMIN_MAX_USER_ID belongs to a non-admin account")
        if account is None:
            session.add(
                Account(
                    max_user_id=user_id,
                    role="ADMIN",
                    full_name="Администратор",
                    is_active=True,
                )
            )
            await session.flush()

        complex_admin = await session.scalar(
            select(ComplexAdmin).where(ComplexAdmin.user_id == user_id).limit(1)
        )
        if complex_admin is None:
            complex_id = uuid.uuid5(BOOTSTRAP_NS, str(user_id))
            complex_obj = await session.get(ResidentialComplex, complex_id)
            if complex_obj is None:
                complex_obj = ResidentialComplex(
                    id=complex_id,
                    name=settings.initial_complex_name,
                    city=settings.initial_complex_city,
                    timezone=settings.timezone,
                )
                session.add(complex_obj)
                await session.flush()
            session.add(ComplexAdmin(complex_id=complex_obj.id, user_id=user_id))
            session.add(
                AuditEvent(
                    complex_id=complex_obj.id,
                    actor_id=user_id,
                    action="ADMIN_BOOTSTRAPPED",
                    target_id=str(user_id),
                    metadata_json={},
                )
            )
        await session.commit()


async def main() -> None:
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    if settings.demo_seed and settings.environment.lower() == "development":
        await seed_demo()
    await bootstrap_production_admin()
    config = uvicorn.Config("app.web.main:app", host="0.0.0.0", port=8000, proxy_headers=True)
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
