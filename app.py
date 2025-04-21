from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from claude2api.config import get_config

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 创建用于处理Bearer令牌的安全组件
security = HTTPBearer(auto_error=False)

config_instance = get_config()

# 验证API密钥的依赖项
async def verify_token(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)
):
    # 验证Authorization头
    if not credentials:
        raise HTTPException(
            status_code=401, detail={"error": "缺少或无效的Authorization头信息"}
        )

    # 提取并验证API密钥
    token = credentials.credentials
    if token != config_instance.api_key:
        raise HTTPException(status_code=401, detail={"error": "无效的API密钥"})

    return True


@app.get("/health")
async def health_check_handler(request: Request):
    return {"status": "ok"}


@app.get("/v1/models")
async def modules_handler(authorized: bool = Depends(verify_token)):
    models = [
        {"id": "claude-3-7-sonnet-20250219"},
        {"id": "claude-3-7-sonnet-20250219-think"},
    ]
    return {"data": models}

@app.post("/v1/chat/completions")
async def chat_completions_handler(request: Request):
    return {"status": "ok"}