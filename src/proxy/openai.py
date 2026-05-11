"""
OpenAI DALL-E 格式适配器。
负责将 OpenAI 格式的请求转换为 NovelAI 格式，并将 NAI 的响应转回 OpenAI 格式。
"""

import json
import time
import io
import uuid
import zipfile
import base64
import logging
from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse

from .config import settings
from .forwarder import forward
from .queue import gate

logger = logging.getLogger("gateway")

def parse_size(size_str: str, default_w: int, default_h: int) -> tuple[int, int]:
    if not size_str:
        return default_w, default_h
    try:
        w, h = map(int, size_str.split("x"))
        return w, h
    except Exception:
        return default_w, default_h

async def handle_openai_generations(request: Request) -> Response:
    """处理 /v1/images/generations 请求"""
    
    # 1. 解析 OpenAI 请求
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    openai_model = body.get("model", "nai-diffusion-4-5-curated")
    prompt = body.get("prompt", "")
    size = body.get("size", "1024x1024")
    response_format = body.get("response_format", "url") # 默认 URL，但我们可能得回退到 b64

    width, height = parse_size(size, 1024, 1024)

    # 2. 构建 NAI Payload (参考 novel-api-go)
    # 这里简单实现一个 V4 的转换
    nai_payload = {
        "input": f"{prompt}, best quality, very aesthetic, absurdres",
        "model": openai_model,
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
            "v4_prompt": {
                "caption": {
                    "base_caption": f"{prompt}, best quality, very aesthetic, absurdres",
                    "char_captions": []
                },
                "use_coords": True,
                "use_order": True
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": "lowres, {bad}, error, fewer, extra, missing, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, bad anatomy, bad hands, bad feet, bad proportions, {extra digits}, lowres, {bad}, error, missing fingers, extra digit, fewer digits, bad hands, lower quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, text, logo",
                    "char_captions": []
                },
                "legacy_uc": False
            },
            "negative_prompt": "lowres, {bad}, error, fewer, extra, missing, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, bad anatomy, bad hands, bad feet, bad proportions, {extra digits}, lowres, {bad}, error, missing fingers, extra digit, fewer digits, bad hands, lower quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, text, logo"
        }
    }

    # 3. 排队并转发 (复用 _handle_heavy 的逻辑)
    try:
        await gate.__aenter__()
    except Exception:
        raise HTTPException(status_code=503, detail="Queue timeout")

    try:
        target_url = f"{settings.novelai_image_url}/ai/generate-image"
        
        # 伪造一个 NAI 风格的 Request 头
        headers = dict(request.headers)
        headers["content-type"] = "application/json"
        headers.pop("content-length", None)
        
        # 使用 httpx 直接发
        from .forwarder import get_client
        client = await get_client()
        
        # 转发请求
        nai_resp = await client.post(
            target_url,
            json=nai_payload,
            headers={
                "Authorization": request.headers.get("Authorization", ""),
                "Content-Type": "application/json",
                "Accept": "application/zip",
                "Origin": "https://novelai.net",
                "Referer": "https://novelai.net/"
            },
            timeout=settings.upstream_timeout
        )
        
        if nai_resp.status_code != 200:
            logger.error(f"NAI Error: {nai_resp.status_code} {nai_resp.text}")
            return Response(content=nai_resp.content, status_code=nai_resp.status_code, media_type="application/json")

        # 4. 解析 ZIP 响应
        image_b64 = ""
        with zipfile.ZipFile(io.BytesIO(nai_resp.content)) as zf:
            for name in zf.namelist():
                if name.endswith(".png"):
                    img_data = zf.read(name)
                    image_b64 = base64.b64encode(img_data).decode("utf-8")
                    break
        
        # 5. 返回 OpenAI 格式
        openai_res = {
            "created": int(time.time()),
            "data": [
                {
                    "b64_json": image_b64,
                    "revised_prompt": prompt
                }
            ]
        }

        return Response(
            content=json.dumps(openai_res),
            status_code=200,
            media_type="application/json"
        )

    finally:
        await gate.__aexit__(None, None, None)

