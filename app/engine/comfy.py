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
_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_MOTION_PREFER = ("wananimate_output",)
_ANIMATEDIFF_PREFER = ("video_",)
_MINIMAX_PREFER = ("minimax", "video")
_WAN_T2V_PREFER = ("wanvideo2_2_t2v", "wanvideo2")


def _base(base_url: str | None = None) -> str:
    return (base_url or settings.comfyui_base_url).rstrip("/")


def _prompt_error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception:
        body = (response.text or "")[:500]
        return f"ComfyUI /prompt {response.status_code}: {body or response.reason_phrase}"
    err = data.get("error")
    if isinstance(err, dict):
        message = err.get("message") or err.get("type") or "rejected prompt"
        details = err.get("details")
        if details:
            message = f"{message} ({details})"
        return f"ComfyUI /prompt {response.status_code}: {message}"[:1500]
    if isinstance(err, str):
        return f"ComfyUI /prompt {response.status_code}: {err}"[:1500]
    return f"ComfyUI /prompt {response.status_code}: {(response.text or '')[:500]}"


def prefer_for_tool(tool: str) -> tuple[str, ...]:
    from app.engine.workflow_apps import get_catalog_app

    spec = get_catalog_app(tool)
    if spec and spec.prefer_prefixes:
        return spec.prefer_prefixes
    if tool == "animatediff":
        return _ANIMATEDIFF_PREFER
    if tool == "minimax":
        return _MINIMAX_PREFER
    if tool == "wan_t2v":
        return _WAN_T2V_PREFER
    return _MOTION_PREFER


def prefers_video(tool: str) -> bool:
    from app.engine.workflow_apps import get_catalog_app

    spec = get_catalog_app(tool)
    if spec:
        return spec.output_kind == "video"
    return True


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
            raise RuntimeError(_prompt_error_message(response))
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"ComfyUI rejected prompt: {data['error']}")
        node_errors = data.get("node_errors") or {}
        if node_errors:
            parts: list[str] = []
            for node_id, info in node_errors.items():
                for err in info.get("errors") or []:
                    detail = (err.get("details") or err.get("message") or str(err))[:240]
                    parts.append(f"node {node_id}: {detail}")
            summary = "; ".join(parts)[:1500] or str(node_errors)[:1500]
            raise RuntimeError(f"ComfyUI rejected prompt: {summary}")
        return data["prompt_id"]


def _history_entry(payload: object, prompt_id: str) -> dict | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get(prompt_id)
    if isinstance(nested, dict):
        return nested
    if "outputs" in payload or "status" in payload:
        return payload
    return None


def _is_complete(entry: dict) -> bool:
    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        return False
    if status.get("completed") or status.get("status_str") == "success":
        return True
    return False


async def get_history_entry(
    prompt_id: str,
    base_url: str | None = None,
) -> dict | None:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{_base(base_url)}/history/{prompt_id}")
        if response.status_code != 200:
            return None
        return _history_entry(response.json(), prompt_id)


async def poll_history(
    prompt_id: str,
    interval: float = 3.0,
    base_url: str | None = None,
    *,
    wait: bool = True,
) -> dict:
    import asyncio

    while True:
        entry = await get_history_entry(prompt_id, base_url=base_url)
        if entry is not None:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise RuntimeError("ComfyUI execution error")
            if _is_complete(entry):
                return entry
        elif not wait:
            raise RuntimeError(
                "ComfyUI result was lost. Retry the job from the Jobs page."
            )
        await asyncio.sleep(interval)
        if not wait:
            raise RuntimeError("ComfyUI has not finished this prompt yet")


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


def _is_video_file(item: dict) -> bool:
    name = (item.get("filename") or "").lower()
    return Path(name).suffix in _VIDEO_SUFFIXES


def _is_image_file(item: dict) -> bool:
    name = (item.get("filename") or "").lower()
    return Path(name).suffix in _IMAGE_SUFFIXES


def _collect_media(outputs: dict) -> tuple[list[dict], list[dict]]:
    videos: list[dict] = []
    images: list[dict] = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for key, value in node_output.items():
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict) or not item.get("filename"):
                    continue
                if key in ("gifs", "videos") or _is_video_file(item):
                    videos.append(item)
                elif key == "images" or _is_image_file(item):
                    images.append(item)
    return videos, images


def _rank_pool(pool: list[dict], prefer_prefixes: tuple[str, ...]) -> list[dict]:
    saved = [item for item in pool if item.get("type") == "output"]
    use = saved or pool
    preferred = [
        item
        for item in use
        if any(
            item.get("filename", "").lower().startswith(prefix.lower())
            for prefix in prefer_prefixes
        )
    ]
    if preferred:
        return preferred
    final = [
        item
        for item in use
        if not any(
            item.get("filename", "").lower().startswith(prefix)
            for prefix in _SKIP_PREFIXES
        )
    ]
    return final or use


def _pick_output(
    outputs: dict,
    prefer_prefixes: tuple[str, ...] = _MOTION_PREFER,
    *,
    prefer_video: bool = True,
) -> dict | None:
    videos, images = _collect_media(outputs)
    first, second = (videos, images) if prefer_video else (images, videos)
    if first:
        ranked = _rank_pool(first, prefer_prefixes)
        if ranked:
            return ranked[-1]
    if second:
        ranked = _rank_pool(second, prefer_prefixes)
        if ranked:
            return ranked[-1]
    return None


def _pick_video(outputs: dict, prefer_prefixes: tuple[str, ...] = _MOTION_PREFER) -> dict | None:
    return _pick_output(outputs, prefer_prefixes, prefer_video=True)


async def probe_saved_video(
    prefixes: tuple[str, ...],
    base_url: str | None = None,
    start: int = 40,
) -> dict | None:
    """Find a saved mp4 when /history was cleared but output files remain."""
    async with httpx.AsyncClient(timeout=10) as client:
        for prefix in prefixes:
            for index in range(start, 0, -1):
                names = (
                    f"{prefix}{index:05d}.mp4",
                    f"{prefix}_{index:05d}.mp4",
                )
                for name in names:
                    response = await client.get(
                        f"{_base(base_url)}/view",
                        params={"filename": name, "subfolder": "", "type": "output"},
                    )
                    if response.status_code == 200 and len(response.content) > 1000:
                        logger.info("Probed leftover ComfyUI output %s", name)
                        return {
                            "filename": name,
                            "subfolder": "",
                            "type": "output",
                        }
    return None


async def download_output(
    prompt_id: str,
    dest: Path,
    base_url: str | None = None,
    prefer_prefixes: tuple[str, ...] = _MOTION_PREFER,
    prefer_video: bool = True,
) -> Path:
    history = await poll_history(prompt_id, base_url=base_url)
    outputs = history.get("outputs") or {}
    media = _pick_output(
        outputs,
        prefer_prefixes=prefer_prefixes,
        prefer_video=prefer_video,
    )
    if not media:
        raise RuntimeError("ComfyUI finished but returned no output")
    logger.info(
        "Downloading ComfyUI output %s (%s)",
        media.get("filename"),
        media.get("type"),
    )
    suffix = Path(media["filename"]).suffix or (".mp4" if prefer_video else ".png")
    dest = dest.with_suffix(suffix)
    await download_file(
        media["filename"],
        media.get("subfolder", ""),
        media.get("type", "output"),
        dest,
        base_url=base_url,
    )
    return dest
