import os
import yaml
import random
import threading
from pathlib import Path
from typing import List, Optional, Tuple
from abc import ABC, abstractmethod
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
    address: str = "0.0.0.0:8080"
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


class ConfigLoader(ABC):
    """配置加载器抽象基类"""
    
    @abstractmethod
    def load(self) -> dict:
        """加载配置并返回字典"""
        pass


class YamlConfigLoader(ConfigLoader):
    """YAML文件配置加载器"""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
    
    def load(self) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"从YAML加载配置失败: {e}")
            return {}


class EnvConfigLoader(ConfigLoader):
    """环境变量配置加载器"""
    
    def load(self) -> dict:
        try:
            max_chat_history_length = int(os.getenv("MAX_CHAT_HISTORY_LENGTH", "10000"))
        except ValueError:
            max_chat_history_length = 10000
        
        # 解析SESSIONS环境变量
        retry_count, sessions = self._parse_session_env(os.getenv("SESSIONS", ""))
        
        return {
            "sessions": sessions,
            "address": os.getenv("ADDRESS", "0.0.0.0:8080"),
            "api_key": os.getenv("APIKEY", ""),
            "proxy": os.getenv("PROXY", ""),
            "chat_delete": os.getenv("CHAT_DELETE", "true").lower() != "false",
            "max_chat_history_length": max_chat_history_length,
            "retry_count": retry_count,
            "no_role_prefix": os.getenv("NO_ROLE_PREFIX", "").lower() == "true",
            "prompt_disable_artifacts": os.getenv("PROMPT_DISABLE_ARTIFACTS", "").lower() == "true",
        }
    
    def _parse_session_env(self, env_value: str) -> Tuple[int, List[SessionInfo]]:
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


def config_file_exists() -> Tuple[bool, str]:
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
            
        random.seed()  # 初始化随机数种子
        
        # 确定配置加载顺序
        loaders: List[ConfigLoader] = []
        
        # 1. 如果指定了配置文件路径
        if config_path:
            loaders.append(YamlConfigLoader(config_path))
        
        # 2. 检查默认配置文件
        exists, path = config_file_exists()
        if exists:
            print(f"在 {path} 找到配置文件")
            loaders.append(YamlConfigLoader(path))
        
        # 3. 最后使用环境变量
        loaders.append(EnvConfigLoader())
        
        # 尝试按顺序加载
        config_data = {}
        for loader in loaders:
            data = loader.load()
            if data:
                config_data = data
                break
        
        # 创建配置模型
        self.config_model = ClaudeConfig(**config_data)
        
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
    
    def get_next_session(self) -> Optional[SessionInfo]:
        """获取下一个会话信息"""
        if not self.config_model or not self.config_model.sessions:
            return None
        
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

def get_next_session() -> Optional[SessionInfo]:
    """获取下一个会话信息"""
    return Config().get_next_session()

def initialize(config_path: str = "") -> ClaudeConfig:
    """初始化配置"""
    return Config().initialize(config_path)


# 初始化全局配置
initialize()
