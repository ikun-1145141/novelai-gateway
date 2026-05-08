import json
import os
import logging
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

def record_generation(size_bytes: int, path: str):
    """记录生成统计：小于 2MB 为小图，大于等于 2MB 为大图"""
    # 只统计生成图片的接口
    if "/ai/generate-image" not in path:
        return

    is_large = size_bytes >= 2 * 1024 * 1024
    size_type = "large" if is_large else "small"
    size_label = "大图" if is_large else "小图"
    
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
        log_msg = (f"生成确认 | 类型: {size_label} | 大小: {size_bytes/1024/1024:.2f}MB | "
                   f"今日累计: 小图={current_total['small']}, 大图={current_total['large']}")
        stats_logger.info(log_msg)
        
        # 3. 控制台实时反馈
        print(f"📊 {log_msg}")
