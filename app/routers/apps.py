from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.models import App
from app.core.schemas import AppResponse

router = APIRouter()


@router.get("", response_model=list[AppResponse])
async def list_apps(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(App).where(App.is_live.is_(True)).order_by(App.sort_order, App.id)
    )
    return result.scalars().all()
