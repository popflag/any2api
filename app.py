from typing import Callable, Awaitable

from fastapi import FastAPI, Request, Response, HTTPException  # 添加HTTPException导入
from starlette.middleware.base import BaseHTTPMiddleware
import claude2api.config as config

app = FastAPI()


# 自定义认证中间件
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 检查是否启用镜像API且路径匹配
        if config.ConfigInstance.EnableMirrorApi and request.url.path.startswith(
            config.ConfigInstance.MirrorApiPrefix
        ):
            request.state.use_mirror_api = True
            return await call_next(request)

        # 获取Authorization头
        auth_header = request.headers.get("Authorization")
        if auth_header:
            key = auth_header.replace("Bearer ", "", 1)
            if key == config.ConfigInstance.APIKey:
                request.state.authenticated = True
                return await call_next(request)
            else:
                return HTTPException(status_code=401, detail="Invalid API key")
        else:
            return HTTPException(
                status_code=401, detail="Missing or invalid Authorization header"
            )


# 添加认证中间件
app.add_middleware(AuthMiddleware)


@app.get("/health")
async def health_check_handler(request: Request):
    return {"status": "ok"}


@app.get("/v1/models")
def modules_handler():
    models = [
        {"id": "claude-3-7-sonnet-20250219"},
        {"id": "claude-3-7-sonnet-20250219-think"},
    ]
    return {"data": models}
