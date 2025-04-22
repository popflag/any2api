from fastapi import Request
from fastapi.responses import StreamingResponse
from claude2api.models import (
    Delta,
    StreamChoice,
    OpenAIStreamResponse,
    NoStreamChoice,
    Message,
    OpenAIResponse,
    Usage,
)


async def return_openai_response(text: str, stream: bool, request: Request):
    """生成 OpenAI 格式的响应"""
    if stream:
        return await stream_response(text, request)
    else:
        return await no_stream_response(text)


async def stream_response(text: str, request: Request):
    """生成流式响应"""
    async def generate():
        yield formatted_data
    
    # 检查是否为结束标记
    if text == "[DONE]":
        async def generate():
            yield "data: [DONE]\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")

    # 创建流式响应对象
    resp = OpenAIStreamResponse(
        choices=[StreamChoice(index=0, delta=Delta(content=text))]
    )

    # 转换为 JSON
    json_data = resp.model_dump_json()

    # 添加 SSE 格式
    formatted_data = f"data: {json_data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def no_stream_response(text: str):
    """生成非流式响应"""
    resp = OpenAIResponse(
        choices=[
            NoStreamChoice(index=0, message=Message(role="assistant", content=text))
        ],
        usage=Usage(),
    )

    return resp
