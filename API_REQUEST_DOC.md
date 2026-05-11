# NovelAI Gateway OpenAI 兼容接口文档

## 认证

所有请求需要在 Header 中携带 NovelAI 的 API Key：

```
Authorization: Bearer pst-xxxxxxxxxxxx
```

---

## 图像生成（Chat Completions 格式）

### 端点
```
POST /v1/chat/completions
```

### 请求参数

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model` | string | 是 | — | 模型名称，见支持的模型列表 |
| `messages` | array | 是 | — | 消息数组，见消息解析规则 |
| `stream` | bool | 否 | `false` | 是否使用 SSE 流式返回 |
| `scale` | float | 否 | `5.0` | 提示词指导强度（Prompt Guidance），范围 `1.0–10.0` |
| `cfg_rescale` | float | 否 | `0.7` | CFG 缩放比例，范围 `0.0–1.0` |
| `width` | int | 否 | `832` | 图片宽度，只允许 `832`、`1024`、`1216` |
| `height` | int | 否 | `1216` | 图片高度，只允许 `832`、`1024`、`1216` |
| `sampler` | string | 否 | `k_euler_ancestral` | 采样器 |
| `noise_schedule` | string | 否 | `karras` | 噪声调度 |

> **画幅组合**：只接受官方三种标准尺寸（均为小图，≤ 1M 像素），传入其他值自动回退到 `832×1216`：
> - `832×1216`（竖图，默认）
> - `1024×1024`（方图）
> - `1216×832`（横图）
>
> **固定参数（不可修改）：**
> - 步数：固定 `28`
>
> 步数被锁定以确保不会额外消耗 Anlas。
>
> **可选采样器**：`k_euler`、`k_euler_ancestral`、`k_dpmpp_2s_ancestral`、`k_dpmpp_2m`、`k_dpmpp_sde`、`ddim_v3`
>
> **可选噪声调度**：`native`、`karras`、`exponential`、`polyexponential`

### 支持的模型

| 模型 ID | 说明 |
|---------|------|
| `nai-diffusion-4-5-curated` | V4.5 精选版（默认） |
| `nai-diffusion-4-5-full` | V4.5 完整版 |
| `nai-diffusion-4-curated-preview` | V4 精选预览版 |
| `nai-diffusion-3` | V3 |
| `nai-diffusion-furry-3` | V3 Furry |

### 消息解析规则

#### 方式一：纯文本提示词

`role: "user"` 的 content 直接作为正面提示词：

```json
{
  "messages": [
    {"role": "user", "content": "1girl, blue hair, outdoor, best quality"}
  ]
}
```

#### 方式二：JSON 结构化提示词（推荐）

`role: "user"` 的 content 为 JSON 字符串，可精确控制提示词和画幅：

```json
{
  "messages": [
    {
      "role": "user",
      "content": "{\"prompt\": \"1girl, blue hair\", \"negative_prompt\": \"lowres, bad\", \"size\": [1024, 1024]}"
    }
  ]
}
```

JSON content 支持的字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `prompt` | string | 正面提示词 |
| `negative_prompt` | string | 负面提示词（覆盖默认） |
| `size` | [int, int] | 画幅 `[width, height]`，必须是三种合法组合之一 |

#### 方式三：System 消息控制负面词和多人物

```json
{
  "messages": [
    {"role": "user", "content": "2girls, outdoor, garden"},
    {"role": "system", "content": "Negative prompt: lowres, bad quality, blurry"},
    {"role": "system", "content": "Characters: [{\"prompt\": \"1girl, red hair\", \"uc\": \"bad hands\", \"center\": {\"x\": 0.3, \"y\": 0.5}}]"}
  ]
}
```

- `Negative prompt:` 前缀的 system 消息 → 覆盖默认负面词
- `Characters:` 前缀的 system 消息 → 多人物坐标控制

### 完整请求示例

```json
{
  "model": "nai-diffusion-4-5-curated",
  "stream": false,
  "scale": 5.0,
  "cfg_rescale": 0.7,
  "sampler": "k_euler_ancestral",
  "noise_schedule": "karras",
  "width": 832,
  "height": 1216,
  "messages": [
    {
      "role": "user",
      "content": "2girls, outdoor, garden, best quality"
    },
    {
      "role": "system",
      "content": "Negative prompt: lowres, bad quality, blurry, bad anatomy"
    },
    {
      "role": "system",
      "content": "Characters: [{\"prompt\": \"1girl, red hair, red eyes\", \"uc\": \"bad hands\", \"center\": {\"x\": 0.3, \"y\": 0.5}}, {\"prompt\": \"1girl, blue hair, blue eyes\", \"uc\": \"bad anatomy\", \"center\": {\"x\": 0.7, \"y\": 0.5}}]"
    }
  ]
}
```

### 响应格式（非流式）

```json
{
  "id": "chatcmpl-1715162047",
  "object": "chat.completion",
  "created": 1715162047,
  "model": "nai-diffusion-4-5-full",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "![image](https://your-domain.com/images/abc123.png)"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

### 响应格式（流式 stream=true）

```
data: {"id":"chatcmpl-1715162047","object":"chat.completion.chunk","created":1715162047,"model":"nai-diffusion-4-5-full","choices":[{"index":0,"delta":{"role":"assistant","content":"![image](https://your-domain.com/images/abc123.png)"},"finish_reason":"stop"}]}

data: [DONE]
```

---

## 图像生成（DALL-E 格式）

### 端点
```
POST /v1/images/generations
```

### 请求参数

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model` | string | 是 | — | 模型名称 |
| `prompt` | string | 是 | — | 正面提示词（会自动追加质量标签） |
| `size` | string | 否 | `1024x1024` | 图片尺寸，格式 `WxH` |

> 此接口会自动在 prompt 后追加 `, best quality, very aesthetic, absurdres`。

### 响应格式

返回 base64 编码的图片数据：

```json
{
  "created": 1715162047,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANS...",
      "revised_prompt": "1girl, blue eyes, long hair"
    }
  ]
}
```

---

## 获取模型列表

### 端点
```
GET /v1/models
```

### 响应格式

```json
{
  "object": "list",
  "data": [
    {"id": "nai-diffusion-4-5-curated", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    {"id": "nai-diffusion-4-5-full", "object": "model", "created": 1700000000, "owned_by": "novelai"},
    ...
  ]
}
```

---

## 错误响应

| 状态码 | 含义 |
|--------|------|
| 400 | 请求参数错误（如无提示词、JSON 格式错误） |
| 401 | NovelAI API Key 无效或已过期 |
| 402 | Anlas 积分不足 |
| 503 | 排队超时（默认 300 秒） |
| 502 | 上游请求失败 |

---

## 注意事项

1. **并发限制**：同时只处理 1 个图像生成请求，其余排队等待（可通过 `MAX_CONCURRENT` 配置）
2. **冷却机制**：每次生成完成后有 0.5–1.0 秒的随机冷却，避免触发 NovelAI 的频率限制
3. **图片存储**：Chat Completions 格式生成的图片保存在本地 `images/` 目录，通过 URL 访问
4. **HTTPS 要求**：如果前端是 HTTPS，`IMAGE_BASE_URL` 也必须配置为 HTTPS 地址，否则浏览器会拒绝加载图片（Mixed Content）
5. **多人物坐标**：`center` 中的 `x` 和 `y` 为相对坐标（`0.0–1.0`），`{x: 0.5, y: 0.5}` 表示画面正中央
6. **Anlas 消耗控制**：画幅固定 832×1216、步数固定 28，确保每次生成只消耗小图额度
