# TY Memory Agent Dockerfile
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.7.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

# 安装系统依赖
# - gcc, g++: Python包编译
# - git: 代码版本控制
# - curl: 健康检查和网络请求
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js 和 npm（用于 npx 命令）
# 使用 NodeSource 官方源安装最新 LTS 版本
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 验证 Node.js 和 npm 安装
RUN node --version && npm --version && npx --version

# 安装 Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

# 安装 uvx（用于运行 MCP 服务，如 time server）
RUN pip install uv

# 复制项目文件（从 Qwen-Agent 根目录）
COPY pyproject.toml poetry.lock* /app/
COPY qwen_agent /app/qwen_agent
COPY ty_mem_agent /app/ty_mem_agent

# 安装依赖（包括所有必要的 extras 和 ty-mem-agent 依赖组）
# - mcp: MCP 协议支持
# - code_interpreter: fastapi, uvicorn 等 Web 服务依赖
# - rag: RAG 功能支持
# - ty-mem-agent: TY Memory Agent 专用依赖（loguru, httpx, redis 等）
RUN poetry install --no-root --with ty-mem-agent --extras "mcp code_interpreter rag" || \
    pip install -e ".[mcp,code_interpreter,rag]"


# 创建日志目录
RUN mkdir -p /app/ty_mem_agent/logs

# 暴露端口
EXPOSE 10081

# 工作目录切换到 ty_mem_agent
WORKDIR /app/ty_mem_agent

# 启动命令
CMD ["python", "main.py"]

