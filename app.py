from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import sys
from claude2api.auth import verify_token
from claude2api.config import get_config
from claude2api.handlers import (
    health_check_handler,
    modules_handler,
    chat_completions_handler,
)

logger.remove()
logger.add(
    sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", level="INFO"
)
logger.add("logs/file_{time}.log", rotation="10 MB", level="INFO")

# 初始化 FastAPI 应用
app = FastAPI()

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,  # 允许携带凭据
    allow_methods=["POST", "GET", "OPTIONS", "PUT", "DELETE"],  # 允许特定的 HTTP 方法
    allow_headers=[
        "Content-Type",
        "Content-Length",
        "Accept-Encoding",
        "Authorization",
    ],  # 允许特定的Header
)

# 注册路由
app.get("/health")(health_check_handler)
app.get("/v1/models", dependencies=[Depends(verify_token)])(modules_handler)
app.post("/v1/chat/completions", dependencies=[Depends(verify_token)])(
    chat_completions_handler
)


if __name__ == "__main__":
    import uvicorn

    # 从配置中获取地址和端口
    config = get_config()
    host, port_str = config.address.split(":")
    port = int(port_str)

    logger.info(f"正在启动 Uvicorn 服务器，地址: {host}，端口: {port}...")
    uvicorn.run(app, host=host, port=port)
