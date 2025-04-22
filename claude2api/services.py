import logging
import asyncio
from typing import List, Dict, Any
from fastapi import Request, HTTPException
from json.decoder import JSONDecodeError
from pydantic import ValidationError
from claude2api.config import SessionInfo, get_config
from claude2api.models import ChatCompletionRequest
from claude2api.core import ClaudeClient, new_client

config_instance = get_config()


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

        # 如果配置禁用了 artifacts
        if (
            hasattr(config_instance, "prompt_disable_artifacts")
            and config_instance.prompt_disable_artifacts
        ):
            self.prompt += "System: Forbidden to use <antArtifac> </antArtifac> to wrap code blocks, use markdown syntax instead, which means wrapping code blocks with ``` ```\n\n"

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
        logging.debug(f"Processed prompt: {self.prompt}")
        logging.debug(f"Image data list: {self.img_data_list}")

    def reset(self) -> None:
        """重置处理器"""
        self.prompt = ""
        self.img_data_list = []

    def reset_for_big_context(self) -> None:
        """重置提示为大型上下文使用"""
        self.prompt = ""

        # 如果配置禁用了 artifacts
        if (
            hasattr(config_instance, "prompt_disable_artifacts")
            and config_instance.prompt_disable_artifacts
        ):
            self.prompt += "System: Forbidden to use <antArtifac> </antArtifac> to wrap code blocks, use markdown syntax instead, which means wrapping code blocks with ``` ```\n\n"

        self.prompt += "You must immerse yourself in the role of assistant in context.txt, cannot respond as a user, cannot reply to this message, cannot mention this message, and ignore this message in your response.\n\n"


async def cleanup_conversation(
    client: ClaudeClient, conversation_id: str, retry: int
) -> None:
    """清理会话"""
    for i in range(retry):
        try:
            await client.delete_conversation(conversation_id)
            logging.info(f"成功删除会话: {conversation_id}")
            return
        except Exception as e:
            logging.error(f"删除会话失败: {e}")
            await asyncio.sleep(2)

    # 当所有重试都失败后执行
    logging.error(
        f"清理 {client.session_key} 会话 {conversation_id} 在 {retry} 次重试后失败"
    )


async def handle_chat_request(
    request: Request,
    session: SessionInfo,
    model: str,
    processor: ChatRequestProcessor,
    stream: bool = True,
) -> bool:
    """处理聊天请求"""
    # 初始化 Claude 客户端
    claude_client = await new_client(session.session_key, config_instance.proxy)

    # 如果没有组织 ID，则获取
    if not session.org_id:
        try:
            org_id = await claude_client.get_org_id()
            session.org_id = org_id
            config_instance.set_session_org_id(session.session_key, session.org_id)
        except Exception as e:
            logging.error(f"获取组织 ID 失败: {e}")
            return False

    claude_client.set_org_id(session.org_id)

    # 上传图片文件（如果有）
    if processor.img_data_list:
        try:
            await claude_client.upload_file(processor.img_data_list)
        except Exception as e:
            logging.error(f"上传文件失败: {e}")
            return False

    # 处理大型上下文
    if len(processor.prompt) > config_instance.max_chat_history_length:
        claude_client.set_big_context(processor.prompt)
        processor.reset_for_big_context()
        logging.info(
            f"提示长度超过最大限制 ({config_instance.max_chat_history_length})，使用文件上下文"
        )

    # 创建会话
    try:
        conversation_id = await claude_client.create_conversation(model)
    except Exception as e:
        logging.error(f"创建会话失败: {e}")
        return False

    # 发送消息
    try:
        status = await claude_client.send_message(
            conversation_id, processor.prompt, stream, request
        )
        if status != 200:
            logging.error(f"发送消息失败，状态码: {status}")
            asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))
            return False
    except Exception as e:
        logging.error(f"发送消息失败: {e}")
        asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))
        return False

    # 如果启用了自动清理，则清理会话
    if config_instance.chat_delete:
        asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))

    return True


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
