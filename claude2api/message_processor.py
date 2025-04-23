"""
消息处理模块，负责格式化和处理聊天消息。
"""

from typing import List, Dict, Any
from loguru import logger
from pydantic import BaseModel

from claude2api.config import get_config


class ChatMessage(BaseModel):
    """聊天消息模型"""

    role: str
    content: str


class MessageProcessor:
    """消息处理器，负责将消息转换为Claude API所需的格式"""

    def __init__(self):
        """初始化消息处理器"""
        self.config = get_config()
        self.prompt = ""
        self.img_data_list = []

    def get_role_prefix(self, role: str) -> str:
        """获取角色前缀

        Args:
            role: 角色名称

        Returns:
            str: 角色对应的前缀
        """
        # 如果配置指定不使用角色前缀，则返回空字符串
        if hasattr(self.config, "no_role_prefix") and self.config.no_role_prefix:
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
            hasattr(self.config, "prompt_disable_artifacts")
            and self.config.prompt_disable_artifacts
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

        # 调试输出
        logger.debug(f"Processed prompt: {self.prompt}")
        logger.debug(f"Image data list: {self.img_data_list}")

    def reset(self) -> None:
        """重置处理器状态"""
        self.prompt = ""
        self.img_data_list = []

    def get_prompt(self) -> str:
        """获取处理后的Prompt"""
        return self.prompt

    def get_image_data(self) -> List[str]:
        """获取处理后的图片数据列表"""
        return self.img_data_list