async def handle_openai_models() -> Response:
    """返回支持的模型列表，供 New API 等工具调用。"""
    models = [
        {"id": "nai-diffusion-4-5-curated", "object": "model", "created": 1700000000, "owned_by": "novelai"},
        {"id": "nai-diffusion-4-5-full", "object": "model", "created": 1700000000, "owned_by": "novelai"},
        {"id": "nai-diffusion-4-curated-preview", "object": "model", "created": 1700000000, "owned_by": "novelai"},
        {"id": "nai-diffusion-3", "object": "model", "created": 1700000000, "owned_by": "novelai"},
        {"id": "nai-diffusion-furry-3", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    ]
    return Response(
        content=json.dumps({"object": "list", "data": models}),
        status_code=200,
        media_type="application/json"
    )

async def handle_openai_chat_completions(request: Request) -> Response:
    """处理 /v1/chat/completions 请求，将其适配为图像生成。
    适配 Neo-MoFox 插件格式：参数固定，只传正负面提示词。
    """

    # 1. 解析请求
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages", [])
    model = body.get("model", "nai-diffusion-4-5-curated")

    # 提示词指导（scale），范围 1.0–10.0，默认 5.0
    scale = min(max(float(body.get("scale", 5.0)), 1.0), 10.0)
    # 缩放比例（cfg_rescale），范围 0.0–1.0，默认 0.7
    cfg_rescale = min(max(float(body.get("cfg_rescale", 0.7)), 0.0), 1.0)
    # 步数固定 28
    steps = 28

    # 画幅限制为官方三种（超出回退默认 832x1216）
    _VALID_SIZES = {(1024, 1024), (1216, 832), (832, 1216)}
    width = int(body.get("width", 832))
    height = int(body.get("height", 1216))
    if (width, height) not in _VALID_SIZES:
        width, height = 832, 1216

    # 默认负面词
    negative_prompt = "lowres, {bad}, error, fewer, extra, missing, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, bad anatomy, bad hands, bad feet, bad proportions, {extra digits}, lowres, {bad}, error, missing fingers, extra digit, fewer digits, bad hands, lower quality, normal quality, jpeg artifacts, signature, watermark, username, blurry, text, logo"

    # 提取提示词
    prompt = ""
    character_prompts = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            prompt = content
        elif role == "system":
            if "Negative prompt:" in content:
                negative_prompt = content.replace("Negative prompt:", "").strip()
            elif "Characters:" in content:
                try:
                    char_data = json.loads(content.replace("Characters:", "").strip())
                    if isinstance(char_data, list):
                        character_prompts = char_data
                except:
                    pass

    # 兜底：如果没有解析到 prompt，把所有 user 消息拼起来当正面词
    if not prompt:
        user_contents = [msg.get("content", "") for msg in messages if msg.get("role") == "user"]
        prompt = " ".join(user_contents).strip()

    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt found in messages")

    # 2. 构建 NAI Payload (参考 API_REQUEST_FORMAT.md 的 V4 格式)

    # 构造 char_captions
    v4_char_captions = []
    v4_neg_char_captions = []
    nai_character_prompts = []

    for char in character_prompts:
        pos = char.get("prompt", "")
        neg = char.get("uc", "")
        center = char.get("center", {"x": 0.5, "y": 0.5})

        v4_char_captions.append({
            "char_caption": pos,
            "centers": [center]
        })
        v4_neg_char_captions.append({
            "char_caption": neg,
            "centers": [center]
        })
        nai_character_prompts.append({
            "prompt": pos,
            "uc": neg,
            "center": center,
            "enabled": True
        })

    use_coords = len(character_prompts) > 0

    nai_payload = {
        "input": prompt,
        "model": model,
        "action": "generate",
        "parameters": {
            "width": width,
            "height": height,
            "scale": scale,
            "steps": steps,
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
            "v4_prompt": {
                "caption": {
                    "base_caption": prompt,
                    "char_captions": v4_char_captions
                },
                "use_coords": use_coords,
                "use_order": True
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": negative_prompt,
                    "char_captions": v4_neg_char_captions
                },
                "legacy_uc": False
            },
            "characterPrompts": nai_character_prompts,
            "reference_image_multiple": [],
            "reference_information_extracted_multiple": [],
            "reference_strength_multiple": []
        }
    }

    try:
        await gate.__aenter__()
    except Exception:
        raise HTTPException(status_code=503, detail="Queue timeout")

    try:
        from .forwarder import get_client
        client = await get_client()

        target_url = f"{settings.novelai_image_url}/ai/generate-image"

        nai_resp = await client.post(
            target_url,
            json=nai_payload,
            headers={
                "Authorization": request.headers.get("Authorization", ""),
                "Content-Type": "application/json",
                "Accept": "application/zip",
                "Origin": "https://novelai.net",
                "Referer": "https://novelai.net/"
            },
            timeout=settings.upstream_timeout
        )

        if nai_resp.status_code != 200:
            return Response(content=nai_resp.content, status_code=nai_resp.status_code, media_type="application/json")

        # 解析图片
        img_data = b""
        with zipfile.ZipFile(io.BytesIO(nai_resp.content)) as zf:
            for name in zf.namelist():
                if name.endswith(".png"):
                    img_data = zf.read(name)
                    break

        # 保存到本地图床
        filename = f"{uuid.uuid4().hex}.png"
        settings.image_dir.mkdir(parents=True, exist_ok=True)
        (settings.image_dir / filename).write_bytes(img_data)

        # 动态获取 Base URL: 优先使用配置，否则根据当前请求的 Host 自动生成
        base_url = settings.image_base_url
        if not base_url:
            # 获取请求协议 (http/https) 和 Host
            scheme = request.url.scheme
            host = request.headers.get("host")
            base_url = f"{scheme}://{host}"

        image_url = f"{base_url}/images/{filename}"

        # 封装为 OpenAI Chat 格式
        timestamp = int(time.time())
        content = f"![image]({image_url})"
        stream = body.get("stream", False)

        if stream:
            chunk = {
                "id": f"chatcmpl-{timestamp}",
                "object": "chat.completion.chunk",
                "created": timestamp,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": "stop"}]
            }

            async def gen():
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(gen(), media_type="text/event-stream")

        openai_res = {
            "id": f"chatcmpl-{timestamp}",
            "object": "chat.completion",
            "created": timestamp,
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }

        return Response(
            content=json.dumps(openai_res),
            status_code=200,
            media_type="application/json"
        )

    finally:
        await gate.__aexit__(None, None, None)
