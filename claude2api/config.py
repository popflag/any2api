import os
import yaml
from pathlib import Path
from typing import List, Optional
import random
import threading
from pydantic import BaseModel, field_validator, ConfigDict


class SessionInfo(BaseModel):
    """会话信息模型"""

    session_key: str
    org_id: str = ""


class SessionRange:
    """会话索引范围管理器"""

    def __init__(self):
        self.index = 0
        self.mutex = threading.Lock()

    def next_index(self, sessions_count):
        """获取下一个会话索引"""
        with self.mutex:
            index = self.index
            self.index = (index + 1) % sessions_count if sessions_count > 0 else 0
            return index


class ClaudeConfig(BaseModel):
    """Claude配置模型"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    sessions: List[SessionInfo] = []
    address: str = "0.0.0.0:8080"  # 默认值
    api_key: str = ""
    proxy: str = ""
    chat_delete: bool = True
    max_chat_history_length: int = 10000
    retry_count: int = 0
    no_role_prefix: bool = False
    prompt_disable_artifacts: bool = False

    # 分割address字段为host和port的验证器
    @field_validator("address")
    def validate_address(cls, v: str) -> str:
        if ":" not in v:
            raise ValueError("address必须包含端口号，格式示例：0.0.0.0:8080")
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
                print(f"设置会话 {session_key} 的组织ID为 {org_id}")
                self.sessions[i].org_id = org_id
                return


def parse_session_env(env_value: str) -> tuple[int, List[SessionInfo]]:
    """解析SESSION格式的环境变量"""
    if not env_value:
        return 0, []

    sessions = []
    session_pairs = env_value.split(",")
    retry_count = len(session_pairs)  # 重试次数等于会话数量

    for pair in session_pairs:
        if not pair:
            retry_count -= 1
            continue

        parts = pair.split(":")
        session = SessionInfo(session_key=parts[0])

        if len(parts) > 1:
            session.org_id = parts[1]

        sessions.append(session)

    # 限制最大重试次数为5次
    if retry_count > 5:
        retry_count = 5

    return retry_count, sessions


def config_file_exists() -> tuple[bool, str]:
    """检查配置文件是否存在"""
    # 获取可执行文件目录和工作目录
    exec_dir = Path(os.path.dirname(os.path.abspath(__file__))).parent
    work_dir = Path.cwd()

    exe_config_path = exec_dir / "config.yaml"
    if exe_config_path.exists():
        return True, str(exe_config_path)

    work_config_path = work_dir / "config.yaml"
    if work_config_path.exists():
        return True, str(work_config_path)

    return False, ""


def load_config_from_yaml(config_path: str) -> ClaudeConfig:
    """从YAML文件加载配置"""
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        config = ClaudeConfig(**data)
        print("成功从YAML文件加载配置")
        return config
    except Exception as e:
        print(f"从YAML加载配置失败: {e}")
        return None


def load_config_from_env() -> ClaudeConfig:
    """从环境变量加载配置"""
    try:
        max_chat_history_length = int(os.getenv("MAX_CHAT_HISTORY_LENGTH", "10000"))
    except ValueError:
        max_chat_history_length = 10000

    # 解析SESSIONS环境变量
    retry_count, sessions = parse_session_env(os.getenv("SESSIONS", ""))

    config = ClaudeConfig(
        sessions=sessions,
        address=os.getenv("ADDRESS", "0.0.0.0:8080"),
        api_key=os.getenv("APIKEY", ""),
        proxy=os.getenv("PROXY", ""),
        chat_delete=os.getenv("CHAT_DELETE", "true").lower() != "false",
        max_chat_history_length=max_chat_history_length,
        retry_count=retry_count,
        no_role_prefix=os.getenv("NO_ROLE_PREFIX", "").lower() == "true",
        prompt_disable_artifacts=os.getenv("PROMPT_DISABLE_ARTIFACTS", "").lower()
        == "true",
    )

    return config


def load_config(config_path: str = None) -> ClaudeConfig:
    """加载配置，优先从配置文件加载，失败则从环境变量加载"""
    # 如果指定了配置文件路径
    if config_path:
        config = load_config_from_yaml(config_path)
        if config:
            return config

    # 检查默认配置文件是否存在
    exists, path = config_file_exists()
    if exists:
        print(f"在 {path} 找到配置文件")
        config = load_config_from_yaml(path)
        if config:
            return config
        print("从YAML加载配置失败，回退到环境变量")

    # 从环境变量加载
    print("从环境变量加载配置")
    return load_config_from_env()


# 全局配置实例和会话范围管理器
config_instance = None
session_range = SessionRange()


# 初始化配置
def init_config():
    global config_instance
    random.seed()  # 初始化随机数种子
    config_instance = load_config()

    # 打印配置信息
    print("已加载配置:")
    print(f"最大重试次数: {config_instance.retry_count}")
    for session in config_instance.sessions:
        print(f"会话: {session.session_key}, 组织ID: {session.org_id}")
    print(f"地址: {config_instance.address}")
    print(f"APIKey: {config_instance.api_key}")
    print(f"代理: {config_instance.proxy}")
    print(f"聊天删除: {config_instance.chat_delete}")
    print(f"最大聊天历史长度: {config_instance.max_chat_history_length}")
    print(f"无角色前缀: {config_instance.no_role_prefix}")
    print(f"提示词禁用artifacts: {config_instance.prompt_disable_artifacts}")

    return config_instance


# 初始化全局配置
init_config()
