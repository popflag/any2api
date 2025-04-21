import logging
import json
import uuid
from typing import List, Dict, Any
from fastapi import Request
from curl_cffi.requests import AsyncSession


class ClaudeClient:
    """Claude API 客户端，使用 curl_cffi 实现浏览器指纹模拟"""

    # 默认 API 配置
    BASE_URL = "https://claude.ai/api"
    DEFAULT_HEADERS = {
        "accept": "text/event-stream, text/event-stream",
        "accept-language": "zh-CN,zh;q=0.9",
        "anthropic-client-platform": "web_claude_ai",
        "content-type": "application/json",
        "origin": "https://claude.ai",
        "priority": "u=1, i",
    }

    # 默认请求属性
    DEFAULT_ATTRS = {
        "personalized_styles": [
            {
                "type": "default",
                "key": "Default",
                "name": "Normal",
                "nameKey": "normal_style_name",
                "prompt": "Normal",
                "summary": "Default responses from Claude",
                "summaryKey": "normal_style_summary",
                "isDefault": True,
            }
        ],
        "tools": [
            {
                "type": "web_search_v0",
                "name": "web_search",
            }
        ],
        "parent_message_uuid": "00000000-0000-4000-8000-000000000000",
        "attachments": [],
        "files": [],
        "sync_sources": [],
        "rendering_mode": "messages",
        "timezone": "America/New_York",
    }

    def __init__(self, session_key: str, proxy: str = ""):
        """初始化客户端

        Args:
            session_key: Claude 会话密钥
            proxy: 代理服务器地址
        """
        self.session_key = session_key
        self.org_id = ""
        self.proxy = proxy
        self.request_attrs = self.DEFAULT_ATTRS.copy()

        # 创建会话
        self.session = self._create_session(session_key, proxy)

    def _create_session(self, session_key: str, proxy: str) -> AsyncSession:
        """创建 curl_cffi 会话

        Args:
            session_key: 会话密钥
            proxy: 代理地址

        Returns:
            AsyncSession: 配置好的会话对象
        """
        return AsyncSession(
            impersonate="chrome",
            timeout=300,
            proxy=proxy if proxy else "",
            headers=self.DEFAULT_HEADERS,
            cookies={"sessionKey": session_key},
        )

    async def get_org_id(self) -> str:
        """获取组织 ID

        Returns:
            str: 组织 ID

        Raises:
            Exception: 获取失败时抛出异常
        """
        url = f"{self.BASE_URL}/organizations"

        try:
            response = await self.session.get(
                url, headers={"referer": "https://claude.ai/new"}
            )

            if response.status_code != 200:
                raise Exception(f"获取组织 ID 失败，状态码: {response.status_code}")

            orgs = response.json()

            if not orgs:
                raise Exception("未找到组织")

            # 优先使用单一组织或默认组织
            if len(orgs) == 1:
                return orgs[0]["uuid"]

            # 查找默认组织
            for org in orgs:
                if org.get("rate_limit_tier") == "default_claude_ai":
                    return org["uuid"]

            raise Exception("未找到默认组织")

        except Exception as e:
            logging.error(f"获取组织 ID 失败: {e}")
            raise

    def set_org_id(self, org_id: str) -> None:
        """设置组织 ID

        Args:
            org_id: 组织 ID
        """
        self.org_id = org_id

    async def create_conversation(self, model: str) -> str:
        """创建会话并返回会话 ID

        Args:
            model: 模型名称

        Returns:
            str: 会话 ID

        Raises:
            Exception: 未设置组织 ID 或创建失败时抛出
        """
        if not self.org_id:
            raise Exception("未设置组织 ID")

        url = f"{self.BASE_URL}/organizations/{self.org_id}/chat_conversations"

        # 准备请求体
        request_body = {
            "model": model,
            "uuid": str(uuid.uuid4()),
            "name": "",
            "include_conversation_preferences": True,
        }

        # 检查是否使用思考模式
        if model.endswith("-think"):
            request_body["paprika_mode"] = "extended"
            request_body["model"] = model[:-6]  # 移除 "-think" 后缀

        try:
            response = await self.session.post(
                url, json=request_body, headers={"referer": "https://claude.ai/new"}
            )

            if response.status_code != 201:
                raise Exception(f"创建会话失败，状态码: {response.status_code}")

            result = response.json()
            conversation_id = result.get("uuid")

            if not conversation_id:
                raise Exception("响应中未找到会话 ID")

            return conversation_id

        except Exception as e:
            logging.error(f"创建会话失败: {e}")
            raise

    async def send_message(
        self, conversation_id: str, message: str, stream: bool, request: Request
    ) -> int:
        """发送消息到会话

        Args:
            conversation_id: 会话 ID
            message: 消息内容
            stream: 是否流式响应
            request: FastAPI 请求对象

        Returns:
            int: 状态码

        Raises:
            Exception: 未设置组织 ID 或发送失败时抛出
        """
        if not self.org_id:
            raise Exception("未设置组织 ID")

        url = f"{self.BASE_URL}/organizations/{self.org_id}/chat_conversations/{conversation_id}/completion"

        # 创建请求体
        request_body = self.request_attrs.copy()
        request_body["prompt"] = message

        try:
            response = await self.session.post(
                url,
                json=request_body,
                headers={
                    "referer": f"https://claude.ai/chat/{conversation_id}",
                    "accept": "text/event-stream, text/event-stream",
                    "anthropic-client-platform": "web_claude_ai",
                    "cache-control": "no-cache",
                },
                stream=True,
            )

            logging.info(f"Claude 响应状态码: {response.status_code}")

            if response.status_code == 429:
                return 429

            if response.status_code != 200:
                return response.status_code

            # 处理流式响应
            await self._handle_response(response, stream, request)
            return 200

        except Exception as e:
            logging.error(f"发送消息失败: {e}")
            raise

    async def _handle_response(self, response, stream: bool, request: Request) -> None:
        """处理 Claude 的 SSE 响应

        Args:
            response: curl_cffi 响应对象
            stream: 是否流式响应
            request: FastAPI 请求对象
        """
        from claude2api.utils import return_openai_response

        # 跟踪完整响应和思考状态
        thinking_shown = False
        res_all_text = ""

        async for line in response.aiter_lines():
            # 检查客户端是否已断开连接
            if await request.is_disconnected():
                logging.info("客户端已断开连接")
                return

            if not line.startswith("data: "):
                continue

            data = line[6:]
            try:
                event = json.loads(data)

                # 处理错误事件
                if self._is_error_event(event):
                    error_message = event["error"]["message"]
                    await return_openai_response(error_message, stream, request)
                    return

                # 处理文本增量
                if self._is_text_delta(event):
                    res_text = event["delta"]["text"]
                    if thinking_shown:
                        res_text = "</think>\n" + res_text
                        thinking_shown = False

                    res_all_text += res_text
                    if stream:
                        await return_openai_response(res_text, stream, request)
                    continue

                # 处理思考增量
                if self._is_thinking_delta(event):
                    res_text = event["delta"]["THINKING"]
                    if not thinking_shown:
                        res_text = "<think>" + res_text
                        thinking_shown = True

                    res_all_text += res_text
                    if stream:
                        await return_openai_response(res_text, stream, request)
                    continue

            except json.JSONDecodeError:
                logging.warning(f"解析 SSE 事件失败: {data}")
                continue

        # 处理非流式响应或发送结束标记
        if not stream:
            await return_openai_response(res_all_text, stream, request)
        else:
            await response.write(b"data: [DONE]\n\n")
            await response.flush()

    def _is_error_event(self, event: Dict[str, Any]) -> bool:
        """检查是否为错误事件

        Args:
            event: 事件数据

        Returns:
            bool: 是否为错误事件
        """
        return event.get("type") == "error" and event.get("error", {}).get("message")

    def _is_text_delta(self, event: Dict[str, Any]) -> bool:
        """检查是否为文本增量事件

        Args:
            event: 事件数据

        Returns:
            bool: 是否为文本增量事件
        """
        delta = event.get("delta", {})
        return delta.get("type") == "text_delta" and delta.get("text")

    def _is_thinking_delta(self, event: Dict[str, Any]) -> bool:
        """检查是否为思考增量事件

        Args:
            event: 事件数据

        Returns:
            bool: 是否为思考增量事件
        """
        delta = event.get("delta", {})
        return delta.get("type") == "thinking_delta" and delta.get("THINKING")

    async def delete_conversation(self, conversation_id: str) -> None:
        """删除会话

        Args:
            conversation_id: 会话 ID

        Raises:
            Exception: 未设置组织 ID 或删除失败时抛出
        """
        if not self.org_id:
            raise Exception("未设置组织 ID")

        url = f"{self.BASE_URL}/organizations/{self.org_id}/chat_conversations/{conversation_id}"

        request_body = {"uuid": conversation_id}

        try:
            response = await self.session.delete(
                url,
                json=request_body,
                headers={"referer": f"https://claude.ai/chat/{conversation_id}"},
            )

            if response.status_code not in (200, 204):
                raise Exception(f"删除会话失败，状态码: {response.status_code}")

        except Exception as e:
            logging.error(f"删除会话失败: {e}")
            raise

    async def upload_file(self, file_data: List[str]) -> None:
        """上传文件到 Claude

        Args:
            file_data: 文件数据列表，格式为: data:image/jpeg;base64,/9j/4AA...
        """
        # TODO
        pass

    def set_big_context(self, context: str) -> None:
        """设置大型上下文

        Args:
            context: 上下文内容
        """
        self.request_attrs["attachments"] = [
            {
                "file_name": "context.txt",
                "file_type": "text/plain",
                "file_size": len(context),
                "extracted_content": context,
            }
        ]


async def new_client(session_key: str, proxy: str = "") -> ClaudeClient:
    """创建新的 Claude 客户端

    Args:
        session_key: Claude 会话密钥
        proxy: 代理服务器地址

    Returns:
        ClaudeClient: Claude 客户端实例
    """
    client = ClaudeClient(session_key, proxy)
    return client
