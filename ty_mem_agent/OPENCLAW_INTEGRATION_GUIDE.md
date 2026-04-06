# OpenClaw 对接指南

> **本文档接收方：OpenClaw 团队（及中间「适配层」开发方）**  
> **发送方：ty-mem-agent 团队**  
> **版本：v1.2 / 2026-03-24**

**联调与上线（阶段 0～4）**：[doc/OPENCLAW_INTEGRATION_RUNBOOK.md](doc/OPENCLAW_INTEGRATION_RUNBOOK.md)

---

## 部署架构说明（重要）

实际落地采用 **三层**：`ty-mem-agent` → **OpenClaw 适配层（Adapter）** → **OpenClaw Gateway**。

- 本文档中的 **`POST /tasks`、`GET/DELETE /tasks/{openclaw_task_id}`** 及 **带 HMAC 的回调**，由 **适配层** 对 ty-mem-agent 实现；ty-mem-agent 的 `OPENCLAW_API_BASE` 指向适配层。
- **OpenClaw 侧**按官方能力提供 **Cron + `agentTurn` + `delivery.mode: "webhook"`**（见 [Cron Jobs](https://docs.openclaw.ai/automation/cron-jobs)）；Webhook 可先 POST 到适配层入站地址，由适配层 **转签** 后再 POST 到 ty-mem-agent。
- **开源 OpenClaw**：适配层通过官方 HTTP **[Tools Invoke](https://docs.openclaw.ai/gateway/tools-invoke-http-api)** 使用 **`tool":"cron"`** 与 **`action":"add"|"remove"|"list"`**（与 `cron.add` 文档中的 **参数对象** 对应到 `args`，**不是** `tool":"cron.list"`）；须在 Gateway 配置 **`gateway.tools.allow`** 中放行 `cron`，详见 `openclaw_adapter/README.md` 与 [RUNBOOK](doc/OPENCLAW_INTEGRATION_RUNBOOK.md) 阶段 2。
- 适配层设计要点见仓库内 **[doc/OPENCLAW_ADAPTOR_SERVICE.md](doc/OPENCLAW_ADAPTOR_SERVICE.md)**。

以下接口契约仍以「ty-mem-agent 的客户端视角」描述，**实现方可为适配层**；OpenClaw 核心无需为 ty-mem-agent 单独改代码。

---

## 背景

ty-mem-agent 是一个面向 C 端用户的 AI 助手服务，内置了天气、打车、日历、股票查询等本地能力。
本次改造目标是：**凡是本地 Agent 无法完成的任务（周期性执行、复杂调研、长时间运算等），自动交给 OpenClaw 来处理，处理完后将结果推送回给用户。**

整体流程如下：

```
用户发消息
  → ty-mem-agent 判断本地是否可执行
  → 无法执行时，向「适配层」POST 任务（携带用户原始需求）
  → 适配层创建/调度 OpenClaw Cron（agentTurn 等）
  → OpenClaw 每次执行完成后 webhook → 适配层 → HMAC 回调 ty-mem-agent
  → ty-mem-agent 将结果以卡片形式推送给用户（支持离线推送）
```

---

## 一、能力清单（分工：适配层 vs OpenClaw Gateway）

| # | 能力 | 必须 | 建议实现方 | 说明 |
|---|------|------|------------|------|
| 1 | **任务接收 REST（本文档 `/tasks`）** | 是 | **适配层** | ty-mem-agent 只调适配层 |
| 2 | **Cron + 时区 + 持久化** | 是 | **OpenClaw Gateway** | 官方 Cron，见文档 |
| 3 | **agentTurn 执行** | 是 | **OpenClaw Gateway** | 隔离会话跑用户任务 |
| 4 | **webhook 投递完成态** | 是 | **OpenClaw Gateway** | `delivery.mode: "webhook"` → 适配层入站 URL |
| 5 | **HMAC 回调 ty-mem-agent** | 是 | **适配层** | Gateway 多为 Bearer；HMAC 由适配层加签转发 |
| 6 | **任务状态查询 / 取消 REST** | 是 | **适配层**（聚合 Gateway） | 路径中的 id 为适配层返回的 `openclaw_task_id` |
| 7 | **幂等 `client_task_id`** | 是 | **适配层** | 映射到唯一 OpenClaw job |
| 8 | **run 历史 / 失败重试** | 推荐 | **适配层 + Gateway** | 可用 `cron runs` 等 API 做监控与补偿 |

---

## 二、我们提交给你们的任务格式

### 接口地址（由你们提供）

```
POST {你们的 API 基础地址}/tasks
Authorization: Bearer {你们颁发的 API Key}
Content-Type: application/json
```

### 请求 Payload 完整示例

```json
{
  "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": "12345",
  "task_description": "对港股当日行情进行汇总分析，包括恒生指数、国企指数、主要板块涨跌及成交额",
  "original_message": "帮我每天港股收盘后汇总今日表现",
  "callback_url": "https://agent.example.com/agent/api/v1/chat/openclaw/callback",
  "task_type": "periodic",
  "schedule": "30 16 * * 1-5",
  "schedule_timezone": "Asia/Shanghai",
  "fallback_reason": "keyword_trigger",
  "context": {
    "session_id": "sess-uuid-xxxx",
    "calendar_user_id": 12345
  }
}
```

### 字段详解

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `client_task_id` | string | 是 | **我们侧生成的唯一任务 ID（UUID）**，用于幂等防重。相同 `client_task_id` 重复提交时，你们应返回已有任务而非新建 |
| `user_id` | string | 是 | 用户唯一标识，回调时需通过 `client_task_id` 关联，用于我们定向推送给该用户 |
| `task_description` | string | 是 | **任务内容描述**（自然语言）：描述需要做什么，不包含调度规则。你们以此为主要输入执行任务 |
| `original_message` | string | 是 | 用户发送的**原始消息**（未经加工），可辅助理解用户意图 |
| `callback_url` | string | 是 | 任务执行完成后，你们 POST 回调的完整 URL |
| `task_type` | string | 是 | 见下表 |
| `schedule` | string | 否 | cron 表达式，**仅 `periodic` 类型有值**，时区由 `schedule_timezone` 指定 |
| `schedule_timezone` | string | 否 | cron 执行时区，默认 `Asia/Shanghai`。`periodic` 类型时建议传递 |
| `fallback_reason` | string | 是 | 触发原因，供你们参考调整执行策略（见下表） |
| `context` | object | 否 | 额外上下文（session_id、calendar_user_id 等），我们内部使用，你们无需解析，回调时可忽略 |

### `task_type` 说明

| 值 | 含义 | 你们的处理方式 |
|----|------|---------------|
| `periodic` | 用户要求定期执行 | 按 `schedule`（cron）+ `schedule_timezone` 定时触发，**长期运行直到被取消** |
| `research` | 复杂一次性调研 | 立即异步执行，允许较长耗时（无超时限制），完成后回调 |
| `one_time` | 普通一次性任务 | 立即执行，完成后回调 |

### `fallback_reason` 说明（用于理解任务来源）

| 值 | 含义 | 建议执行策略 |
|----|------|------------|
| `keyword_trigger` | 用户消息含"每天/每周/定期"等周期词，本地直接识别 | 严格按 cron 定期执行 |
| `inability_response` | 我们本地 LLM 判断自身无法完成此任务 | 用你们更强的工具链深度执行，质量优先 |
| `execution_error` | 我们本地执行出现工具调用异常 | 换思路重新执行，优先保证能产出结果 |
| `timeout` | 我们本地执行超时（>120s） | 不限时异步执行，质量优先 |

### 你们需要返回的响应

```json
{
  "openclaw_task_id": "oc-internal-task-id-xxxx",
  "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "accepted",
  "message": "任务已接受"
}
```

| 字段 | 说明 |
|------|------|
| `openclaw_task_id` | **你们内部的任务 ID**，我们后续查询和取消均使用此 ID |
| `client_task_id` | 原样回传我们提交时的 ID，方便我们核对 |
| `status` | 固定为 `accepted`（若已存在相同任务则返回 `already_exists`） |

> **幂等性**：若收到重复的 `client_task_id`，应返回已有任务的 `openclaw_task_id`，不重复创建也不重复执行。

---

## 三、你们完成任务后，回调我们的格式

### 回调地址（我们提供，即提交任务时的 `callback_url`）

```
POST {callback_url}
Content-Type: application/json
X-OpenClaw-Timestamp: {Unix 时间戳，秒级，字符串}
X-OpenClaw-Signature: {HMAC-SHA256 签名，十六进制字符串}
```

### 签名算法（必须实现）

```python
import hmac, hashlib, time, json

timestamp = str(int(time.time()))
body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

msg = timestamp.encode() + b"." + body_bytes
signature = hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()

# 请求头：
# X-OpenClaw-Timestamp: timestamp
# X-OpenClaw-Signature: signature
```

`SECRET` 即双方约定的 `OPENCLAW_CALLBACK_SECRET`。

> **防重放**：我们会拒绝时间戳与当前时间相差超过 **5 分钟** 的回调请求（HTTP 401），请确保发起回调时生成新的时间戳和签名。

### 回调 Payload

```json
{
  "openclaw_task_id": "oc-internal-task-id-xxxx",
  "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "done",
  "result": "## 今日港股日报（2026-03-19）\n\n**恒生指数**：19,234.56（+1.23%）\n\n...",
  "error_message": null,
  "next_run_at": "2026-03-20T16:30:00+08:00",
  "executed_at": "2026-03-19T16:30:05+08:00"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `openclaw_task_id` | string | 是 | 你们内部任务 ID（与提交响应中的一致） |
| `client_task_id` | string | **必须** | 我们提交时的 `client_task_id`，**请原样透传**，我们用此字段快速定位任务和用户 |
| `status` | string | 是 | `done`（成功）/ `failed`（失败） |
| `result` | string | 成功时必填 | **请使用 Markdown 格式**，内容会直接渲染给用户 |
| `error_message` | string | 失败时必填 | 人类可读的失败原因 |
| `next_run_at` | string | 周期任务必填 | 下次执行时间，ISO 8601 含时区，如 `2026-03-20T16:30:00+08:00` |
| `executed_at` | string | 建议填 | 本次执行完成时间，ISO 8601 含时区 |

### 我们的响应

成功：
```json
{"code": 0, "msg": "ok", "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}
```

失败（签名错误 / 时间戳过期）：
```json
{"detail": "签名验证失败"}   // HTTP 401
```

### 定期任务回调机制（重要）

对于 `task_type=periodic` 的任务，**每次执行完成后必须单独回调一次**，不可合并多次结果。

**这是定期任务结果送达用户的唯一通道**：我们没有主动轮询你们的能力，完全依赖你们的每次回调来触发推送。回调链路如下：

```
每次 cron 触发
  → OpenClaw 执行任务
  → POST 回调我们（携带本次执行结果）
  → 我们构建结果卡片
  → 通过卡片岛（Card Island）推送给用户
  → 用户手机收到推送通知（离线也可达，类似系统消息）
```

每次回调都需携带：
- `result`：本次执行的完整结果（Markdown 格式）
- `next_run_at`：下次执行时间（展示给用户，让用户知道下次何时推送）
- `executed_at`：本次执行时间

---

## 四、任务查询和取消接口

> 以下接口路径中的 `{openclaw_task_id}` 均指**你们提交响应中返回的** `openclaw_task_id`，不是我们的 `client_task_id`。

### 4.1 任务状态查询

```
GET {你们的 API 基础地址}/tasks/{openclaw_task_id}
Authorization: Bearer {API Key}
```

响应：
```json
{
  "openclaw_task_id": "oc-internal-task-id-xxxx",
  "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "running",
  "task_type": "periodic",
  "created_at": "2026-03-19T10:00:00+08:00",
  "last_executed_at": "2026-03-19T16:30:00+08:00",
  "next_run_at": "2026-03-20T16:30:00+08:00",
  "result_summary": "最近一次执行的结果摘要（可截断至 500 字以内）"
}
```

`status` 枚举：`accepted`（已接受待执行）/ `running`（执行中）/ `done`（一次性任务完成）/ `failed`（失败）/ `cancelled`（已取消）

### 4.2 任务取消

```
DELETE {你们的 API 基础地址}/tasks/{openclaw_task_id}
Authorization: Bearer {API Key}
```

响应：
```json
{
  "openclaw_task_id": "oc-internal-task-id-xxxx",
  "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "cancelled",
  "message": "任务已取消"
}
```

> `periodic` 任务取消后，应立即停止后续所有调度执行；若任务正在执行中，可等当次执行完成后再停止，但不发送本次回调。

---

## 五、result 内容规范（重要）

`result` 字段内容会**直接渲染成卡片展示给用户**，请遵守以下规范：

### 格式要求

- 使用 **Markdown 格式**
- 用 `##` 级标题作为报告标题（如 `## 今日港股日报`）
- 数字数据使用加粗突出（如 `**+1.23%**`）
- 排行/清单使用有序或无序列表
- 总字数控制在 **3000 字以内**（过长请提炼摘要，可附"查看完整报告"链接）
- 不支持嵌入图片（base64 或 URL 图片均不渲染）

### 按场景的推荐格式

**股市日报**：
```markdown
## 今日港股日报（2026-03-19）

**恒生指数**：19,234.56（**+1.23%**）  
**国企指数**：6,782.10（**-0.45%**）  
**成交额**：1,234 亿港元

### 涨幅榜 Top 5
1. 某某科技 +8.5%
2. 某某银行 +5.2%

### 今日要闻
- 联储局维持利率不变，港股午后拉升
```

**行业调研报告**：
```markdown
## 国内新能源汽车行业竞争格局调研（2026年3月）

### 市场概况
当前新能源汽车渗透率已超过 45%，...

### 主要竞争者
| 企业 | 市场份额 | 核心优势 |
|------|----------|----------|
| 比亚迪 | 32% | 电池垂直整合 |
| 特斯拉 | 15% | 自动驾驶 |

### 趋势研判
...
```

**新闻周报**：
```markdown
## 科技行业周报（2026.03.10 - 2026.03.16）

1. **OpenAI 发布新模型** — 支持实时语音交互...
2. **英伟达市值突破 4 万亿美元** — 受 AI 算力需求推动...
```

---

## 六、时区与调度规范

- 所有时间字段（`next_run_at`、`executed_at`、`last_executed_at` 等）均使用 **ISO 8601 含时区格式**，推荐北京时间（`+08:00`）
- cron 表达式的执行时区以请求体中的 `schedule_timezone` 字段为准（默认 `Asia/Shanghai`）

常用 cron 表达式参考（时区 Asia/Shanghai）：

| cron 表达式 | 含义 |
|------------|------|
| `30 16 * * 1-5` | 工作日 16:30（港股收盘后半小时） |
| `0 16 * * 1-5` | 工作日 16:00（A股收盘后半小时） |
| `0 9 * * *` | 每天 09:00 |
| `0 9 * * 1` | 每周一 09:00 |
| `0 20 * * *` | 每天 20:00 |
| `0 9 1 * *` | 每月1日 09:00 |

---

## 七、错误处理规范

### 执行失败时的回调

即使执行失败，也**必须发送回调**，`status` 设为 `failed`，便于我们告知用户：

```json
{
  "openclaw_task_id": "oc-internal-task-id-xxxx",
  "client_task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "failed",
  "result": null,
  "error_message": "股票数据接口连接超时，任务执行失败，请稍后重试",
  "next_run_at": null,
  "executed_at": "2026-03-19T16:30:05+08:00"
}
```

### 回调失败重试策略（你们侧）

- 若我们的回调端点返回非 2xx，请**最多重试 3 次**，间隔依次为 30s → 2min → 10min
- 3 次重试均失败后，记录日志，停止重试，不影响后续定期任务的正常执行

### 幂等性

- 我们的回调端点是幂等的，相同 `client_task_id` 的重复回调只处理一次，不会重复推送给用户

---

## 八、对接联调步骤

1. **你们提供（给我们配置）：**
   - API 基础地址（`OPENCLAW_API_BASE`）
   - API Key（`OPENCLAW_API_KEY`）
   - 双方约定的回调签名密钥（`OPENCLAW_CALLBACK_SECRET`，建议 32 字节随机字符串）

2. **我们提供（给你们知晓）：**
   - 回调基础地址（`OPENCLAW_CALLBACK_BASE_URL`）
   - 测试环境的具体回调 URL

3. **联调顺序：**
   1. 你们搭好任务接收 API 后，我们用 Postman 手动 POST 提交一个测试任务
   2. 你们接收并执行，模拟结果，POST 回调（带签名）到我们的测试回调地址
   3. 确认我们能正确解析并推送卡片给测试用户
   4. 端到端测试：用户在 APP 上真实发消息触发全链路

---

## 九、完整端到端测试用例

### 用例1：每日港股收盘汇总（定期任务）

**用户发送**：`"帮我每天港股收盘后半小时汇总今日表现"`

**我们提交给你们：**
```json
{
  "client_task_id": "test-task-001",
  "user_id": "12345",
  "task_description": "对港股当日行情进行汇总分析，包括恒生指数、国企指数、主要板块涨跌及成交额",
  "original_message": "帮我每天港股收盘后半小时汇总今日表现",
  "callback_url": "https://agent.example.com/agent/api/v1/chat/openclaw/callback",
  "task_type": "periodic",
  "schedule": "30 16 * * 1-5",
  "schedule_timezone": "Asia/Shanghai",
  "fallback_reason": "keyword_trigger",
  "context": {"session_id": "sess-001", "calendar_user_id": 12345}
}
```

**你们返回：**
```json
{"openclaw_task_id": "oc-task-001", "client_task_id": "test-task-001", "status": "accepted"}
```

**工作日 16:30，你们回调我们：**
```json
{
  "openclaw_task_id": "oc-task-001",
  "client_task_id": "test-task-001",
  "status": "done",
  "result": "## 今日港股日报（2026-03-19）\n\n**恒生指数**：19,234.56（+1.23%）\n...",
  "next_run_at": "2026-03-20T16:30:00+08:00",
  "executed_at": "2026-03-19T16:30:05+08:00"
}
```

**最终效果**：用户每个工作日 16:30 收到港股日报卡片推送

---

### 用例2：新能源汽车行业调研（一次性）

**用户发送**：`"帮我调研一下当前国内新能源汽车行业的竞争格局"`（本地 Agent 返回无能力文本后转交）

**我们提交给你们：**
```json
{
  "client_task_id": "test-task-002",
  "user_id": "12345",
  "task_description": "调研国内新能源汽车行业竞争格局，包括市场规模、主要厂商份额、技术路线及近期动态",
  "original_message": "帮我调研一下当前国内新能源汽车行业的竞争格局",
  "callback_url": "https://agent.example.com/agent/api/v1/chat/openclaw/callback",
  "task_type": "research",
  "schedule": null,
  "schedule_timezone": null,
  "fallback_reason": "inability_response",
  "context": {"session_id": "sess-002", "calendar_user_id": 12345}
}
```

**你们调研完成后回调（预计 5-30 分钟）：**
```json
{
  "openclaw_task_id": "oc-task-002",
  "client_task_id": "test-task-002",
  "status": "done",
  "result": "## 国内新能源汽车行业竞争格局（2026年3月）\n\n### 市场概况\n...",
  "next_run_at": null,
  "executed_at": "2026-03-19T10:25:00+08:00"
}
```

---

### 用例3：每周科技新闻周报（定期任务）

**用户发送**：`"帮我每周一早上总结一下上周科技行业新闻"`

**我们提交给你们：**
```json
{
  "client_task_id": "test-task-003",
  "user_id": "12345",
  "task_description": "汇总上一周（周一至周日）科技行业重要新闻，每条新闻附简短摘要",
  "original_message": "帮我每周一早上总结一下上周科技行业新闻",
  "callback_url": "https://agent.example.com/agent/api/v1/chat/openclaw/callback",
  "task_type": "periodic",
  "schedule": "0 9 * * 1",
  "schedule_timezone": "Asia/Shanghai",
  "fallback_reason": "keyword_trigger",
  "context": {"session_id": "sess-003", "calendar_user_id": 12345}
}
```

**你们每周一 09:00 回调，result 示例：**
```markdown
## 科技行业周报（2026.03.10 - 2026.03.16）

1. **字节跳动发布新 AI 产品** — 主打多模态交互体验...
2. **华为麒麟新芯片曝光** — 据悉工艺达到 3nm 级别...
```

---

## 十、配置汇总

**你们需要告诉我们：**

| 配置项名称 | 说明 |
|-----------|------|
| `OPENCLAW_ENABLED` | `true`（默认）启用 OpenClaw 预判与兜底；`false` 时关闭全部 OpenClaw 逻辑（不提交适配层、回调接口直接 ignored） |
| `OPENCLAW_API_BASE` | 你们的 API 基础地址，如 `https://api.openclaw.com/v1` |
| `OPENCLAW_API_KEY` | 你们颁发的鉴权 API Key |
| `OPENCLAW_CALLBACK_SECRET` | 双方约定的 HMAC 签名密钥（建议 32 字节以上随机字符串） |

**我们需要告诉你们：**

| 内容 | 说明 |
|------|------|
| `callback_url` | 每次提交任务时会携带，测试示例：`https://agent.example.com/agent/api/v1/chat/openclaw/callback` |
| 测试用 `client_task_id` | 联调时使用固定值（如 `test-task-001`）便于两侧排查 |

---

## 附录：我们侧数据流说明（供参考）

```
用户消息
  ↓
[快速预判] 单次 LLM 判定「周期性/定时」并输出 5 段 cron（多语言，非关键词正则）
  ↓ 命中且 cron 合法
跳过本地执行，直接提交 OpenClaw（task_type=periodic）
  ↓ 未命中
[本地 Agent 执行]（ReAct + MCP 工具）
  ↓ 执行完成
[结果检测]
  - LLM 输出含"我无法…"  → 提交 OpenClaw（task_type=research / one_time，fallback_reason=inability_response）
  - 执行超时 >120s        → 提交 OpenClaw（task_type=one_time，fallback_reason=timeout）
  - 执行异常              → 提交 OpenClaw（task_type=one_time，fallback_reason=execution_error）
  - 正常输出              → 直接流式返回用户，不触发 OpenClaw
  ↓ 提交 OpenClaw
[WebSocket 通知用户] "任务已提交，完成后将推送结果"
  ↓
[OpenClaw 执行（可定期）]
  ↓ 执行完成
[POST 回调我们的 callback_url（带 HMAC 签名）]
  ↓
[卡片岛推送] 将结果卡片推送给用户（支持离线）
```

---

*如有任何问题，请联系 ty-mem-agent 团队。*
