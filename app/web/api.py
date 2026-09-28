from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import admin, auth, guards, notifications, registry, residents
from app.config import settings
from app.domain.models import Account
from app.integrations.max_webhook import router as max_webhook_router
from app.security.auth import require_role
from app.web.db import get_session

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(residents.router)
api_router.include_router(guards.router)
api_router.include_router(admin.router)
api_router.include_router(registry.router)
api_router.include_router(notifications.router)
api_router.include_router(max_webhook_router)


@api_router.get("/demo/users", tags=["demo"])
async def demo_users(
    account: Account = Depends(require_role("ADMIN", "GUARD", "RESIDENT")),
    session: AsyncSession = Depends(get_session),
):
    if not settings.demo_auth_enabled:
        raise HTTPException(404, "Demo mode is disabled")
    result = await session.scalars(
        select(Account)
        .where(Account.is_demo.is_(True), Account.is_active.is_(True))
        .order_by(Account.role, Account.full_name)
    )
    return [
        {"user_id": user.max_user_id, "role": user.role, "full_name": user.full_name}
        for user in result
    ]


@api_router.get("/demo/users-public", tags=["demo"])
async def demo_users_public(session: AsyncSession = Depends(get_session)):
    if not settings.demo_auth_enabled:
        raise HTTPException(404, "Demo mode is disabled")
    result = await session.scalars(
        select(Account)
        .where(Account.is_demo.is_(True), Account.is_active.is_(True))
        .order_by(Account.role, Account.full_name)
    )
    return [
        {"user_id": user.max_user_id, "role": user.role, "full_name": user.full_name}
        for user in result
    ]
