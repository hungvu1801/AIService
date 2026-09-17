from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.core.models import Job
from app.core.schemas import JobResponse
from app.engine import comfy
from app.engine.worker import job_upload_dir, new_job_id
from app.engine.workflow_apps import (
    catalog_inputs_exist,
    get_catalog_app,
    is_catalog_app,
)
from app.engine.workflow_convert import (
    WAN_T2V_LENGTH_BY_SECONDS,
    WAN_T2V_SIZES,
    wan_t2v_frame_count,
    wan_t2v_size,
)

router = APIRouter()

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_RETRYABLE = frozenset({"failed", "cancelled"})


def _to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        tool=job.tool,
        status=job.status,
        image_name=job.image_name,
        video_name=job.video_name,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
        has_output=bool(job.output_path),
    )


def _safe_filename(name: str, fallback: str) -> str:
    cleaned = _SAFE_NAME.sub("_", Path(name or fallback).name).strip("._")
    return cleaned or fallback


def _inputs_exist(job: Job) -> bool:
    image = Path(job.image_path) if job.image_path else None
    video = Path(job.video_path) if job.video_path else None
    if job.tool == "motion_transfer":
        return bool(image and video and image.is_file() and video.is_file())
    if job.tool == "animatediff":
        return bool(video and video.is_file())
    if job.tool == "minimax":
        return bool(image and video and image.is_file() and video.is_file())
    if job.tool == "wan_t2v":
        return bool(video and video.is_file())
    if is_catalog_app(job.tool):
        return catalog_inputs_exist(
            job.id, job.tool, job.image_path or "", job.video_path or ""
        )
    return False


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large (max {limit} bytes)",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    return data


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_job(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    image: Annotated[UploadFile, File()],
    video: Annotated[UploadFile, File()],
):
    image_bytes = await _read_limited(image, settings.max_upload_size_bytes)
    video_bytes = await _read_limited(video, settings.max_video_upload_bytes)

    job_id = new_job_id()
    folder = job_upload_dir(job_id)
    image_name = _safe_filename(image.filename or "portrait.png", "portrait.png")
    video_name = _safe_filename(video.filename or "dance.mp4", "dance.mp4")
    image_path = folder / image_name
    video_path = folder / video_name
    image_path.write_bytes(image_bytes)
    video_path.write_bytes(video_bytes)

    job = Job(
        id=job_id,
        user_id=current_user.id,
        tool="motion_transfer",
        status="queued",
        image_path=str(image_path),
        video_path=str(video_path),
        image_name=image_name,
        video_name=video_name,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.post("/animatediff", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_animatediff_job(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    video: Annotated[UploadFile, File()],
):
    video_bytes = await _read_limited(video, settings.max_video_upload_bytes)
    job_id = new_job_id()
    folder = job_upload_dir(job_id)
    video_name = _safe_filename(video.filename or "clip.mp4", "clip.mp4")
    video_path = folder / video_name
    video_path.write_bytes(video_bytes)

    job = Job(
        id=job_id,
        user_id=current_user.id,
        tool="animatediff",
        status="queued",
        image_path="",
        video_path=str(video_path),
        image_name="-",
        video_name=video_name,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.post("/minimax", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_minimax_job(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    image: Annotated[UploadFile, File()],
    prompt: Annotated[str, Form()] = "",
):
    image_bytes = await _read_limited(image, settings.max_upload_size_bytes)
    job_id = new_job_id()
    folder = job_upload_dir(job_id)
    image_name = _safe_filename(image.filename or "frame.png", "frame.png")
    image_path = folder / image_name
    image_path.write_bytes(image_bytes)
    prompt_path = folder / "prompt.txt"
    prompt_path.write_text(prompt or "", encoding="utf-8")
    label = (prompt or "").strip().replace("\n", " ")[:80] or "prompt"

    job = Job(
        id=job_id,
        user_id=current_user.id,
        tool="minimax",
        status="queued",
        image_path=str(image_path),
        video_path=str(prompt_path),
        image_name=image_name,
        video_name=label,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.post("/wan", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_wan_t2v_job(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    prompt: Annotated[str, Form()],
    negative: Annotated[str, Form()] = "",
    seconds: Annotated[int, Form()] = 5,
    size: Annotated[str, Form()] = "832x480",
):
    text = (prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Prompt is required")
    if len(text) > 16000:
        raise HTTPException(status_code=400, detail="Prompt is too long")
    if seconds not in WAN_T2V_LENGTH_BY_SECONDS:
        raise HTTPException(
            status_code=400,
            detail="Duration must be 2, 4, 5, or 8 seconds",
        )
    if size not in WAN_T2V_SIZES:
        raise HTTPException(
            status_code=400,
            detail="Resolution must be 640x384, 832x480, 1024x576, or 1280x720",
        )

    job_id = new_job_id()
    folder = job_upload_dir(job_id)
    prompt_path = folder / "prompt.txt"
    prompt_path.write_text(text, encoding="utf-8")
    negative_text = (negative or "").strip()
    if negative_text:
        (folder / "negative.txt").write_text(negative_text, encoding="utf-8")
    (folder / "length.txt").write_text(
        str(wan_t2v_frame_count(seconds)), encoding="utf-8"
    )
    width, height = wan_t2v_size(size)
    (folder / "size.txt").write_text(f"{width}x{height}", encoding="utf-8")
    (folder / "seconds.txt").write_text(str(seconds), encoding="utf-8")
    flat = " ".join(text.split())
    label = f"{seconds}s · {width}x{height} · {flat}"[:80]

    job = Job(
        id=job_id,
        user_id=current_user.id,
        tool="wan_t2v",
        status="queued",
        image_path="",
        video_path=str(prompt_path),
        image_name="-",
        video_name=label,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.post("/app/{slug}", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def create_catalog_job(
    slug: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    image: Annotated[UploadFile | None, File()] = None,
    image2: Annotated[UploadFile | None, File()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
    prompt: Annotated[str, Form()] = "",
    negative: Annotated[str, Form()] = "",
    extra: Annotated[str, Form()] = "",
):
    spec = get_catalog_app(slug)
    if spec is None:
        raise HTTPException(status_code=404, detail="App not found")

    text = (prompt or "").strip()
    if spec.needs_prompt and not spec.prompt_optional and not text:
        raise HTTPException(status_code=400, detail="Prompt is required")
    if len(text) > 16000:
        raise HTTPException(status_code=400, detail="Prompt is too long")
    if spec.needs_image and image is None:
        raise HTTPException(status_code=400, detail="Image is required")
    if spec.needs_image2 and not spec.image2_optional and image2 is None:
        raise HTTPException(status_code=400, detail="Reference image is required")
    if spec.needs_audio and audio is None:
        raise HTTPException(status_code=400, detail="Audio is required")

    job_id = new_job_id()
    folder = job_upload_dir(job_id)
    image_path = ""
    image_name = "-"
    if image is not None:
        image_bytes = await _read_limited(image, settings.max_upload_size_bytes)
        image_name = _safe_filename(image.filename or "image.png", "image.png")
        stored = folder / image_name
        stored.write_bytes(image_bytes)
        image_path = str(stored)
    if image2 is not None:
        image2_bytes = await _read_limited(image2, settings.max_upload_size_bytes)
        suffix = Path(image2.filename or "image.png").suffix or ".png"
        (folder / f"image2{suffix}").write_bytes(image2_bytes)
    if audio is not None:
        audio_bytes = await _read_limited(audio, settings.max_video_upload_bytes)
        suffix = Path(audio.filename or "audio.mp3").suffix or ".mp3"
        (folder / f"audio{suffix}").write_bytes(audio_bytes)

    prompt_path = folder / "prompt.txt"
    prompt_path.write_text(text, encoding="utf-8")
    negative_text = (negative or "").strip()
    if negative_text:
        (folder / "negative.txt").write_text(negative_text, encoding="utf-8")
    extra_text = (extra or "").strip()
    if extra_text:
        (folder / "extra.txt").write_text(extra_text, encoding="utf-8")

    label_parts: list[str] = []
    if image_name != "-":
        label_parts.append(image_name)
    if audio is not None:
        label_parts.append(_safe_filename(audio.filename or "audio.mp3", "audio.mp3"))
    if text:
        label_parts.append(" ".join(text.split())[:80])
    label = " · ".join(label_parts)[:80] or spec.title

    job = Job(
        id=job_id,
        user_id=current_user.id,
        tool=spec.slug,
        status="queued",
        image_path=image_path,
        video_path=str(prompt_path),
        image_name=image_name,
        video_name=label,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.get("", response_model=list[JobResponse])
async def list_my_jobs(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Job)
        .where(Job.user_id == current_user.id)
        .order_by(Job.created_at.desc())
        .limit(50)
    )
    return [_to_response(job) for job in result.scalars().all()]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "done":
        raise HTTPException(status_code=400, detail="Job already finished")
    if job.status == "processing":
        await comfy.interrupt()
    job.status = "cancelled"
    job.error = "Cancelled by user"
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in _RETRYABLE:
        raise HTTPException(
            status_code=400,
            detail="Only failed or cancelled jobs can be retried",
        )
    if not _inputs_exist(job):
        raise HTTPException(
            status_code=400,
            detail="Original files are missing. Start a new run from Studio.",
        )
    job.status = "queued"
    job.error = None
    job.prompt_id = None
    job.output_path = None
    await db.commit()
    await db.refresh(job)
    return _to_response(job)


@router.get("/{job_id}/download")
async def download_job(
    job_id: str,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    job = await db.get(Job, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "done" or not job.output_path:
        raise HTTPException(status_code=404, detail="Output not ready")
    path = Path(job.output_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output file missing")
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/octet-stream",
    )
