from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.models import Job
from app.engine import comfy
from app.engine.workflow_apps import (
    inject_catalog_app,
    is_catalog_app,
    sidecar_file,
)
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
        if job is None:
            return

        dest = data_root() / "outputs" / job_id
        try:
            if job.status == "processing" and job.prompt_id:
                logger.info("Resuming job %s prompt %s", job_id, job.prompt_id)
                entry = await comfy.get_history_entry(job.prompt_id)
                if entry is None:
                    probed = await comfy.probe_saved_video(
                        comfy.prefer_for_tool(job.tool)
                    )
                    if probed is None:
                        raise RuntimeError(
                            "ComfyUI result was lost after a restart. Retry the job."
                        )
                    dest = dest.with_suffix(Path(probed["filename"]).suffix or ".mp4")
                    await comfy.download_file(
                        probed["filename"],
                        probed.get("subfolder", ""),
                        probed.get("type", "output"),
                        dest,
                    )
                    output = dest
                else:
                    output = await comfy.download_output(
                        job.prompt_id,
                        dest,
                        prefer_prefixes=comfy.prefer_for_tool(job.tool),
                        prefer_video=comfy.prefers_video(job.tool),
                    )
                await db.refresh(job)
                if job.status == "cancelled":
                    return
                job.output_path = str(output)
                job.status = "done"
                job.error = None
                await db.commit()
                logger.info("Job %s done → %s", job_id, output)
                return

            if job.status == "processing" and not job.prompt_id:
                logger.warning("Job %s was interrupted before submit; requeue", job_id)
                job.status = "queued"
                await db.commit()

            if job.status != "queued":
                return

            job.status = "processing"
            await db.commit()

            await comfy.free_memory()
            if job.tool == "animatediff":
                video_name = await comfy.upload_input(Path(job.video_path))
                workflow = await asyncio.to_thread(inject_animatediff, video_name)
            elif job.tool == "minimax":
                image_name = await comfy.upload_input(Path(job.image_path))
                prompt = ""
                prompt_file = Path(job.video_path)
                if prompt_file.is_file():
                    prompt = prompt_file.read_text(encoding="utf-8")
                workflow = await asyncio.to_thread(inject_minimax, image_name, prompt)
            elif job.tool == "wan_t2v":
                prompt = ""
                prompt_file = Path(job.video_path)
                if prompt_file.is_file():
                    prompt = prompt_file.read_text(encoding="utf-8")
                negative = ""
                negative_file = prompt_file.with_name("negative.txt")
                if negative_file.is_file():
                    negative = negative_file.read_text(encoding="utf-8")
                length = None
                length_file = prompt_file.with_name("length.txt")
                if length_file.is_file():
                    try:
                        length = int(length_file.read_text(encoding="utf-8").strip())
                    except ValueError:
                        length = None
                width = height = None
                size_file = prompt_file.with_name("size.txt")
                if size_file.is_file():
                    raw = size_file.read_text(encoding="utf-8").strip().lower()
                    if "x" in raw:
                        try:
                            width_s, height_s = raw.split("x", 1)
                            width, height = int(width_s), int(height_s)
                        except ValueError:
                            width = height = None
                seconds = None
                seconds_file = prompt_file.with_name("seconds.txt")
                if seconds_file.is_file():
                    try:
                        seconds = int(seconds_file.read_text(encoding="utf-8").strip())
                    except ValueError:
                        seconds = None
                workflow = await asyncio.to_thread(
                    inject_wan_t2v,
                    prompt,
                    negative,
                    length,
                    width,
                    height,
                    seconds,
                )
            elif job.tool == "motion_transfer":
                image_name = await comfy.upload_input(Path(job.image_path))
                video_name = await comfy.upload_input(Path(job.video_path))
                workflow = await asyncio.to_thread(
                    inject_motion, load_workflow(), image_name, video_name
                )
            elif is_catalog_app(job.tool):
                folder = job_upload_dir(job.id)
                image_name = None
                if job.image_path and Path(job.image_path).is_file():
                    image_name = await comfy.upload_input(Path(job.image_path))
                image2_path = sidecar_file(folder, "image2")
                image2_name = (
                    await comfy.upload_input(image2_path) if image2_path else None
                )
                audio_path = sidecar_file(folder, "audio")
                audio_name = (
                    await comfy.upload_input(audio_path) if audio_path else None
                )
                prompt = ""
                prompt_file = folder / "prompt.txt"
                if prompt_file.is_file():
                    prompt = prompt_file.read_text(encoding="utf-8")
                negative = ""
                negative_file = folder / "negative.txt"
                if negative_file.is_file():
                    negative = negative_file.read_text(encoding="utf-8")
                extra = ""
                extra_file = folder / "extra.txt"
                if extra_file.is_file():
                    extra = extra_file.read_text(encoding="utf-8")
                workflow = await asyncio.to_thread(
                    inject_catalog_app,
                    job.tool,
                    image_name=image_name,
                    image2_name=image2_name,
                    audio_name=audio_name,
                    prompt=prompt,
                    negative=negative,
                    extra=extra,
                )
            else:
                raise ValueError(f"Unknown job tool: {job.tool}")

            prompt_id = await comfy.submit_prompt(workflow)
            job.prompt_id = prompt_id
            await db.commit()

            output = await comfy.download_output(
                prompt_id,
                dest,
                prefer_prefixes=comfy.prefer_for_tool(job.tool),
                prefer_video=comfy.prefers_video(job.tool),
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
    result = await db.execute(
        select(Job.id)
        .where(Job.status == "processing")
        .order_by(Job.updated_at.asc())
        .limit(1)
    )
    processing_id = result.scalar_one_or_none()
    if processing_id:
        return processing_id
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
