from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from claude2api.config import get_config, SessionInfo

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


async def extract_session_from_auth_header(request) -> Optional[SessionInfo]:
    """从请求头中提取会话信息"""
    auth_info = request.headers.get("Authorization", "")
    auth_info = auth_info.replace("Bearer ", "")

    if not auth_info:
        return None

    if ":" in auth_info:
        parts = auth_info.split(":")
        return SessionInfo(session_key=parts[0], org_id=parts[1])

    return SessionInfo(session_key=auth_info, org_id="")
