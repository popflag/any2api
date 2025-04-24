from loguru import logger
import yaml
import threading
from pathlib import Path
import os
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class SessionInfo(BaseModel):
    """会话信息模型"""

    session_key: str
    org_id: str = ""


class SessionRange:
    """会话索引范围管理器"""

    def __init__(self):
        self.index = 0
        self.mutex = threading.Lock()

    def next_index(self, sessions_count: int) -> int:
        """获取下一个会话索引"""
        with self.mutex:
            index = self.index
            self.index = (index + 1) % sessions_count if sessions_count > 0 else 0
            return index


class ClaudeConfig(BaseModel):
    """Claude配置模型"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sessions: List[SessionInfo] = Field(default_factory=list)
    address: str = "0.0.0.0:8000"
    api_key: str = ""
    proxy: str = ""
    chat_delete: bool = True
    max_chat_history_length: int = 10000
    retry_count: int = 0
    no_role_prefix: bool = False
    prompt_disable_artifacts: bool = False

    @field_validator("address")
    def validate_address(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("address必须包含端口号，格式示例：0.0.0.0:8000")
        host, port = v.split(":", 1)
        return f"{host}:{port}"

    def get_session_for_model(self, idx: int) -> Optional[SessionInfo]:
        """获取指定索引的会话信息"""
        if not self.sessions or idx < 0 or idx >= len(self.sessions):
            return None
        return self.sessions[idx]

    def set_session_org_id(self, session_key: str, org_id: str) -> None:
        """设置指定会话的组织ID"""
        for i, session in enumerate(self.sessions):
            if session.session_key == session_key:
                print(f"Setting OrgID for session {session_key} to {org_id}")
                self.sessions[i].org_id = org_id
                return


def find_config_file() -> Optional[str]:
    """查找配置文件路径"""
    # 获取可执行文件目录和工作目录
    exec_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent
    work_dir = Path.cwd()

    # 检查可执行文件目录中的配置
    exe_config_path = exec_dir / "config.yaml"
    if exe_config_path.exists():
        return str(exe_config_path)

    # 检查工作目录中的配置
    work_config_path = work_dir / "config.yaml"
    if work_config_path.exists():
        return str(work_config_path)

    return None


def load_config_from_yaml(config_path: str) -> dict:
    """从YAML文件加载配置"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"从YAML加载配置失败: {e}")
        return {}


class Config:
    """全局配置单例类"""

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if Config._initialized:
            return

        self.config_model = None
        self.session_range = SessionRange()
        Config._initialized = False

    def initialize(self, config_path: str = "") -> ClaudeConfig:
        """初始化配置"""
        if Config._initialized:
            return self.config_model

        # 加载配置文件
        config_data = {}

        # 如果指定了配置文件路径，使用指定路径
        if config_path:
            config_data = load_config_from_yaml(config_path)
        else:
            # 自动查找配置文件
            found_path = find_config_file()
            if found_path:
                print(f"在 {found_path} 找到配置文件")
                config_data = load_config_from_yaml(found_path)

        # 创建配置模型
        self.config_model = ClaudeConfig(**config_data)

        # 如果没有设置重试次数，设置为会话数量，但不超过5
        if self.config_model.retry_count == 0 and self.config_model.sessions:
            self.config_model.retry_count = min(len(self.config_model.sessions), 5)

        # 打印配置信息
        self._log_config()

        Config._initialized = True
        return self.config_model

    def _log_config(self):
        """记录配置信息"""
        print("已加载配置:")
        print(f"最大重试次数: {self.config_model.retry_count}")
        for session in self.config_model.sessions:
            print(f"会话: {session.session_key}, 组织ID: {session.org_id}")
        print(f"地址: {self.config_model.address}")
        print(f"APIKey: {'已设置' if self.config_model.api_key else '未设置'}")
        print(f"代理: {self.config_model.proxy}")
        print(f"聊天删除: {self.config_model.chat_delete}")
        print(f"最大聊天历史长度: {self.config_model.max_chat_history_length}")
        print(f"无角色前缀: {self.config_model.no_role_prefix}")
        print(f"提示词禁用artifacts: {self.config_model.prompt_disable_artifacts}")

    def get_next_session(self) -> SessionInfo:
        """获取下一个会话信息"""
        if not self.config_model or not self.config_model.sessions:
            logger.error("config session 字段错误")
            raise ValueError("config session 字段错误")

        idx = self.session_range.next_index(len(self.config_model.sessions))
        return self.config_model.get_session_for_model(idx)

    @property
    def claude_config(self) -> ClaudeConfig:
        """获取Claude配置"""
        return self.config_model


# 导出便捷访问接口
def get_config() -> ClaudeConfig:
    """获取当前配置"""
    return Config().claude_config


def get_next_session() -> SessionInfo:
    """获取下一个会话信息"""
    return Config().get_next_session()


def initialize(config_path: str = "") -> ClaudeConfig:
    """初始化配置"""
    return Config().initialize(config_path)


# 初始化全局配置
initialize()
