import json
import os
import logging
import struct
import zipfile
import io
from datetime import datetime
from threading import Lock

# 确保日志目录存在
os.makedirs("logs", exist_ok=True)

# 配置统计专用日志文件
stats_logger = logging.getLogger("stats")
stats_logger.setLevel(logging.INFO)
if not stats_logger.handlers:
    fh = logging.FileHandler("logs/stats.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    stats_logger.addHandler(fh)

STATS_JSON = "logs/stats_summary.json"
_stats_lock = Lock()

def _get_png_size(data: bytes) -> tuple[int, int]:
    """从 PNG 二进制数据中解析宽高"""
    if len(data) < 24: return 0, 0
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        w, h = struct.unpack('>II', data[16:24])
        return w, h
    return 0, 0

def _get_size_from_any(content: bytes) -> tuple[int, int]:
    """尝试从响应内容（可能是 ZIP 或 PNG）中检测宽高"""
    if not content: return 0, 0
    # 1. 尝试当作 PNG 解析
    w, h = _get_png_size(content)
    if w > 0: return w, h
    # 2. 尝试当作 ZIP 解析
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.endswith(".png"):
                    return _get_png_size(zf.read(name))
    except:
        pass
    return 0, 0

def record_generation(content: bytes, path: str, width: int = 0, height: int = 0):
    """记录生成统计：根据画幅判断，超过 1024x1024 (1,048,576 像素) 为大图"""
    # 只统计生成图片的接口
    if "/ai/generate-image" not in path:
        return

    # 如果没传宽高，尝试从内容中检测
    if width <= 0 or height <= 0:
        width, height = _get_size_from_any(content)

    # 按像素数判断（NAI 官方标准：> 1M 像素算大图）
    is_large = (width * height) > 1024 * 1024
        
    size_type = "large" if is_large else "small"
    size_label = "大图" if is_large else "小图"
    size_bytes = len(content)
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    with _stats_lock:
        # 1. 更新持久化 JSON 统计
        stats_data = {}
        if os.path.exists(STATS_JSON):
            try:
                with open(STATS_JSON, "r", encoding="utf-8") as f:
                    stats_data = json.load(f)
            except:
                stats_data = {}
        
        if today not in stats_data:
            stats_data[today] = {"small": 0, "large": 0}
        
        stats_data[today][size_type] += 1
        
        with open(STATS_JSON, "w", encoding="utf-8") as f:
            json.dump(stats_data, f, indent=2, ensure_ascii=False)
        
        # 2. 写入日志文件
        current_total = stats_data[today]
        dim_str = f"{width}x{height}" if width > 0 else "未知"
        log_msg = (f"生成确认 | 类型: {size_label} | 画幅: {dim_str} | 大小: {size_bytes/1024/1024:.2f}MB | "
                   f"今日累计: 小图={current_total['small']}, 大图={current_total['large']}")
        stats_logger.info(log_msg)
        
        # 3. 控制台实时反馈
        print(f"📊 {log_msg}")
