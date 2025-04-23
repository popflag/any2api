"""
会话管理模块，负责会话的创建、管理和清理。
"""

import asyncio
from loguru import logger

from claude2api.config import get_config, SessionInfo
from claude2api.claude_client import ClaudeClient, new_client


class ConversationManager:
    """会话管理器，负责会话的创建、管理和清理"""

    def __init__(self):
        """初始化会话管理器"""
        self.config = get_config()

    async def create_client(self, session: SessionInfo) -> ClaudeClient:
        """创建Claude客户端

        Args:
            session: 会话信息

        Returns:
            ClaudeClient: Claude客户端

        Raises:
            Exception: 获取组织ID失败时抛出
        """
        # 初始化 Claude 客户端
        client = await new_client(session.session_key, self.config.proxy)

        # 如果没有组织 ID，则获取
        if not session.org_id:
            try:
                org_id = await client.get_org_id()
                session.org_id = org_id
                self.config.set_session_org_id(session.session_key, session.org_id)
                logger.info(f"成功获取并设置组织 ID: {org_id}")
            except Exception as e:
                logger.error(f"获取组织 ID 失败: {e}")
                raise Exception(f"获取组织 ID 失败: {e}")

        client.set_org_id(session.org_id)
        return client

    async def create_conversation(self, client: ClaudeClient, model: str) -> str:
        """创建会话

        Args:
            client: Claude客户端
            model: 模型名称

        Returns:
            str: 会话ID

        Raises:
            Exception: 创建会话失败时抛出
        """
        try:
            conversation_id = await client.create_conversation(model)
            logger.info(f"成功创建会话: {conversation_id}")
            return conversation_id
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            raise Exception(f"创建会话失败: {e}")

    async def cleanup_conversation(
        self, client: ClaudeClient, conversation_id: str
    ) -> None:
        """清理会话

        Args:
            client: Claude客户端
            conversation_id: 会话ID
        """
        if not self.config.chat_delete:
            return

        # 使用 create_task 调度清理，不阻塞当前函数返回
        asyncio.create_task(self._cleanup_conversation_task(client, conversation_id, 3))
        logger.info(f"已调度会话 {conversation_id} 的清理任务")

    async def _cleanup_conversation_task(
        self, client: ClaudeClient, conversation_id: str, retry: int
    ) -> None:
        """清理会话任务

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
