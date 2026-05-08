# NovelAI Gateway

NovelAI 透明反向代理网关，支持并发控制和请求排队。

## 功能特性

- 透明代理 NovelAI 网站和 API
- 重负载请求（图片生成）自动排队，避免 429 错误
- 自动注入 API 劫持脚本

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 启动服务

```bash
start.bat
```

### 3. 访问

- 本地访问: `http://127.0.0.1:31555/image`
- 内网穿透: 配置你的穿透工具转发到 `http://127.0.0.1:31555`

## 配置

编辑 `src/proxy/config.py` 或创建 `.env` 文件：

```env
HOST=127.0.0.1
PORT=31555
MAX_CONCURRENT=1          # 同时允许的重负载请求数
COOLDOWN_MIN=0.5          # 冷却最小值（秒）
COOLDOWN_MAX=1.0          # 冷却最大值（秒）
```

## 内网穿透建议

1. **使用 Cloudflare Tunnel**：自动提供 HTTPS，无需配置证书
2. **使用 frp/ngrok**：配置转发到 `http://127.0.0.1:31555`
3. **关闭 Cloudflare Rocket Loader**：如果使用 Cloudflare，需要在控制面板关闭 Rocket Loader 功能

## 故障排查

### 429 错误（请求过于频繁）

- 检查 `MAX_CONCURRENT` 是否为 1
- 检查日志中的冷却时间是否正常执行

### 内网穿透无法访问

- 检查系统代理是否允许局域网连接
- 检查 Cloudflare Rocket Loader 是否已关闭
- 检查内网穿透配置是否正确转发到 31555 端口

### 图片上传功能

- HTTP 环境下，浏览器限制 `crypto.subtle` API
- 建议使用 HTTPS 访问（通过 Cloudflare 或 Nginx 反向代理）

## 技术栈

- FastAPI - Web 框架
- httpx - HTTP 客户端
- BeautifulSoup4 - HTML 解析
- uvicorn - ASGI 服务器
