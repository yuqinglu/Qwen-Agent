#!/bin/bash
# 快速重建 Docker 镜像（使用 BuildKit 和缓存）

set -e

echo "⚡ 快速重建 Docker 镜像（使用缓存）..."
echo ""

# 显示上次构建时间
if [ -f ".last-build-time" ]; then
    echo "📊 上次构建时间："
    cat .last-build-time
    echo ""
fi

# 记录开始时间
START_TIME=$(date +%s)

# 使用 BuildKit 构建（支持更好的缓存）
echo "🔨 开始构建..."
DOCKER_BUILDKIT=1 docker-compose build

# 计算构建耗时
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
MINUTES=$((DURATION / 60))
SECONDS=$((DURATION % 60))

echo ""
echo "✅ 构建完成！"
echo "⏱️  本次构建耗时: ${MINUTES}分${SECONDS}秒"

# 保存构建时间
echo "构建时间: ${MINUTES}分${SECONDS}秒 ($(date))" > .last-build-time

echo ""
echo "💡 优化建议："
echo "   - 首次构建: ~3-5分钟（使用国内镜像源）"
echo "   - 代码变更后重建: ~10-30秒（使用缓存）"
echo "   - 依赖变更后重建: ~2-3分钟"
echo ""
echo "🚀 启动服务："
echo "   ./docker-start.sh"
