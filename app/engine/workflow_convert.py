from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}
_SEED_CONTROL_TOKENS = {"fixed", "randomize", "increment", "decrement"}
_object_info_cache: dict | None = None


def _comfy_base() -> str:
    return settings.comfyui_base_url.rstrip("/")


def _fetch_object_info() -> dict:
    global _object_info_cache
    if _object_info_cache is None:
        try:
            with httpx.Client(timeout=3.0) as client:
                raw = client.get(f"{_comfy_base()}/object_info")
                raw.raise_for_status()
                _object_info_cache = raw.json()
        except Exception as exc:
            logger.warning("ComfyUI object_info unavailable: %s", exc)
            return {}
    return _object_info_cache


def _widget_input_order(class_type: str, object_info: dict) -> list[tuple[str, bool]]:
    node_def = object_info.get(class_type, {})
    node_input = node_def.get("input", {})
    result: list[tuple[str, bool]] = []
    for section in ("required", "optional"):
        for name, spec in node_input.get(section, {}).items():
            if not spec:
                continue
            inp_type = spec[0]
            config = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            force_input = config.get("forceInput", False)
            is_widget = (not force_input) and (
                isinstance(inp_type, list) or inp_type in _WIDGET_TYPES
            )
            result.append((name, is_widget))
    return result


def is_ui_format(workflow: dict) -> bool:
    return "nodes" in workflow and isinstance(workflow["nodes"], list)


