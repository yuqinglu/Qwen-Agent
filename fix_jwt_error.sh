#!/bin/bash
# JWT 依赖冲突快速修复脚本
# 修复 "AttributeError: module 'jwt' has no attribute 'encode'" 错误

set -e

echo "🔧 修复 JWT 依赖冲突..."
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "📁 当前目录: $(pwd)"
echo ""

# 1. 检查当前JWT安装情况
echo "1️⃣ 检查当前 JWT 包安装情况..."
poetry run pip list | grep -i jwt || echo "未找到JWT相关包"
echo ""

# 2. 卸载所有JWT相关包
echo "2️⃣ 卸载所有 JWT 相关包..."
poetry run pip uninstall -y jwt pyjwt 2>/dev/null || echo "已清理"
echo ""

# 3. 重新安装依赖
echo "3️⃣ 重新安装依赖..."
poetry install
echo ""

# 4. 验证修复
echo "4️⃣ 验证 JWT 功能..."
poetry run python -c "
import jwt
print('✅ jwt 模块位置:', jwt.__file__)
print('✅ jwt.encode 存在:', hasattr(jwt, 'encode'))
print('✅ jwt.decode 存在:', hasattr(jwt, 'decode'))

# 测试编码解码
test_data = {'test': 'data'}
token = jwt.encode(test_data, 'secret', algorithm='HS256')
print('✅ JWT 编码成功')

decoded = jwt.decode(token, 'secret', algorithms=['HS256'])
print('✅ JWT 解码成功:', decoded)
print('')
print('🎉 JWT 依赖已修复！')
" && {
    echo ""
    echo "✅ 修复完成！现在可以重启服务了。"
    echo ""
    echo "重启服务:"
    echo "  ./ty_mem_agent/restart.sh"
    echo ""
    echo "或者启动服务:"
    echo "  ./ty_mem_agent/start.sh"
} || {
    echo ""
    echo "❌ 修复失败，请检查错误信息"
    exit 1
}

