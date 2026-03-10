#!/bin/bash
# Docker 启动脚本 - 自动创建容器专用目录并启动

set -e

echo "🐳 准备启动 TY Memory Agent Docker 容器..."

# 创建容器专用目录
echo "📁 创建容器专用数据目录..."
mkdir -p data_docker
mkdir -p logs_docker
mkdir -p config

echo "✅ 目录创建完成"
echo ""
echo "📋 目录说明:"
echo "  - data_docker: 容器专用数据目录（数据库、会话文件等）"
echo "  - logs_docker: 容器专用日志目录"
echo "  - data:        本地运行专用数据目录（poetry/sh start.sh）"
echo "  - logs:        本地运行专用日志目录"
echo ""

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  警告: .env 文件不存在"
    if [ -f env.docker.example ]; then
        echo "📝 从 env.docker.example 创建 .env 文件..."
        cp env.docker.example .env
        echo "✅ 已创建 .env 文件，请编辑并填入您的配置"
        echo ""
    else
        echo "❌ 错误: 找不到 env.docker.example 文件"
        exit 1
    fi
fi


# 构建镜像
echo "🔨 构建 Docker 镜像..."
echo "💡 提示：首次构建约需 3-5 分钟，后续构建会利用缓存加速"
echo "⚡ 使用 BuildKit 可进一步加速：DOCKER_BUILDKIT=1 docker-compose build"
DOCKER_BUILDKIT=1 docker-compose build
# 启动容器
echo "🚀 启动 Docker 容器..."
docker-compose up -d

# 等待容器启动
echo "⏳ 等待容器启动..."
sleep 3

# 检查容器状态
if docker ps | grep -q "ty-memory-agent"; then
    echo ""
    echo "========================================="
    echo "✅ 容器启动成功！"
    echo "========================================="
    echo ""
    echo "📊 容器信息:"
    docker ps --filter "name=ty-memory-agent" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo "📝 查看日志:"
    echo "  docker-compose logs -f"
    echo ""
    echo "🔍 进入容器:"
    echo "  docker exec -it ty-memory-agent bash"
    echo ""
    echo "🛑 停止容器:"
    echo "  docker-compose down"
    echo ""
    echo "🌐 服务地址:"
    echo "  http://localhost:10081"
    echo ""
else
    echo ""
    echo "❌ 容器启动失败，查看日志:"
    docker-compose logs --tail=50
    exit 1
fi
