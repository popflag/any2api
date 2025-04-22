import logging
from fastapi import Request, HTTPException
from json.decoder import JSONDecodeError
from pydantic import ValidationError
from claude2api.config import get_config
from claude2api.pipeline import ChatRequest


config_instance = get_config()


async def parse_and_validate_request(request: Request) -> ChatRequest:
    """解析并验证请求"""
    try:
        # 从请求体中提取 JSON 数据
        json_data = await request.json()

        # 使用 Pydantic 模型直接验证和解析请求数据
        # 使用从 pipeline 导入的 ChatRequest 模型
        req = ChatRequest(**json_data)

        # 验证消息
        if not req.messages:
            raise HTTPException(status_code=400, detail={"error": "未提供消息"})

        return req
    except ValidationError as ve:
        # 捕获 Pydantic 验证错误并返回详细信息
        logging.error(f"请求验证失败: {ve}")
        # 提取更友好的错误信息
        errors = ve.errors()
        # 确保 loc 是可迭代的，并且至少有一个元素
        error_detail = "; ".join(
            [f"{e['loc'][0] if e['loc'] else 'unknown'}: {e['msg']}" for e in errors]
        )
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
        raise HTTPException(
            status_code=500,
            detail={"error": f"处理请求时发生内部错误: {type(e).__name__}"},
        )
