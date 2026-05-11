"""
请求转发模块。

负责将客户端请求原样转发到 NovelAI 上游，并构建返回给客户端的响应。
"""

from urllib.parse import urlparse

import httpx
from fastapi import Request, Response
from fastapi.responses import StreamingResponse

from .config import settings
from .rewriter import rewrite_html, rewrite_js

# ── 全局 HTTP 客户端 ────────────────────────────────────────

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    """获取或创建全局 HTTP 客户端（单例）。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.upstream_timeout, connect=30.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
            trust_env=True,
        )
    return _client


async def close_client() -> None:
    """关闭全局 HTTP 客户端。"""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


# ── CORS ────────────────────────────────────────────────────

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "*",
    "Access-Control-Allow-Headers": "*",
}

# ── 请求头处理 ───────────────────────────────────────────────

_HOP_BY_HOP = frozenset({"host", "content-length", "accept-encoding", "connection"})

_STRIP_RESPONSE_HEADERS = frozenset({
    "content-encoding", "transfer-encoding", "content-length", "connection",
    "content-security-policy", "content-security-policy-report-only",
    "strict-transport-security", "x-frame-options",
})


def _build_upstream_headers(request: Request, target_url: str) -> dict[str, str]:
    """构建转发给上游的请求头。"""
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP
    }
    headers["Host"] = urlparse(target_url).netloc
    if "novelai.net" in target_url:
        headers["origin"] = "https://novelai.net"
        headers["referer"] = "https://novelai.net/"
    return headers


# ── 转发 ────────────────────────────────────────────────────

async def forward(request: Request, target_url: str) -> httpx.Response:
    """将请求原样转发到上游（流式模式，支持大响应体）。"""
    client = await get_client()
    headers = _build_upstream_headers(request, target_url)
    body = await request.body()

    req = client.build_request(
        method=request.method,
        url=target_url,
        headers=headers,
        content=body,
        params=request.query_params,
    )
    return await client.send(req, stream=True)


# ── 响应构建 ────────────────────────────────────────────────

def _clean_response_headers(response: httpx.Response) -> dict[str, str]:
    """清理上游响应头并添加 CORS。"""
    headers = {
        k: v for k, v in response.headers.items()
        if k.lower() not in _STRIP_RESPONSE_HEADERS
    }
    headers.update(_CORS_HEADERS)
    return headers


def _local_api_prefix(request: Request) -> str:
    """获取本地 API 前缀（用于 JS/HTML 重写）。"""
    return f"{request.url.scheme}://{request.url.netloc}/_api"


async def build_response(
    request: Request,
    upstream: httpx.Response,
    *,
    do_rewrite: bool = False,
) -> Response:
    """
    将上游响应转换为客户端响应。

    do_rewrite=True 时对 HTML 注入劫持脚本，对 JS 替换 API 域名。
    """
    headers = _clean_response_headers(upstream)
    content_type = upstream.headers.get("content-type", "")
    prefix = _local_api_prefix(request)

    # HTML → 注入劫持脚本
    if do_rewrite and "text/html" in content_type:
        await upstream.aread()
        body = rewrite_html(upstream.content, prefix)
        return Response(
            content=body, status_code=upstream.status_code,
            headers=headers, media_type=content_type,
        )

    # JS → 替换 API 域名
    if do_rewrite and "javascript" in content_type:
        await upstream.aread()
        body = rewrite_js(upstream.text, prefix)
        return Response(
            content=body, status_code=upstream.status_code,
            headers=headers, media_type=content_type,
        )

    # 已读取完毕的响应（如被 aread() 过的）
    if upstream.is_stream_consumed:
        return Response(
            content=upstream.content, status_code=upstream.status_code,
            headers=headers, media_type=content_type,
        )

    # 默认：流式透传
    async def _stream():
        async for chunk in upstream.aiter_bytes():
            yield chunk

    return StreamingResponse(
        _stream(), status_code=upstream.status_code,
        headers=headers, media_type=content_type,
    )
