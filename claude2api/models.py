from typing import Optional, List, Dict, Any
import time
import uuid
from pydantic import BaseModel, Field


# 请求模型
class ChatCompletionRequest(BaseModel):
    """聊天请求模型"""

    model: str = "claude-3-7-sonnet-20250219"
    messages: List[Dict[str, Any]]
    stream: bool = True
    tools: Optional[List[Dict[str, Any]]] = None


# 流式响应相关模型
class Delta(BaseModel):
    """增量内容模型"""

    content: str


class StreamChoice(BaseModel):
    """流式选择模型"""

    index: int
    delta: Delta
    logprobs: Optional[Any] = None
    finish_reason: Optional[Any] = None


# 非流式响应相关模型
class Message(BaseModel):
    """消息模型"""

    role: str
    content: str
    refusal: Optional[Any] = None
    annotation: Optional[List[Any]] = None


class NoStreamChoice(BaseModel):
    """非流式选择模型"""

    index: int
    message: Message
    logprobs: Optional[Any] = None
    finish_reason: str = "stop"


class Usage(BaseModel):
    """使用统计模型"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIStreamResponse(BaseModel):
    """OpenAI 流式响应模型"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "claude-3-7-sonnet-20250219"
    choices: List[StreamChoice]


class OpenAIResponse(BaseModel):
    """OpenAI 完整响应模型"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = "claude-3-7-sonnet-20250219"
    choices: List[NoStreamChoice]
    usage: Usage
