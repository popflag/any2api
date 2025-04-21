from pathlib import Path
from typing import List
from pydantic import BaseModel, field_validator
from pydantic import ConfigDict
import yaml


class Session(BaseModel):
    """会话配置模型"""

    session_key: str = ""
    org_id: str = ""


class ClaudeConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    """主配置模型"""
    sessions: List[Session] = []
    address: str
    api_key: str
    chat_delete: bool = False
    max_chat_history_length: int = 5000
    no_role_prefix: bool = False
    prompt_disable_artifacts: bool = False
    enable_mirror_api: bool = False
    mirror_api_prefix: str = ""

    # 分割address字段为host和port
    @field_validator("address")
    def validate_address(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("address必须包含端口号，格式示例：0.0.0.0:8080")
        host, port = v.split(":", 1)  # 新增拆分验证
        return f"{host}:{port}"


def load_config(config_path: str) -> ClaudeConfig:
    """加载并验证配置文件
    Args:
        config_path: 配置文件路径
    Returns:
        ClaudeConfig: 验证后的配置对象
    """
    raw_data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    return ClaudeConfig(**raw_data)
