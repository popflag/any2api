from typing import Callable, Awaitable

from fastapi import FastAPI, Request, Response, HTTPException  # 添加HTTPException导入
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import claude2api.config as config
from config_parser import load_config  # 导入配置加载函数

# 加载配置
yaml_config = load_config("config.yaml")

# 更新全局配置实例
config.ConfigInstance.api_key = yaml_config.get("api_key", "")
config.ConfigInstance.address = yaml_config.get("address", "0.0.0.0:8080")
config.ConfigInstance.sessions = yaml_config.get("sessions", [])
config.ConfigInstance.chat_delete = yaml_config.get("chat_delete", True)
config.ConfigInstance.max_chat_history_length = yaml_config.get("max_chat_history_length", 10000)
config.ConfigInstance.no_role_prefix = yaml_config.get("no_role_prefix", False)
config.ConfigInstance.prompt_disable_artifacts = yaml_config.get("prompt_disable_artifacts", False)
config.ConfigInstance.enable_mirror_api = yaml_config.get("enable_mirror_api", False)
config.ConfigInstance.mirror_api_prefix = yaml_config.get("mirror_api_prefix", "")

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
