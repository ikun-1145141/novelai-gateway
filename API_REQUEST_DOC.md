# NovelAI Gateway OpenAI 兼容接口文档

## 图像生成（Chat Completions 格式）

### 端点
```
POST /v1/chat/completions
```

### 参数说明

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model` | string | 是 | — | 模型名称，见支持的模型列表 |
| `messages` | array | 是 | — | 消息数组，见消息解析规则 |
| `scale` | float | 否 | `5.0` | 提示词指导强度（Prompt Guidance），范围 `1.0–10.0` |
| `cfg_rescale` | float | 否 | `0.6` | 提示词引导缩放比例，范围 `0.0–1.0` |
| `width` | int | 否 | `832` | 图片宽度，只允许 `832`、`1024`、`1216` |
| `height` | int | 否 | `1216` | 图片高度，只允许 `832`、`1024`、`1216` |

> **画幅组合**：只接受官方三种标准尺寸，传入其他值自动回退到 `832×1216`：
> - `832×1216`（竖图，默认）
> - `1024×1024`（方图）
> - `1216×832`（横图）
>
> **步数**：固定为 `28`，不可修改。

### 支持的模型

- `nai-diffusion-4-5-curated`
- `nai-diffusion-4-5-full`
- `nai-diffusion-4-curated-preview`
- `nai-diffusion-3`
- `nai-diffusion-furry-3`

### 消息解析规则

1. **正面提示词**：从 `role: "user"` 的消息中提取，多条自动拼接，无则返回 400。
2. **负面提示词**（可选）：从 `role: "system"` 且含 `"Negative prompt:"` 的消息提取，不提供则使用默认负面词。
3. **多人物**（可选）：从 `role: "system"` 且含 `"Characters:"` 的消息提取，值为 JSON 数组。

### 完整请求示例

```json
{
  "model": "nai-diffusion-4-5-curated",
  "scale": 6.5,
  "cfg_rescale": 0.6,
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

### 响应格式

```json
{
  "id": "chatcmpl-1715162047",
  "object": "chat.completion",
  "created": 1715162047,
  "model": "nai-diffusion-4-5-curated",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "![image](http://<host>/images/<uuid>.png)"
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

---

## 图像生成（DALL-E 格式）

### 端点
```
POST /v1/images/generations
```

### 参数说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `model` | string | 是 | 模型名称 |
| `prompt` | string | 是 | 正面提示词 |
| `size` | string | 否 | 图片尺寸，格式 `WxH`，默认 `1024x1024` |

### 响应格式

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

```
GET /v1/models
```

---

## 错误响应

| 状态码 | 含义 |
|--------|------|
| 400 | 请求参数错误（如无提示词） |
| 401 | API Key 无效或已过期 |
| 402 | Anlas 积分不足 |
| 503 | 排队超时（默认 300 秒） |

---

## 注意事项

- **并发限制**：同时只处理 1 个图像生成请求，其余排队等待
- **多人物坐标**：`x` 和 `y` 为相对坐标（`0.0–1.0`），`{x: 0.5, y: 0.5}` 表示画面正中央
