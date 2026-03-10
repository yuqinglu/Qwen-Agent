# TY Memory Agent — 开发者指南

> 本文件面向内部开发团队，涵盖环境配置、目录说明、开发规范与部署方式。  
> 原 Qwen-Agent 项目文档见根目录 [README.md](../README.md) / [README_CN.md](../README_CN.md)。

---

## 目录

- [项目简介与架构](#项目简介与架构)
- [目录结构说明](#目录结构说明)
- [User ID 体系说明](#user-id-体系说明)
- [环境配置](#环境配置)
- [依赖管理与同步规范](#依赖管理与同步规范)
- [启动方式](#启动方式)
- [开发规范与 Git 分支策略](#开发规范与git分支策略)
- [新增业务 Skill 开发指南](#新增业务-skill-开发指南)
- [API 端点速查表](#api-端点速查表)

---

## 项目简介与架构

TY Memory Agent 是一个基于 **Qwen-Agent 框架**构建的生产级智能记忆助手服务，向 App 端和智能眼镜端开放 REST + WebSocket + SSE 接口。

```
                    ┌─────────────────────────────────────────────────────────────┐
                    │                    TY Memory Agent                          │
                    │                                                             │
  App / 眼镜端  ──► │  FastAPI (port 10081)                                        │
                    │  ├── REST  /agent/api/v1/todo/*    (待办管理)                │
                    │  ├── REST  /agent/api/v1/asr/*     (语音识别代理)             │
                    │  ├── WS    /agent/api/v1/chat/ws   (通用聊天)                 │
                    │  ├── REST  /auth/*  /user/* (认证/用户，内部聊天页面的API)      │
                    │  └── WS    /ws/{token}              (旧版，已废弃)            │
                    │                                                             │
                    │  核心组件：                                                   │
                    │  ├── TYMemoryAgent (qwen_agent.agents.Assistant)            │
                    │  ├── MemOS 记忆系统 (HTTP 调用外部 API)                        │
                    │  ├── ToolRegistry  (MCP + 自定义工具)                         │
                    │  └── Skills        (业务技能，含交互流程控制)                   │
                    └─────────────────────────────────────────────────────────────┘
                           │               │              │
                    MemOS API        MCP 工具服务      阿里云 ASR/TTS
                    (记忆存取)    (高德/滴滴/日历等)   (语音能力)
```

---

## 目录结构说明

```
ty_mem_agent/
├── main.py                      ← 唯一启动入口（TYMemoryAgentApp）
│
├── agents/
│   ├── ty_memory_agent.py       ← 核心 Agent（带记忆，集成 MCP 工具）
│   └── todo_chat_agent.py       ← 待办专用 AI 聊天 Agent
│
├── config/
│   └── settings.py              ← Pydantic Settings，所有环境变量在此声明
│
├── memory/
│   ├── memos_client.py          ← MemOS 记忆 HTTP 客户端
│   ├── todo_manager.py          ← 待办事项管理
│   └── user_memory.py           ← 用户记忆集成层
│
├── mcp_integrations/            ← MCP 工具集成（高德/滴滴/日历/股票等）
│   ├── tool_registry.py         ← 统一工具注册中心（单例）
│   ├── amap_mcp_server.py       ← 高德地图 MCP
│   ├── calendar_mcp_server.py   ← 日历 MCP
│   ├── didi_mcp_server.py       ← 滴滴打车 MCP
│   └── ...
│
├── tools/                       ← 自定义工具（非 MCP，本地执行）
│   ├── todo_tools.py            ← 待办提取 / 查询 / 更新工具
│   ├── profile_tools.py         ← 用户画像工具
│   ├── feishu_meeting_sdk.py    ← 飞书会议 SDK
│   ├── eleme_tools.py           ← 饿了么外卖工具
│   └── natural_time_parser.py   ← 自然语言时间解析
│
├── server/                      ← FastAPI 服务层
│   ├── chat_server.py           ← App 组装（挂载所有路由，仅此职责）
│   ├── auth_routes.py           ← 认证端点（/auth/*）
│   ├── user_routes.py           ← 用户信息端点（/user/*）
│   ├── conversation_routes.py   ← 旧版会话管理（/conversations/*）
│   ├── app_api_routes.py        ← APP 待办 API（/agent/api/v1/todo/*）
│   ├── general_chat_routes.py   ← 通用聊天路由（/agent/api/v1/chat/*）
│   ├── asr_routes.py            ← ASR 语音识别（/agent/api/v1/asr/*）
│   ├── general_chat_websocket_service.py ← 通用聊天 WebSocket 核心逻辑
│   ├── general_chat_manager.py  ← 通用聊天会话管理
│   ├── skills/                  ← 业务技能层（工具文案映射 + 交互流程控制）
│   │   ├── base.py              ← Skill 抽象基类 + SkillRegistry
│   │   ├── ride_hailing.py      ← 打车技能（含叫车场景 TTS 流程）
│   │   ├── weather.py           ← 天气技能
│   │   ├── todo.py              ← 待办/日历技能
│   │   └── general.py           ← 通用兜底技能
│   ├── tts_service.py           ← TTS 语音合成
│   ├── asr_service.py           ← ASR 语音识别代理
│   ├── deep_thinking_planner.py ← 深度思考规划器
│   ├── rich_card_manager.py     ← 富媒体卡片管理
│   ├── attachment_extractor.py  ← 附件文本提取
│   ├── smart_sentence_splitter.py ← 智能分句（TTS 优化）
│   ├── user_manager.py          ← 用户认证 + JWT
│   ├── user_database.py         ← SQLite 用户持久化
│   ├── conversation_manager.py  ← 旧版会话历史（JSON 文件存储）
│   ├── nacos_service.py         ← Nacos 服务注册
│   └── ugc_client.py            ← UGC 文件服务客户端
│
├── utils/
│   └── logger_config.py         ← Loguru 日志配置
│
├── data/                        ← 运行时数据（不入 Git）
│   ├── conversations/           ← 旧版 WebSocket 会话历史（JSON 文件）
│   ├── general_chat/            ← 通用聊天会话历史（JSON 文件）
│   └── chat_sessions.db         ← SQLite 用户数据库
│
├── Dockerfile                   ← Docker 镜像构建配置
├── docker-compose.yml           ← Docker Compose（host 网络，端口 10081）
├── .env                         ← 本地环境变量（不入 Git，从 env_example.txt 复制）
└── env_example.txt              ← 环境变量示例（入 Git）
```

> **数据存储说明**：当前采用轻量级存储方案——会话历史用 JSON 文件，用户数据用 SQLite。
> 如果后续需要多实例部署，可迁移到 PostgreSQL / Redis 统一存储。

---

## User ID 体系说明

本项目存在两种格式的 user_id，分别服务于不同的系统层。理解这一区别对于开发新功能至关重要。

### 概览

```
外部客户端（App / 眼镜端）
    │
    │  calendar_user_id（int64，通过 X-USER-ID Header 或 WS 查询参数传入）
    ▼
┌─────────────────────────────────────┐
│         TY Memory Agent             │
│                                     │
│  接入层自动将 calendar_user_id        │
│  反查为内部 agent_user_id（str）      │
└─────────────────────────────────────┘
    │                    │
    │ agent_user_id       │ calendar_user_id
    │ (str, 如 "user_1")  │ (int64)
    ▼                    ▼
用户认证 / JWT          日历 MCP / 待办系统
Agent 记忆上下文        UGC 文件服务
MemOS 记忆 API
```

### 两种 user_id 详解

#### 1. agent_user_id（内部用户 ID）

| 属性 | 说明 |
|------|------|
| 类型 | `str`，如 `"user_1"`、`"user_abc123"` |
| 来源 | `user_manager` 注册/自动创建时分配 |
| 存储 | SQLite（`data/chat_sessions.db`） |
| 用途 | JWT 认证、WebSocket 会话管理、Agent 记忆上下文、MemOS 记忆系统 |
| 使用方 | `user_manager`、`TYMemoryAgent.set_user_context()`、`conversation_manager` |
| 获取方式 | 登录接口 `/auth/login` 返回 `user_id` 字段；或由 `user_manager.get_or_create_user_by_calendar_id()` 反查 |

#### 2. calendar_user_id（外部对接 ID）

| 属性 | 说明 |
|------|------|
| 类型 | `int64`（Python `int`，值在 JavaScript `Number.MAX_SAFE_INTEGER` 范围内） |
| 来源 | 注册得到，主要是日历待办系统、UGC系统等外部系统的用户ID，agent这里不做鉴权 |
| 存储 | SQLite `calendar_user_id` 字段（与 agent_user_id 关联） |
| 用途 | 日历 MCP 服务（`calendar-service-*`）、待办系统、UGC 文件服务（`userId` 字段）、富媒体卡片 `user_id` |
| 使用方 | `/agent/api/v1/todo/*`、`/agent/api/v1/chat/*`、`ugc_client.upload()` |
| 传入方式 | HTTP Header `X-USER-ID: <int>`（APP API）；WebSocket 查询参数 `?user_id=<int>` |

### 接入层的自动映射

外部客户端**只需知道 calendar_user_id**，不需要感知内部 agent_user_id。接入层代码会自动完成双向映射：

```python
# general_chat_websocket_service.py / app_api_routes.py 内部逻辑（已封装）

# 外部 calendar_user_id（int）→ 内部 agent_user_id（str）
user = user_manager.get_or_create_user_by_calendar_id(calendar_user_id)
agent_user_id = user.user_id   # 供 TYMemoryAgent 使用

# 内部 agent_user_id（str）→ 外部 calendar_user_id（int）
calendar_user_id = UserIdMapper.get_calendar_user_id(agent_user_id)  # 供 MCP 调用使用
```

### 快速参考

| 场景 | 应使用的 user_id | 格式 |
|------|----------------|------|
| `/auth/login` 登录返回值 | `user_id` | str |
| `/user/calendar-id` 接口返回值 | `calendar_user_id` | str（避免 JS 精度丢失） |
| APP API Header `X-USER-ID` | calendar_user_id | int |
| WebSocket 查询参数 `?user_id=` | calendar_user_id | int |
| 调用日历 MCP 工具时传入 | calendar_user_id | int |
| 调用 UGC 文件服务 `userId` 字段 | calendar_user_id | int |
| `TYMemoryAgent.set_user_context()` | agent_user_id | str |
| MemOS 记忆 API | agent_user_id | str |

### 相关文件

- `server/user_id_mapper.py` — `UserIdMapper`，包含 `generate_calendar_user_id()` 映射逻辑
- `server/user_manager.py` — `UserManager`，包含 `get_or_create_user_by_calendar_id()` 反查逻辑
- `server/app_api_routes.py` — APP API 接入层，X-USER-ID 解析说明
- `server/general_chat_websocket_service.py` — WebSocket 接入层，calendar_user_id → agent_user_id 映射

---

## 环境配置

### 前提条件

| 工具 | 版本要求 | 说明 |
|------|---------|------|
| Python | `^3.10` | 推荐 3.10 或 3.11 |
| Poetry | `^1.7` | 依赖管理 |
| Node.js | LTS | MCP stdio 工具需要 `npx` |
| Docker | 可选 | 生产/测试环境推荐 |

### 1. 安装 Poetry

```bash
curl -sSL https://install.python-poetry.org | python3 -
# 验证安装
poetry --version
```

### 2. 克隆仓库并安装依赖

```bash
git clone <公司 GitLab 地址>
cd Qwen-Agent

# 安装所有依赖（包含 TY Memory Agent 依赖组和必要 extras）
poetry install --with ty-mem-agent --extras "mcp code_interpreter rag"
```

### 3. 配置环境变量

```bash
cd ty_mem_agent
cp env_example.txt .env
# 编辑 .env，填入必要的 API Key
```

**必填项：**

| 变量名 | 说明 |
|--------|------|
| `DASHSCOPE_API_KEY` | 阿里云百炼 API Key（LLM + TTS + ASR） |
| `MEMOS_API_KEY` | MemOS 记忆系统 API Key |
| `AMAP_TOKEN` | 高德地图 API Key |

**可选项（按需开启）：**

| 变量名 | 说明 |
|--------|------|
| `DIDI_API_KEY` | 滴滴打车 API Key |
| `BOCHA_API_KEY` | 博查 AI 搜索 |
| `VARIFLIGHT_API_KEY` | 飞常准航班信息 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书会议 |
| `NACOS_ENABLED` | 是否开启 Nacos 服务注册 |

---

## 依赖管理与同步规范

项目使用 **Poetry** 作为主要依赖管理工具，`requirements.txt` 作为 pip 兼容性备份。

### 添加新依赖

```bash
# 添加到 TY Memory Agent 专用依赖组（推荐）
poetry add <包名> --group ty-mem-agent

# 添加到主依赖（如果是 qwen_agent 核心也需要的）
poetry add <包名>

# 添加到 extras（可选功能）
# 需手动编辑 pyproject.toml 的 [tool.poetry.extras] 部分
```

### 同步 requirements.txt

每次在 `pyproject.toml` 新增依赖后，必须同步 `requirements.txt`：

```bash
# 从 pyproject.toml 导出，覆盖 requirements.txt
poetry export \
  -f requirements.txt \
  --with ty-mem-agent \
  --extras "mcp code_interpreter rag" \
  --without-hashes \
  -o ty_mem_agent/requirements.txt
```

> 也可以直接手动在 `requirements.txt` 末尾追加包名，两种方式都可以，
> 重要的是**保持 pyproject.toml 和 requirements.txt 内容一致**。

### 已知配置说明

- `pyproject.toml` 是权威配置，包含精确版本约束
- `requirements.txt` 仅作为 pip 安装的参考，版本号不锁定
- Docker 构建使用 `poetry install`，不依赖 `requirements.txt`

---

## 启动方式

### 方式一：直接运行（开发推荐）

```bash
cd ty_mem_agent

# 启动服务（默认端口 10081，可在 .env 中修改 PORT）
poetry run python main.py
```

访问 `http://localhost:10081/health` 验证服务是否正常。

### 方式二：Docker 启动（生产/测试推荐）

```bash
cd ty_mem_agent

# 首次构建并启动
docker compose up -d

# 查看日志
docker compose logs -f ty-mem-agent

# 重启服务（不重新构建镜像）
docker compose restart

# 快速重建（代码变更时使用，跳过依赖安装层）
bash rebuild-fast.sh

# 停止服务
docker compose down
```

> **注意**：`docker-compose.yml` 使用 `network_mode: host`，仅适用于 Linux。
> macOS/Windows Docker Desktop 下需要将 `network_mode: host` 改为 `ports: ["10081:10081"]`
> 并将 MCP 服务地址从 `localhost` 改为 `host.docker.internal`。

### 环境变量端口说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PORT` | `10081` | 服务监听端口 |
| `HOST` | `0.0.0.0` | 服务监听地址 |

---

## 开发规范与Git分支策略

### 分支结构

```
main      ← 稳定主干，只接受来自 dev 的 MR，不直接提交
dev       ← 日常开发集成分支，功能分支合并到这里
feature/* ← 功能开发分支，如 feature/add-stock-skill
fix/*     ← Bug 修复分支，如 fix/tts-crash-on-empty-text
release/* ← 发版分支（可选），如 release/v1.2.0
```

### 工作流程

```bash
# 1. 从 dev 切出功能分支
git checkout dev
git pull origin dev
git checkout -b feature/your-feature-name

# 2. 开发、提交
git add .
git commit -m "feat: 添加XX功能"

# 3. 推送并创建 Merge Request
git push origin feature/your-feature-name
# 在 GitLab 上创建 MR，指向 dev 分支

# 4. 代码审查通过后，使用 Squash Merge 合并到 dev
# 5. 测试稳定后，从 dev 创建 MR 到 main
```

### 提交信息规范（Conventional Commits）

```
feat:     新功能
fix:      Bug 修复
refactor: 代码重构（无功能变更）
docs:     文档更新
chore:    工具/依赖/配置变更
test:     测试相关
```

示例：
```
feat: 新增航班查询 Skill
fix: 修复打车场景在只说目的地时 TTS 未播报的问题
refactor: 将 scenarios 合并到 skills 统一管理
```

### MR 合并策略

- 合并到 `dev`：允许 Squash Merge（保持历史整洁）
- 合并到 `main`：必须通过 Code Review，使用 Merge Commit（保留完整记录）
- `main` 分支禁止直接 force push

---

## 新增业务 Skill 开发指南

每个 Skill 文件覆盖两层能力：
1. **工具文案映射**：工具名 → 深度思考步骤展示的用户可见文案
2. **交互流程控制**（可选）：多轮对话中的 TTS 时机与卡片推送控制

### 最简示例：新增一个股票查询 Skill

新建 `ty_mem_agent/server/skills/stock.py`：

```python
from typing import Any, List, Optional
from .base import Skill, SkillInteractionResult

class StockSkill(Skill):
    @property
    def skill_id(self) -> str:
        return "stock"

    @property
    def display_name(self) -> str:
        return "股票行情"

    @property
    def description(self) -> str:
        return "查询股票实时行情、历史数据、财务报告等。"

    def matches_tool(self, tool_name: str) -> bool:
        return "stock" in tool_name.lower() or "股票" in tool_name

    def get_business_short(self, tool_name: str) -> Optional[str]:
        return "查询股票信息"

    def get_thinking_after_result(self, tool_name: str, tool_result: Any = None) -> Optional[str]:
        return "已查询到股票数据，正在整理后为您回复。"

    def tool_categories(self) -> List[str]:
        return ["stock"]

    # 如果需要交互流程控制（TTS 时机等），可选重写以下方法：
    # def applies_to(self, user_message: str) -> bool:
    #     return "查股票" in user_message or "股价" in user_message
    #
    # def on_tool_result(self, tool_name, tool_result, tool_args, context):
    #     return SkillInteractionResult(tts_to_say="已查到股价，正在整理。")
```

然后在 `ty_mem_agent/server/skills/__init__.py` 注册：

```python
from .stock import StockSkill

def _register_default_skills() -> None:
    reg = get_skill_registry()
    if reg.all_skills():
        return
    reg.register(WeatherSkill())
    reg.register(StockSkill())     # 新增这行
    reg.register(RideHailingSkill())
    reg.register(TodoSkill())
    reg.register(GeneralSkill())
```

### Skill 方法说明

| 方法 | 必须实现 | 说明 |
|------|---------|------|
| `skill_id` | 是 | 唯一标识 |
| `matches_tool(tool_name)` | 是 | 返回 True 表示本技能处理该工具 |
| `get_business_short(tool_name)` | 建议 | 深度思考步骤中显示的短描述 |
| `get_thinking_after_result(...)` | 建议 | 工具完成后的思考句 |
| `tool_categories()` | 可选 | 依赖的工具类别（用于按技能过滤工具） |
| `applies_to(user_message)` | 可选 | 返回 True 表示进入本技能的交互流程 |
| `on_tool_result(...)` | 可选 | 工具回调后的 TTS/卡片推送决策 |
| `should_tts_model_output(context)` | 可选 | 控制是否 TTS 模型中间输出 |

---

## API 端点速查表

所有接口基础地址：`http://<服务IP>:10081`


### 通用聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| WS | `/agent/api/v1/chat/ws` | WebSocket 通用聊天（需 Bearer Token Header） |
| GET | `/agent/api/v1/chat/sessions` | 会话列表 |
| GET | `/agent/api/v1/chat/sessions/{id}` | 会话详情 |
| POST | `/agent/api/v1/chat/sessions/{id}/title` | 更新会话标题 |
| POST | `/agent/api/v1/chat/sessions/{id}/delete` | 删除会话 |
| GET | `/agent/api/v1/chat/sessions/{id}/cards` | 获取富卡片列表 |
| POST | `/agent/api/v1/chat/attachments/request-upload` | 申请上传附件 |
| POST | `/agent/api/v1/chat/attachments/use` | 标记附件已使用 |

### 待办管理（APP API，使用 X-USER-ID Header）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/api/v1/todo/quick-create` | 一句话创建待办 |
| POST | `/agent/api/v1/todo/extract-params` | 提取待办参数 |
| GET | `/agent/api/v1/todo/list` | 待办列表 |
| POST | `/agent/api/v1/todo/{id}/chat/sessions` | 创建待办聊天会话 |
| POST | `/agent/api/v1/todo/{id}/chat/sessions/{sid}/messages` | 发送消息（SSE 流式） |

### 语音识别

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agent/api/v1/asr/formats` | 支持的音频格式 |
| POST | `/agent/api/v1/asr/recognize` | 语音识别（文件上传） |

### 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 服务健康状态 |

### 认证(可以无视)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 登录，返回 Bearer Token |
| POST | `/auth/logout` | 登出（需 Bearer Token） |

### 用户信息（需 Bearer Token）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/profile` | 获取用户资料（含记忆摘要） |
| GET | `/user/calendar-id` | 获取日历用户 ID |
| GET | `/user/stats` | 获取统计信息 |