.PHONY: help docker-build docker-up docker-down docker-restart docker-logs docker-ps clean

# 默认目标：显示帮助
help:
	@echo "TY Memory Agent - 部署管理命令"
	@echo ""
	@echo "Docker 部署命令："
	@echo "  make docker-start      - 构建并启动 Docker 服务"
	@echo "  make docker-stop       - 停止 Docker 服务"
	@echo "  make docker-restart    - 重启 Docker 服务"
	@echo "  make docker-logs       - 查看 Docker 日志"
	@echo "  make docker-ps         - 查看 Docker 容器状态"
	@echo "  make docker-shell      - 进入 Docker 容器 shell"
	@echo "  make docker-build      - 构建 Docker 镜像"
	@echo ""
	@echo "脚本部署命令："
	@echo "  make start             - 使用脚本启动服务"
	@echo "  make stop              - 停止脚本启动的服务"
	@echo "  make restart           - 重启脚本启动的服务"
	@echo "  make logs              - 查看脚本服务日志"
	@echo ""
	@echo "维护命令："
	@echo "  make clean             - 清理临时文件和日志"
	@echo "  make health            - 检查服务健康状态"
	@echo "  make check-calendar    - 检查日历 MCP 状态"
	@echo ""
	@echo "配置命令："
	@echo "  make init              - 初始化配置文件"

# Docker 部署命令
docker-build:
	@echo "🔨 构建 Docker 镜像..."
	docker-compose build

docker-up: docker-build
	@echo "🚀 启动 Docker 服务..."
	docker-compose up -d
	@echo "⏳ 等待服务启动..."
	@sleep 5
	@make health

docker-start: docker-up

docker-down:
	@echo "🛑 停止 Docker 服务..."
	docker-compose down

docker-stop: docker-down

docker-restart:
	@echo "🔄 重启 Docker 服务..."
	@make docker-stop
	@sleep 2
	@make docker-start

docker-logs:
	@echo "📋 查看 Docker 日志..."
	docker-compose logs -f

docker-ps:
	@echo "📊 Docker 容器状态："
	docker-compose ps

docker-shell:
	@echo "🐚 进入容器 shell..."
	docker-compose exec ty-mem-agent /bin/bash

# 脚本部署命令
start:
	@echo "🚀 使用脚本启动服务..."
	./start.sh

stop:
	@echo "🛑 停止服务..."
	./stop.sh

restart:
	@echo "🔄 重启服务..."
	./restart.sh

logs:
	@echo "📋 查看服务日志..."
	tail -f logs/ty_mem_agent.log

# 维护命令
clean:
	@echo "🧹 清理临时文件..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name "*.pid" -delete 2>/dev/null || true
	@echo "✅ 清理完成"

health:
	@echo "🏥 检查服务健康状态..."
	@curl -s http://localhost:10081/health || echo "❌ 服务未响应"
	@echo ""

check-calendar:
	@echo "📅 检查日历 MCP 状态..."
	@docker ps | grep calendar || echo "❌ 日历 MCP 容器未运行"
	@curl -s http://localhost:18091/health 2>/dev/null && echo "✅ 日历 MCP 响应正常" || echo "⚠️  日历 MCP 未响应"

# 配置初始化
init:
	@echo "📝 初始化配置..."
	@if [ ! -f .env ]; then \
		cp env.docker.example .env; \
		echo "✅ 已创建 .env 文件，请编辑配置：vim .env"; \
	else \
		echo "⚠️  .env 文件已存在"; \
	fi

# 完整部署流程
deploy: init docker-start
	@echo "🎉 部署完成！"
	@echo ""
	@echo "📊 服务信息："
	@echo "  - 健康检查: http://localhost:10081/health"
	@echo "  - 聊天页面: http://localhost:10081/chat/demo"
	@echo "  - 待办管理: http://localhost:10081/todos"
	@echo ""
	@echo "📋 查看日志: make docker-logs"

