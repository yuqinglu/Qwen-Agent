#!/bin/sh
# 停止 TY Memory Agent 服务

# 获取脚本所在目录（ty_mem_agent目录）
SCRIPT_DIR=`dirname "$0"`
# 切换到ty_mem_agent目录
cd "$SCRIPT_DIR"

echo "🛑 停止 TY Memory Agent 服务..."

if [ -f "ty_memory_agent.pid" ]; then
    PID=`cat ty_memory_agent.pid`
    
    if ps -p $PID > /dev/null 2>&1; then
        echo "🔍 找到运行中的服务 (PID: $PID)"
        
        # 优雅关闭
        echo "📤 发送 SIGTERM 信号..."
        kill -TERM $PID
        
        # 等待进程结束
        echo "⏳ 等待服务关闭..."
        for i in 1 2 3 4 5 6 7 8 9 10; do
            if ! ps -p $PID > /dev/null 2>&1; then
                echo "✅ 服务已关闭"
                break
            fi
            sleep 1
        done
        
        # 如果还在运行，强制关闭
        if ps -p $PID > /dev/null 2>&1; then
            echo "⚠️  强制关闭服务..."
            kill -KILL $PID
            sleep 1
        fi
        
        # 清理 PID 文件
        rm -f ty_memory_agent.pid
        echo "🧹 清理完成"
    else
        echo "⚠️  PID 文件存在但进程未运行，清理 PID 文件"
        rm -f ty_memory_agent.pid
    fi
else
    echo "⚠️  未找到 PID 文件，尝试查找并关闭相关进程..."
    
    # 查找可能的进程
    PIDS=`pgrep -f "python.*main.py" || true`
    if [ -n "$PIDS" ]; then
        echo "🔍 找到相关进程: $PIDS"
        for pid in $PIDS; do
            echo "🛑 关闭进程 $pid"
            kill -TERM $pid
        done
        sleep 2
    else
        echo "ℹ️  未找到运行中的服务"
    fi
fi

echo "✅ 停止操作完成"
