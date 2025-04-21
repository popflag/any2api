from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
import asyncio
from typing import Optional, List, Dict, Any
import time
import uuid
from pydantic import BaseModel, Field, ValidationError
from json.decoder import JSONDecodeError
from fastapi.responses import StreamingResponse
from claude2api.config import get_config, get_next_session, SessionInfo

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


async def handle_chat_request(request, session, model, processor, stream=True) -> bool:
    """处理聊天请求"""
    # 初始化 Claude 客户端
    config_instance = get_config()
    # claude_client = await core.new_client(session.session_key, config_instance.proxy) # Uncomment if core is in claude2api
    claude_client = None  # Replace with actual client initialization

    # 如果没有组织 ID，则获取
    if not session.org_id:
        try:
            # org_id = await claude_client.get_org_id() # Uncomment if core is in claude2api
            org_id = "dummy_org_id"  # Replace with actual org id retrieval
            session.org_id = org_id
            config_instance.set_session_org_id(session.session_key, session.org_id)
        except Exception as e:
            logging.error(f"获取组织 ID 失败: {e}")
            return False

    # claude_client.set_org_id(session.org_id) # Uncomment if core is in claude2api

    # 上传图片文件（如果有）
    if processor.img_data_list:
        try:
            # await claude_client.upload_file(processor.img_data_list) # Uncomment if core is in claude2api
            pass
        except Exception as e:
            logging.error(f"上传文件失败: {e}")
            return False

    # 处理大型上下文
    if len(processor.prompt) > config_instance.max_chat_history_length:
        # await claude_client.set_big_context(processor.prompt) # Uncomment if core is in claude2api
        processor.reset_for_big_context()
        logging.info(
            f"提示长度超过最大限制 ({config_instance.max_chat_history_length})，使用文件上下文"
        )

    # 创建会话
    try:
        # conversation_id = await claude_client.create_conversation(model) # Uncomment if core is in claude2api
        conversation_id = (
            "dummy_conversation_id"  # Replace with actual conversation creation
        )
    except Exception as e:
        logging.error(f"创建会话失败: {e}")
        return False

    # 发送消息
    try:
        # await claude_client.send_message(conversation_id, processor.prompt, stream, request) # Uncomment if core is in claude2api
        pass
    except Exception as e:
        logging.error(f"发送消息失败: {e}")
        asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))
        return False

    # 如果启用了自动清理，则清理会话
    if config_instance.chat_delete:
        asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))

    return True


async def cleanup_conversation(client, conversation_id: str, retry: int) -> None:
    """清理会话"""
    for i in range(retry):
        try:
            # await client.delete_conversation(conversation_id) # Uncomment if core is in claude2api
            logging.info(f"成功删除会话: {conversation_id}")
            return
        except Exception as e:
            logging.error(f"删除会话失败: {e}")
            await asyncio.sleep(2)

    # 当所有重试都失败后执行
    logging.error(
        f"清理 {client.session_key} 会话 {conversation_id} 在 {retry} 次重试后失败"
    )


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


async def parse_and_validate_request(request: Request) -> ChatCompletionRequest:
    """解析并验证请求"""
    try:
        # 从请求体中提取 JSON 数据
        json_data = await request.json()

        # 使用 Pydantic 模型直接验证和解析请求数据
        req = ChatCompletionRequest(**json_data)

        # 验证消息
        if not req.messages:
            raise HTTPException(status_code=400, detail={"error": "未提供消息"})

        return req
    except ValidationError as ve:
        # 捕获 Pydantic 验证错误并返回详细信息
        logging.error(f"请求验证失败: {ve}")
        raise HTTPException(
            status_code=400, detail={"error": f"请求验证失败: {str(ve)}"}
        )
    except JSONDecodeError as je:
        # 捕获 JSON 解析错误
        logging.error(f"无效的 JSON 格式: {je}")
        raise HTTPException(status_code=400, detail={"error": "无效的 JSON 格式"})
    except Exception as e:
        # 捕获其他所有错误
        logging.error(f"请求处理错误: {e}")
        raise HTTPException(status_code=400, detail={"error": f"无效的请求: {str(e)}"})


async def return_openai_response(text: str, stream: bool, request: Request):
    """生成 OpenAI 格式的响应"""
    if stream:
        return await stream_response(text, request)
    else:
        return await no_stream_response(text)


async def stream_response(text: str, request: Request):
    """生成流式响应"""
    # 创建流式响应对象
    resp = OpenAIStreamResponse(
        choices=[StreamChoice(index=0, delta=Delta(content=text))]
    )

    # 转换为 JSON
    json_data = resp.model_dump_json()

    # 添加 SSE 格式
    formatted_data = f"data: {json_data}\n\n"

    async def generate():
        yield formatted_data

    return StreamingResponse(generate(), media_type="text/event-stream")


async def no_stream_response(text: str):
    """生成非流式响应"""
    resp = OpenAIResponse(
        choices=[
            NoStreamChoice(index=0, message=Message(role="assistant", content=text))
        ],
        usage=Usage(),
    )

    return resp


