from loguru import logger
import asyncio
from typing import Dict, Any, AsyncGenerator, List
from pydantic import BaseModel

from claude2api.claude_client import ClaudeClient, new_client
from claude2api.config import SessionInfo, get_config
from claude2api.models import ChatCompletionRequest

config_instance = get_config()


class ChatMessage(BaseModel):
    """聊天消息模型"""

    role: str
    content: str


class ChatPipeline:
    """聊天处理管道，负责处理用户请求并通过 Claude API 生成响应"""

    def __init__(self):
        """初始化处理管道"""
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
        self.reset()  # 重置处理器状态

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
        logger.debug(f"Processed prompt: {self.prompt}")
        logger.debug(f"Image data list: {self.img_data_list}")

    def reset(self) -> None:
        """重置处理器状态"""
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

    async def execute(
        self, request: ChatCompletionRequest, session: SessionInfo
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理聊天请求并生成响应流

        Args:
            request: 聊天请求对象
            session: 会话信息对象

        Yields:
            Dict[str, Any]: 包含响应类型和内容的字典
              - type: "text", "thinking", "error", "done"
              - content: 事件的具体内容
        """
        # 处理消息
        self.process_messages(request.messages)

        # 初始化 Claude 客户端
        claude_client = await new_client(session.session_key, config_instance.proxy)

        conversation_id = None

        try:
            # 如果没有组织 ID，则获取
            if not session.org_id:
                try:
                    org_id = await claude_client.get_org_id()
                    session.org_id = org_id
                    config_instance.set_session_org_id(
                        session.session_key, session.org_id
                    )
                    logger.info(f"成功获取并设置组织 ID: {org_id}")
                except Exception as e:
                    logger.error(f"获取组织 ID 失败: {e}")
                    yield {"type": "error", "content": f"获取组织 ID 失败: {e}"}
                    return  # 发生错误，停止执行

            claude_client.set_org_id(session.org_id)

            # 上传图片文件（如果有）
            if self.img_data_list:
                try:
                    await claude_client.upload_file(self.img_data_list)
                    logger.info(f"成功上传 {len(self.img_data_list)} 个文件")
                except Exception as e:
                    logger.error(f"上传文件失败: {e}")
                    yield {"type": "error", "content": f"上传文件失败: {e}"}
                    return  # 发生错误，停止执行

            # 处理大型上下文
            if len(self.prompt) > config_instance.max_chat_history_length:
                try:
                    claude_client.set_big_context(self.prompt)
                    self.reset_for_big_context()
                    logger.info(
                        f"提示长度超过最大限制 ({config_instance.max_chat_history_length})，使用文件上下文"
                    )
                except Exception as e:
                    logger.error(f"设置大型上下文失败: {e}")
                    yield {"type": "error", "content": f"设置大型上下文失败: {e}"}
                    return  # 发生错误，停止执行

            # 创建会话
            try:
                conversation_id = await claude_client.create_conversation(request.model)
                logger.info(f"成功创建会话: {conversation_id}")
            except Exception as e:
                logger.error(f"创建会话失败: {e}")
                yield {"type": "error", "content": f"创建会话失败: {e}"}
                return  # 发生错误，停止执行

            # 发送消息并处理响应流
            try:
                message_generator = claude_client.send_message(
                    conversation_id, self.prompt, request.stream
                )

                # 转发来自Claude客户端的事件
                async for event in message_generator:
                    logger.debug(event)
                    yield event

            except Exception as e:
                logger.error(f"处理消息流时发生意外错误: {e}")
                yield {"type": "error", "content": f"处理响应时发生内部错误: {e}"}

        finally:
            # 无论成功或失败，如果启用了自动清理且会话已创建，则清理会话
            if config_instance.chat_delete and conversation_id:
                # 使用 create_task 调度清理，不阻塞当前函数返回
                asyncio.create_task(
                    self._cleanup_conversation(claude_client, conversation_id, 3)
                )
                logger.info(f"已调度会话 {conversation_id} 的清理任务")

    async def _cleanup_conversation(
        self, client: ClaudeClient, conversation_id: str, retry: int
    ) -> None:
        """清理会话

        Args:
            client: Claude客户端
            conversation_id: 会话ID
            retry: 重试次数
        """
        for i in range(retry):
            try:
                await client.delete_conversation(conversation_id)
                logger.info(f"成功删除会话: {conversation_id}")
                return
            except Exception as e:
                logger.error(f"删除会话失败 (重试 {i + 1}/{retry}): {e}")
                await asyncio.sleep(2)

        # 当所有重试都失败后执行
        logger.error(f"清理会话 {conversation_id} 在 {retry} 次重试后失败")


# 创建单例实例供全局使用
pipeline = ChatPipeline()
