"""
内容重写模块。

负责在返回给客户端的 HTML / JS 中注入脚本或替换 URL，
使前端的 API 请求自动指向本地网关而非 NovelAI 官方。
"""

from bs4 import BeautifulSoup

# 需要被劫持的官方域名
_OFFICIAL_ORIGINS = (
    "https://api.novelai.net",
    "https://image.novelai.net",
)


def build_hijack_script(local_api_prefix: str) -> str:
    """生成注入到 HTML <head> 中的 fetch 劫持脚本。"""
    return f"""
(function() {{
    const LOCAL = '{local_api_prefix}';
    const rewrite = (url) => {{
        if (typeof url !== 'string') return url;
        return url.replace(/https:\\/\\/(api|image)\\.novelai\\.net/g, LOCAL);
    }};
    const hijack = () => {{
        if (window.fetch && !window.fetch.__gw) {{
            const orig = window.fetch;
            window.fetch = function(input, init) {{
                if (typeof input === 'string') input = rewrite(input);
                else if (input instanceof Request) input = new Request(rewrite(input.url), input);
                return orig.call(this, input, init);
            }};
            window.fetch.__gw = true;
        }}
    }};
    hijack();
    setInterval(hijack, 500);
}})();
"""


def rewrite_html(html_bytes: bytes, local_api_prefix: str) -> bytes:
    """在 HTML 的 <head> 最前面注入劫持脚本。"""
    try:
        soup = BeautifulSoup(html_bytes, "html.parser")
        tag = soup.new_tag("script")
        tag.string = build_hijack_script(local_api_prefix)
        target = soup.head if soup.head else soup
        target.insert(0, tag)
        return str(soup).encode("utf-8")
    except Exception:
        return html_bytes


def rewrite_js(js_text: str, local_api_prefix: str) -> str:
    """将 JS 源码中的官方 API 域名替换为本地网关地址。"""
    result = js_text
    for origin in _OFFICIAL_ORIGINS:
        result = result.replace(origin, local_api_prefix)
    return result
