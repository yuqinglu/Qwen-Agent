#!/bin/bash
# Docker 方式停止 TY Memory Agent 服务

set -e

echo "🛑 停止 TY Memory Agent 服务..."

# 检查容器是否在运行
if ! docker ps | grep -q ty-memory-agent; then
    echo "⚠️  服务未在运行"
    exit 0
fi

# 停止服务
docker-compose down

echo "✅ 服务已停止"

# 清理 PID 文件（如果存在）
if [ -f "ty_memory_agent.pid" ]; then
    echo "🧹 清理 PID 文件..."
    rm -f ty_memory_agent.pid
fi

