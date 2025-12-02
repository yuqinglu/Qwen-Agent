# 🚀 Docker 部署 - 快速开始

## 一键部署（3步）

```bash
cd ty_mem_agent

# 1. 配置
cp env.docker.example .env
vim .env  # 填写必要配置（见下方）

# 2. 启动
./docker-start.sh

# 3. 访问
open http://localhost:10081/chat/demo
```

## 📝 必填配置

编辑 `.env` 文件，至少需要配置以下内容：

```bash
# AI 服务（必须配置至少一个）
DASHSCOPE_API_KEY=sk-your-api-key  # 推荐
# 或者
# OPENAI_API_KEY=sk-your-openai-key

# Memos 记忆系统（必填）
MEMOS_API_KEY=your-memos-key
MEMOS_API_BASE=https://api.openmem.net

# 日历 MCP（自动配置，通常不需要改）
CALENDAR_MCP_SERVER_URL=http://localhost:18091/mcp
```

**可选配置（按需添加）：**
- `AMAP_TOKEN` - 高德地图（天气、导航、POI搜索）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` - 飞书会议
- `DIDI_API_KEY` - 滴滴叫车
- `BOCHA_API_KEY` - 博查AI搜索
- `VARIFLIGHT_API_KEY` - 航班信息
- `ELEME_APP_KEY` / `ELEME_APP_SECRET` - 饿了么外卖

**完整配置说明：** 查看 `env.docker.example` 文件中的注释

## 🧪 测试配置

启动前可以测试配置是否正确：

```bash
# 在 ty_mem_agent 目录下
python test_docker_config.py
```

会显示所有配置的加载状态，帮助你发现配置问题。

## 常用命令

### 使用脚本
```bash
./docker-start.sh    # 启动
./docker-stop.sh     # 停止
./docker-restart.sh  # 重启
```

### 使用 Makefile（快捷命令）
```bash
make docker-start    # 启动
make docker-stop     # 停止
make docker-logs     # 查看日志
make health          # 健康检查
make help            # 查看所有命令
```

## Makefile 是什么？

**简单说：** 命令快捷方式工具，简化复杂命令。

**举例：**
```bash
# 原来需要输入：
docker-compose build && docker-compose up -d && sleep 5 && curl http://localhost:10081/health

# 现在只需输入：
make docker-start
```

## 文档

- **完整部署文档：** [DOCKER_DEPLOY.md](./DOCKER_DEPLOY.md)
- **原有 README：** [README.md](./README.md)

## 核心特性

✅ **自动环境适配** - Docker 和研发机自动切换日历 MCP 地址  
✅ **一键部署** - 3 步完成 Docker 部署  
✅ **向后兼容** - 脚本启动方式（`./start.sh`）完全不受影响  
✅ **Host 网络** - Docker 容器直接访问宿主机日历 MCP（localhost:18091）

## 故障排查

```bash
# 查看日志
make docker-logs

# 健康检查
make health

# 检查日历 MCP
make check-calendar

# 查看所有命令
make help
```

---

**就是这么简单！** 🎉

