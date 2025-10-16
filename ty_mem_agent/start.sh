#!/bin/sh
# 启动 TY Memory Agent 服务

set -e

# 检查是否已经在运行
if [ -f "ty_memory_agent.pid" ]; then
    PID=`cat ty_memory_agent.pid`
    if ps -p $PID > /dev/null 2>&1; then
        echo "⚠️  服务已在运行 (PID: $PID)"
        echo "如需重启，请先运行: ./stop.sh"
        exit 1
    else
        echo "🧹 清理旧的 PID 文件..."
        rm -f ty_memory_agent.pid
    fi
fi

# 创建日志目录
mkdir -p logs

# 启动服务
echo "🚀 启动 TY Memory Agent 服务..."
nohup poetry run python main.py > logs/ty_mem_agent.log 2>&1 &
PID=$!

# 保存 PID
echo $PID > ty_memory_agent.pid

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 3

# 检查服务是否启动成功
if ps -p $PID > /dev/null 2>&1; then
    echo "✅ 服务启动成功 (PID: $PID)"
    echo "📊 服务状态: http://localhost:10081/health"
    echo "💬 聊天页面: http://localhost:10081/chat/demo"
    echo "📝 待办管理: http://localhost:10081/todos"
    echo "📋 查看日志: tail -f logs/ty_mem_agent.log"
else
    echo "❌ 服务启动失败"
    echo "📋 查看日志: cat logs/ty_mem_agent.log"
    exit 1
fi
