#!/bin/bash
# Docker 方式重启 TY Memory Agent 服务

set -e

echo "🔄 重启 TY Memory Agent 服务..."

# 停止服务
./docker-stop.sh

# 等待一下
sleep 2

# 启动服务
./docker-start.sh

