from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from app.engine.workflow_convert import (
    _fetch_object_info,
    assert_nodes_installed,
    is_ui_format,
    load_workflow_file,
    to_api_workflow,
)

_SEED_KEYS = ("seed", "noise_seed")


@dataclass(frozen=True)
class TextPatch:
    node_id: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class CatalogApp:
    slug: str
    title: str
    description: str
    engine_label: str
    media_class: str
    workflow_path: str
    hint: str
    sort_order: int
    image_label: str = "Image"
    image2_label: str = "Reference image"
    audio_label: str = "Audio"
    prompt_label: str = "Prompt"
    prompt_placeholder: str = (
        "Describe the result. Leave empty to keep the workflow default."
    )
    extra_label: str = ""
    extra_placeholder: str = ""
    negative_label: str = "Negative (optional)"
    negative_placeholder: str = "Leave empty unless you want a negative prompt."
    needs_image: bool = False
    needs_image2: bool = False
    image2_optional: bool = True
    needs_audio: bool = False
    needs_prompt: bool = False
    prompt_optional: bool = True
    needs_negative: bool = False
    needs_extra: bool = False
    image_nodes: tuple[str, ...] = ()
    image2_nodes: tuple[str, ...] = ()
    audio_nodes: tuple[str, ...] = ()
    prompt_patches: tuple[TextPatch, ...] = ()
    negative_patches: tuple[TextPatch, ...] = ()
    extra_patches: tuple[TextPatch, ...] = ()
    default_prompt: str = ""
    replace_prompts: tuple[str, ...] = ()
    prefer_prefixes: tuple[str, ...] = ()
    output_kind: str = "image"

    def public_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "hint": self.hint,
            "engine_label": self.engine_label,
            "needs_image": self.needs_image,
            "needs_image2": self.needs_image2,
            "image2_optional": self.image2_optional,
            "needs_audio": self.needs_audio,
            "needs_prompt": self.needs_prompt,
            "prompt_optional": self.prompt_optional,
            "needs_negative": self.needs_negative,
            "needs_extra": self.needs_extra,
            "image_label": self.image_label,
            "image2_label": self.image2_label,
            "audio_label": self.audio_label,
            "prompt_label": self.prompt_label,
            "prompt_placeholder": self.prompt_placeholder,
            "extra_label": self.extra_label,
            "extra_placeholder": self.extra_placeholder,
            "negative_label": self.negative_label,
            "negative_placeholder": self.negative_placeholder,
        }

    def seed_row(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "engine_label": self.engine_label,
            "route_name": "studio_app_page",
            "media_class": self.media_class,
            "badge_label": "Run",
            "is_live": True,
            "sort_order": self.sort_order,
        }


