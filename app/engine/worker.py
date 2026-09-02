from __future__ import annotations

import logging
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.models import Job
from app.engine import comfy
from app.engine.workflow_convert import (
    inject_animatediff,
    inject_minimax,
    inject_motion,
    inject_wan_t2v,
    load_workflow,
)

logger = logging.getLogger(__name__)


def data_root() -> Path:
    root = Path(settings.data_dir)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    return root


def job_upload_dir(job_id: str) -> Path:
    path = data_root() / "uploads" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


async def process_job(job_id: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "processing"
        await db.commit()

        dest = data_root() / "outputs" / job_id
        try:
            await comfy.free_memory()
            if job.tool == "animatediff":
                video_name = await comfy.upload_input(Path(job.video_path))
                workflow = inject_animatediff(video_name)
            elif job.tool == "minimax":
                image_name = await comfy.upload_input(Path(job.image_path))
                prompt = ""
                prompt_file = Path(job.video_path)
                if prompt_file.is_file():
                    prompt = prompt_file.read_text(encoding="utf-8")
                workflow = inject_minimax(image_name, prompt)
            elif job.tool == "wan_t2v":
                prompt = ""
                prompt_file = Path(job.video_path)
                if prompt_file.is_file():
                    prompt = prompt_file.read_text(encoding="utf-8")
                negative = ""
                negative_file = prompt_file.with_name("negative.txt")
                if negative_file.is_file():
                    negative = negative_file.read_text(encoding="utf-8")
                workflow = inject_wan_t2v(prompt, negative)
            elif job.tool == "motion_transfer":
                image_name = await comfy.upload_input(Path(job.image_path))
                video_name = await comfy.upload_input(Path(job.video_path))
                workflow = inject_motion(load_workflow(), image_name, video_name)
            else:
                raise ValueError(f"Unknown job tool: {job.tool}")

            prompt_id = await comfy.submit_prompt(workflow)
            job.prompt_id = prompt_id
            await db.commit()

            output = await comfy.download_output(
                prompt_id,
                dest,
                prefer_prefixes=comfy.prefer_for_tool(job.tool),
            )
            await db.refresh(job)
            if job.status == "cancelled":
                return
            job.output_path = str(output)
            job.status = "done"
            job.error = None
            await db.commit()
            logger.info("Job %s done → %s", job_id, output)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)[:2000]
            await db.commit()


async def next_queued_job_id(db: AsyncSession) -> str | None:
    processing = await db.scalar(
        select(func.count()).select_from(Job).where(Job.status == "processing")
    )
    if processing:
        return None
    result = await db.execute(
        select(Job.id)
        .where(Job.status == "queued")
        .order_by(Job.priority.desc(), Job.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def job_worker() -> None:
    import asyncio

    await asyncio.sleep(1)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                job_id = await next_queued_job_id(db)
            if job_id:
                await process_job(job_id)
        except Exception:
            logger.exception("Job worker loop error")
        await asyncio.sleep(3)


def new_job_id() -> str:
    return str(uuid.uuid4())
