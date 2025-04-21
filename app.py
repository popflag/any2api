from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
import asyncio
from typing import Optional

from claude2api.config import get_config, get_next_session, SessionInfo
from claude2api.model import ChatCompletionRequest
# Assuming core, ChatRequestProcessor are defined elsewhere.  If not, define them.
# from claude2api import core  # Uncomment if core is in claude2api
# from claude2api.processor import ChatRequestProcessor # Uncomment if processor is in claude2api

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


# 从请求中解析和验证请求
async def parse_and_validate_request(request: Request) -> ChatCompletionRequest:
    """解析并验证请求"""
    try:
        # 从请求体中提取 JSON 数据
        json_data = await request.json()
        # 使用默认值创建请求对象
        req = ChatCompletionRequest(stream=True)
        # 更新请求对象
        req = ChatCompletionRequest(**json_data)

        # 验证消息
        if not req.messages:
            raise HTTPException(status_code=400, detail={"error": "未提供消息"})

        return req
    except Exception as e:
        raise HTTPException(status_code=400, detail={"error": f"无效的请求: {str(e)}"})


# 获取模型名称或使用默认值
def get_model_or_default(model: str) -> str:
    """获取模型或使用默认模型"""
    if not model:
        return "claude-3-7-sonnet-20250219"
    return model


# 创建处理器实例
# processor = ChatRequestProcessor() # Uncomment if processor is in claude2api
class ChatRequestProcessor:  # Dummy class
    def __init__(self):
        self.img_data_list = []
        self.prompt = ""
        self.root_prompt = ""

    def process_messages(self, messages):
        pass

    def reset(self):
        pass

    def reset_for_big_context(self):
        pass


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

    # 获取模型名称或使用默认模型
    model = get_model_or_default(req.model)

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

        # 如果是重试，重置处理器
        if i > 0:
            processor.reset()
            processor.prompt = processor.root_prompt

        # 处理消息
        processor.process_messages(req.messages)

        # 初始化客户端并处理请求
        success = await handle_chat_request(
            request, session, model, processor, req.stream
        )
        if success:
            # 这里的实现可能需要根据您的需求进行调整
            # 如果 handle_chat_request 函数已经处理了响应（例如 StreamingResponse），则这里不需要返回
            # 否则，您可能需要返回适当的响应
            return

        # 如果到这里，请求失败 - 使用另一个会话重试
        logging.info("正在尝试另一个会话")

    # 所有重试都失败
    logging.error("所有重试都失败")
    return {"error": "在多次尝试后无法处理请求"}
