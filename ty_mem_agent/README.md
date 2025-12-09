# TY Memory Agent

🤖 **智能记忆助手系统** - 集成MemOS记忆系统、QwenAgent框架和MCP工具调用的多用户智能对话系统

## ✨ 主要特性

### 🧠 智能记忆系统
- **长期记忆**: 集成 [MemOS记忆平台](https://memos.openmem.net/)，支持持久化记忆
- **用户画像**: 自动学习和记录用户的个人信息、偏好和兴趣
- **上下文连续**: 跨会话保持对话上下文和历史记忆
- **记忆洞察**: 分析用户模式，提供个性化服务

### 🔧 MCP工具集成
- **滴滴叫车**: 支持叫车、价格估算、订单查询
- **高德天气**: 实时天气查询和天气预报
- **时间查询**: 获取当前时间和日期信息
- **智能路由**: 根据用户意图自动选择合适的工具

### 👥 多用户支持
- **用户管理**: 完整的用户注册、登录、认证系统
- **会话管理**: 独立的用户会话和记忆空间
- **权限控制**: 基于JWT的安全认证机制
- **并发支持**: 支持多用户同时在线聊天

### 💬 实时聊天
- **WebSocket**: 实时双向通信
- **流式响应**: 支持流式消息返回
- **富交互**: 支持文本、状态、错误等多种消息类型
- **Web界面**: 内置简洁的聊天演示界面

### 📋 日志系统
- **统一配置**: 基于loguru的统一日志管理
- **分级记录**: 支持DEBUG、INFO、WARNING、ERROR级别
- **模块分离**: 不同模块独立的logger实例
- **文件轮转**: 自动日志文件切割和压缩
- **装饰器**: 函数执行时间记录装饰器
- **上下文**: 操作上下文管理器

## 🏗️ 系统架构

```
TY Memory Agent
├── 🧠 记忆层 (MemOS + 本地存储)
│   ├── 用户画像管理
│   ├── 对话历史记录  
│   ├── 记忆洞察分析
│   └── 知识图谱构建
├── 🤖 智能层 (QwenAgent)
│   ├── 自定义记忆Agent
│   ├── 意图理解分析
│   ├── 上下文增强
│   └── 响应生成
├── 🔧 工具层 (MCP协议)
│   ├── 智能路由器
│   ├── 滴滴叫车服务
│   ├── 高德天气服务
│   └── 扩展工具接口
└── 🌐 服务层 (FastAPI + WebSocket)
    ├── 用户认证管理
    ├── 会话状态管理
    ├── 实时通信处理
    └── API接口服务
```

## 🚀 快速开始

### 1. 环境准备

**Python 环境**:
```bash
# 确保Python版本 >= 3.10
python --version

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows
```

**安装依赖**:
```bash
# 进入项目目录
cd ty_mem_agent

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置API密钥

**复制配置文件**:
```bash
cp env_example.txt .env
```

**编辑 `.env` 文件**，填入您的API密钥：

```bash
# === 必需配置 ===

# DashScope API密钥（推荐）
DASHSCOPE_API_KEY=your_dashscope_api_key

# MemOS记忆系统API密钥
MEMOS_API_KEY=your_memos_api_key

# === 可选配置 ===

# 高德地图API密钥（用于天气查询）
AMAP_TOKEN=your_amap_api_key

# 滴滴API密钥（用于叫车服务）
DIDI_API_KEY=your_didi_api_key

# OpenAI API密钥（备选LLM）
# OPENAI_API_KEY=your_openai_api_key
```

### 3. 获取API密钥指南

#### 🔑 DashScope API密钥
1. 访问 [阿里云DashScope](https://dashscope.console.aliyun.com/)
2. 注册/登录账号并完成实名认证
3. 创建API密钥并复制

#### 🧠 MemOS API密钥  
1. 访问 [MemOS平台](https://memos.openmem.net/)
2. 注册账号并获取API密钥
3. 参考 [MemOS文档](https://memos.openmem.net/cn/quickstart/)

#### 🌤️ 高德地图API密钥
1. 访问 [高德开放平台](https://lbs.amap.com/)
2. 注册开发者账号
3. 创建应用并选择"Web服务"
4. 获取API Key

#### 🚗 滴滴API密钥（模拟）
*注：当前为模拟服务，实际使用需要滴滴开放平台API密钥*

### 4. 启动系统

**快速启动**:
```bash
python run.py
```

**或者使用main.py**:
```bash
python main.py
```

**成功启动后**，您将看到：
```
🚀 TY Memory Agent 启动中...
🌐 服务地址: http://0.0.0.0:8080
🤖 LLM模型: qwen-max
🧠 记忆系统: https://api.openmem.net
🔧 MCP服务: 2 个已启用
```

### 5. 访问系统

**聊天演示界面**: http://localhost:8080/chat/demo

**API文档**: http://localhost:8080/docs

**健康检查**: http://localhost:8080/health

## 💡 使用示例

### 基本对话
```
用户: 你好，我是张三，住在北京
助手: 你好张三！很高兴认识您。我已经记住您来自北京，之后我会记住我们的对话内容和您的偏好。有什么可以帮助您的吗？

用户: 今天北京天气怎么样？
助手: 🌤️ 北京当前天气：晴朗，温度22°C，湿度45%，西北风3级
我记得您在北京，之后询问天气时我会优先关注北京的天气信息。

用户: 帮我叫个车去机场
助手: 🚗 已为您安排从当前位置到北京首都机场的快车
• 订单号：DD20251127143021
• 车型：快车  
• 预估费用：85元
• 预计到达：5分钟
• 预计行程：45分钟
```

### 记忆功能展示
```
# 第一次对话
用户: 我喜欢听音乐和旅行
助手: 我记住了您的兴趣爱好！您喜欢音乐和旅行，这很棒。

# 几天后的对话  
用户: 推荐一些活动
助手: 基于我对您的了解，您喜欢音乐和旅行，我推荐：
• 🎵 北京音乐节（本周末）
• ✈️ 周边古镇一日游
• 🎪 音乐主题咖啡厅
```

## 🔧 高级配置

### 日志系统配置
```python
# 在代码中使用日志
from utils.logger_config import get_logger

# 获取模块专用logger
logger = get_logger("YourModule")
logger.info("这是一条信息")
logger.warning("这是一条警告")
logger.error("这是一条错误")

# 使用装饰器记录执行时间
from utils.logger_config import log_execution_time

@log_execution_time("函数名")
def your_function():
    # 函数执行时间会自动记录
    pass

# 使用上下文管理器
from utils.logger_config import LogContext

with LogContext("操作描述", logger):
    # 自动记录操作开始和结束时间
    pass
```

### Agent配置
```python
# config/settings.py 中的 AGENT_CONFIG
AGENT_CONFIG = {
    "max_memory_context": 10,        # 最大记忆上下文轮数
    "enable_proactive_memory": True, # 启用主动记忆
    "memory_update_threshold": 3,    # 记忆更新阈值
    "mcp_selection_strategy": "auto" # MCP选择策略
}
```

### MCP服务配置
```python
# 启用/禁用MCP服务
MCP_SERVICES = {
    "didi_ride": {"enabled": True},
    "amap_weather": {"enabled": True},
    "time": {"enabled": True},
    "filesystem": {"enabled": False}
}
```

### 记忆系统配置
```bash
# .env 中的记忆配置
MEMORY_MAX_TOKENS=4000      # 最大记忆token数
MEMORY_RETENTION_DAYS=30    # 记忆保留天数
```

## 🛠️ 开发指南

### 添加自定义MCP服务

1. **创建服务类**:
```python
# ty_mem_agent/mcp/my_service.py
from .enhanced_mcp_router import MCPService, MCPRequest, MCPResponse

class MyCustomService(MCPService):
    def __init__(self):
        super().__init__(
            name="my_service",
            description="我的自定义服务",
            capabilities=["custom"],
            keywords=["关键词"]
        )
    
    async def can_handle(self, request: MCPRequest) -> float:
        # 判断能否处理请求，返回置信度
        return 0.8 if "关键词" in request.intent else 0.0
    
    async def execute(self, request: MCPRequest) -> MCPResponse:
        # 执行具体功能
        return MCPResponse(
            service_name=self.name,
            success=True,
            result="处理结果"
        )
```

2. **注册服务**:
```python
# ty_mem_agent/agents/memory_agent.py
def _init_mcp_services(self):
    # 注册自定义服务
    from ..mcp.my_service import MyCustomService
    enhanced_router = get_enhanced_router()
    enhanced_router.register_service(MyCustomService())
```

### 扩展记忆功能

```python
# 自定义记忆处理
async def custom_memory_handler(self, user_message: str, context: Dict):
    # 实现自定义记忆逻辑
    updates = self.extract_custom_info(user_message)
    await integrated_memory.update_user_info(self.current_user_id, updates)
```

## 📚 API文档

### 用户认证
- `POST /auth/register` - 用户注册
- `POST /auth/login` - 用户登录  
- `POST /auth/logout` - 用户登出

### 用户信息
- `GET /user/profile` - 获取用户资料
- `GET /user/stats` - 获取用户统计

### WebSocket聊天
- `WS /ws/{token}` - WebSocket聊天连接

### 系统接口
- `GET /health` - 健康检查
- `GET /chat/demo` - 聊天演示页面

## 🐛 故障排除

### 常见问题

**1. 启动失败 - API密钥错误**
```
解决方案：
1. 检查 .env 文件中的API密钥是否正确
2. 确认API密钥有足够的权限和额度
3. 检查网络连接是否正常
```

**2. 记忆功能异常**
```
解决方案：
1. 确认MEMOS_API_KEY配置正确
2. 检查MemOS服务是否可用
3. 查看日志文件了解详细错误信息
```

**3. MCP工具调用失败**  
```
解决方案：
1. 检查对应的API密钥（AMAP_TOKEN等）
2. 确认MCP服务已启用
3. 查看工具调用的错误日志
```

**4. WebSocket连接失败**
```
解决方案：
1. 确认访问令牌有效
2. 检查防火墙设置
3. 确认服务器端口正常监听
```

### 日志分析

**日志文件位置**: `logs/ty_mem_agent.log`

**重要日志关键词**:
- `🤖 TY Memory Agent 初始化完成` - 系统启动成功
- `👤 设置用户上下文` - 用户会话建立
- `💾 保存记忆成功` - 记忆保存成功
- `🎯 路由成功` - MCP工具调用成功
- `❌` - 错误信息

## 🤝 贡献指南

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 📄 许可证

本项目基于 MIT 许可证开源 - 查看 [LICENSE](LICENSE) 文件了解详情

## 🙏 致谢

- [QwenAgent](https://github.com/QwenLM/Qwen-Agent) - 强大的AI智能体框架
- [MemOS](https://memos.openmem.net/) - 专业的AGI记忆管理平台  
- [FastAPI](https://fastapi.tiangolo.com/) - 现代高性能Web框架
- [MCP](https://modelcontextprotocol.io/) - 模型上下文协议

## 📱 APP 接入指南

TY Memory Agent 支持外部APP或服务器调用。所有API接口都在 `/api/v1` 路径下。

### 快速开始

1. **部署服务**: 使用 Docker 部署（参见上方部署说明）
2. **测试连接**: 运行测试脚本验证外部访问
   ```bash
   ./test-external-access.sh <服务器IP> 10081
   ```
3. **获取用户ID**: 通过注册/登录接口获取 calendar_user_id
4. **调用API**: 使用 X-USER-ID Header 进行身份认证

### API 示例

```bash
# 一句话创建待办
curl -X POST "http://your-server:10081/api/v1/todo/quick-create" \
  -H "Content-Type: application/json" \
  -H "X-USER-ID: 1" \
  -d '{
    "text": "明天下午3点开会",
    "timezone": "Asia/Shanghai"
  }'

# 查询待办列表
curl -X GET "http://your-server:10081/api/v1/todo/list" \
  -H "X-USER-ID: 1"

# 创建待办聊天会话
curl -X POST "http://your-server:10081/api/v1/todo/1/chat/sessions" \
  -H "Content-Type: application/json" \
  -H "X-USER-ID: 1" \
  -d '{
    "content": "帮我完善这个待办的详细内容"
  }'
```

### 详细文档

- [部署与外部访问指南](DEPLOYMENT.md) - 部署配置、外部访问、APP接入
- [脚本参考](SCRIPTS_REFERENCE.md) - 常用脚本使用说明

更多详细配置请查看 [部署指南](DEPLOYMENT.md)

## 📞 支持

如有问题或建议，请：

1. 提交 [Issue](../../issues)
2. 查看 [文档](../../wiki)
3. 参与 [讨论](../../discussions)

---

**TY Memory Agent** - 让AI拥有真正的记忆能力！🧠✨