def load_workflow() -> dict:
    path = Path(settings.comfyui_workflow_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Workflow not found: {path}. Copy the ComfyUI export to this path."
        )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def ui_to_api_format(ui_wf: dict) -> dict:
    bypassed_nodes: set[str] = {
        str(int(n["id"])) for n in ui_wf.get("nodes", []) if n.get("mode", 0) == 4
    }

    link_map: dict[int, tuple[str, int]] = {}
    for link in ui_wf.get("links", []):
        lid, src_node, src_slot, _tgt_node, _tgt_slot, *_ = link
        src_id = str(int(src_node))
        if src_id not in bypassed_nodes:
            link_map[int(lid)] = (src_id, int(src_slot))

    set_sources: dict[str, tuple[str, int]] = {}
    for node in ui_wf.get("nodes", []):
        if node.get("mode", 0) == 4:
            continue
        ntype = node.get("type", "")
        node_id = str(int(node["id"]))
        raw_wv = node.get("widgets_values", [])
        if ntype != "SetNode":
            continue
        if isinstance(raw_wv, dict):
            channel = next(iter(raw_wv.values()), None)
        elif raw_wv:
            channel = raw_wv[0]
        else:
            continue
        for inp in node.get("inputs", []):
            lid = inp.get("link")
            if lid is not None:
                src = link_map.get(int(lid))
                if src and channel:
                    set_sources[str(channel)] = src
                break

    get_resolution: dict[str, tuple[str, int]] = {}
    for node in ui_wf.get("nodes", []):
        if node.get("type") != "GetNode" or node.get("mode", 0) == 4:
            continue
        node_id = str(int(node["id"]))
        raw_wv = node.get("widgets_values", [])
        if isinstance(raw_wv, dict):
            channel = next(iter(raw_wv.values()), None)
        elif raw_wv:
            channel = raw_wv[0]
        else:
            continue
        if channel and str(channel) in set_sources:
            get_resolution[node_id] = set_sources[str(channel)]

    for node in ui_wf.get("nodes", []):
        if (
            node.get("type") not in {"RHHiddenNodes", "Reroute", "SetNode"}
            or node.get("mode", 0) == 4
        ):
            continue
        node_id = str(int(node["id"]))
        for inp in node.get("inputs", []):
            lid = inp.get("link")
            if lid is not None:
                src = link_map.get(int(lid))
                if src:
                    resolved_id, resolved_slot = src
                    while resolved_id in get_resolution:
                        resolved_id, resolved_slot = get_resolution[resolved_id]
                    get_resolution[node_id] = (resolved_id, resolved_slot)
                break

    constant_types = {"Bool", "Int"}
    constant_values: dict[str, object] = {}
    for node in ui_wf.get("nodes", []):
        if node.get("type") not in constant_types or node.get("mode", 0) == 4:
            continue
        node_id = str(int(node["id"]))
        raw_wv = node.get("widgets_values", [])
        if isinstance(raw_wv, list) and raw_wv:
            val = raw_wv[0]
        elif isinstance(raw_wv, dict):
            val = next(iter(raw_wv.values()), None)
        else:
            val = None
        constant_values[node_id] = val

    dead_nodes: set[str] = set()
    for node in ui_wf.get("nodes", []):
        if node.get("type") == "VideoCombineNode" and node.get("mode", 0) != 4:
            dead_nodes.add(str(int(node["id"])))
    link_src_map = {l[0]: str(int(l[1])) for l in ui_wf.get("links", [])}
    changed = True
    while changed:
        changed = False
        for node in ui_wf.get("nodes", []):
            nid = str(int(node["id"]))
            if nid in dead_nodes or node.get("mode", 0) == 4:
                continue
            connected_inputs = [
                inp for inp in node.get("inputs", []) if inp.get("link") is not None
            ]
            if connected_inputs and all(
                link_src_map.get(inp["link"], "") in dead_nodes
                for inp in connected_inputs
            ):
                dead_nodes.add(nid)
                changed = True

    try:
        object_info = _fetch_object_info()
    except Exception:
        object_info = {}

    api: dict[str, dict] = {}
    skip_types = {
        "GetNode",
        "SetNode",
        "Note",
        "MarkdownNote",
        "RHHiddenNodes",
        "Reroute",
        "VRAMReserver",
        *constant_types,
    }
    for node in ui_wf.get("nodes", []):
        if node.get("mode", 0) == 4:
            continue
        node_id = str(int(node["id"]))
        class_type = node.get("type", "")
        if class_type in skip_types or node_id in dead_nodes:
            continue

        raw_wv = node.get("widgets_values", [])
        wv_is_dict = isinstance(raw_wv, dict)
        widgets_vals = raw_wv if wv_is_dict else list(raw_wv)
        built: dict = {}

        linked: dict[str, tuple[str, int] | None] = {}
        for inp in node.get("inputs", []):
            inp_name = inp.get("name", "")
            link_id = inp.get("link")
            if link_id is not None:
                src = link_map.get(int(link_id))
                if src:
                    src_id, src_slot = src
                    if src_id in get_resolution:
                        src_id, src_slot = get_resolution[src_id]
                    linked[inp_name] = (src_id, src_slot)
                else:
                    linked[inp_name] = None
            else:
                linked[inp_name] = None

        schema_order = _widget_input_order(class_type, object_info)

        if schema_order and wv_is_dict:
            for inp_name, is_widget in schema_order:
                if inp_name in linked and linked[inp_name] is not None:
                    src_id, src_slot = linked[inp_name]
                    built[inp_name] = (
                        constant_values.get(src_id, [src_id, src_slot])
                        # constant_values[src_id]
                        # if src_id in constant_values
                        # else [src_id, src_slot]
                    )
                elif is_widget and inp_name in widgets_vals:
                    built[inp_name] = widgets_vals[inp_name]
            schema_names = {name for name, _ in schema_order}
            for key, value in widgets_vals.items():
                if (
                    key not in built
                    and key not in schema_names
                    and key != "videopreview"
                ):
                    built[key] = value
        elif schema_order:
            wv_idx = 0
            for inp_name, is_widget in schema_order:
                if inp_name in linked and linked[inp_name] is not None:
                    src_id, src_slot = linked[inp_name]
                    built[inp_name] = (
                        constant_values.get(src_id, [src_id, src_slot])
                        # constant_values[src_id]
                        # if src_id in constant_values
                        # else [src_id, src_slot]
                    )
                    if is_widget:
                        wv_idx += 1
                        if (
                            inp_name == "seed"
                            and wv_idx < len(widgets_vals)
                            and widgets_vals[wv_idx] in _SEED_CONTROL_TOKENS
                        ):
                            wv_idx += 1
                elif is_widget and wv_idx < len(widgets_vals):
                    built[inp_name] = widgets_vals[wv_idx]
                    wv_idx += 1
                    if (
                        inp_name == "seed"
                        and wv_idx < len(widgets_vals)
                        and widgets_vals[wv_idx] in _SEED_CONTROL_TOKENS
                    ):
                        wv_idx += 1
        else:
            wv_idx = 0
            for inp in node.get("inputs", []):
                inp_name = inp.get("name", "")
                is_widget = "widget" in inp
                link_id = inp.get("link")
                if link_id is not None:
                    if inp_name in linked and linked[inp_name] is not None:
                        src_id, src_slot = linked[inp_name]
                        built[inp_name] = (
                            constant_values.get(src_id, [src_id, src_slot])
                            # constant_values[src_id]
                            # if src_id in constant_values
                            # else [src_id, src_slot]
                        )
                    if is_widget and not wv_is_dict:
                        wv_idx += 1
                elif is_widget:
                    if wv_is_dict:
                        wv_name = inp.get("widget", {}).get("name", inp_name)
                        if wv_name in widgets_vals:
                            built[inp_name] = widgets_vals[wv_name]
                        elif inp_name in widgets_vals:
                            built[inp_name] = widgets_vals[inp_name]
                    elif wv_idx < len(widgets_vals):
                        built[inp_name] = widgets_vals[wv_idx]
                        wv_idx += 1

        api[node_id] = {"class_type": class_type, "inputs": built}

    return api


