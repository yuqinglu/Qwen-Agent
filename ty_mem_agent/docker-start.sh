#!/bin/bash
# Docker 方式启动 TY Memory Agent 服务

set -e

echo "🐳 使用 Docker 启动 TY Memory Agent 服务..."

# 检查 .env 文件是否存在
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 文件"
    echo "📝 正在从 .env.example 创建 .env 文件..."
    cp .env.example .env
    echo "⚠️  请编辑 .env 文件并填写必要的配置"
    echo "   vim .env"
    exit 1
fi

# 检查是否已经在运行
if docker ps | grep -q ty-memory-agent; then
    echo "⚠️  服务已在运行"
    echo "如需重启，请先运行: ./docker-stop.sh"
    exit 1
fi

# 构建镜像
echo "🔨 构建 Docker 镜像..."
docker-compose build

# 启动服务
echo "🚀 启动服务..."
docker-compose up -d

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 5

# 检查服务状态
if docker ps | grep -q ty-memory-agent; then
    echo "✅ 服务启动成功"
    echo "📊 服务状态: http://localhost:10081/health"
    echo "💬 聊天页面: http://localhost:10081/chat/demo"
    echo "📝 待办管理: http://localhost:10081/todos"
    echo ""
    echo "📋 查看日志: docker-compose logs -f"
    echo "🔍 查看状态: docker-compose ps"
else
    echo "❌ 服务启动失败"
    echo "📋 查看日志: docker-compose logs"
    exit 1
fi

