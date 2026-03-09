#!/bin/bash
# MCP Server 启动脚本

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../.."

# 检查虚拟环境
if [ -d "venv" ]; then
    echo "激活虚拟环境..."
    source venv/bin/activate
elif [ -d ".venv" ]; then
    echo "激活虚拟环境..."
    source .venv/bin/activate
fi

# 检查Tushare Token
if [ -z "$TUSHARE_API_TOKEN" ]; then
    echo "⚠️ 警告: TUSHARE_API_TOKEN 环境变量未设置"
    echo "请设置环境变量:"
    echo "export TUSHARE_API_TOKEN=your_token_here"
    echo ""
    echo "从 https://tushare.pro/register 获取免费Token"
    echo ""
    echo "是否继续? (y/n)"
    read -r response
    if [ "$response" != "y" ]; then
        exit 1
    fi
fi

# 启动MCP Server
echo "🚀 启动 Financial MCP Server..."
python -m app.mcp_server.server