def _combo_choices(spec: object) -> list[str]:
    if not isinstance(spec, (list, tuple)) or not spec:
        return []
    first = spec[0]
    if isinstance(first, list):
        return [item for item in first if isinstance(item, str)]
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options") or spec[1].get("choices") or []
        return [item for item in options if isinstance(item, str)]
    return []


def _norm_model_path(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _match_combo_value(requested: str, choices: list[str]) -> str | None:
    if requested in choices:
        return requested
    want = _norm_model_path(requested)
    for choice in choices:
        if _norm_model_path(choice) == want:
            return choice
    want_name = want.rsplit("/", 1)[-1]
    named = [
        choice
        for choice in choices
        if _norm_model_path(choice).rsplit("/", 1)[-1] == want_name
    ]
    if len(named) == 1:
        return named[0]
    return None


def resolve_combo_values(wf: dict, object_info: dict | None = None) -> None:
    """Rewrite combo widgets to the exact strings this ComfyUI lists.

    Windows ComfyUI stores subfolder models as ``Wan22Animate\\file.safetensors``.
    Exported graphs often use ``Wan22Animate/file.safetensors``. Validation is
    an exact match, so a slash mismatch drops the video output nodes.
    """
    if object_info is None:
        try:
            object_info = _fetch_object_info()
        except Exception:
            object_info = {}

    for node in wf.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or not class_type:
            continue
        node_input = (object_info.get(class_type) or {}).get("input") or {}
        for section in ("required", "optional"):
            for name, spec in (node_input.get(section) or {}).items():
                current = inputs.get(name)
                if not isinstance(current, str):
                    continue
                choices = _combo_choices(spec)
                if not choices:
                    continue
                matched = _match_combo_value(current, choices)
                if matched and matched != current:
                    logger.info(
                        "Combo %s.%s remapped %r -> %r",
                        class_type,
                        name,
                        current,
                        matched,
                    )
                    inputs[name] = matched


def assert_nodes_installed(wf: dict) -> None:
    try:
        object_info = _fetch_object_info()
    except Exception as exc:
        raise RuntimeError(f"Cannot reach ComfyUI: {exc}") from exc
    missing = sorted(
        {
            class_type
            for node in wf.values()
            if isinstance(node, dict)
            and (class_type := node.get("class_type"))
            and class_type not in object_info
        }
    )
    if not missing:
        return
    hint = ""
    if any(name.startswith("MiniMaxH3") for name in missing):
        version = "unknown"
        try:
            stats = httpx.get(f"{_comfy_base()}/system_stats", timeout=10).json()
            version = stats.get("system", {}).get("comfyui_version") or version
        except Exception:
            pass
        hint = (
            f" MiniMax H3 is built into ComfyUI 0.30+; this engine is {version}."
            " Update ComfyUI on the GPU PC, then retry."
        )
    raise RuntimeError("ComfyUI is missing nodes: " + ", ".join(missing) + hint)


def to_api_workflow(workflow: dict) -> dict:
    wf = ui_to_api_format(workflow) if is_ui_format(workflow) else dict(workflow)
    resolve_combo_values(wf)
    return wf


def inject_motion(workflow: dict, image_name: str, video_name: str) -> dict:
    wf = to_api_workflow(workflow)
    found_img = False
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == "LoadImage":
            node.setdefault("inputs", {})["image"] = image_name
            found_img = True
    if not found_img:
        raise KeyError("LoadImage node not found in workflow")

    video_node = next(
        (
            node
            for node in wf.values()
            if isinstance(node, dict) and node.get("class_type") == "VHS_LoadVideo"
        ),
        None,
    )
    if video_node is None:
        raise KeyError("VHS_LoadVideo node not found in workflow")
    inputs = video_node.setdefault("inputs", {})
    inputs["video"] = video_name
    inputs.setdefault("frame_load_cap", 504)
    inputs.setdefault("force_rate", 24)
    inputs.setdefault("select_every_nth", 1)
    return wf


def load_workflow_file(path: str) -> dict:
    workflow_path = Path(path)
    if not workflow_path.is_file():
        raise FileNotFoundError(f"Workflow not found: {workflow_path}")
    with workflow_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def inject_animatediff(video_name: str) -> dict:
    import copy
    import random

    wf = copy.deepcopy(load_workflow_file(settings.comfyui_animatediff_workflow_path))
    node_id = settings.comfyui_animatediff_video_node
    node = wf.get(node_id)
    if not isinstance(node, dict):
        raise KeyError(f"AnimateDiff video node {node_id} not found")
    node.setdefault("inputs", {})["video"] = video_name

    sampler_types = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "Seed (rgthree)"}
    for node in wf.values():
        if not isinstance(node, dict) or node.get("class_type") not in sampler_types:
            continue
        inputs = node.get("inputs", {})
        for key in ("noise_seed", "seed"):
            if key in inputs and isinstance(inputs[key], (int, float)):
                inputs[key] = random.randint(0, 2**32 - 1)
    return wf


