import logging
import asyncio
from typing import List, Dict, Any, AsyncGenerator # 导入 AsyncGenerator
from fastapi import Request, HTTPException
from json.decoder import JSONDecodeError
from pydantic import ValidationError
from claude2api.config import SessionInfo, get_config
from claude2api.models import ChatCompletionRequest
from claude2api.core import ClaudeClient, new_client
# 导入用于返回 OpenAI 格式响应的工具函数
from claude2api.utils import return_openai_response

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
            logging.error(f"删除会话失败 (重试 {i+1}/{retry}): {e}")
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
) -> bool: # 返回值可以考虑改为 None 或移除，通过异常表示失败
    """处理聊天请求"""
    # 初始化 Claude 客户端
    claude_client = await new_client(session.session_key, config_instance.proxy)

    # 如果没有组织 ID，则获取
    if not session.org_id:
        try:
            org_id = await claude_client.get_org_id()
            session.org_id = org_id
            config_instance.set_session_org_id(session.session_key, session.org_id)
            logging.info(f"成功获取并设置组织 ID: {org_id}")
        except Exception as e:
            logging.error(f"获取组织 ID 失败: {e}")
            # 可以考虑直接抛出 HTTPException 或返回特定错误信息
            await return_openai_response(f"Error: 获取组织 ID 失败: {e}", False, request)
            return False # 指示处理失败

    claude_client.set_org_id(session.org_id)

    # 上传图片文件（如果有）
    if processor.img_data_list:
        try:
            await claude_client.upload_file(processor.img_data_list)
            logging.info(f"成功上传 {len(processor.img_data_list)} 个文件")
        except Exception as e:
            logging.error(f"上传文件失败: {e}")
            await return_openai_response(f"Error: 上传文件失败: {e}", False, request)
            return False

    # 处理大型上下文
    if len(processor.prompt) > config_instance.max_chat_history_length:
        try:
            claude_client.set_big_context(processor.prompt)
            processor.reset_for_big_context()
            logging.info(
                f"提示长度超过最大限制 ({config_instance.max_chat_history_length})，使用文件上下文"
            )
        except Exception as e:
             logging.error(f"设置大型上下文失败: {e}")
             await return_openai_response(f"Error: 设置大型上下文失败: {e}", False, request)
             return False


    conversation_id = None # 初始化 conversation_id
    message_sent_successfully = False # 标记是否至少成功发送了部分消息

    try:
        conversation_id = await claude_client.create_conversation(model)
        logging.info(f"成功创建会话: {conversation_id}")
    except Exception as e:
        logging.error(f"创建会话失败: {e}")
        await return_openai_response(f"Error: 创建会话失败: {e}", False, request)
        return False

    # 发送消息并处理响应流
    try:
        # 调用 send_message 时移除 request 参数
        message_generator: AsyncGenerator[Dict[str, Any], None] = claude_client.send_message(
            conversation_id, processor.prompt, stream
        )

        # 迭代处理生成器返回的事件
        async for event in message_generator:
            # 检查客户端是否断开连接
            if await request.is_disconnected():
                logging.warning(f"客户端在处理会话 {conversation_id} 时断开连接")
                # 如果客户端断开，需要确保清理任务仍然被调度（如果需要）
                if config_instance.chat_delete and conversation_id:
                     asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))
                return False # 指示处理因客户端断开而中断

            event_type = event.get("type")
            event_content = event.get("content", "")

            if event_type == "error":
                logging.error(f"从 Claude 收到错误事件: {event_content}")
                # 将错误信息发送给客户端
                # 错误通常不使用流式，即使 stream=True 也发送一次性错误响应
                await return_openai_response(f"Error: {event_content}", False, request)
                # 收到错误后，停止处理流
                message_sent_successfully = False # 标记处理失败
                break # 退出循环

            elif event_type in ["text", "thinking"]:
                # 将文本或思考内容发送给客户端
                await return_openai_response(event_content, stream, request)
                message_sent_successfully = True # 标记至少成功发送了一些内容

            elif event_type == "done":
                # 流结束信号
                if stream:
                    await return_openai_response("[DONE]", stream, request)
                message_sent_successfully = True # 标记成功完成
                break # 正常结束循环

        # 循环结束后，检查是否是正常完成 (收到 done 事件)
        # 如果循环因 break 以外的原因结束 (例如生成器耗尽但没有 done 事件)，
        # 或者 message_sent_successfully 仍为 False (例如只收到错误事件)
        if not message_sent_successfully:
             logging.warning(f"消息流处理完成，但未收到任何有效内容或完成信号。会话ID: {conversation_id}")
             # 可以选择发送一个空响应或错误，取决于期望的行为
             # await return_openai_response("Error: 未收到来自 Claude 的有效响应", False, request)
             # return False # 根据策略决定是否视为失败

    except Exception as e:
        logging.error(f"处理消息流时发生意外错误: {e}")
        # 尝试向客户端发送错误
        try:
            await return_openai_response(f"Error: 处理响应时发生内部错误: {e}", False, request)
        except Exception as send_error:
            logging.error(f"向客户端发送错误信息失败: {send_error}")
        # 即使发送消息失败，也尝试清理会话
        message_sent_successfully = False # 标记处理失败

    finally:
        # 无论成功或失败，如果启用了自动清理且会话已创建，则清理会话
        if config_instance.chat_delete and conversation_id:
            # 使用 create_task 调度清理，不阻塞当前函数返回
            asyncio.create_task(cleanup_conversation(claude_client, conversation_id, 3))
            logging.info(f"已调度会话 {conversation_id} 的清理任务")

    return message_sent_successfully # 返回是否成功处理了消息流（至少发送了部分内容并正常结束或收到错误）

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
        # 提取更友好的错误信息
        errors = ve.errors()
        error_detail = "; ".join([f"{e['loc'][0]}: {e['msg']}" for e in errors])
        raise HTTPException(
            status_code=400, detail={"error": f"请求验证失败: {error_detail}"}
        )
    except JSONDecodeError as je:
        # 捕获 JSON 解析错误
        logging.error(f"无效的 JSON 格式: {je}")
        raise HTTPException(status_code=400, detail={"error": "无效的 JSON 格式"})
    except Exception as e:
        # 捕获其他所有错误
        logging.error(f"请求处理错误: {e}")
        # 对于未知错误，返回通用错误信息
        raise HTTPException(status_code=500, detail={"error": f"处理请求时发生内部错误: {type(e).__name__}"})
