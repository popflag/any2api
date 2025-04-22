from loguru import logger
from fastapi import Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from claude2api.config import get_config, get_next_session
from claude2api.auth import verify_token
from claude2api.models import (
    ChatCompletionRequest,
    OpenAIStreamResponse,
    StreamChoice,
    Delta
)
from claude2api.pipeline import pipeline
from claude2api.utils import return_openai_response  # 仍然需要用于非流式响应

# 获取配置实例
config_instance = get_config()


async def parse_and_validate_request(request: Request) -> ChatCompletionRequest:
    """
    解析并验证聊天完成请求
    """
    # 获取请求体数据
    try:
        json_data = await request.json()

        # 使用 pydantic 模型验证并更新请求
        chat_completion_request = ChatCompletionRequest(**json_data)
    except Exception as e:
        logger.error(f"无效的请求格式: {e}")
        raise HTTPException(status_code=400, detail=f"无效的请求: {str(e)}")

    # 验证是否提供了消息
    if not chat_completion_request.messages:
        logger.error("未提供消息")
        raise HTTPException(status_code=400, detail="未提供消息")

    return chat_completion_request


async def health_check_handler(request: Request):
    """健康检查处理函数"""
    return {"status": "ok"}


async def modules_handler(authorized: bool = Depends(verify_token)):
    """获取可用模型处理函数"""
    models = [
        {"id": "claude-3-7-sonnet-20250219"},
        {"id": "claude-3-7-sonnet-20250219-think"},
    ]
    return {"data": models}


async def chat_completions_handler(
    request: Request, authorized: bool = Depends(verify_token)
):
    """处理聊天完成请求"""
    # 验证请求
    chat_request: ChatCompletionRequest = await parse_and_validate_request(request)

    # 使用重试机制
    success = False  # 标记是否成功处理
    for i in range(config_instance.retry_count + 1):  # +1 是为了确保至少尝试一次
        session = get_next_session()

        if not session:
            logger.error(f"无法获取模型 {chat_request.model} 的会话")
            if i == config_instance.retry_count:  # 如果是最后一次尝试
                raise HTTPException(
                    status_code=500, detail="在多次尝试后无法获取可用会话"
                )
            logger.info("正在尝试另一个会话")
            continue  # 继续下一次重试

        logger.info(f"使用模型 {chat_request.model} 的会话: {session.session_key}")

        # 处理请求并生成响应流
        response_generator = pipeline.execute(chat_request, session)

        # 如果是流式响应，直接返回StreamingResponse
        if chat_request.stream:

            async def generate():
                async for event in response_generator:
                    # 检查客户端是否断开连接
                    if await request.is_disconnected():
                        logger.warning("客户端断开连接")
                        # 客户端断开，停止生成
                        break  # 使用 break 退出生成器循环

                    event_type = event.get("type")
                    event_content = event.get("content", "")

                    if event_type == "error":
                        logger.error(f"从 Claude 收到错误事件: {event_content}")
                        # 收到错误，停止当前会话的处理，进入下一次重试
                        # 这里不直接raise HTTPException，而是让外层循环处理重试
                        # 可以考虑发送一个错误标记给客户端，或者直接断开流
                        # 为了简化，这里直接break，依赖外层重试
                        break

                    elif event_type in ["text", "thinking"]:
                        # 创建SSE格式的响应
                        resp = OpenAIStreamResponse(
                            choices=[
                                StreamChoice(
                                    index=0, delta=Delta(content=event_content)
                                )
                            ]
                        )
                        json_data = resp.model_dump_json()
                        logger.debug(f"输出流式数据: {json_data}")
                        yield f"data: {json_data}\n\n"

                    elif event_type == "done":
                        # 发送结束标记
                        logger.debug("发送流结束标记 [DONE]")
                        yield "data: [DONE]\n\n"
                        success = True  # 标记成功完成
                        break  # 正常结束循环

                # 如果循环因错误或客户端断开而中断，确保不会标记成功
                # success 变量在外层循环中判断

            # 直接返回 StreamingResponse
            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",  # 禁用Nginx等代理的缓冲
                },
            )
        else:
            # 非流式响应，收集完整文本
            full_text = ""
            async for event in response_generator:
                event_type = event.get("type")
                event_content = event.get("content", "")

                if event_type == "error":
                    logger.error(f"从 Claude 收到错误事件: {event_content}")
                    success = False  # 标记处理失败
                    break  # 收到错误，停止当前会话的处理，进入下一次重试

                elif event_type in ["text", "thinking"]:
                    full_text += event_content

                elif event_type == "done":
                    success = True  # 标记成功完成
                    break  # 正常结束循环

            if success:
                # 返回完整响应
                return await return_openai_response(full_text, False, request)

        # 如果当前会话处理失败 (success is False)，外层循环会尝试下一个会话

    # 所有重试都失败
    logger.error("所有重试都失败")
    raise HTTPException(status_code=500, detail="处理请求失败")
