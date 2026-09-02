from __future__ import annotations

import logging
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_SKIP_PREFIXES = (
    "vitpose",
    "openpose",
    "dwpose",
    "depth_",
    "normal_",
    "wanvideo2_1_t2v",
)
_MOTION_PREFER = ("wananimate_output",)
_ANIMATEDIFF_PREFER = ("video_", "animatediff")
_MINIMAX_PREFER = ("minimax", "video")
_WAN_T2V_PREFER = ("wanvideo2_2_t2v", "wanvideo2")


def _base(base_url: str | None = None) -> str:
    return (base_url or settings.comfyui_base_url).rstrip("/")


def prefer_for_tool(tool: str) -> tuple[str, ...]:
    if tool == "animatediff":
        return _ANIMATEDIFF_PREFER
    if tool == "minimax":
        return _MINIMAX_PREFER
    if tool == "wan_t2v":
        return _WAN_T2V_PREFER
    return _MOTION_PREFER


async def upload_input(path: Path, base_url: str | None = None) -> str:
    safe_name = "".join(
        ch if ch.isalnum() or ch in "._-" else "_" for ch in path.name
    )
    async with httpx.AsyncClient(timeout=120) as client:
        with path.open("rb") as handle:
            response = await client.post(
                f"{_base(base_url)}/upload/image",
                files={"image": (safe_name, handle, "application/octet-stream")},
                data={"overwrite": "true"},
            )
        response.raise_for_status()
        assigned = response.json().get("name", safe_name)
    logger.info("Uploaded %s to ComfyUI as %s", path.name, assigned)
    return assigned


async def submit_prompt(workflow: dict, base_url: str | None = None) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{_base(base_url)}/prompt",
            json={"prompt": workflow},
        )
        if not response.is_success:
            logger.error("ComfyUI /prompt %s: %s", response.status_code, response.text[:2000])
            response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"ComfyUI rejected prompt: {data['error']}")
        return data["prompt_id"]


async def poll_history(
    prompt_id: str,
    interval: float = 3.0,
    base_url: str | None = None,
) -> dict:
    import asyncio

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            response = await client.get(f"{_base(base_url)}/history/{prompt_id}")
            if response.status_code == 200:
                history = response.json()
                if prompt_id in history:
                    entry = history[prompt_id]
                    status = entry.get("status") or {}
                    if status.get("status_str") == "error":
                        raise RuntimeError("ComfyUI execution error")
                    if status.get("completed") or entry.get("outputs"):
                        return entry
            await asyncio.sleep(interval)


async def interrupt(base_url: str | None = None) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(f"{_base(base_url)}/interrupt")
            await client.post(f"{_base(base_url)}/queue", json={"clear": True})
        except httpx.HTTPError:
            logger.warning("Could not interrupt ComfyUI queue")


async def free_memory(base_url: str | None = None) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            await client.post(
                f"{_base(base_url)}/free",
                json={"unload_models": True, "free_memory": True},
            )
        except httpx.HTTPError:
            logger.warning("Could not free ComfyUI VRAM")


async def download_file(
    filename: str,
    subfolder: str,
    file_type: str,
    dest: Path,
    base_url: str | None = None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    params = {"filename": filename, "subfolder": subfolder or "", "type": file_type}
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.get(f"{_base(base_url)}/view", params=params)
        response.raise_for_status()
        dest.write_bytes(response.content)


def _pick_video(outputs: dict, prefer_prefixes: tuple[str, ...] = _MOTION_PREFER) -> dict | None:
    videos: list[dict] = []
    for node_output in outputs.values():
        videos.extend(node_output.get("gifs") or [])
        videos.extend(node_output.get("videos") or [])
    saved = [item for item in videos if item.get("type") == "output"]
    pool = saved or videos
    preferred = [
        item
        for item in pool
        if any(item.get("filename", "").lower().startswith(prefix) for prefix in prefer_prefixes)
    ]
    if preferred:
        return preferred[-1]
    final = [
        item
        for item in pool
        if not any(item.get("filename", "").lower().startswith(prefix) for prefix in _SKIP_PREFIXES)
    ]
    chosen = final or pool
    return chosen[-1] if chosen else None


async def download_output(
    prompt_id: str,
    dest: Path,
    base_url: str | None = None,
    prefer_prefixes: tuple[str, ...] = _MOTION_PREFER,
) -> Path:
    history = await poll_history(prompt_id, base_url=base_url)
    outputs = history.get("outputs") or {}
    video = _pick_video(outputs, prefer_prefixes=prefer_prefixes)
    if not video:
        raise RuntimeError("ComfyUI finished but returned no video output")
    suffix = Path(video["filename"]).suffix or ".mp4"
    dest = dest.with_suffix(suffix)
    await download_file(
        video["filename"],
        video.get("subfolder", ""),
        video.get("type", "output"),
        dest,
        base_url=base_url,
    )
    return dest
