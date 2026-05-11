"""
NovelAI 透明反向代理网关 — 路由层。

职责：定义路由、分发请求、调用排队门控。
"""

import asyncio
import logging
import subprocess
import os

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from .config import settings
from .queue import gate
from .forwarder import forward, build_response, close_client, _CORS_HEADERS
from .stats import record_generation
from .openai import handle_openai_generations, handle_openai_chat_completions, handle_openai_models

logger = logging.getLogger("gateway")

# 不应透传给客户端的响应头
_DROP_HEADERS = frozenset({
    "content-encoding", "transfer-encoding", "connection",
    "content-security-policy", "content-security-policy-report-only",
    "strict-transport-security", "x-frame-options",
    "content-disposition",  # 强制去掉，防止触发下载拦截
})


# ── 生命周期 ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.image_dir.mkdir(parents=True, exist_ok=True)

    # 自动启动 Cloudflare Tunnel
    if settings.cloudflare_tunnel_token:
        logger.info("☁️ 正在启动 Cloudflare Tunnel...")
        try:
            # 使用 subprocess.Popen 异步启动，不阻塞主进程
            # shell=True 在 Windows 上比较稳妥
            cmd = f"cloudflared.exe tunnel run --token {settings.cloudflare_tunnel_token}"
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("✅ Cloudflare Tunnel 已在后台启动")
        except Exception as e:
            logger.error(f"❌ 启动 Cloudflare Tunnel 失败: {e}")

    logger.info(f"🚀 网关已启动  http://{settings.host}:{settings.port}")
    yield
    await close_client()
    logger.info("🛑 网关已关闭")


app = FastAPI(title="NovelAI Gateway", lifespan=lifespan)


@app.get("/images/{filename}")
async def serve_image(filename: str):
    path = settings.image_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="image/png")


# ── 工具函数 ────────────────────────────────────────────────

def _cors_preflight() -> Response:
    return Response(status_code=204, headers=_CORS_HEADERS)


def _clean_headers(upstream) -> dict[str, str]:
    """清理上游响应头：去掉 hop-by-hop / 安全策略头，加上 CORS。"""
    headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in _DROP_HEADERS
    }
    headers.update(_CORS_HEADERS)
    return headers


# ── 重负载请求处理 ───────────────────────────────────────────

async def _handle_heavy(request: Request, target_url: str) -> Response:
    """排队 → 转发 → 完整读取 → 冷却 → 释放锁 → 返回。"""
    
    # 0. 预检请求直接返回，不参与排队
    if request.method == "OPTIONS":
        return _cors_preflight()

    # 1. 排队获取锁
    try:
        await gate.__aenter__()
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="排队超时，请稍后重试。")

    # 2. 转发并读取完整响应
    try:
        upstream = await forward(request, target_url)
        await upstream.aread()
        
        ct = upstream.headers.get("content-type", "")
        logger.info(
            f"✅ 完成  status={upstream.status_code}  "
            f"type={ct}  size={len(upstream.content)}B"
        )

        # 记录统计信息
        if upstream.status_code == 200:
            # 尝试从请求体中获取宽高
            width, height = 0, 0
            try:
                body = await request.json()
                params = body.get("parameters", {})
                width = params.get("width", 0)
                height = params.get("height", 0)
            except:
                pass
            record_generation(upstream.content, target_url, width, height)

        headers = _clean_headers(upstream)
        
        # 3. 先释放锁（包含冷却），再返回响应
        await gate.__aexit__(None, None, None)
        
        await upstream.aclose()

        # 额外安全头，防止 IDM 等工具拦截
        headers["X-Content-Type-Options"] = "nosniff"

        # 如果是 204 No Content，确保不返回任何可能触发下载的头
        if upstream.status_code == 204:
            logger.warning(f"⚠️ 上游返回了 204 No Content: {target_url}")
            return Response(status_code=204, headers=_CORS_HEADERS)

        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=headers,
            media_type=ct or "application/octet-stream",
        )
    except Exception as exc:
        await gate.__aexit__(None, None, None)
        if isinstance(exc, HTTPException):
            raise
        logger.error(f"❌ 请求失败: {exc}")
        raise HTTPException(status_code=502, detail="上游请求失败。")


# ── 路由 ────────────────────────────────────────────────────

@app.post("/v1/images/generations")
async def openai_generations(request: Request):
    """适配 OpenAI DALL-E 格式的接口。"""
    return await handle_openai_generations(request)


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    """适配 OpenAI Chat 格式的接口，将对话转为图像生成。"""
    return await handle_openai_chat_completions(request)


@app.get("/v1/models")
async def openai_models():
    """返回支持的模型列表。"""
    return await handle_openai_models()


@app.api_route(
    "/_api/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_api(request: Request, path: str):
    """API 代理：重负载走排队，其余直接透传。"""
    if request.method == "OPTIONS":
        return _cors_preflight()

    api_path = f"/{path}" if not path.startswith("/") else path
    target_url = settings.get_upstream_url(api_path)

    if settings.is_heavy(api_path):
        return await _handle_heavy(request, target_url)

    upstream = await forward(request, target_url)
    return await build_response(request, upstream)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_site(request: Request, path: str):
    """网站代理（兜底）：透传并注入劫持脚本。"""
    if request.method == "OPTIONS":
        return _cors_preflight()

    target_url = f"{settings.novelai_base_url}/{path}"
    upstream = await forward(request, target_url)
    return await build_response(request, upstream, do_rewrite=True)
