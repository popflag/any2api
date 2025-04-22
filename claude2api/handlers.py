import logging
from fastapi import Request, Depends, HTTPException
from claude2api.config import get_config, get_next_session
from claude2api.auth import verify_token
from claude2api.pipeline import ChatRequest, pipeline
from claude2api.services import parse_and_validate_request
from claude2api.utils import return_openai_response

# 获取配置实例
config_instance = get_config()


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
    # 解析并验证请求，使用 services 中的函数
    try:
        chat_request: ChatRequest = await parse_and_validate_request(request)
    except HTTPException as e:
        # parse_and_validate_request 已经抛出了 HTTPException，直接返回其 detail
        return e.detail

    # 使用重试机制
    success = False  # 标记是否成功处理
    for i in range(config_instance.retry_count + 1):  # +1 是为了确保至少尝试一次
        session = get_next_session()

        if not session:
            logging.error(f"无法获取模型 {chat_request.model} 的会话")
            if i == config_instance.retry_count:  # 如果是最后一次尝试
                await return_openai_response(
                    "Error: 在多次尝试后无法获取可用会话", False, request
                )
                return  # 所有尝试失败
            logging.info("正在尝试另一个会话")
            continue  # 继续下一次重试

        logging.info(f"使用模型 {chat_request.model} 的会话: {session.session_key}")

        # 执行管道处理
        try:
            # 处理请求并生成响应流
            response_generator = pipeline.execute(chat_request, session)

            # 处理响应流并转发给客户端
            async for event in response_generator:
                # 检查客户端是否断开连接
                if await request.is_disconnected():
                    logging.warning("客户端断开连接")
                    # 客户端断开，停止处理并返回
                    return

                event_type = event.get("type")
                event_content = event.get("content", "")

                if event_type == "error":
                    logging.error(f"从 Claude 收到错误事件: {event_content}")
                    # 将错误信息发送给客户端
                    await return_openai_response(
                        f"Error: {event_content}", False, request
                    )
                    success = False  # 标记处理失败
                    break  # 收到错误，停止当前会话的处理，进入下一次重试

                elif event_type in ["text", "thinking"]:
                    # 将文本或思考内容发送给客户端
                    await return_openai_response(
                        event_content, chat_request.stream, request
                    )
                    success = True  # 标记至少发送了部分内容

                elif event_type == "done":
                    # 流结束信号
                    if chat_request.stream:
                        await return_openai_response(
                            "[DONE]", chat_request.stream, request
                        )
                    success = True  # 标记成功完成
                    break  # 正常结束循环

            if success:
                return

        except Exception as e:
            # 捕获管道执行过程中的意外异常
            logging.error(f"管道执行时出现意外异常: {e}")
            # 尝试向客户端发送错误
            try:
                await return_openai_response(
                    f"Error: 处理请求时发生内部错误: {type(e).__name__}", False, request
                )
            except Exception as send_error:
                logging.error(f"向客户端发送错误信息失败: {send_error}")
            success = False  # 标记处理失败
            # 继续下一次重试

    logging.error("所有重试都失败")
