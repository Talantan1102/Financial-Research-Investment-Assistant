"""
MCP Server 配置模块

管理MCP Server和Tushare数据源的配置
"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


logger = logging.getLogger(__name__)


@dataclass
class TushareConfig:
    """Tushare数据源配置"""
    api_token: str
    cache_ttl_seconds: int = 300  # 默认5分钟缓存
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    timeout_seconds: int = 30
    
    @classmethod
    def from_env(cls) -> "TushareConfig":
        """从环境变量加载配置"""
        api_token = os.getenv("TUSHARE_API_TOKEN", "")
        
        if not api_token:
            logger.warning("TUSHARE_API_TOKEN not set in environment variables")
        
        return cls(
            api_token=api_token,
            cache_ttl_seconds=int(os.getenv("TUSHARE_CACHE_TTL", "300")),
            max_retries=int(os.getenv("TUSHARE_MAX_RETRIES", "3")),
            retry_delay_seconds=float(os.getenv("TUSHARE_RETRY_DELAY", "1.0")),
            timeout_seconds=int(os.getenv("TUSHARE_TIMEOUT", "30"))
        )
    
    def is_valid(self) -> bool:
        """检查配置是否有效"""
        return bool(self.api_token)


@dataclass
class MCPServerConfig:
    """MCP Server配置"""
    name: str = "financial-research-assistant"
    version: str = "1.0.0"
    transport: str = "stdio"  # 支持 stdio, sse, websocket
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    enable_cors: bool = True
    
    @classmethod
    def from_env(cls) -> "MCPServerConfig":
        """从环境变量加载配置"""
        return cls(
            name=os.getenv("MCP_SERVER_NAME", "financial-research-assistant"),
            version=os.getenv("MCP_SERVER_VERSION", "1.0.0"),
            transport=os.getenv("MCP_TRANSPORT", "stdio"),
            host=os.getenv("MCP_HOST", "0.0.0.0"),
            port=int(os.getenv("MCP_PORT", "8000")),
            log_level=os.getenv("MCP_LOG_LEVEL", "INFO"),
            enable_cors=os.getenv("MCP_ENABLE_CORS", "true").lower() == "true"
        )


@dataclass
class Config:
    """全局配置"""
    tushare: TushareConfig = field(default_factory=TushareConfig.from_env)
    mcp_server: MCPServerConfig = field(default_factory=MCPServerConfig.from_env)
    
    # 其他数据源配置（可扩展）
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    
    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量加载完整配置"""
        return cls(
            tushare=TushareConfig.from_env(),
            mcp_server=MCPServerConfig.from_env(),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            database_url=os.getenv("DATABASE_URL", "")
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "tushare": {
                "api_token_configured": bool(self.tushare.api_token),
                "cache_ttl_seconds": self.tushare.cache_ttl_seconds,
                "max_retries": self.tushare.max_retries,
                "timeout_seconds": self.tushare.timeout_seconds
            },
            "mcp_server": {
                "name": self.mcp_server.name,
                "version": self.mcp_server.version,
                "transport": self.mcp_server.transport,
                "host": self.mcp_server.host,
                "port": self.mcp_server.port,
                "log_level": self.mcp_server.log_level
            },
            "redis_url_configured": bool(self.redis_url),
            "database_url_configured": bool(self.database_url)
        }


# 全局配置实例
_config: Optional[Config] = None


def get_config() -> Config:
    """
    获取全局配置实例（单例）
    
    Returns:
        全局配置
    """
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def reload_config() -> Config:
    """
    重新加载配置
    
    Returns:
        新的配置实例
    """
    global _config
    _config = Config.from_env()
    logger.info("Configuration reloaded")
    return _config