CATALOG_APPS: tuple[CatalogApp, ...] = (
    CatalogApp(
        slug="2d_to_3d",
        title="2D to 3D Upscale",
        description="Upload a flat image. WD14 tags drive img2img, then upscale for a 2.5D / 3D look.",
        engine_label="SD1.5 · WD14",
        media_class="pixel",
        workflow_path="workflows/2D转2.5D转3D.json",
        hint="Uses the 2D→2.5D→3D graph you added. Needs WD14 Tagger and ImageResize+ on that ComfyUI.",
        sort_order=50,
        image_label="Source image",
        needs_image=True,
        image_nodes=("47",),
        prefer_prefixes=("TensorArt",),
        output_kind="image",
    ),
    CatalogApp(
        slug="cute_doll",
        title="Cute Doll",
        description="Turn a photo into a chibi blind-box doll with Flux, PuLID, and VQA prompt fill.",
        engine_label="Flux · PuLID",
        media_class="pixel",
        workflow_path="workflows/Cute+Doll+(flux+pulid).json",
        hint="Uses Cute Doll (Flux + PuLID). Face lock and VQA fill the doll prompt from the photo.",
        sort_order=60,
        image_label="Reference photo",
        needs_image=True,
        needs_prompt=True,
        prompt_optional=True,
        prompt_label="Prompt template (optional)",
        prompt_placeholder="Leave empty to keep the VQA doll template. Edit only if you want to override it.",
        image_nodes=("226",),
        prompt_patches=(TextPatch("252", ("prompt", "text", "template")),),
        prefer_prefixes=("blindboxstudio",),
        output_kind="image",
    ),
    CatalogApp(
        slug="ltx25_t2v",
        title="LTX 2.5 Text to Video",
        description="Fast text to video with synchronized audio using LTX 2.5 AV.",
        engine_label="LTX 2.5 AV",
        media_class="motion",
        workflow_path="workflows/文生视频++急速++LTX2.5+音画同出.json",
        hint="Uses the LTX 2.5 AV graph. Needs LTX 2.5 audio-video nodes on that ComfyUI.",
        sort_order=70,
        needs_prompt=True,
        prompt_optional=False,
        needs_negative=True,
        prompt_label="Prompt",
        prompt_placeholder="Describe the scene, motion, and sound.",
        image_label="",
        prompt_patches=(TextPatch("499", ("value", "text")),),
        negative_patches=(TextPatch("475", ("text",)),),
        prefer_prefixes=("LTX-2.5_t2v", "LTX"),
        output_kind="video",
    ),
    CatalogApp(
        slug="rh_style_ref",
        title="Style Reference",
        description="Content image + style image + prompt → Midjourney V8.1 via the RunningHub node.",
        engine_label="RH · MJ V8.1",
        media_class="pixel",
        workflow_path="workflows/RH+leisure+boat+mat+image+style+reference+image.json",
        hint="Uses the RH leisure-boat style-reference graph. The RH node must already be configured on that ComfyUI.",
        sort_order=80,
        image_label="Content image",
        image2_label="Style reference",
        needs_image=True,
        needs_image2=True,
        image2_optional=False,
        needs_prompt=True,
        prompt_optional=True,
        prompt_placeholder="Leave empty to keep the workflow prompt. Edit to change the MJ description.",
        image_nodes=("6",),
        image2_nodes=("4",),
        prompt_patches=(TextPatch("7", ("prompt",)),),
        prefer_prefixes=("ComfyUI",),
        output_kind="image",
    ),
    CatalogApp(
        slug="logo_poster",
        title="Logo Poster",
        description="SDXL text-logo poster. Set the subject and optional logo word from the Michael Jackson poster graph.",
        engine_label="SDXL · Logo",
        media_class="outfit",
        workflow_path="workflows/迈克尔杰克逊海报.json",
        hint="Uses the logo-poster graph. Subject text replaces the illustration box; logo text replaces the LOGO box.",
        sort_order=90,
        needs_prompt=True,
        prompt_optional=False,
        needs_extra=True,
        prompt_label="Subject / illustration",
        prompt_placeholder="Michael Jackson's music poster,",
        extra_label="Logo word",
        extra_placeholder="LOGO",
        prompt_patches=(TextPatch("123", ("Text", "text", "value")),),
        extra_patches=(TextPatch("102", ("Text", "text", "value")),),
        prefer_prefixes=("Logos-", "Logos"),
        output_kind="image",
    ),
    CatalogApp(
        slug="interior_colorize",
        title="Interior Colorize",
        description="Colorize an interior line drawing with BrushNet, ControlNet, and a room-style prompt.",
        engine_label="BrushNet",
        media_class="pixel",
        workflow_path="workflows/室内设计线稿图上色.json",
        hint="Uses the interior line-art colorize graph. Needs BrushNet, BRIA RMBG, and ControlNet on that ComfyUI.",
        sort_order=100,
        image_label="Line art",
        needs_image=True,
        needs_prompt=True,
        prompt_optional=True,
        prompt_label="Room theme (optional)",
        prompt_placeholder="Pink girl e-sports theme room, interior design, bright, sunny…",
        image_nodes=("17",),
        prompt_patches=(TextPatch("350", ("text", "Text")),),
        prefer_prefixes=("ComfyUI",),
        output_kind="image",
    ),
    CatalogApp(
        slug="product_bg",
        title="Product Background",
        description="One-click product photo background change with auto-caption, Kolors, and SUPIR.",
        engine_label="Kolors · SUPIR",
        media_class="outfit",
        workflow_path="workflows/[One-click+background+change]+Product+picture+photography.json",
        hint="Uses the product photography graph. First image is the product. Second image is optional extra reference.",
        sort_order=110,
        image_label="Product photo",
        image2_label="Extra reference (optional)",
        needs_image=True,
        needs_image2=True,
        image2_optional=True,
        image_nodes=("104",),
        image2_nodes=("99",),
        prefer_prefixes=("ComfyUI",),
        output_kind="image",
    ),
    CatalogApp(
        slug="image_matting",
        title="Image Matting",
        description="Qwen Edit cutout — isolate the subject on a clean background.",
        engine_label="Qwen Edit",
        media_class="pixel",
        workflow_path="workflows/image+matting.json",
        hint="Uses the image matting graph. Upload one photo; the Qwen edit prompt stays as exported.",
        sort_order=120,
        image_label="Photo to matte",
        needs_image=True,
        image_nodes=("33",),
        prefer_prefixes=("Emerald_Isle_Parade", "ComfyUI"),
        output_kind="image",
    ),
    CatalogApp(
        slug="infinitetalk",
        title="InfiniteTalk",
        description="Portrait + voice → talking-head video with Wan InfiniteTalk and MultiTalk.",
        engine_label="Wan InfiniteTalk",
        media_class="wan",
        workflow_path="workflows/infinitetalk+digital+human.json",
        hint="Uses the InfiniteTalk digital-human graph. Needs WanVideoWrapper and MultiTalk on that ComfyUI.",
        sort_order=130,
        image_label="Portrait",
        audio_label="Speech audio",
        needs_image=True,
        needs_audio=True,
        needs_prompt=True,
        prompt_optional=True,
        needs_negative=True,
        prompt_label="Prompt (optional)",
        prompt_placeholder="A person is speaking.",
        default_prompt="A person is speaking.",
        replace_prompts=("one person is raping.",),
        image_nodes=("133",),
        audio_nodes=("218",),
        prompt_patches=(TextPatch("135", ("positive_prompt",)),),
        negative_patches=(TextPatch("135", ("negative_prompt",)),),
        prefer_prefixes=("infinitetalk",),
        output_kind="video",
    ),
)

