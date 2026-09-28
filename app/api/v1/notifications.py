from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Account, Notification
from app.security.auth import require_role
from app.web.db import get_session

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(
    account: Account = Depends(require_role("ADMIN", "GUARD", "RESIDENT")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(Notification)
        .where(Notification.recipient_id == account.max_user_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return [
        {
            "id": str(item.id),
            "request_id": str(item.request_id) if item.request_id else None,
            "text": item.text,
            "status": item.status,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "sent_at": item.sent_at.isoformat() if item.sent_at else None,
        }
        for item in rows
    ]
