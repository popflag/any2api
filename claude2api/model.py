from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class ErrorResponse(BaseModel):
    """错误响应模型"""
    error: str

class ChatCompletionRequest(BaseModel):
    """聊天完成请求模型"""
    model: str = ""
    messages: List[Dict[str, Any]] = []
    stream: bool = True
