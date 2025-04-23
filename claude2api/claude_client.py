from loguru import logger
import json
import uuid
import base64
from typing import List, Dict, Any, AsyncGenerator
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.models import Response as curl_Response
from pydantic import BaseModel


class Organization(BaseModel):
    """组织信息模型"""

    id: int
    uuid: str
    name: str
    rate_limit_tier: str


class ClaudeClient:
    """Claude API 客户端，负责与 Claude AI 服务进行通信"""

    # Claude API 配置
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
        """初始化 Claude 客户端

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
            response: curl_Response = await self.session.get(
                url, headers={"referer": "https://claude.ai/new"}
            )

            if response.status_code != 200:
                raise Exception(f"获取组织 ID 失败，状态码: {response.status_code}")

            # 解析为具有明确结构的组织列表
            orgs_data: List[Dict[str, Any]] = response.json()

            if not orgs_data:
                raise Exception("未找到组织")

            # 转换为Organization对象列表
            orgs: List[Organization] = [
                Organization(
                    id=org.get("id", 0),
                    uuid=org.get("uuid", ""),
                    name=org.get("name", ""),
                    rate_limit_tier=org.get("rate_limit_tier", ""),
                )
                for org in orgs_data
            ]

            # 优先使用单一组织或默认组织
            if len(orgs) == 1:
                return orgs[0].uuid

            # 查找默认组织
            for org in orgs:
                if org.rate_limit_tier == "default_claude_ai":
                    return org.uuid

            raise Exception("未找到默认组织")

        except Exception as e:
            logger.error(f"获取组织 ID 失败: {e}")
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
            response: curl_Response = await self.session.post(
                url, json=request_body, headers={"referer": "https://claude.ai/new"}
            )

            if response.status_code != 201:
                raise Exception(f"创建会话失败，状态码: {response.status_code}")

            result: dict = response.json()
            conversation_id = result.get("uuid")

            if not conversation_id:
                raise Exception("响应中未找到会话 ID")

            return conversation_id

        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            raise

    async def send_message(
        self, conversation_id: str, message: str, stream: bool
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """发送消息到会话并产生事件流

        Args:
            conversation_id: 会话 ID
            message: 消息内容
            stream: 是否流式响应
        """
        if not self.org_id:
            # 直接抛出异常，因为这是客户端配置问题，不是流中的事件
            raise Exception("未设置组织 ID")

        url = f"{self.BASE_URL}/organizations/{self.org_id}/chat_conversations/{conversation_id}/completion"

        # 创建请求体
        request_body = self.request_attrs.copy()
        request_body["prompt"] = message

        response: curl_Response = await self.session.post(
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

        logger.info(f"Claude 响应状态码: {response.status_code}")

        # 在开始流式处理前检查初始状态码
        if response.status_code == 429:
            yield {"type": "error", "content": "Rate limit exceeded"}
            return  # 停止生成器
        elif response.status_code != 200:
            # TODO: 处理错误
            logger.error("请求出错")

        # 处理流式响应
        # 使用 async for 迭代 _handle_response 生成器并 yield 其结果
        async for event in self._handle_response(response, stream):
            yield event

    async def _handle_response(
        self, response: curl_Response, stream: bool
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理 Claude 的 SSE 响应，并产生事件流

        Args:
            response: curl_cffi 响应对象
            stream: 是否流式响应

        Yields:
            Dict[str, Any]: 包含事件类型和内容的字典
                - type: "text", "thinking", "error", "done"
                - content: 事件的具体内容 (文本、错误消息等)
        """
        # 跟踪完整响应文本（用于非流式模式）
        res_all_text = ""

        async for line in response.aiter_lines():
            # 确保line是字符串类型
            if isinstance(line, bytes):
                line = line.decode("utf-8")

            # 忽略非数据行
            if not line.startswith("data: "):
                continue

            data = line[6:]
            # 忽略空的 data 行
            if not data:
                continue

            try:
                event = json.loads(data)

                # 处理错误事件
                if self._is_error_event(event):
                    error_message = event["error"]["message"]
                    yield {"type": "error", "content": error_message}  # Yield 错误事件
                    return  # 发生错误后停止处理

                # 处理文本增量
                if self._is_text_delta(event):
                    res_text = event["delta"]["text"]

                    res_all_text += res_text
                    if stream:
                        yield {"type": "text", "content": res_text}  # Yield 文本事件
                    continue

                # 处理思考增量
                if self._is_thinking_delta(event):
                    res_text = event["delta"]["THINKING"]

                    res_all_text += res_text
                    if stream:
                        yield {
                            "type": "thinking",
                            "content": res_text,
                        }  # Yield 思考事件
                    continue

                # 处理其他可能的事件类型，例如 completion
                if event.get("type") == "completion":
                    # 这是一个结束事件，但我们使用自定义的 "done" 事件来标记流的结束
                    pass  # 忽略 Claude 的 completion 事件，等待流结束

            except json.JSONDecodeError:
                logger.warning(f"解析 SSE 事件失败: {data}")
                continue  # 继续处理下一行

        # 处理非流式响应或发送结束标记
        if not stream:
            yield {"type": "text", "content": res_all_text}  # Yield 完整文本
        yield {"type": "done"}  # Yield 完成事件

    def _is_error_event(self, event: Dict[str, Any]) -> bool:
        """检查是否为错误事件"""
        return (
            event.get("type") == "error"
            and event.get("error", {}).get("message") is not None
        )

    def _is_text_delta(self, event: Dict[str, Any]) -> bool:
        """检查是否为文本增量事件"""
        delta = event.get("delta", {})
        return delta.get("type") == "text_delta" and delta.get("text") is not None

    def _is_thinking_delta(self, event: Dict[str, Any]) -> bool:
        """检查是否为思考增量事件"""
        delta = event.get("delta", {})
        return (
            delta.get("type") == "thinking_delta" and delta.get("THINKING") is not None
        )

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
                # 尝试读取错误信息
                error_text = await response.text()
                raise Exception(
                    f"删除会话失败，状态码: {response.status_code}, 响应: {error_text}"
                )

        except Exception as e:
            logger.error(f"删除会话失败: {e}")
            raise

    async def upload_file(self, file_data: List[str]) -> None:
        """上传文件到 Claude

        Args:
            file_data: 文件数据列表，格式为: data:image/jpeg;base64,/9j/4AA...

        Raises:
            Exception: 当组织ID未设置、文件数据为空、数据格式无效或上传失败时抛出
        """
        if not self.org_id:
            raise Exception("未设置组织 ID")

        if not file_data:
            # 文件数据为空不应抛出异常，只是没有文件需要上传
            logger.info("没有文件数据需要上传")
            return

        # 确保files数组已初始化
        if "files" not in self.request_attrs:
            self.request_attrs["files"] = []

        # 处理每个文件
        for fd in file_data:
            if not fd:
                continue  # 跳过空条目

            # 解析base64数据
            parts = fd.split(",", 1)
            if len(parts) != 2:
                raise Exception(f"文件数据格式无效: {fd[:50]}...")  # 避免打印整个数据

            # 从数据URI获取内容类型
            meta_parts = parts[0].split(":", 1)
            if len(meta_parts) != 2:
                raise Exception(f"文件数据中的内容类型无效: {parts[0]}")

            meta_info = meta_parts[1].split(";", 1)
            if len(meta_info) != 2 or meta_info[1] != "base64":
                raise Exception(f"文件数据中的编码无效: {meta_parts[1]}")

            content_type = meta_info[0]

            # 解码base64数据
            try:
                file_bytes = base64.b64decode(parts[1])
            except Exception as e:
                raise Exception(f"解码base64数据失败: {e}")

            # 根据内容类型确定文件名
            filename = "file"
            if content_type == "image/jpeg":
                filename = "image.jpg"
            elif content_type == "image/png":
                filename = "image.png"
            elif content_type == "application/pdf":
                filename = "document.pdf"
            # 可以根据需要添加更多文件类型

            # 创建上传URL
            url = f"{self.BASE_URL}/organizations/{self.org_id}/upload"

            try:
                # 创建multipart/form-data请求
                form_data = {"file": (filename, file_bytes, content_type)}

                response: curl_Response = await self.session.post(
                    url,
                    files=form_data,
                    headers={
                        "referer": "https://claude.ai/new",
                        "anthropic-client-platform": "web_claude_ai",
                    },
                )

                if response.status_code != 200:
                    raise Exception(
                        f"上传失败，状态码: {response.status_code}，响应: {response.text}"
                    )

                # 解析响应
                result: dict = response.json()
                file_uuid: str = result.get("file_uuid", "")

                if not file_uuid:
                    raise Exception("响应中未找到文件UUID")

                # 将文件添加到默认属性
                # 确保 self.request_attrs["files"] 是列表
                if "files" not in self.request_attrs or not isinstance(
                    self.request_attrs["files"], list
                ):
                    self.request_attrs["files"] = []
                self.request_attrs["files"].append(file_uuid)  # type: ignore
                logger.info(
                    f"文件 {filename} ({content_type}) 上传成功，UUID: {file_uuid}"
                )

            except Exception as e:
                logger.error(f"上传文件失败: {e}")
                raise

    def set_big_context(self, context: str) -> None:
        """设置大型上下文

        Args:
            context: 上下文内容
        """
        # 确保 attachments 数组已初始化
        if "attachments" not in self.request_attrs or not isinstance(
            self.request_attrs["attachments"], list
        ):
            self.request_attrs["attachments"] = []

        self.request_attrs["attachments"].append(  # type: ignore
            {
                "file_name": "context.txt",
                "file_type": "text/plain",
                "file_size": len(context),
                "extracted_content": context,
            }
        )
        logger.info("大型上下文已添加到请求属性中")


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
