# Copyright © 2026 深圳市深维智见教育科技有限公司 版权所有
# 未经授权，禁止转售或仿制。

"""MCP Server 配置管理"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class MCPServerConfig(BaseSettings):
    """
    MCP Server 配置类
    
    支持从环境变量读取配置，环境变量前缀为 MCP_
    """
    
    # Server 基础配置
    server_name: str = Field(default="financial-research-mcp-server", description="MCP Server 名称")
    server_version: str = Field(default="1.0.0", description="MCP Server 版本")
    
    # Tushare API 配置
    tushare_api_token: Optional[str] = Field(default=None, description="Tushare API Token")
    
    # 缓存配置
    cache_ttl: int = Field(default=300, description="缓存过期时间（秒）")
    
    # 日志配置
    log_level: str = Field(default="INFO", description="日志级别")
    
    class Config:
        env_prefix = "MCP_"
        case_sensitive = False
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 如果环境变量存在，优先使用环境变量
        if not self.tushare_api_token:
            self.tushare_api_token = os.getenv("TUSHARE_API_TOKEN")


# 全局配置实例
_config: Optional[MCPServerConfig] = None


def get_config() -> MCPServerConfig:
    """
    获取 MCP Server 配置（单例）
    
    Returns:
        MCPServerConfig 配置实例
    """
    global _config
    if _config is None:
        _config = MCPServerConfig()
    return _config


# 向后兼容别名
Config = MCPServerConfig


def reload_config() -> MCPServerConfig:
    """
    重新加载配置
    
    Returns:
        新的 MCPServerConfig 实例
    """
    global _config
    _config = MCPServerConfig()
    return _config
