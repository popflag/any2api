"""
Claude管道模块，负责协调消息处理、上下文管理和会话管理，生成响应。
"""

from typing import Dict, Any, AsyncGenerator

from claude2api.config import SessionInfo
from claude2api.models import ChatCompletionRequest
from claude2api.message_processor import MessageProcessor
from claude2api.context_manager import ContextManager
from claude2api.conversation_manager import ConversationManager


class ClaudePipeline:
    """Claude处理管道，负责处理用户请求并通过Claude API生成响应"""

    def __init__(self):
        """初始化Claude处理管道"""
        self.message_processor = MessageProcessor()
        self.context_manager = ContextManager()
        self.conversation_manager = ConversationManager()

    async def pipline(
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
        self.message_processor.process_messages(request.messages)
        prompt = self.message_processor.get_prompt()
        image_data = self.message_processor.get_image_data()

        # 保存原始提示以便上下文管理
        self.context_manager.set_original_prompt(prompt)

        # 初始化变量
        conversation_id = None
        client = None

        try:
            # 创建客户端
            try:
                client = await self.conversation_manager.create_client(session)
            except Exception as e:
                yield {"type": "error", "content": str(e)}
                return

            # 上传图片文件（如果有）
            if image_data:
                try:
                    await self.context_manager.upload_images(client, image_data)
                except Exception as e:
                    yield {"type": "error", "content": str(e)}
                    return

            # 处理大型上下文
            try:
                prompt = await self.context_manager.handle_large_context(client, prompt)
            except Exception as e:
                yield {"type": "error", "content": str(e)}
                return

            # 创建会话
            try:
                conversation_id = await self.conversation_manager.create_conversation(
                    client, request.model
                )
            except Exception as e:
                yield {"type": "error", "content": str(e)}
                return

            # 发送消息并处理响应流
            try:
                message_generator = client.send_message(
                    conversation_id, prompt, request.stream
                )

                # 转发来自Claude客户端的事件
                async for event in message_generator:
                    yield event

            except Exception as e:
                yield {"type": "error", "content": f"处理响应时发生内部错误: {e}"}

        finally:
            # 无论成功或失败，如果会话已创建，则清理会话
            if client and conversation_id:
                await self.conversation_manager.cleanup_conversation(
                    client, conversation_id
                )


# 创建单例实例供全局使用
claude_pipeline = ClaudePipeline()
