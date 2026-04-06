# OpenClaw Adapter Service

位于本仓库的 **`openclaw_adapter/`** 目录，可整体拷贝为独立 Git 项目维护。

**联调与上线（阶段 0～4）**：[ty_mem_agent/doc/OPENCLAW_INTEGRATION_RUNBOOK.md](../ty_mem_agent/doc/OPENCLAW_INTEGRATION_RUNBOOK.md)

## 作用

- **对上**：为 `ty-mem-agent` 提供 `OPENCLAW_INTEGRATION_GUIDE.md` 中的 REST（均带 **`/openclaw-adapter`** 前缀）：`POST /openclaw-adapter/v1/tasks`、`GET/DELETE /openclaw-adapter/v1/tasks/{openclaw_task_id}`。
- **对下**：将任务转为 OpenClaw Gateway 的 **`cron.add`** 形态（`agentTurn` + `delivery.webhook` 指回本服务），接收 Gateway Webhook 后 **HMAC 转发** 到 ty-mem-agent 的 `/agent/api/v1/chat/openclaw/callback`。

## 快速启动

```bash
cd openclaw_adapter
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：ADAPTER_API_KEY、TY_MEM_CALLBACK_HMAC_SECRET、ADAPTER_PUBLIC_BASE_URL
python -m uvicorn openclaw_adapter.main:app --host 0.0.0.0 --port 8090 --app-dir src
```

> `--app-dir src` 保证以 `src` 为根找到包 `openclaw_adapter`。

或使用安装模式：

```bash
pip install -e .
openclaw-adapter
```

## ty-mem-agent 配置对齐

| ty_mem_agent `.env` | 适配层 `.env` |
|---------------------|---------------|
| `OPENCLAW_API_BASE=http://适配层:8090/openclaw-adapter/v1` | — |
| `OPENCLAW_API_KEY` | `ADAPTER_API_KEY`（相同字符串） |
| `OPENCLAW_CALLBACK_SECRET` | `TY_MEM_CALLBACK_HMAC_SECRET`（相同字符串） |
| `OPENCLAW_CALLBACK_BASE_URL` | ty-mem-agent 自身公网根地址（适配层 POST 回调用） |

## Gateway 模式（对齐开源 OpenClaw，**不修改 OpenClaw 源码**）

官方说明要点：

- **控制面主协议**为 **WebSocket**（[Gateway protocol](https://docs.openclaw.ai/gateway/protocol)）。
- 同端口上另有 **HTTP**：[Tools Invoke](https://docs.openclaw.ai/gateway/tools-invoke-http-api) 固定为 `POST /tools/invoke`。
- **默认情况下** `cron` 在 HTTP 上处于 **拒绝列表**，须在 **`~/.openclaw/openclaw.json`（或等价配置）** 中放行，例如：

```json5
{
  gateway: {
    tools: {
      allow: ["cron"],
    },
  },
}
```

（见 Tools Invoke 文档中的 *hard deny list* 与 `gateway.tools` 说明。）

| `ADAPTER_GATEWAY_MODE` | 行为 |
|------------------------|------|
| `stub` | 不请求真实 Gateway，生成 `stub-*` job id；联调 ty-mem 时用 `POST /openclaw-adapter/internal/dev/simulate-callback`（需 `ADAPTER_DEV_ENDPOINTS=true`）模拟回调。 |
| `http` | **默认**向 `ADAPTER_GATEWAY_HTTP_URL`（建议 `http://127.0.0.1:18789/tools/invoke`）POST；体为 **`{"tool":"cron","action":"add","args":{...}}`**。job id：先按 `ADAPTER_GATEWAY_HTTP_JOB_ID_PATH`（默认 `result.jobId`）取；若无，则自动从 **`result.content[].type=="text"`** 的 **`text` JSON 字符串** 中解析 **`jobId` / `id`**（开源 Gateway 常见返回形态）。**取消**：同 URL POST **`{"tool":"cron","action":"remove","args":{"jobId":"..."}}`**。 |

Bearer：`ADAPTER_GATEWAY_HTTP_TOKEN` 使用 Gateway 的 `gateway.auth.token`（或环境变量 `OPENCLAW_GATEWAY_TOKEN`），与官方文档一致。

**可选后续**：若部署策略禁止 HTTP 调 `cron`、且不愿改配置，再在适配层实现 **WebSocket** Backend（连接成本较高，见 [Architecture](https://docs.openclaw.ai/concepts/architecture)）。

**排错**：若 `/tools/invoke` 返回 `Tool not available: cron.list`，应改用 **`{"tool":"cron","action":"list"}`**（列表）、**`action":"add"`**（创建）、**`action":"remove"`**（删除）。先确认已配置 `gateway.tools.allow` 含 **`cron`**；`jobId` 若在嵌套 JSON 字符串里，调整 `ADAPTER_GATEWAY_HTTP_JOB_ID_PATH` 或改 `gateway_client`。

## 主要路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/openclaw-adapter/health` | 健康检查 |
| POST | `/openclaw-adapter/v1/tasks` | 创建任务（需 `Authorization: Bearer ADAPTER_API_KEY`） |
| GET | `/openclaw-adapter/v1/tasks/{id}` | 查询 |
| DELETE | `/openclaw-adapter/v1/tasks/{id}` | 取消 |
| POST | `/openclaw-adapter/internal/openclaw/webhook` | OpenClaw `delivery.webhook` 入站 |
| POST | `/openclaw-adapter/internal/dev/simulate-callback` | 开发模拟回调（需 `ADAPTER_DEV_ENDPOINTS=true`） |

## 文档

- 架构说明：`ty_mem_agent/doc/OPENCLAW_ADAPTOR_SERVICE.md`
- 对 OpenClaw / 适配层约定：`ty_mem_agent/OPENCLAW_INTEGRATION_GUIDE.md`
