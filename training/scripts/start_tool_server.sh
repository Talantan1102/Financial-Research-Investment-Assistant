#!/usr/bin/env bash
# 启动 verl-tool 的 tool server
#
# 对接方式：verl-tool 的 mcp_interface 工具 → MCP gateway → 你的 sandbox
#
# 前置条件：
#   1. pip install verl-tool
#   2. sandbox 已启动: ./start_sandbox_server.sh --config configs/sandbox-server/finance_research_config.json
#
# 用法：
#   bash training/scripts/start_tool_server.sh [--port 5005]

set -euo pipefail

cd "$(dirname "$0")/../.."

PORT="${1:-5005}"
WORKERS_PER_TOOL="${WORKERS_PER_TOOL:-4}"
SANDBOX_URL="${SANDBOX_URL:-http://127.0.0.1:18890}"

# ── 1. 检查 sandbox ─────────────────────────────────────────────
if ! curl -s "${SANDBOX_URL}/health" > /dev/null 2>&1; then
    echo "Sandbox 未启动，请先执行："
    echo "  ./start_sandbox_server.sh --config configs/sandbox-server/finance_research_config.json"
    exit 1
fi
echo "Sandbox OK: ${SANDBOX_URL}"

# ── 2. 生成 MCP server_list.json（指向你的 sandbox）──────────────
MCP_CONFIG_DIR="/tmp/verl-tool-mcp-config"
mkdir -p "$MCP_CONFIG_DIR"

cat > "${MCP_CONFIG_DIR}/server_list.json" << EOF
{
  "servers": [
    {
      "name": "unified_finance",
      "type": "http",
      "url": "${SANDBOX_URL}",
      "description": "Financial research MCP sandbox"
    }
  ]
}
EOF

echo "MCP config: ${MCP_CONFIG_DIR}/server_list.json"

# ── 3. 启动 tool server ─────────────────────────────────────────
echo "=============================================="
echo "Starting verl-tool server on port ${PORT}"
echo "  tool_type: mcp_interface,finish"
echo "  workers_per_tool: ${WORKERS_PER_TOOL}"
echo "=============================================="

python -m verl_tool.servers.tool_server \
    --tool_type "mcp_interface,finish" \
    --host "127.0.0.1" \
    --port "${PORT}" \
    --workers_per_tool "${WORKERS_PER_TOOL}" \
    --mcp_config_path "${MCP_CONFIG_DIR}/server_list.json"
