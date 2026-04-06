#!/bin/bash
# 服务器部署脚本

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 开始部署 TY Memory Agent..."

# 安装依赖
echo "📦 安装项目依赖..."
poetry install --all-extras

# 创建必要的目录
echo "📁 创建必要目录..."
mkdir -p ty_mem_agent/data
mkdir -p ty_mem_agent/logs

# 设置权限
chmod +x ty_mem_agent/start.sh
chmod +x ty_mem_agent/stop.sh
chmod +x ty_mem_agent/restart.sh

echo "✅ 部署完成！"
echo ""
echo "启动服务: ./ty_mem_agent/start.sh"
echo "停止服务: ./ty_mem_agent/stop.sh"
echo "重启服务: ./ty_mem_agent/restart.sh"
echo "查看日志: tail -f ty_mem_agent/logs/ty_mem_agent.log"
