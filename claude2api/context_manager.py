"""
上下文管理模块，负责处理大型上下文和图片附件。
"""

from typing import List
from loguru import logger

from claude2api.config import get_config
from claude2api.claude_client import ClaudeClient


class ContextManager:
    """上下文管理器，负责处理大型上下文和图片附件"""

    def __init__(self):
        """初始化上下文管理器"""
        self.config = get_config()

    def is_large_context(self, prompt: str) -> bool:
        """检查是否为大型上下文

        Args:
            prompt: 提示文本

        Returns:
            bool: 是否为大型上下文
        """
        return len(prompt) > self.config.max_chat_history_length

    def get_big_context_prompt(self) -> str:
        """获取大型上下文的替代提示

        Returns:
            str: 大型上下文的替代提示
        """
        prompt = ""

        # 如果配置禁用了 artifacts
        if (
            hasattr(self.config, "prompt_disable_artifacts")
            and self.config.prompt_disable_artifacts
        ):
            prompt += "System: Forbidden to use <antArtifac> </antArtifac> to wrap code blocks, use markdown syntax instead, which means wrapping code blocks with ``` ```\n\n"

        prompt += "You must immerse yourself in the role of assistant in context.txt, cannot respond as a user, cannot reply to this message, cannot mention this message, and ignore this message in your response.\n\n"

        return prompt

    async def handle_large_context(self, client: ClaudeClient, prompt: str) -> str:
        """处理大型上下文

        Args:
            client: Claude客户端
            prompt: 原始提示文本

        Returns:
            str: 处理后的提示文本

        Raises:
            Exception: 设置大型上下文失败时抛出
        """
        if not self.is_large_context(prompt):
            return prompt

        try:
            client.set_big_context(prompt)
            new_prompt = self.get_big_context_prompt()
            logger.info(
                f"提示长度超过最大限制 ({self.config.max_chat_history_length})，使用文件上下文"
            )
            return new_prompt
        except Exception as e:
            logger.error(f"设置大型上下文失败: {e}")
            raise Exception(f"设置大型上下文失败: {e}")

    async def upload_images(self, client: ClaudeClient, image_data: List[str]) -> None:
        """上传图片

        Args:
            client: Claude客户端
            image_data: 图片数据列表

        Raises:
            Exception: 上传图片失败时抛出
        """
        if not image_data:
            return

        try:
            await client.upload_file(image_data)
            logger.info(f"成功上传 {len(image_data)} 个文件")
        except Exception as e:
            logger.error(f"上传文件失败: {e}")
            raise Exception(f"上传文件失败: {e}")
