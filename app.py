from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
import logging
from claude2api.auth import verify_token
from claude2api.handlers import (
    health_check_handler,
    modules_handler,
    chat_completions_handler,
)

# 初始化 FastAPI 应用
app = FastAPI()

# 添加 CORS 中间件
# 根据用户要求，修改 CORS 配置，限制允许的方法和头部
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
    ],  # 允许特定的头部
)

# 注册路由
app.get("/health")(health_check_handler)
# /v1/models 路由需要验证 token
app.get("/v1/models", dependencies=[Depends(verify_token)])(modules_handler)
app.post("/v1/chat/completions", dependencies=[Depends(verify_token)])(
    chat_completions_handler
)

# 设置日志级别（可选）
logging.basicConfig(level=logging.INFO)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app)
