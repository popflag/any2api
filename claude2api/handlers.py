import logging
from fastapi import Request, Depends, HTTPException
from claude2api.config import get_config, get_next_session
from claude2api.auth import verify_token
from claude2api.services import (
    ChatRequestProcessor,
    parse_and_validate_request,
    handle_chat_request,
)


# 初始化请求处理器实例
processor = ChatRequestProcessor()


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
    # 解析并验证请求
    try:
        req = await parse_and_validate_request(request)
    except HTTPException as e:
        return e.detail

    # 获取模型名称
    model = req.model

    # 获取配置实例
    config_instance = get_config()

    # 使用重试机制
    for i in range(config_instance.retry_count + 1):  # +1 是为了确保至少尝试一次
        session = get_next_session()

        if not session:
            logging.error(f"无法获取模型 {model} 的会话")
            logging.info("正在尝试另一个会话")
            continue

        logging.info(f"使用模型 {model} 的会话: {session.session_key}")

        # 处理消息
        processor.process_messages(req.messages)

        # 如果是重试，重置处理器
        if i > 0:
            processor.reset()
            processor.prompt = processor.root_prompt

        # 初始化客户端并处理请求
        success = await handle_chat_request(
            request, session, model, processor, req.stream
        )
        if success:
            # 这里应该根据实际情况返回响应
            # 假设 handle_chat_request 在内部使用了 return_openai_response
            return  # return_openai_response is called inside handle_chat_request

        # 如果到这里，请求失败 - 使用另一个会话重试
        logging.info("正在尝试另一个会话")

    # 所有重试都失败
    logging.error("所有重试都失败")
    return {"error": "在多次尝试后无法处理请求"}
