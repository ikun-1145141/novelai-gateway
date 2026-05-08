import logging
import uvicorn
from src.proxy.config import settings

# 只让 gateway logger 输出 INFO，其余静默
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("gateway").setLevel(logging.INFO)
# 彻底禁用 uvicorn 的访问日志，只保留 gateway 的业务日志
logging.getLogger("uvicorn.access").handlers = []
logging.getLogger("uvicorn.access").propagate = False

if __name__ == "__main__":
    uvicorn.run(
        "src.proxy.app:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="warning",
    )
