#!/bin/sh
# 重启 TY Memory Agent 服务

# 获取脚本所在目录（ty_mem_agent目录）
SCRIPT_DIR=`dirname "$0"`
# 切换到ty_mem_agent目录
cd "$SCRIPT_DIR"

echo "🔄 重启 TY Memory Agent 服务..."

# 停止服务
./stop.sh

# 等待一下
sleep 2

# 启动服务
./start.sh