def inject_minimax(image_name: str, prompt: str) -> dict:
    import random

    wf = to_api_workflow(load_workflow_file(settings.comfyui_minimax_workflow_path))
    first_frame = wf.get("197")
    if isinstance(first_frame, dict) and first_frame.get("class_type") == "LoadImage":
        first_frame.setdefault("inputs", {})["image"] = image_name
    else:
        found = False
        for node in wf.values():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                node.setdefault("inputs", {})["image"] = image_name
                found = True
                break
        if not found:
            raise KeyError("LoadImage node not found in MiniMax workflow")

    i2v = wf.get("198")
    if isinstance(i2v, dict) and prompt.strip():
        i2v.setdefault("inputs", {})["prompt"] = prompt.strip()

    for node in wf.values():
        if not isinstance(node, dict) or node.get("class_type") != "RandomNoise":
            continue
        seed = node.get("inputs", {}).get("noise_seed")
        if isinstance(seed, (int, float)):
            node["inputs"]["noise_seed"] = random.randint(0, 2**32 - 1)
    assert_nodes_installed(wf)
    return wf


# Filenames from the GPU ComfyUI error list (this machine does not have the
# Lightning 4-step pack the exported graph named).
WAN_T2V_FPS = 16
WAN_T2V_DEFAULT_SECONDS = 5
WAN_T2V_LENGTH_BY_SECONDS = {
    2: 33,
    4: 65,
    5: 81,
    8: 129,
}
WAN_T2V_DEFAULT_SIZE = "832x480"
WAN_T2V_SIZES = {
    "640x384": (640, 384),
    "832x480": (832, 480),
    "1024x576": (1024, 576),
    "1280x720": (1280, 720),
}

_WAN_T2V_MODEL_REMAP = {
    "vae_name": {
        "wan_2.1_vae.safetensors": "Wan2_1_VAE_bf16.safetensors",
    },
    "unet_name": {
        "Wan2.2-T2V-A14B-4steps-250928-dyno-high-lightx2v.safetensors": (
            "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors"
        ),
        "wan2.2_t2v_low_noise_14B_fp16.safetensors": (
            "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors"
        ),
    },
}


def wan_t2v_frame_count(seconds: int | None) -> int:
    return WAN_T2V_LENGTH_BY_SECONDS.get(
        int(seconds or WAN_T2V_DEFAULT_SECONDS),
        WAN_T2V_LENGTH_BY_SECONDS[WAN_T2V_DEFAULT_SECONDS],
    )


def wan_t2v_size(size: str | None) -> tuple[int, int]:
    key = (size or WAN_T2V_DEFAULT_SIZE).strip().lower()
    return WAN_T2V_SIZES.get(key, WAN_T2V_SIZES[WAN_T2V_DEFAULT_SIZE])