CATALOG: dict[str, CatalogApp] = {item.slug: item for item in CATALOG_APPS}


def get_catalog_app(slug: str) -> CatalogApp | None:
    return CATALOG.get(slug)


def is_catalog_app(slug: str) -> bool:
    return slug in CATALOG


def catalog_seed_rows() -> list[dict]:
    return [item.seed_row() for item in CATALOG_APPS]


def sidecar_file(folder: Path, stem: str) -> Path | None:
    if not folder.is_dir():
        return None
    for path in folder.iterdir():
        if path.is_file() and path.stem == stem:
            return path
    return None


def catalog_inputs_exist(
    job_id: str, slug: str, image_path: str, video_path: str
) -> bool:
    spec = get_catalog_app(slug)
    if spec is None:
        return False
    folder = Path(video_path).parent if video_path else Path(image_path).parent
    if spec.needs_image and not (image_path and Path(image_path).is_file()):
        return False
    if (
        spec.needs_image2
        and not spec.image2_optional
        and sidecar_file(folder, "image2") is None
    ):
        return False
    if spec.needs_audio and sidecar_file(folder, "audio") is None:
        return False
    if spec.needs_prompt and not spec.prompt_optional:
        prompt_file = folder / "prompt.txt"
        if (
            not prompt_file.is_file()
            or not prompt_file.read_text(encoding="utf-8").strip()
        ):
            return False
    return True


