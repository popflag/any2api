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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.get("/health")(health_check_handler)
app.get("/v1/models", dependencies=[Depends(verify_token)])(modules_handler)
app.post("/v1/chat/completions")(chat_completions_handler)

# 设置日志级别（可选）
logging.basicConfig(level=logging.INFO)