def _snap_wan_length(frames: int) -> int:
    frames = max(5, int(frames))
    return ((frames - 1) // 4) * 4 + 1


def _empty_latent_max_length() -> int:
    try:
        spec = (
            (_fetch_object_info().get("EmptyHunyuanLatentVideo") or {})
            .get("input", {})
            .get("required", {})
            .get("length")
        )
        if (
            isinstance(spec, (list, tuple))
            and len(spec) > 1
            and isinstance(spec[1], dict)
        ):
            return int(spec[1].get("max") or 16384)
    except Exception:
        pass
    return 16384


def inject_wan_t2v(
    prompt: str,
    negative: str = "",
    length: int | None = None,
    width: int | None = None,
    height: int | None = None,
    seconds: int | None = None,
) -> dict:
    import copy
    import random

    text = prompt.strip()
    if not text:
        raise ValueError("Wan T2V prompt is empty")

    duration = (
        seconds if isinstance(seconds, int) and seconds > 0 else WAN_T2V_DEFAULT_SECONDS
    )
    frames = (
        length
        if isinstance(length, int) and length >= 5
        else wan_t2v_frame_count(duration)
    )
    frames = _snap_wan_length(frames)
    cap = _empty_latent_max_length()
    fps = float(WAN_T2V_FPS)
    if frames > cap:
        frames = _snap_wan_length(min(frames, cap))
        fps = max(1.0, frames / duration)
        logger.warning(
            "Wan T2V length capped at %s frames; using %.2f fps for %ss",
            frames,
            fps,
            duration,
        )

    wf = copy.deepcopy(
        to_api_workflow(load_workflow_file(settings.comfyui_wan_t2v_workflow_path))
    )
    positive = wf.get("6")
    if not isinstance(positive, dict) or positive.get("class_type") != "CLIPTextEncode":
        raise KeyError("Positive CLIPTextEncode node 6 not found in Wan T2V workflow")
    positive.setdefault("inputs", {})["text"] = text

    negative_node = wf.get("7")
    if (
        isinstance(negative_node, dict)
        and negative_node.get("class_type") == "CLIPTextEncode"
    ):
        negative_node.setdefault("inputs", {})["text"] = negative.strip()

    for node in wf.values():
        if not isinstance(node, dict):
            continue
        inputs = node.setdefault("inputs", {})
        for key, mapping in _WAN_T2V_MODEL_REMAP.items():
            current = inputs.get(key)
            if isinstance(current, str) and current in mapping:
                inputs[key] = mapping[current]

    # Lightning LoRA is missing on this GPU. Wire the low-noise UNET straight in.
    low_sampler_model = wf.get("55")
    if isinstance(low_sampler_model, dict):
        low_sampler_model.setdefault("inputs", {})["model"] = ["56", 0]
    wf.pop("68", None)

    # Two 14B UNETs + UMT5-XXL filled 32 GB even at 832x480. Keep low-noise only.
    decode = wf.get("8")
    if isinstance(decode, dict):
        decode.setdefault("inputs", {})["samples"] = ["58", 0]
    high_path = wf.get("57")
    if isinstance(high_path, dict):
        high_path.setdefault("inputs", {})["latent_image"] = ["59", 0]
    low_sampler = wf.get("58")
    if isinstance(low_sampler, dict):
        inputs = low_sampler.setdefault("inputs", {})
        inputs["latent_image"] = ["59", 0]
        inputs["add_noise"] = "enable"
        inputs["return_with_leftover_noise"] = "disable"
        inputs["steps"] = 20
        inputs["start_at_step"] = 0
        inputs["end_at_step"] = 20
    for node_id in ("37", "54", "57"):
        wf.pop(node_id, None)

    default_width, default_height = wan_t2v_size(WAN_T2V_DEFAULT_SIZE)
    out_w = width if isinstance(width, int) and width >= 64 else default_width
    out_h = height if isinstance(height, int) and height >= 64 else default_height
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        inputs = node.setdefault("inputs", {})
        if class_type == "EmptyHunyuanLatentVideo":
            inputs["width"] = out_w
            inputs["height"] = out_h
            inputs["length"] = frames
        elif class_type == "CreateVideo":
            inputs["fps"] = fps
            if "frame_rate" in inputs:
                inputs["frame_rate"] = fps

    logger.info(
        "Wan T2V %sx%s × %s frames @ %.2f fps (%.1fs)",
        out_w,
        out_h,
        frames,
        fps,
        frames / fps,
    )

    seed = random.randint(0, 2**32 - 1)
    sampler = wf.get("58")
    if isinstance(sampler, dict) and sampler.get("class_type") == "KSamplerAdvanced":
        sampler.setdefault("inputs", {})["noise_seed"] = seed

    # SeedVR2 is optional upscale. This ComfyUI does not have those nodes, and
    # the graph already saves a video at CreateVideo/SaveVideo 60–61.
    for node_id in ("71", "72", "73", "74", "75"):
        wf.pop(node_id, None)
    return wf
