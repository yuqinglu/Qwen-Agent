# TY Memory Agent 部署指南

> 支持 Docker 部署和脚本部署两种方式，自动适配不同环境

## 📋 目录

- [快速开始](#快速开始)
- [部署方式对比](#部署方式对比)
- [Docker 部署](#docker-部署)
- [脚本部署](#脚本部署)
- [配置说明](#配置说明)
- [常用命令](#常用命令)
- [故障排查](#故障排查)

## 🚀 快速开始

### 方式一：Docker 部署（推荐用于生产环境）

```bash
cd ty_mem_agent

# 1. 配置环境变量
cp env.docker.example .env
vim .env  # 填写 DASHSCOPE_API_KEY 等必要配置

# 2. 启动服务
./docker-start.sh

# 3. 访问服务
open http://localhost:10081/chat/demo
```

**就这么简单！** 服务会自动连接宿主机上的日历 MCP（localhost:18091）

### 方式二：脚本部署（研发机环境）

```bash
cd ty_mem_agent
./start.sh  # 自动使用 IP 地址访问日历 MCP
```

**完全不需要改动！** 代码会自动检测环境并配置。

---

## 📊 部署方式对比

| 特性 | Docker 部署 | 脚本部署 |
|------|------------|---------|
| **适用场景** | 生产环境、宿主机部署 | 研发机、快速测试 |
| **启动命令** | `./docker-start.sh` | `./start.sh` |
| **日历 MCP** | localhost:18091（自动） | 10.1.115.38:18091（自动） |
| **环境隔离** | ✅ 容器隔离 | ❌ 依赖本地环境 |
| **部署难度** | 简单（3步） | 简单（1步） |

---

## 🐳 Docker 部署

### 前置条件

1. **Docker 已安装**
   ```bash
   docker --version
   docker-compose --version
   ```

2. **日历 MCP 已启动**
   ```bash
   docker ps | grep calendar
   # 应该看到: 0.0.0.0:18091->18091/tcp
   ```

### 详细步骤

#### 1. 配置环境变量

```bash
cp env.docker.example .env
vim .env
```

**必填配置：**
```bash
CALENDAR_MCP_SERVER_URL=http://localhost:18091/mcp  # 自动配置，通常不需要改
DASHSCOPE_API_KEY=sk-your-api-key                   # 必填
```

#### 2. 启动服务

**使用脚本（推荐）：**
```bash
./docker-start.sh   # 启动
./docker-stop.sh    # 停止
./docker-restart.sh # 重启
```

**使用 Makefile（快捷命令）：**
```bash
make docker-start   # 启动
make docker-stop    # 停止
make docker-logs    # 查看日志
make health         # 健康检查
```

**使用 docker-compose（原生命令）：**
```bash
docker-compose up -d    # 启动
docker-compose down     # 停止
docker-compose logs -f  # 查看日志
```

#### 3. 验证服务

```bash
# 检查容器状态
docker ps | grep ty-memory-agent

# 健康检查
curl http://localhost:10081/health

# 访问聊天页面
open http://localhost:10081/chat/demo
```

---

## 📝 脚本部署

### 使用方法

```bash
cd ty_mem_agent

# 启动
./start.sh

# 停止
./stop.sh

# 重启
./restart.sh

# 查看日志
tail -f logs/ty_mem_agent.log
```

**特点：**
- 代码自动检测非 Docker 环境
- 自动使用 IP 地址 `10.1.115.38:18091/mcp`
- 无需任何配置改动

---

## ⚙️ 配置说明

### 环境变量配置

**Docker 环境（.env 文件）：**

项目使用 `pydantic_settings` 自动从 `.env` 文件加载配置。所有配置都在 `config/settings.py` 中定义。

**必填配置：**
```bash
# AI 服务（必须配置至少一个）
DASHSCOPE_API_KEY=sk-your-api-key
# 或者
# OPENAI_API_KEY=sk-your-openai-key

# Memos 记忆系统（必填）
MEMOS_API_KEY=your-memos-key
MEMOS_API_BASE=https://api.openmem.net
```

**日历 MCP 配置：**
```bash
# Docker 环境（自动配置，使用 localhost）
CALENDAR_MCP_SERVER_URL=http://localhost:18091/mcp
```

**可选 MCP 服务配置：**
```bash
# 高德地图（天气、地理编码、POI搜索、路径规划等）
AMAP_TOKEN=your-amap-token

# 滴滴叫车
DIDI_API_KEY=your-didi-key
DIDI_MCP_MODE=production

# 博查AI搜索
BOCHA_API_KEY=your-bocha-key

# 飞常准航班信息
VARIFLIGHT_API_KEY=your-variflight-key

# 饿了么外卖
ELEME_APP_KEY=your-eleme-key
ELEME_APP_SECRET=your-eleme-secret
ELEME_MODE=sandbox

# 飞书会议
FEISHU_APP_ID=your-feishu-app-id
FEISHU_APP_SECRET=your-feishu-secret
```

**其他配置：**
```bash
# 服务配置
HOST=0.0.0.0
PORT=10081

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=logs/ty_mem_agent.log

# Agent 行为配置
AGENT_PROACTIVITY_LEVEL=proactive  # passive/moderate/proactive/aggressive

# 安全配置
SECRET_KEY=your-secret-key
ACCESS_TOKEN_EXPIRE_MINUTES=43200
```

**完整配置示例：** 查看 `env.docker.example` 文件

**脚本环境：**
- 无需配置，自动使用默认值
- 可选：通过环境变量 `export CALENDAR_MCP_SERVER_URL=xxx` 覆盖

### 配置加载机制

1. **Docker Compose** 通过 `env_file: .env` 加载环境变量到容器
2. **挂载 .env 文件** 到容器内 `/app/ty_mem_agent/.env`
3. **pydantic_settings** 自动读取 `.env` 文件中的配置
4. **config/settings.py** 定义所有配置字段和默认值

```python
# config/settings.py 中的配置读取示例
class Settings(BaseSettings):
    DASHSCOPE_API_KEY: Optional[str] = Field(default=None, env="DASHSCOPE_API_KEY")
    AMAP_TOKEN: Optional[str] = Field(default=None, env="AMAP_TOKEN")
    # ... 其他配置
    
    class Config:
        env_file = ".env"  # 自动读取 .env 文件
        case_sensitive = True
```

### 网络架构

```
宿主机
├── 日历 MCP 容器 (Port 18091)
└── TY Memory Agent 容器 (Host 网络)
    └── 通过 localhost:18091 访问 ✅
```

**使用 Host 网络模式：**
- ✅ 容器直接使用宿主机网络
- ✅ 通过 localhost 访问日历 MCP
- ✅ 性能最佳，配置简单

### 自动环境检测

代码会自动检测运行环境：

1. **优先使用环境变量** `CALENDAR_MCP_SERVER_URL`
2. **检测 Docker 环境** → 使用 `localhost:18091`
3. **研发机环境** → 使用 `10.1.115.38:18091`

**完全自动，无需手动配置！**

## 🎯 常用命令

### Makefile 快捷命令（推荐）

**Makefile 是什么？** 一个命令快捷方式工具，简化复杂命令。

```bash
# 查看所有可用命令
make help

# Docker 部署
make docker-start      # 启动服务
make docker-stop       # 停止服务
make docker-restart    # 重启服务
make docker-logs       # 查看日志（实时）
make docker-ps         # 查看容器状态
make docker-shell      # 进入容器 shell

# 脚本部署
make start             # 启动服务
make stop              # 停止服务
make logs              # 查看日志

# 维护命令
make health            # 健康检查
make check-calendar    # 检查日历 MCP 状态
make clean             # 清理临时文件
```

### 脚本命令

```bash
# Docker 部署
./docker-start.sh      # 启动
./docker-stop.sh       # 停止
./docker-restart.sh    # 重启

# 脚本部署
./start.sh             # 启动
./stop.sh              # 停止
./restart.sh           # 重启
```

### Docker Compose 原生命令

```bash
docker-compose up -d           # 启动
docker-compose down            # 停止
docker-compose logs -f         # 查看日志
docker-compose ps              # 查看状态
docker-compose restart         # 重启
```

### 服务端点

| 功能 | URL |
|------|-----|
| 健康检查 | http://localhost:10081/health |
| 聊天页面 | http://localhost:10081/chat/demo |
| 待办管理 | http://localhost:10081/todos |

---

## 🐛 故障排查

### 问题 1：日历 MCP 连接失败

**现象：**
```
❌ 日历 MCP Server 连接失败: Connection refused
```

**解决步骤：**

```bash
# 1. 检查日历 MCP 是否运行
docker ps | grep calendar
# 应该看到: 0.0.0.0:18091->18091/tcp

# 2. 测试日历 MCP 连接
curl http://localhost:18091/health  # Docker 环境
curl http://10.1.115.38:18091/health  # 研发机环境

# 3. 检查网络模式（Docker）
docker inspect ty-memory-agent | grep NetworkMode
# 应该显示: "NetworkMode": "host"

# 4. 查看日志
docker-compose logs ty-mem-agent | grep "日历 MCP"
```

### 问题 2：端口被占用

**现象：**
```
Error: Port 10081 is already in use
```

**解决方案：**

```bash
# 检查端口占用
lsof -i :10081

# 停止旧服务
./stop.sh  # 如果是脚本启动的
./docker-stop.sh  # 如果是 Docker 启动的

# 或直接杀死进程
kill <PID>
```

### 问题 3：服务启动失败

**检查步骤：**

```bash
# 1. 查看日志
docker-compose logs ty-mem-agent  # Docker
tail -f logs/ty_mem_agent.log      # 脚本

# 2. 检查环境变量
cat .env | grep DASHSCOPE_API_KEY

# 3. 检查依赖服务
docker ps  # 查看所有容器

# 4. 重新构建（Docker）
docker-compose build --no-cache
docker-compose up -d
```

### 问题 4：需要更新部署

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建和启动
make docker-restart  # 或
./docker-restart.sh

# 3. 验证
make health
```

---

## 📚 文件说明

### Docker 相关
- `Dockerfile` - Docker 镜像构建文件
- `docker-compose.yml` - Docker Compose 配置
- `.dockerignore` - 构建忽略文件
- `env.docker.example` - 环境变量示例
- `docker-*.sh` - Docker 管理脚本

### 部署脚本
- `start.sh` / `stop.sh` / `restart.sh` - 脚本部署管理
- `Makefile` - 命令快捷方式工具

### 配置文件
- `.env` - 环境变量配置（需创建）
- `env_example.txt` - 脚本部署环境变量示例

---

## 🎉 部署成功检查清单

- [ ] 日历 MCP 容器正在运行 `docker ps | grep calendar`
- [ ] TY Memory Agent 服务已启动 `docker ps | grep ty-memory-agent`
- [ ] 健康检查通过 `curl http://localhost:10081/health`
- [ ] 可以访问聊天页面 `http://localhost:10081/chat/demo`
- [ ] 日志中显示 "✅ 日历 MCP Server 连接成功"

---

## 💡 技术特点

1. **自动环境适配** - 无需手动配置日历 MCP 地址
2. **Host 网络模式** - Docker 容器直接访问宿主机服务
3. **向后兼容** - 脚本部署方式完全不受影响
4. **灵活配置** - 支持环境变量覆盖默认配置

---

**部署愉快！如有问题请查看日志。** 🚀