def _ui_widget_text(raw: dict, node_id: str) -> str | None:
    if not is_ui_format(raw):
        return None
    for node in raw.get("nodes", []):
        if str(int(node.get("id", -1))) != str(node_id):
            continue
        values = node.get("widgets_values")
        if isinstance(values, list):
            for item in values:
                if isinstance(item, str) and item.strip():
                    return item
        if isinstance(values, dict):
            for item in values.values():
                if isinstance(item, str) and item.strip():
                    return item
    return None


def _backfill_text_from_ui(raw: dict, wf: dict, patches: tuple[TextPatch, ...]) -> None:
    """Keep exported text widgets when object_info is missing and conversion drops them."""
    for patch in patches:
        node = wf.get(patch.node_id)
        if not isinstance(node, dict):
            continue
        inputs = node.setdefault("inputs", {})
        if any(
            name in inputs and not isinstance(inputs.get(name), list)
            for name in patch.fields
        ):
            continue
        fallback = _ui_widget_text(raw, patch.node_id)
        if fallback is not None:
            inputs[patch.fields[0]] = fallback


def _set_text(node: dict, value: str, fields: tuple[str, ...]) -> None:
    inputs = node.setdefault("inputs", {})
    for name in fields:
        current = inputs.get(name)
        if name in inputs and not isinstance(current, list):
            inputs[name] = value
            return
    inputs[fields[0]] = value


def _randomize_seeds(wf: dict) -> None:
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for key in _SEED_KEYS:
            if isinstance(inputs.get(key), (int, float)):
                inputs[key] = random.randint(0, 2**32 - 1)


def resolve_prompt_text(spec: CatalogApp, prompt: str) -> str:
    text = (prompt or "").strip()
    if spec.replace_prompts and (not text or text.lower() in spec.replace_prompts):
        return spec.default_prompt
    return text


def inject_catalog_app(
    slug: str,
    *,
    image_name: str | None = None,
    image2_name: str | None = None,
    audio_name: str | None = None,
    prompt: str = "",
    negative: str = "",
    extra: str = "",
) -> dict:
    spec = get_catalog_app(slug)
    if spec is None:
        raise ValueError(f"Unknown catalog app: {slug}")

    raw = load_workflow_file(spec.workflow_path)
    wf = to_api_workflow(raw)
    _backfill_text_from_ui(raw, wf, spec.prompt_patches)
    _backfill_text_from_ui(raw, wf, spec.negative_patches)
    _backfill_text_from_ui(raw, wf, spec.extra_patches)

    for node_id in spec.image_nodes:
        node = wf.get(node_id)
        if isinstance(node, dict) and image_name:
            node.setdefault("inputs", {})["image"] = image_name

    second = image2_name or image_name
    for node_id in spec.image2_nodes:
        node = wf.get(node_id)
        if isinstance(node, dict) and second:
            node.setdefault("inputs", {})["image"] = second

    for node_id in spec.audio_nodes:
        node = wf.get(node_id)
        if isinstance(node, dict) and audio_name:
            node.setdefault("inputs", {})["audio"] = audio_name

    text = resolve_prompt_text(spec, prompt)
    if text:
        for patch in spec.prompt_patches:
            node = wf.get(patch.node_id)
            if isinstance(node, dict):
                _set_text(node, text, patch.fields)

    negative_text = (negative or "").strip()
    if negative_text:
        for patch in spec.negative_patches:
            node = wf.get(patch.node_id)
            if isinstance(node, dict):
                _set_text(node, negative_text, patch.fields)

    extra_text = (extra or "").strip()
    if extra_text:
        for patch in spec.extra_patches:
            node = wf.get(patch.node_id)
            if isinstance(node, dict):
                _set_text(node, extra_text, patch.fields)

    _randomize_seeds(wf)
    if _fetch_object_info():
        assert_nodes_installed(wf)
    return wf
