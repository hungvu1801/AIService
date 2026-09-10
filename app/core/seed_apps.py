from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.models import App

# Inserted only when the slug is missing. Later edits in the DB are kept.
SEED_APPS: list[dict] = [
    {
        "slug": "motion_transfer",
        "title": "Motion Transfer",
        "description": "Put your face on a dance video. Portrait image + reference clip → new video.",
        "engine_label": "WanVideo 14B",
        "route_name": "studio_page",
        "media_class": "motion",
        "badge_label": "Run",
        "is_live": True,
        "sort_order": 10,
    },
    {
        "slug": "animatediff",
        "title": "Pixel Art Video",
        "description": "AnimateDiff V2V. Restyle a clip as pixel art on the SD1.5 ComfyUI.",
        "engine_label": "AnimateDiff",
        "route_name": "studio_pixel_page",
        "media_class": "pixel",
        "badge_label": "Run",
        "is_live": True,
        "sort_order": 20,
    },
    {
        "slug": "minimax",
        "title": "MiniMax H3",
        "description": "Still image + prompt → video. MiniMaxH3ImageToVideo on the same engine.",
        "engine_label": "Image to video",
        "route_name": "studio_minimax_page",
        "media_class": "outfit",
        "badge_label": "Run",
        "is_live": True,
        "sort_order": 30,
    },
    {
        "slug": "wan_t2v",
        "title": "Wan T2V",
        "description": "Text to video. 4-step Lightning Wan 2.2 on this ComfyUI — no image or clip required.",
        "engine_label": "Wan 2.2 · 14B",
        "route_name": "studio_wan_page",
        "media_class": "wan",
        "badge_label": "Run",
        "is_live": True,
        "sort_order": 40,
    },
]


async def seed_apps(db: AsyncSession) -> None:
    result = await db.execute(select(App.slug))
    existing = set(result.scalars().all())
    for row in SEED_APPS:
        if row["slug"] in existing:
            continue
        db.add(App(**row))
    await db.commit()


def _as_plaza_card(row: object) -> SimpleNamespace:
    slug = getattr(row, "slug", "")
    return SimpleNamespace(
        slug=slug,
        title=getattr(row, "title", ""),
        description=getattr(row, "description", ""),
        engine_label=getattr(row, "engine_label", ""),
        route_name=getattr(row, "route_name", ""),
        media_class=getattr(row, "media_class", "motion"),
        badge_label=getattr(row, "badge_label", "Run"),
        is_live=bool(getattr(row, "is_live", True)),
        sort_order=getattr(row, "sort_order", 0),
        author=getattr(row, "author", None) or "aidancing",
        stars=int(getattr(row, "stars", 0) or 0),
        cover_url=f"/static/plaza/{slug}.png" if slug else "",
    )


def _seed_as_objects() -> list[SimpleNamespace]:
    return [_as_plaza_card(SimpleNamespace(**row)) for row in SEED_APPS]


async def load_plaza_apps() -> list:
    """Live rows from Postgres, or the seed catalog if the DB is down/empty."""
    try:
        async with asyncio.timeout(2):
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(App).order_by(App.sort_order, App.id))
                rows = list(result.scalars().all())
                if rows:
                    return [_as_plaza_card(row) for row in rows]
    except Exception:
        pass
    return _seed_as_objects()
