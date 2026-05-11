"""
OpenAI API 兼容适配器。

将 OpenAI 格式的请求（/v1/images/generations、/v1/chat/completions、/v1/models）
转换为 NovelAI 格式，并将响应转回 OpenAI 格式。
"""

import json
import time
import io
import uuid
import zipfile
import base64
import logging
from typing import Any

from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse

from .config import settings
from .queue import gate
from .stats import record_generation

logger = logging.getLogger("gateway")

# ── 常量 ─────────────────────────────────────────────────────

# 支持的模型列表
SUPPORTED_MODELS = [
    {"id": "nai-diffusion-4-5-curated", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    {"id": "nai-diffusion-4-5-full", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    {"id": "nai-diffusion-4-curated-preview", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    {"id": "nai-diffusion-3", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    {"id": "nai-diffusion-furry-3", "object": "model", "created": 1700000000, "owned_by": "novelai"},
]

# 默认负面提示词
DEFAULT_NEGATIVE_PROMPT = (
    "lowres, {bad}, error, fewer, extra, missing, worst quality, low quality, "
    "normal quality, jpeg artifacts, signature, watermark, username, blurry, "
    "bad anatomy, bad hands, bad feet, bad proportions, {extra digits}, lowres, "
    "{bad}, error, missing fingers, extra digit, fewer digits, bad hands, "
    "lower quality, normal quality, jpeg artifacts, signature, watermark, "
    "username, blurry, text, logo"
)

# 官方支持的画幅
VALID_SIZES = {(1024, 1024), (1216, 832), (832, 1216)}

# NAI 请求头模板
_NAI_HEADERS_TEMPLATE = {
    "Content-Type": "application/json",
    "Accept": "application/zip",
    "Origin": "https://novelai.net",
    "Referer": "https://novelai.net/",
}


# ── 工具函数 ──────────────────────────────────────────────────

def _parse_size(size_str: str, default_w: int = 1024, default_h: int = 1024) -> tuple[int, int]:
    """解析 'WxH' 格式的尺寸字符串。"""
    if not size_str:
        return default_w, default_h
    try:
        w, h = map(int, size_str.split("x"))
        return w, h
    except (ValueError, AttributeError):
        return default_w, default_h


def _build_v4_prompt(prompt: str, char_captions: list[dict] | None = None,
                     use_coords: bool = False) -> dict[str, Any]:
    """构建 NAI V4 格式的正面提示词结构。"""
    return {
        "caption": {
            "base_caption": prompt,
            "char_captions": char_captions or [],
        },
        "use_coords": use_coords,
        "use_order": True,
    }


def _build_v4_negative_prompt(negative: str, char_captions: list[dict] | None = None) -> dict[str, Any]:
    """构建 NAI V4 格式的负面提示词结构。"""
    return {
        "caption": {
            "base_caption": negative,
            "char_captions": char_captions or [],
        },
        "legacy_uc": False,
    }


def _extract_png_from_zip(content: bytes) -> bytes:
    """从 ZIP 响应中提取第一个 PNG 文件的原始数据。"""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for name in zf.namelist():
            if name.lower().endswith(".png"):
                return zf.read(name)
    return b""


def _get_image_base_url(request: Request) -> str:
    """获取图片访问的基础 URL。优先使用配置，否则根据请求自动生成。"""
    if settings.image_base_url:
        return settings.image_base_url
    scheme = request.url.scheme
    host = request.headers.get("host", "localhost")
    return f"{scheme}://{host}"


async def _send_nai_request(request: Request, payload: dict[str, Any]) -> Response | bytes:
    """
    向 NovelAI 发送图片生成请求。

    成功时返回响应体 bytes；失败时返回错误 Response。
    """
    from .forwarder import get_client

    client = await get_client()
    target_url = f"{settings.novelai_image_url}/ai/generate-image"

    headers = {**_NAI_HEADERS_TEMPLATE}
    headers["Authorization"] = request.headers.get("Authorization", "")

    nai_resp = await client.post(
        target_url,
        json=payload,
        headers=headers,
        timeout=settings.upstream_timeout,
    )

    if nai_resp.status_code != 200:
        logger.error(f"NAI 上游错误: status={nai_resp.status_code}")
        return Response(
            content=nai_resp.content,
            status_code=nai_resp.status_code,
            media_type="application/json",
        )

    return nai_resp.content


# ── /v1/models ────────────────────────────────────────────────

async def handle_openai_models() -> Response:
    """返回支持的模型列表。"""
    return Response(
        content=json.dumps({"object": "list", "data": SUPPORTED_MODELS}),
        status_code=200,
        media_type="application/json",
    )


# ── /v1/images/generations ────────────────────────────────────

async def handle_openai_generations(request: Request) -> Response:
    """处理 OpenAI DALL-E 格式的图片生成请求，返回 base64 编码图片。"""

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    model = body.get("model", "nai-diffusion-4-5-curated")
    prompt = body.get("prompt", "")
    size = body.get("size", "1024x1024")
    width, height = _parse_size(size)

    # 构建 NAI 请求体
    enhanced_prompt = f"{prompt}, best quality, very aesthetic, absurdres"
    nai_payload = {
        "input": enhanced_prompt,
        "model": model,
        "action": "generate",
        "parameters": {
            "width": width,
            "height": height,
            "scale": 5.0,
            "sampler": "k_euler_ancestral",
            "steps": 28,
            "n_samples": 1,
            "ucPreset": 0,
            "qualityToggle": True,
            "noise_schedule": "karras",
            "params_version": 3,
            "v4_prompt": _build_v4_prompt(enhanced_prompt, use_coords=True),
            "v4_negative_prompt": _build_v4_negative_prompt(DEFAULT_NEGATIVE_PROMPT),
            "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
        },
    }

    # 排队 → 发送 → 释放
    try:
        await gate.__aenter__()
    except Exception:
        raise HTTPException(status_code=503, detail="Queue timeout")

    try:
        target_url = f"{settings.novelai_image_url}/ai/generate-image"
        result = await _send_nai_request(request, nai_payload)

        if isinstance(result, Response):
            return result

        # 记录统计
        record_generation(result, target_url, width, height)

        # 提取图片并编码为 base64
        img_data = _extract_png_from_zip(result)
        image_b64 = base64.b64encode(img_data).decode("utf-8")

        return Response(
            content=json.dumps({
                "created": int(time.time()),
                "data": [{"b64_json": image_b64, "revised_prompt": prompt}],
            }),
            status_code=200,
            media_type="application/json",
        )
    finally:
        await gate.__aexit__(None, None, None)


# ── /v1/chat/completions ──────────────────────────────────────

def _parse_chat_messages(messages: list[dict], body: dict) -> dict[str, Any]:
    """
    从 Chat 消息中解析生成参数。

    返回包含 prompt、negative_prompt、width、height、steps、character_prompts 的字典。
    """
    prompt = ""
    negative_prompt = DEFAULT_NEGATIVE_PROMPT
    character_prompts: list[dict] = []
    steps = 28

    # 从 body 顶层读取画幅（可被消息内容覆盖）
    width = int(body.get("width", 832))
    height = int(body.get("height", 1216))
    if (width, height) not in VALID_SIZES:
        width, height = 832, 1216

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            # 尝试解析 JSON 格式的结构化提示词
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    prompt = parsed.get("prompt", prompt)
                    if "negative_prompt" in parsed:
                        negative_prompt = parsed["negative_prompt"]
                    if "size" in parsed and isinstance(parsed["size"], list) and len(parsed["size"]) == 2:
                        w, h = int(parsed["size"][0]), int(parsed["size"][1])
                        if (w, h) in VALID_SIZES:
                            width, height = w, h
                    if "steps" in parsed:
                        steps = int(parsed["steps"])
                else:
                    prompt = content
            except (json.JSONDecodeError, ValueError):
                prompt = content

        elif role == "system":
            if "Negative prompt:" in content:
                negative_prompt = content.replace("Negative prompt:", "").strip()
            elif "Characters:" in content:
                try:
                    char_data = json.loads(content.replace("Characters:", "").strip())
                    if isinstance(char_data, list):
                        character_prompts = char_data
                except (json.JSONDecodeError, ValueError):
                    pass

    # 兜底：拼接所有 user 消息
    if not prompt:
        user_contents = [m.get("content", "") for m in messages if m.get("role") == "user"]
        prompt = " ".join(user_contents).strip()

    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "character_prompts": character_prompts,
    }


def _build_chat_nai_payload(model: str, params: dict, scale: float, cfg_rescale: float) -> dict[str, Any]:
    """根据解析后的参数构建完整的 NAI 请求体。"""
    prompt = params["prompt"]
    negative_prompt = params["negative_prompt"]
    character_prompts = params["character_prompts"]

    # 构造角色提示词
    v4_char_captions = []
    v4_neg_char_captions = []
    nai_character_prompts = []

    for char in character_prompts:
        pos = char.get("prompt", "")
        neg = char.get("uc", "")
        center = char.get("center", {"x": 0.5, "y": 0.5})

        v4_char_captions.append({"char_caption": pos, "centers": [center]})
        v4_neg_char_captions.append({"char_caption": neg, "centers": [center]})
        nai_character_prompts.append({"prompt": pos, "uc": neg, "center": center, "enabled": True})

    use_coords = len(character_prompts) > 0

    return {
        "input": prompt,
        "model": model,
        "action": "generate",
        "parameters": {
            "width": params["width"],
            "height": params["height"],
            "scale": scale,
            "steps": params["steps"],
            "sampler": "k_euler_ancestral",
            "seed": int(time.time() * 1000) % 1000000000,
            "n_samples": 1,
            "ucPreset": 0,
            "qualityToggle": True,
            "sm": False,
            "sm_dyn": False,
            "autoSmea": False,
            "noise_schedule": "karras",
            "params_version": 3,
            "cfg_rescale": cfg_rescale,
            "legacy": False,
            "legacy_v3_extend": False,
            "add_original_image": True,
            "controlnet_strength": 1,
            "dynamic_thresholding": False,
            "prefer_brownian": True,
            "normalize_reference_strength_multiple": True,
            "use_coords": use_coords,
            "inpaintImg2ImgStrength": 1,
            "deliberate_euler_ancestral_bug": False,
            "skip_cfg_above_sigma": None,
            "negative_prompt": negative_prompt,
            "v4_prompt": _build_v4_prompt(prompt, v4_char_captions, use_coords),
            "v4_negative_prompt": _build_v4_negative_prompt(negative_prompt, v4_neg_char_captions),
            "characterPrompts": nai_character_prompts,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": [],
        },
    }


async def handle_openai_chat_completions(request: Request) -> Response:
    """
    处理 /v1/chat/completions 请求，将对话消息适配为图像生成。

    生成的图片保存到本地图床，返回 Markdown 图片链接。
    支持 stream 和非 stream 两种模式。
    """

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    model = body.get("model", "nai-diffusion-4-5-curated")
    stream = body.get("stream", False)

    # 解析生成参数
    scale = min(max(float(body.get("scale", 5.0)), 1.0), 10.0)
    cfg_rescale = min(max(float(body.get("cfg_rescale", 0.7)), 0.0), 1.0)

    params = _parse_chat_messages(messages, body)
    if not params["prompt"]:
        raise HTTPException(status_code=400, detail="No prompt found in messages")

    # 构建 NAI 请求
    nai_payload = _build_chat_nai_payload(model, params, scale, cfg_rescale)

    # 排队 → 发送 → 释放
    try:
        await gate.__aenter__()
    except Exception:
        raise HTTPException(status_code=503, detail="Queue timeout")

    try:
        target_url = f"{settings.novelai_image_url}/ai/generate-image"
        result = await _send_nai_request(request, nai_payload)

        if isinstance(result, Response):
            return result

        # 记录统计
        record_generation(result, target_url, params["width"], params["height"])

        # 提取图片并保存到本地图床
        img_data = _extract_png_from_zip(result)
        filename = f"{uuid.uuid4().hex}.png"
        settings.image_dir.mkdir(parents=True, exist_ok=True)
        (settings.image_dir / filename).write_bytes(img_data)

        # 构建图片 URL
        base_url = _get_image_base_url(request)
        image_url = f"{base_url}/images/{filename}"

        # 封装为 OpenAI Chat 格式
        timestamp = int(time.time())
        content = f"![image]({image_url})"

        if stream:
            return _build_stream_response(timestamp, model, content)

        return Response(
            content=json.dumps({
                "id": f"chatcmpl-{timestamp}",
                "object": "chat.completion",
                "created": timestamp,
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }),
            status_code=200,
            media_type="application/json",
        )
    finally:
        await gate.__aexit__(None, None, None)


def _build_stream_response(timestamp: int, model: str, content: str) -> StreamingResponse:
    """构建 SSE 流式响应。"""
    chunk = {
        "id": f"chatcmpl-{timestamp}",
        "object": "chat.completion.chunk",
        "created": timestamp,
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }

    async def generate():
        yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
