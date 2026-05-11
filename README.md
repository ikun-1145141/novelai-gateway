# NovelAI Gateway

NovelAI 透明反向代理网关，支持并发控制、请求排队和 OpenAI API 兼容接口。

## 功能特性

- 透明代理 NovelAI 网站和 API
- 重负载请求（图片生成）自动排队，避免 429 错误
- 自动注入 API 劫持脚本
- 兼容 OpenAI API 格式（`/v1/chat/completions`、`/v1/images/generations`、`/v1/models`）
- 本地图床，自动保存生成的图片
- 生成统计（按日统计大图/小图数量）
- 可选 Cloudflare Tunnel 自动启动

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置

复制示例配置并按需修改：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
# 图片访问基础 URL（留空则自动根据请求 Host 生成）
# 如果你有 HTTPS 反代，填写你的公网地址，例如: https://your-domain.com
IMAGE_BASE_URL=

# Cloudflare Tunnel Token（可选，填写后启动时自动开启隧道）
CLOUDFLARE_TUNNEL_TOKEN=

# 服务监听配置
HOST=0.0.0.0
PORT=31555

# 并发与冷却
MAX_CONCURRENT=1
COOLDOWN_MIN=0.5
COOLDOWN_MAX=1.0
```

### 3. 启动服务

```bash
uv run main.py
```

或使用 Windows 批处理：

```bash
start.bat
```

### 4. 访问

- 本地访问: `http://127.0.0.1:31555`
- OpenAI 兼容接口: `http://127.0.0.1:31555/v1/chat/completions`

## 部署到服务器

### 使用 HTTPS（推荐）

如果你的 NewAPI 或前端是 HTTPS 的，图片 URL 也必须是 HTTPS，否则浏览器会因为 Mixed Content 拒绝加载。

方案：

1. **Nginx 反代 + Let's Encrypt**：在服务器上配置 Nginx 反代到 `127.0.0.1:31555`，并申请 SSL 证书
2. **Cloudflare Tunnel**：填写 `CLOUDFLARE_TUNNEL_TOKEN`，自动提供 HTTPS
3. **frp + HTTPS**：在 frp 服务端配置 TLS

配置好 HTTPS 后，将 `IMAGE_BASE_URL` 设为你的公网 HTTPS 地址：

```env
IMAGE_BASE_URL=https://your-domain.com
```

### 使用 systemd（Linux）

```ini
[Unit]
Description=NovelAI Gateway
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/novelai-gateway
ExecStart=/path/to/uv run main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## OpenAI 兼容接口

### POST /v1/chat/completions

将聊天消息转为图像生成。支持 JSON 格式的 prompt：

```json
{
  "model": "nai-diffusion-4-5-full",
  "messages": [
    {"role": "user", "content": "{\"prompt\": \"1girl, blue hair\", \"negative_prompt\": \"lowres\", \"size\": [832, 1216]}"}
  ],
  "stream": true
}
```

### POST /v1/images/generations

标准 OpenAI 图片生成接口，返回 base64 编码的图片。

### GET /v1/models

返回支持的模型列表。

## 故障排查

### 429 错误（请求过于频繁）

- 检查 `MAX_CONCURRENT` 是否为 1
- 检查日志中的冷却时间是否正常执行

### 图片无法渲染

- 确认 `IMAGE_BASE_URL` 的协议与前端一致（都是 HTTPS 或都是 HTTP）
- 检查 CORS 是否正常（网关已自动添加 CORS 头）

### 内网穿透无法访问

- 检查防火墙是否放行端口
- 检查穿透工具是否正确转发到网关端口
- 检查 Cloudflare Rocket Loader 是否已关闭

## 技术栈

- FastAPI - Web 框架
- httpx - HTTP 客户端
- BeautifulSoup4 - HTML 解析
- uvicorn - ASGI 服务器
- pydantic-settings - 配置管理
