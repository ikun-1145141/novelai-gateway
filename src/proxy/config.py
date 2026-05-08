"""
网关配置，可通过 .env 文件或环境变量覆盖。
"""

from pathlib import Path
from typing import Set
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 31555

    # 本地图床，如果为空则根据请求 Host 自动识别
    image_dir: Path = Path("images")
    image_base_url: str = ""

    # NovelAI 上游地址
    novelai_base_url: str = "https://novelai.net"
    novelai_api_url: str = "https://api.novelai.net"
    novelai_image_url: str = "https://image.novelai.net"

    # 需要排队的重负载 API 路径前缀
    heavy_prefixes: Set[str] = {
        "/ai/generate-image",
        "/ai/upscale",
        "/ai/generate-voice",
    }

    max_concurrent: int = 1          # 同时允许的重负载请求数
    queue_timeout: int = 300         # 排队超时（秒）
    cooldown_min: float = 0.5        # 冷却最小值（秒）
    cooldown_max: float = 1.0        # 冷却最大值（秒）
    upstream_timeout: float = 120.0  # httpx 请求超时（秒）

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def is_heavy(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.heavy_prefixes)

    def get_upstream_url(self, api_path: str) -> str:
        if api_path.startswith(("/ai/generate-image", "/ai/upscale")):
            return f"{self.novelai_image_url}{api_path}"
        return f"{self.novelai_api_url}{api_path}"


settings = Settings()