# 聊天请求处理器
class ChatRequestProcessor:
    """聊天请求处理器，用于处理聊天消息和提取图片数据"""

    def __init__(self):
        """初始化处理器"""
        self.prompt = ""  # 当前提示内容
        self.root_prompt = ""  # 原始提示内容备份
        self.img_data_list = []  # 图片数据列表

    def get_role_prefix(self, role: str) -> str:
        """获取角色前缀"""
        # 如果配置指定不使用角色前缀，则返回空字符串
        config_instance = get_config()
        if (
            hasattr(config_instance, "no_role_prefix")
            and config_instance.no_role_prefix
        ):
            return ""

        # 根据角色返回对应前缀
        role_map = {
            "system": "System: ",
            "user": "Human: ",
            "assistant": "Assistant: ",
        }
        # 返回对应的角色前缀，如果角色不在映射中则返回 "Unknown: "
        return role_map.get(role.lower(), "Unknown: ")

    def process_messages(self, messages: List[Dict[str, Any]]) -> None:
        """处理消息数组为提示并提取图片

        Args:
            messages: 消息列表
        """
        config_instance = get_config()

        # 如果配置禁用了 artifacts
        if (
            hasattr(config_instance, "prompt_disable_artifacts")
            and config_instance.prompt_disable_artifacts
        ):
            self.prompt = "System: Forbidden to use <antArtifac> </antArtifac> to wrap code blocks, use markdown syntax instead, which means wrapping code blocks with ``` ```\n\n"
        else:
            self.prompt = ""

        # 处理每条消息
        for msg in messages:
            # 检查消息是否有效
            if "role" not in msg:
                continue

            role = msg["role"]
            if "content" not in msg:
                continue

            content = msg["content"]
            role_prefix = self.get_role_prefix(role)
            self.prompt += role_prefix

            # 处理不同类型的内容
            if isinstance(content, str):
                # 直接是字符串类型
                self.prompt += content + "\n\n"
            elif isinstance(content, list):
                # 内容是列表类型
                for item in content:
                    if not isinstance(item, dict) or "type" not in item:
                        continue

                    item_type = item["type"]
                    if item_type == "text" and "text" in item:
                        self.prompt += item["text"] + "\n\n"
                    elif item_type == "image_url" and "image_url" in item:
                        # 提取图片URL并添加到图片列表
                        if (
                            isinstance(item["image_url"], dict)
                            and "url" in item["image_url"]
                        ):
                            self.img_data_list.append(item["image_url"]["url"])

        # 保存原始提示
        self.root_prompt = self.prompt

        # 调试输出
        logging.debug(f"处理后的提示: {self.prompt}")
        logging.debug(f"图片数据列表: {self.img_data_list}")

    def reset(self) -> None:
        """重置处理器"""
        self.prompt = ""
        self.img_data_list = []

    def reset_for_big_context(self) -> None:
        """重置提示为大型上下文使用"""
        self.prompt = ""
        config_instance = get_config()

        # 如果配置禁用了 artifacts
        if (
            hasattr(config_instance, "prompt_disable_artifacts")
            and config_instance.prompt_disable_artifacts
        ):
            self.prompt += "System: Forbidden to use <antArtifac> </antArtifac> to wrap code blocks, use markdown syntax instead, which means wrapping code blocks with ``` ```\n\n"

        self.prompt += "You must immerse yourself in the role of assistant in context.txt, cannot respond as a user, cannot reply to this message, cannot mention this message, and ignore this message in your response.\n\n"


processor = ChatRequestProcessor()


@app.post("/v1/chat/completions")
async def chat_completions_handler(
    request: Request, authorized: bool = Depends(verify_token)
):
    """处理聊天完成请求"""
    # 解析并验证请求
    try:
        req = await parse_and_validate_request(request)
    except HTTPException as e:
        return e.detail

    # 获取模型名称
    model = req.model  # 现在这是一个固定的字段，不需要检查是否存在

    # 获取配置实例
    config_instance = get_config()

    # 使用重试机制
    for i in range(config_instance.retry_count + 1):  # +1 是为了确保至少尝试一次
        session = get_next_session()

        if not session:
            logging.error(f"无法获取模型 {model} 的会话")
            logging.info("正在尝试另一个会话")
            continue

        logging.info(f"使用模型 {model} 的会话: {session.session_key}")

        # 处理消息
        processor.process_messages(req.messages)

        # 如果是重试，重置处理器
        if i > 0:
            processor.reset()
            processor.prompt = processor.root_prompt

        # 初始化客户端并处理请求
        success = await handle_chat_request(
            request, session, model, processor, req.stream
        )
        if success:
            # 这里应该根据实际情况返回响应
            # 假设 handle_chat_request 在内部使用了 return_openai_response
            return

        # 如果到这里，请求失败 - 使用另一个会话重试
        logging.info("正在尝试另一个会话")

    # 所有重试都失败
    logging.error("所有重试都失败")
    return {"error": "在多次尝试后无法处理请求"}
