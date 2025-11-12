#!/usr/bin/env python3
"""
TY Memory Agent - 基于QwenAgent的智能记忆代理
直接集成QwenAgent内置工具，简洁高效
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import asdict
from datetime import datetime
from loguru import logger

# 添加QwenAgent路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

try:
    from qwen_agent.agents.assistant import Assistant
    from qwen_agent.llm import get_chat_model
    from qwen_agent.llm.schema import Message, USER, SYSTEM
    from qwen_agent.tools.base import BaseTool
    from qwen_agent.llm.schema import ContentItem
    logger.info("✅ 成功导入QwenAgent核心组件")
except ImportError as e:
    logger.error(f"❌ 无法导入QwenAgent核心组件: {e}")
    raise

# 本地导入
from ty_mem_agent.config.settings import get_llm_config
from ty_mem_agent.memory.user_memory import get_integrated_memory


class TYMemoryAgent(Assistant):
    """TY个人智能助理 - 基于QwenAgent Assistant
    
    特性：
    - 个人助理定位：在保护隐私前提下提供贴心服务
    - 记忆管理：记住用户信息、偏好、待办事项
    - 智能工具：查询天气、规划行程等实用功能
    - 多用户支持：为不同用户提供个性化服务
    - 隐私保护：严格保护用户个人信息安全
    """
    
    def __init__(self, 
                 function_list: Optional[List[Union[str, Dict, BaseTool]]] = None,
                 llm: Optional[Union[Dict, Any]] = None,
                 system_message: Optional[str] = None,
                 name: Optional[str] = "TY个人智能助理",
                 description: Optional[str] = None,
                 **kwargs):
        
        # 默认系统消息
        if not system_message:
            system_message = self._build_system_message()
        
        if not description:
            description = ("个人智能助理，在保护用户隐私的前提下，"
                          "帮助用户记住待办事项、个人信息及偏好，"
                          "具备智能工具调用能力，可查询天气、规划行程等")
        
        # 默认LLM配置
        if llm is None:
            llm_config = get_llm_config()
            logger.info("=" * 50)
            logger.info("🔑 TYMemoryAgent 使用的API Key信息")
            logger.info("=" * 50)
            logger.info(f"模型类型: {llm_config.get('model_type', 'unknown')}")
            logger.info(f"模型名称: {llm_config.get('model', 'unknown')}")
            logger.info(f"API Key: {llm_config.get('api_key', 'None')[:10]}...")
            if 'model_server' in llm_config:
                logger.info(f"模型服务器: {llm_config.get('model_server', 'None')}")
            logger.info("=" * 50)
            llm = get_chat_model(llm_config)
        
        # 默认工具列表 - 使用QwenAgent内置工具和自定义工具
        if function_list is None:
            function_list = self._get_default_tools()
        
        # 初始化父类
        super().__init__(
            function_list=function_list,
            llm=llm,
            system_message=system_message,
            name=name,
            description=description,
            **kwargs
        )
        
        # 初始化集成记忆系统（包含了memory_manager）
        self.integrated_memory = get_integrated_memory()
        
        # 用户上下文
        self.current_user_id: Optional[str] = None
        self.current_session_id: Optional[str] = None
        
        logger.info(f"✅ 成功创建TY记忆智能代理: {self.name}")
        logger.info(f"✅ 可用工具: {list(self.function_map.keys())}")
    
    def _call_tool(self, tool_name: str, tool_args: Union[str, dict] = '{}', **kwargs) -> Union[str, List[ContentItem]]:
        """重写工具调用方法，自动传递用户上下文
        
        注意：
        1. 只传递 user_id 到 kwargs，不修改 tool_args，避免影响 MCP 工具
        2. 所有工具都接受 **kwargs（BaseTool 的抽象方法要求），所以传递额外的 user_id 是安全的
        3. MCP 工具只使用 params，不使用 kwargs，所以不受影响
        4. 自定义工具可以选择性地使用 kwargs.get("user_id")
        """
        # 如果当前有用户上下文，添加到 kwargs 中
        # 注意：不覆盖已有的 user_id（如果工具已经通过其他方式传递了）
        if self.current_user_id and 'user_id' not in kwargs:
            kwargs['user_id'] = self.current_user_id
        
        # 调用父类方法（会经过 Assistant -> FnCallAgent -> Agent）
        return super()._call_tool(tool_name, tool_args, **kwargs)
    
    def _build_system_message(self) -> str:
        """构建系统消息"""
        # 获取主动性配置
        proactivity_level = self._get_proactivity_level()
        
        base_message = """你是一个个人智能助理，专为AI眼镜、AI耳机等智能穿戴设备设计，在保护用户隐私的前提下，为用户提供贴心服务。

⚡ **核心原则：简洁精炼**
- 回答要简短直接，适合语音播报和快速阅读
- 避免冗长解释，突出关键信息
- 数据类信息（天气、时间等）直接给出结果
- 如果需要详细信息，先给核心答案，再适度补充

"""
        
        if proactivity_level == "passive":
            return base_message + self._get_passive_instructions()
        elif proactivity_level == "moderate":
            return base_message + self._get_moderate_instructions()
        elif proactivity_level == "aggressive":
            return base_message + self._get_aggressive_instructions()
        else:  # proactive (default)
            return base_message + self._get_proactive_instructions()
    
    def _get_proactivity_level(self) -> str:
        """获取主动性级别"""
        try:
            # 从 settings 中读取配置
            from ty_mem_agent.config.settings import settings
            
            proactivity_level = settings.AGENT_PROACTIVITY_LEVEL
            
            # 验证配置值
            valid_levels = ["passive", "moderate", "proactive", "aggressive"]
            if proactivity_level not in valid_levels:
                logger.warning(f"⚠️ 无效的主动性级别: {proactivity_level}，使用默认值: proactive")
                proactivity_level = "proactive"
            
            logger.debug(f"📊 Agent 主动性级别: {proactivity_level}")
            return proactivity_level
            
        except Exception as e:
            logger.warning(f"⚠️ 读取配置失败: {e}，使用默认配置")
            return "proactive"
    
    def _get_passive_instructions(self) -> str:
        """被动模式指令"""
        return """

🧠 记忆管理：
- 记住用户的个人信息、偏好和习惯
- 管理用户的待办事项和重要提醒
- 维护对话上下文，提供连贯的交互体验

👤 **用户画像管理（重要！）**：
当用户纠正或更新其个人信息时，请遵循以下规则：
1. **识别画像更新意图**：当用户说"我不叫XX，我叫YY"、"修改我的年龄/性别等"、"我的信息不对"时
2. **使用专门工具**：使用 `update_user_profile` 工具更新用户画像
3. **不要混淆**：用户画像更新 ≠ 待办事项更新
   - ❌ 错误做法：用户说"我不叫XX"时去修改待办事项中的姓名
   - ✅ 正确做法：用户说"我不叫XX"时只更新用户画像，不要动待办事项
4. **简单直接**：用户通常只想更正自己的个人信息，不需要修改所有相关内容

📝 待办管理：
- 智能识别用户提到的待办事项，自动提取时间、地点、人物、事件等信息
- 当用户说"帮我记个待办"、"添加待办"时，使用extract_todo工具创建待办
- 当用户询问"我今天有什么事"、"明天的日程"时，使用query_todos工具查询
- 支持待办的完成、删除、修改等操作
- 重要：调用待办工具时，必须使用用户的真实user_id

🛠️ 智能工具：
- 查询天气信息，为用户出行提供参考
- 规划行程路线，优化出行方案
- 查询时间和日期，支持不同时区和格式
- 管理待办事项，智能提醒和冲突检测

✈️ **航班和火车票查询规则（重要！）：**
当用户查询航班或火车票信息后，**必须遵循以下规则**：
1. **禁止询问预订**：查询完航班或火车票信息后，**绝对不要**询问"需要我帮您预订机票吗？"或"需要我帮您预订车票吗？"这类问题
2. **直接说明限制**：
   - 查询航班后，直接说明："由于MCP限制，无法直接帮您订购机票，需要您自行在APP上订购"
   - 查询火车票后，直接说明："无法帮您订购火车票，需要您自行在APP上订购"
3. **提供有用信息**：可以提供购票渠道建议（如12306官方APP、航空公司官网等），但不要询问是否需要帮助预订
4. **减少无效沟通**：通过直接说明限制，避免用户产生误解和无效的后续沟通

🚗 **打车服务使用规则（重要！）：**
当用户需要使用打车服务时，必须遵循以下步骤，**确保经纬度精确**：
1. **地理编码**：如果地点没有精确经纬度，必须先调用 `amap_maps-maps_geo` 或 `amap_maps-maps_text_search` 获取精确坐标
2. **使用精确坐标**：调用打车服务工具时，**必须使用**步骤1获取的精确经纬度，不要自己估算或使用记忆中可能不准确的坐标
3. **坐标一致性**：在同一对话中，如果一个地点已经通过工具查询过坐标，后续调用必须使用相同的坐标值

💡 服务原则：
- 严格保护用户隐私，不泄露个人信息
- 只执行用户明确要求的任务，不主动提供建议
- 不主动查询额外信息
- 不主动询问是否需要其他服务
- 保持简洁、直接的服务态度

请根据用户的需求，提供合适的个人助理服务。"""
    
    def _get_moderate_instructions(self) -> str:
        """适中模式指令"""
        return """

🧠 记忆管理：
- 记住用户的个人信息、偏好和习惯
- 管理用户的待办事项和重要提醒
- 维护对话上下文，提供连贯的交互体验

👤 **用户画像管理（重要！）**：
当用户纠正或更新其个人信息时，请遵循以下规则：
1. **识别画像更新意图**：当用户说"我不叫XX，我叫YY"、"修改我的年龄/性别等"、"我的信息不对"时
2. **使用专门工具**：使用 `update_user_profile` 工具更新用户画像
3. **不要混淆**：用户画像更新 ≠ 待办事项更新
   - ❌ 错误做法：用户说"我不叫XX"时去修改待办事项中的姓名
   - ✅ 正确做法：用户说"我不叫XX"时只更新用户画像，不要动待办事项
4. **简单直接**：用户通常只想更正自己的个人信息，不需要修改所有相关内容

📝 待办管理：
- 智能识别用户提到的待办事项，自动提取时间、地点、人物、事件等信息
- 当用户说"帮我记个待办"、"添加待办"时，使用extract_todo工具创建待办
- 当用户询问"我今天有什么事"、"明天的日程"时，使用query_todos工具查询
- 主动检测时间冲突，提醒用户待办安排
- 支持待办的完成、删除、修改等操作
- 重要：调用待办工具时，必须使用用户的真实user_id

🛠️ 智能工具：
- 查询天气信息，为用户出行提供参考
- 规划行程路线，优化出行方案
- 查询时间和日期，支持不同时区和格式
- 管理待办事项，智能提醒和冲突检测

✈️ **航班和火车票查询规则（重要！）：**
当用户查询航班或火车票信息后，**必须遵循以下规则**：
1. **禁止询问预订**：查询完航班或火车票信息后，**绝对不要**询问"需要我帮您预订机票吗？"或"需要我帮您预订车票吗？"这类问题
2. **直接说明限制**：
   - 查询航班后，直接说明："由于MCP限制，无法直接帮您订购机票，需要您自行在APP上订购"
   - 查询火车票后，直接说明："无法帮您订购火车票，需要您自行在APP上订购"
3. **提供有用信息**：可以提供购票渠道建议（如12306官方APP、航空公司官网等），但不要询问是否需要帮助预订
4. **减少无效沟通**：通过直接说明限制，避免用户产生误解和无效的后续沟通

🚗 **打车服务使用规则（重要！）：**
当用户需要使用打车服务时，必须遵循以下步骤，**确保经纬度精确**：
1. **地理编码**：如果地点没有精确经纬度，必须先调用 `amap_maps-maps_geo` 或 `amap_maps-maps_text_search` 获取精确坐标
2. **使用精确坐标**：调用打车服务工具时，**必须使用**步骤1获取的精确经纬度，不要自己估算或使用记忆中可能不准确的坐标
3. **坐标一致性**：在同一对话中，如果一个地点已经通过工具查询过坐标，后续调用必须使用相同的坐标值

💡 服务原则：
- 严格保护用户隐私，不泄露个人信息
- 适度主动：在明显需要时提供少量建议
- 不主动查询额外信息，除非用户明确要求
- 可以询问是否需要相关服务，但不要过度
- 保持友好、专业、贴心的服务态度

请根据用户的需求，提供合适的个人助理服务。"""
    
    def _get_proactive_instructions(self) -> str:
        """主动模式指令"""
        return """

🎯 核心理念：**主动、智能、全面**
不要只是被动地完成用户的明确要求，而要：
1. **理解完整情境**：思考用户需求背后的完整场景
2. **主动发现需求**：识别用户可能需要但没有明说的帮助
3. **立即执行查询**：对于可以直接查询的信息，立即调用工具获取
4. **主动询问确认**：对于需要更多参数的服务，主动询问用户

🧠 记忆管理：
- 记住用户的个人信息、偏好和习惯
- 管理用户的待办事项和重要提醒
- 维护对话上下文，提供连贯的交互体验
- 为不同用户提供个性化服务

👤 **用户画像管理（重要！）**：
当用户纠正或更新其个人信息时，请遵循以下规则：
1. **识别画像更新意图**：当用户说"我不叫XX，我叫YY"、"修改我的年龄/性别等"、"我的信息不对"时
2. **使用专门工具**：使用 `update_user_profile` 工具更新用户画像
3. **不要混淆**：用户画像更新 ≠ 待办事项更新
   - ❌ 错误做法：用户说"我不叫XX"时去修改待办事项中的姓名
   - ✅ 正确做法：用户说"我不叫XX"时只更新用户画像，不要动待办事项
4. **简单直接**：用户通常只想更正自己的个人信息，不需要修改所有相关内容

📝 待办管理（主动式）：
- 智能识别用户提到的待办事项，自动提取时间、地点、人物、事件等信息
- 当用户说"帮我记个待办"、"添加待办"时，使用extract_todo工具创建待办
- **创建待办后，主动分析相关需求**：
  * 如果涉及旅行（机票、火车等），主动询问是否需要：
    - 查询目的地天气
    - 安排接送机/接送站服务
    - 预订酒店
    - 推荐旅游路线和景点
    - 了解出行天数以便更好规划
  * 如果涉及会议，主动询问是否需要：
    - 准备会议资料
    - 提醒参会人员
    - 预订会议室
  * 如果涉及活动，主动询问是否需要：
    - 查询活动地点天气
    - 规划交通路线
    - 设置提醒
- 当用户询问"我今天有什么事"、"明天的日程"时，使用query_todos工具查询
- 主动检测时间冲突，提醒用户待办安排
- 支持待办的完成、删除、修改等操作
- 重要：调用待办工具时，必须使用用户的真实user_id

🛠️ 主动工具调用：
你拥有以下工具，要**积极主动地使用**：
- **天气查询**：发现用户提到出行、旅游、活动时，**立即查询**目的地天气，不要询问
- **时间查询**：需要时间信息时，立即调用
- **地图导航**：涉及地点时，主动提供路线规划
- **待办管理**：智能提醒和冲突检测

✈️ **航班和火车票查询规则（重要！）：**
当用户查询航班或火车票信息后，**必须遵循以下规则**：
1. **禁止询问预订**：查询完航班或火车票信息后，**绝对不要**询问"需要我帮您预订机票吗？"或"需要我帮您预订车票吗？"这类问题
2. **直接说明限制**：
   - 查询航班后，直接说明："由于MCP限制，无法直接帮您订购机票，需要您自行在APP上订购"
   - 查询火车票后，直接说明："无法帮您订购火车票，需要您自行在APP上订购"
3. **提供有用信息**：可以提供购票渠道建议（如12306官方APP、航空公司官网等），但不要询问是否需要帮助预订
4. **减少无效沟通**：通过直接说明限制，避免用户产生误解和无效的后续沟通

🚗 **打车服务使用规则（重要！）：**
当用户需要使用打车服务时，必须遵循以下步骤，**确保经纬度精确**：

1. **地理编码**：如果地点没有精确经纬度，必须先调用 `amap_maps-maps_geo` 或 `amap_maps-maps_text_search` 获取精确坐标
2. **查看工具返回结果**：**必须仔细查看**之前工具调用的返回结果，找到精确的经纬度坐标值
   - `maps_geo` 返回的 `location` 字段格式为 "经度,纬度"，需要**拆分使用**
   - 例如：`"location": "106.513175,29.551821"` → 经度=106.513175，纬度=29.551821
3. **使用精确坐标**：调用打车服务工具时，**必须完全复制**步骤1中工具返回的精确经纬度，**禁止**：
   - ❌ 自己估算或编造经纬度
   - ❌ 使用记忆中可能过时的坐标
   - ❌ 使用类似地点的坐标替代
   - ❌ 修改或近似处理坐标值
4. **坐标一致性**：在同一对话中，如果一个地点已经通过工具查询过坐标，后续调用**必须使用完全相同**的坐标值

**重要提醒**：
- **工具返回的坐标是唯一可信来源**，禁止自己编造
- 如果之前已调用过地理编码工具，**必须查看对话历史中的工具返回结果**并使用
- 如果不确定坐标，**必须重新调用**地理编码工具

**正确示例：**
用户："帮我叫车回家"
步骤1：调用 `amap_maps-maps_geo` 查询"万科锦绣滨江" 
      返回：`{"location": "106.513175,29.551821"}` ← **查看这个返回值！**
步骤2：**从返回结果中提取**：经度=106.513175，纬度=29.551821
步骤3：调用打车服务工具（如 `Didi-Ride-taxi_estimate` 进行价格预估，然后可引导用户使用滴滴等支持直接下单的服务）时使用：
      `dlon: "106.513175", dlat: "29.551821"` ✅

**可用打车服务：**
- **滴滴打车**：支持价格预估，可在穿戴设备场景下使用，通过API直接创建订单
- 优先推荐使用滴滴等支持API直接下单的服务，避免需要跳转到手机APP

💡 主动服务原则：
1. **立即执行**：能直接查询的信息（如天气），立即调用工具获取，不要问用户
2. **主动建议**：基于情境，主动提供相关的服务建议
3. **询问参数**：需要更多信息才能执行的服务，主动询问用户
4. **情境感知**：理解用户真正的需求，不要只看表面
5. **一次到位**：尽量在一次回复中提供完整的帮助
6. **友好专业**：保持助理的专业性和亲和力

⚡ 主动服务示例：
用户："帮我添加待办，本周五18:45的飞机，从北京到重庆江北机场"

**正确做法**：
1. 创建待办事项
2. **立即调用天气工具查询重庆天气**（不要询问）
3. 主动建议相关服务（接送机、酒店、景点等）
4. 询问用户具体需求

**错误做法**：
- 询问是否需要查询天气（应该直接查询）
- 只创建待办不提供其他服务

🔐 隐私保护：
- 严格保护用户隐私，不泄露个人信息
- 主动利用记忆信息提供个性化服务
- 根据用户偏好调整服务风格和内容

请记住：你是一位**积极主动**的智能助理，要像真人助理一样思考和行动，为用户提供超出期望的服务体验！"""
    
    def _get_aggressive_instructions(self) -> str:
        """激进模式指令"""
        return """

🎯 核心理念：**极度主动、全面服务**
要像最贴心的私人助理一样，不仅完成用户的要求，还要：
1. **深度理解情境**：分析用户需求的完整背景和潜在需求
2. **主动发现机会**：识别所有可能的服务机会
3. **立即执行所有查询**：对于任何相关信息，立即调用工具获取
4. **提供全面建议**：基于情境提供详细的服务建议和选择

🧠 记忆管理：
- 深度记住用户的个人信息、偏好和习惯
- 管理用户的待办事项和重要提醒
- 维护对话上下文，提供连贯的交互体验
- 为不同用户提供高度个性化服务

👤 **用户画像管理（重要！）**：
当用户纠正或更新其个人信息时，请遵循以下规则：
1. **识别画像更新意图**：当用户说"我不叫XX，我叫YY"、"修改我的年龄/性别等"、"我的信息不对"时
2. **使用专门工具**：使用 `update_user_profile` 工具更新用户画像
3. **不要混淆**：用户画像更新 ≠ 待办事项更新
   - ❌ 错误做法：用户说"我不叫XX"时去修改待办事项中的姓名
   - ✅ 正确做法：用户说"我不叫XX"时只更新用户画像，不要动待办事项
4. **简单直接**：用户通常只想更正自己的个人信息，不需要修改所有相关内容

📝 待办管理（极度主动）：
- 智能识别用户提到的待办事项，自动提取时间、地点、人物、事件等信息
- 当用户说"帮我记个待办"、"添加待办"时，使用extract_todo工具创建待办
- **创建待办后，深度分析并提供全面服务**：
  * 如果涉及旅行（机票、火车等），立即提供：
    - 查询目的地天气（详细预报）
    - 推荐接送机/接送站服务（多个选项）
    - 推荐酒店（不同价位和位置）
    - 推荐旅游路线和景点（详细攻略）
    - 推荐当地美食和餐厅
    - 提供交通路线规划
    - 询问出行天数并制定详细行程
  * 如果涉及会议，立即提供：
    - 准备会议资料的建议
    - 通知参会人员的方案
    - 预订会议室的选项
    - 会议议程建议
    - 后续跟进提醒
  * 如果涉及活动，立即提供：
    - 查询活动地点天气
    - 规划最佳交通路线
    - 设置多个提醒时间
    - 推荐相关活动
- 当用户询问"我今天有什么事"、"明天的日程"时，使用query_todos工具查询
- 主动检测时间冲突，提醒用户待办安排
- 支持待办的完成、删除、修改等操作
- 重要：调用待办工具时，必须使用用户的真实user_id

🛠️ 极度主动工具调用：
你拥有以下工具，要**极度主动地使用**：
- **天气查询**：发现任何涉及地点、时间的信息，立即查询详细天气，提供完整预报
- **时间查询**：需要任何时间信息时，立即调用
- **地图导航**：涉及任何地点时，主动提供详细路线规划
- **待办管理**：智能提醒和冲突检测
- **其他工具**：根据情境主动调用所有可用工具

✈️ **航班和火车票查询规则（重要！）：**
当用户查询航班或火车票信息后，**必须遵循以下规则**：
1. **禁止询问预订**：查询完航班或火车票信息后，**绝对不要**询问"需要我帮您预订机票吗？"或"需要我帮您预订车票吗？"这类问题
2. **直接说明限制**：
   - 查询航班后，直接说明："由于MCP限制，无法直接帮您订购机票，需要您自行在APP上订购"
   - 查询火车票后，直接说明："无法帮您订购火车票，需要您自行在APP上订购"
3. **提供有用信息**：可以提供购票渠道建议（如12306官方APP、航空公司官网等），但不要询问是否需要帮助预订
4. **减少无效沟通**：通过直接说明限制，避免用户产生误解和无效的后续沟通

🚗 **打车服务使用规则（重要！）：**
当用户需要使用打车服务时，必须遵循以下步骤，**确保经纬度精确**：

1. **地理编码**：如果地点没有精确经纬度，必须先调用 `amap_maps-maps_geo` 或 `amap_maps-maps_text_search` 获取精确坐标
2. **查看工具返回结果**：**必须仔细查看**之前工具调用的返回结果，找到精确的经纬度坐标值
   - `maps_geo` 返回的 `location` 字段格式为 "经度,纬度"，需要**拆分使用**
   - 例如：`"location": "106.513175,29.551821"` → 经度=106.513175，纬度=29.551821
3. **使用精确坐标**：调用打车服务工具时，**必须完全复制**步骤1中工具返回的精确经纬度，**禁止**：
   - ❌ 自己估算或编造经纬度
   - ❌ 使用记忆中可能过时的坐标
   - ❌ 使用类似地点的坐标替代
   - ❌ 修改或近似处理坐标值
4. **坐标一致性**：在同一对话中，如果一个地点已经通过工具查询过坐标，后续调用**必须使用完全相同**的坐标值

**重要提醒**：
- **工具返回的坐标是唯一可信来源**，禁止自己编造
- 如果之前已调用过地理编码工具，**必须查看对话历史中的工具返回结果**并使用
- 如果不确定坐标，**必须重新调用**地理编码工具

**正确示例：**
用户："帮我叫车回家"
步骤1：调用 `amap_maps-maps_geo` 查询"万科锦绣滨江" 
      返回：`{"location": "106.513175,29.551821"}` ← **查看这个返回值！**
步骤2：**从返回结果中提取**：经度=106.513175，纬度=29.551821
步骤3：调用打车服务工具时使用：
      `dlon: "106.513175", dlat: "29.551821"` ✅

⚡ 极度主动服务示例：
用户："帮我添加待办，本周五18:45的飞机，从北京到重庆江北机场"

**极度主动做法**：
1. 创建待办事项
2. **立即调用天气工具查询重庆详细天气**（包括未来几天预报）
3. **立即查询北京到重庆的交通路线**
4. **主动推荐多个接送机服务选项**
5. **主动推荐不同价位的酒店**
6. **主动推荐重庆热门景点和美食**
7. **询问出行天数并制定详细行程**
8. **提供完整的旅行攻略**

**不要询问，直接执行所有能执行的查询！**

💡 极度主动服务原则：
1. **立即执行所有查询**：能查询的任何信息，立即调用工具获取
2. **提供全面建议**：基于情境，提供详细的服务建议和多个选择
3. **主动询问所有参数**：对于任何服务，主动询问所有可能的参数
4. **深度情境感知**：理解用户真正的需求，提供超出期望的服务
5. **一次提供完整服务**：尽量在一次回复中提供所有可能的帮助
6. **极度友好专业**：保持最贴心的服务态度

🔐 隐私保护：
- 严格保护用户隐私，不泄露个人信息
- 主动利用记忆信息提供高度个性化服务
- 根据用户偏好调整服务风格和内容

请记住：你是一位**极度主动**的智能助理，要像最贴心的私人助理一样，为用户提供超出期望的全面服务体验！"""
    
    def _get_default_tools(self) -> List[Union[str, Dict, BaseTool]]:
        """获取默认工具列表（从工具注册中心获取）"""
        try:
            from ty_mem_agent.mcp_integrations import get_tool_registry
            
            # 从工具注册中心获取所有已初始化的工具
            registry = get_tool_registry()
            
            # 检查工具注册中心是否已初始化
            if not registry._initialized or not registry.tools_cache:
                logger.warning("⚠️ 工具注册中心未初始化或工具缓存为空")
                logger.warning("   Agent 将在没有工具的情况下运行")
                logger.warning("   请确保应用启动时正确调用了 initialize_tools()")
                return []
            
            # 获取所有工具
            tools = registry.get_all_tools()
            
            if tools:
                logger.info(f"✅ Agent 从工具注册中心获取到 {len(tools)} 个工具")
                tool_names = [getattr(t, 'name', 'unknown') for t in tools]
                logger.debug(f"   工具列表: {', '.join(tool_names)}")
            else:
                logger.warning("⚠️ 工具注册中心未返回任何工具")
            
            return tools
            
        except Exception as e:
            logger.error(f"❌ 从工具注册中心获取工具失败: {e}")
            logger.error("   Agent 将在没有工具的情况下运行")
            return []
    
    async def run_with_memory(self, 
                       messages: List[Any], 
                       user_id: str = "default_user",
                       session_id: str = "default_session",
                       **kwargs):
        """带记忆的对话运行（异步）"""
        try:
            # 设置当前用户上下文（用于工具调用时自动传递）
            self.current_user_id = user_id
            self.current_session_id = session_id
            
            # 提取用户的原始query
            user_query = ""
            # 规范化消息列表：确保第一条非系统消息是 USER 角色
            normalized_messages = self._normalize_messages(messages)
            
            for msg in normalized_messages:
                if msg.role == USER and isinstance(msg.content, str):
                    user_query = msg.content
                    break
            
            # 获取用户记忆（传入用户原始query）
            user_memory = await self._get_user_memory(user_id, session_id, user_query)
            logger.debug(f"🔍 获取用户记忆: {user_memory}")
            
            # 构建带记忆的消息（使用规范化后的消息列表）
            enhanced_messages = self._enhance_messages_with_memory(normalized_messages, user_memory, user_id)
            logger.debug(f"🔍 构建带记忆的消息: {enhanced_messages}")
            
            # 记录发送给LLM的完整提示词
            logger.info("=" * 80)
            logger.info("📝 发送给LLM的完整提示词:")
            logger.info("=" * 80)
            for i, msg in enumerate(enhanced_messages):
                logger.info(f"消息 {i+1} [{msg.role}]:")
                logger.info(f"{msg.content}")
                logger.info("-" * 40)
            logger.info("=" * 80)
            
            # 运行对话
            logger.info("🔍 开始调用LLM...")
            logger.info(f"🔍 当前LLM配置: {getattr(self.llm, '__class__', 'Unknown')}")
            logger.info(f"🔍 LLM类型: {type(self.llm)}")
            
            response = []
            for chunk in self.run(messages=enhanced_messages, **kwargs):
                response = chunk
                yield chunk
            
            # 更新用户记忆（异步）
            # 使用规范化后的消息列表，确保消息格式正确
            await self._update_user_memory(user_id, session_id, normalized_messages, response)
            
        except Exception as e:
            logger.error(f"❌ 带记忆对话运行失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 回退到普通对话
            for chunk in self.run(messages=messages, **kwargs):
                yield chunk
    
    async def _get_user_memory(self, user_id: str, session_id: str, user_query: str = "") -> Dict[str, Any]:
        """获取用户记忆（结合本地和远程记忆）
        
        Args:
            user_id: 用户ID
            session_id: 会话ID
            user_query: 用户的原始查询内容
        """
        try:
            # 1. 获取用户基本信息（本地）
            user_profile = self.integrated_memory.user_manager.get_user_profile(user_id)
            
            # 2. 获取对话上下文（本地）
            conversation_context = self.integrated_memory.user_manager.get_conversation_context(session_id)
            
            # 3. 提取最近的对话历史（本地）
            conversation_history = []
            if conversation_context and conversation_context.conversation_history:
                conversation_history = conversation_context.conversation_history[-5:]  # 最近5条
            
            # 4. 获取相关记忆（远程 + 本地缓存）
            relevant_memories = []
            try:
                # 构建查询：结合用户原始query和提取的topic
                # 优先使用用户原始query，如果topic存在则追加作为补充
                query_parts = []
                
                if user_query:
                    query_parts.append(user_query)
                
                # 如果有提取的topic，作为补充信息
                if conversation_context and conversation_context.current_topic:
                    # 避免重复：只有当topic不在用户query中时才添加
                    if conversation_context.current_topic not in user_query:
                        query_parts.append(conversation_context.current_topic)
                
                # 组合查询字符串
                combined_query = " ".join(query_parts) if query_parts else ""
                
                logger.debug(f"🔍 组合查询: user_query='{user_query}', topic='{conversation_context.current_topic if conversation_context else ''}', combined='{combined_query}'")
                
                # 使用组合查询获取相关记忆
                if combined_query:
                    relevant_memories = await self.integrated_memory.remote_memory.get_relevant_memories(
                        user_id, 
                        combined_query,
                        session_id=session_id,
                        context=""
                    )
                    logger.debug(f"🔍 获取到 {len(relevant_memories)} 条相关记忆")
                else:
                    logger.debug("🔍 没有有效的查询内容，跳过远程记忆检索")
                    
            except Exception as e:
                logger.warning(f"⚠️ 获取相关记忆失败: {e}")
                relevant_memories = []
            
            # 5. 获取记忆洞察（本地）
            insights = self.integrated_memory.user_manager.get_memory_insights(user_id, limit=5)
            
            return {
                "user_profile": user_profile,
                "conversation_history": conversation_history,
                "conversation_context": conversation_context,
                "relevant_memories": relevant_memories,  # 新增：相关记忆
                "insights": insights,  # 新增：记忆洞察
                "session_id": session_id
            }
        except Exception as e:
            logger.warning(f"⚠️ 获取用户记忆失败: {e}")
            return {}
    
    def _enhance_messages_with_memory(self, messages: List[Message], user_memory: Dict[str, Any], user_id: str = None) -> List[Message]:
        """用记忆增强消息"""
        try:
            enhanced_messages = messages.copy()
            
            # 添加用户记忆信息到第一条消息
            if enhanced_messages and user_memory:
                memory_context = self._format_memory_context(user_memory, user_id)
                if memory_context:
                    # 在第一条消息前添加记忆上下文
                    memory_message = Message(
                        role=SYSTEM,
                        content=f"用户记忆信息：\n{memory_context}"
                    )
                    enhanced_messages.insert(0, memory_message)
                    
                    # 修复：确保系统消息之后的第一条消息是 USER 角色
                    # LLM API要求（除了系统消息外）必须以 USER 消息开始
                    if len(enhanced_messages) > 1:
                        first_non_system_msg = enhanced_messages[1]
                        if first_non_system_msg.role != USER:
                            # 查找第一条 USER 消息
                            first_user_idx = None
                            for i, msg in enumerate(enhanced_messages[1:], start=1):
                                if msg.role == USER:
                                    first_user_idx = i
                                    break
                            
                            if first_user_idx is not None and first_user_idx > 1:
                                # 如果找到 USER 消息且不在第二个位置，需要调整顺序
                                # 将 SYSTEM 消息保留在第一位，USER 消息移到第二位
                                user_msg = enhanced_messages.pop(first_user_idx)
                                enhanced_messages.insert(1, user_msg)
                                logger.debug(f"🔧 调整消息顺序：将 USER 消息移到 SYSTEM 消息之后")
                            else:
                                # 如果没有找到 USER 消息，这是一个错误情况
                                # 移除刚才插入的 SYSTEM 消息，保持原样
                                logger.warning(f"⚠️ 警告：消息列表中没有找到 USER 消息，移除记忆增强")
                                enhanced_messages.pop(0)
            
            return enhanced_messages
        except Exception as e:
            logger.warning(f"⚠️ 记忆增强失败: {e}")
            return messages
    
    def _normalize_messages(self, messages: List[Message]) -> List[Message]:
        """规范化消息列表，确保符合LLM API要求
        
        LLM API要求（除了系统消息外）必须以 USER 消息开始。
        如果传入的消息列表以 ASSISTANT 开始，需要找到第一条 USER 消息并截取。
        """
        try:
            if not messages:
                return messages
            
            # 查找第一条 USER 消息的位置
            first_user_idx = None
            for i, msg in enumerate(messages):
                if msg.role == USER:
                    first_user_idx = i
                    break
            
            # 如果第一条消息就是 USER 或者没找到 USER 消息，直接返回
            if first_user_idx is None or first_user_idx == 0:
                return messages
            
            # 如果第一条非系统消息不是 USER，需要截取从第一条 USER 消息开始的部分
            # 但保留前面的 SYSTEM 消息（如果有）
            normalized = []
            
            # 保留所有 SYSTEM 消息
            for msg in messages[:first_user_idx]:
                if msg.role == SYSTEM:
                    normalized.append(msg)
            
            # 从第一条 USER 消息开始截取
            normalized.extend(messages[first_user_idx:])
            
            if len(normalized) < len(messages):
                logger.debug(f"🔧 规范化消息列表：从 {len(messages)} 条消息截取为 {len(normalized)} 条（第一条 USER 消息在位置 {first_user_idx}）")
            
            return normalized
            
        except Exception as e:
            logger.warning(f"⚠️ 消息规范化失败: {e}")
            return messages
    
    def _format_memory_context(self, user_memory: Dict[str, Any], user_id: str = None) -> str:
        """格式化记忆上下文"""
        try:
            context_parts = []
            
            # 1. 用户基本信息
            user_profile = user_memory.get("user_profile", {})
            if user_profile:
                profile_info = []
                if hasattr(user_profile, 'user_id') and user_profile.user_id:
                    profile_info.append(f"用户ID: {user_profile.user_id}")
                if hasattr(user_profile, 'name') and user_profile.name:
                    profile_info.append(f"姓名: {user_profile.name}")
                if hasattr(user_profile, 'age') and user_profile.age:
                    profile_info.append(f"年龄: {user_profile.age}")
                if hasattr(user_profile, 'location') and user_profile.location:
                    profile_info.append(f"位置: {user_profile.location}")
                if hasattr(user_profile, 'occupation') and user_profile.occupation:
                    profile_info.append(f"职业: {user_profile.occupation}")
                if hasattr(user_profile, 'interests') and user_profile.interests:
                    profile_info.append(f"兴趣: {', '.join(user_profile.interests)}")
                if profile_info:
                    context_parts.append(f"用户画像: {'; '.join(profile_info)}")
            elif user_id:
                context_parts.append(f"用户ID: {user_id}")
            
            # 2. 对话历史
            conversation_history = user_memory.get("conversation_history", [])
            if conversation_history:
                recent_topics = []
                for conv in conversation_history[-3:]:  # 最近3条对话
                    if isinstance(conv, dict) and conv.get('context', {}).get('topic'):
                        recent_topics.append(conv['context']['topic'])
                if recent_topics:
                    context_parts.append(f"最近话题: {', '.join(recent_topics)}")
            
            # 3. 相关记忆（新增）
            relevant_memories = user_memory.get("relevant_memories", [])
            if relevant_memories:
                memory_summaries = []
                for memory in relevant_memories[:5]:  # 最多5条相关记忆
                    if isinstance(memory, dict):
                        # 从MemOS返回的记忆使用memory_value和memory_key字段
                        memory_key = memory.get('memory_key', '')
                        memory_value = memory.get('memory_value', memory.get('content', ''))
                        
                        if memory_value:
                            # 格式化记忆内容
                            memory_text = f"{memory_key}: {memory_value}" if memory_key else memory_value
                            # 截断过长的内容
                            if len(memory_text) > 150:
                                memory_text = memory_text[:150] + "..."
                            memory_summaries.append(memory_text)
                
                if memory_summaries:
                    context_parts.append(f"\n相关历史记忆:\n" + "\n".join([f"- {m}" for m in memory_summaries]))
            
            # 4. 记忆洞察
            insights = user_memory.get("insights", [])
            if insights:
                insight_summaries = []
                
                # 4.1 常见话题分析
                topics = []
                for insight in insights:
                    if isinstance(insight, dict) and insight.get('type') == 'conversation':
                        data = insight.get('data', {})
                        topic = data.get('topic') if isinstance(data, dict) else None
                        if topic and topic != '未分类':
                            topics.append(topic)
                
                if topics:
                    # 统计最常见的话题（使用Counter）
                    from collections import Counter
                    topic_counts = Counter(topics)
                    common_topics = topic_counts.most_common(3)
                    if common_topics:
                        topic_str = ', '.join([f"{t}({c}次)" for t, c in common_topics])
                        insight_summaries.append(f"常讨论: {topic_str}")
                
                # 4.2 用户意图分析（最近5条）
                recent_intents = []
                for insight in insights[:5]:
                    if isinstance(insight, dict) and insight.get('type') == 'conversation':
                        data = insight.get('data', {})
                        intent = data.get('intent') if isinstance(data, dict) else None
                        if intent:
                            recent_intents.append(intent)
                
                if recent_intents:
                    unique_intents = list(set(recent_intents))[:3]
                    insight_summaries.append(f"最近意图: {', '.join(unique_intents)}")
                
                # 4.3 智能分析结果
                for insight in insights:
                    if isinstance(insight, dict) and insight.get('type') == 'smart_analysis':
                        data = insight.get('data', {})
                        if isinstance(data, dict):
                            # 话题偏好
                            topic_dist = data.get('topic_distribution', {})
                            if topic_dist and isinstance(topic_dist, dict):
                                top_topics = list(topic_dist.keys())[:3]
                                if top_topics:
                                    insight_summaries.append(f"话题偏好: {', '.join(top_topics)}")
                            
                            # 时间模式
                            time_patterns = data.get('time_patterns', [])
                            if time_patterns and isinstance(time_patterns, list):
                                insight_summaries.append(f"活跃时段: {', '.join(time_patterns[:3])}")
                            
                            # 交互风格
                            style = data.get('interaction_style')
                            if style:
                                insight_summaries.append(f"交互风格: {style}")
                        break  # 只使用最新的智能分析
                
                # 4.4 模式分析结果
                for insight in insights:
                    if isinstance(insight, dict) and insight.get('type') == 'pattern_analysis':
                        data = insight.get('data', {})
                        if isinstance(data, dict):
                            common_topics = data.get('common_topics', [])
                            if common_topics and isinstance(common_topics, list):
                                topics_str = ', '.join([str(t[0]) for t in common_topics[:3] if isinstance(t, (list, tuple))])
                                if topics_str:
                                    insight_summaries.append(f"模式: {topics_str}")
                        break  # 只使用最新的模式分析
                
                if insight_summaries:
                    context_parts.append("用户行为洞察:\n  • " + "\n  • ".join(insight_summaries))
            
            return "\n".join(context_parts) if context_parts else ""
        except Exception as e:
            logger.warning(f"⚠️ 格式化记忆上下文失败: {e}")
            return ""
    
    async def _update_user_memory(self, 
                           user_id: str, 
                           session_id: str, 
                           messages: List[Message], 
                           response: List[Message]):
        """更新用户记忆"""
        try:
            # 提取最后一条用户消息和助手回复
            user_message = ""
            assistant_response = ""
            
            for msg in messages:
                if isinstance(msg, Message) and msg.role == USER:
                    user_message = msg.content if isinstance(msg.content, str) else str(msg.content)
            
            if response and len(response) > 0:
                last_response = response[-1]
                if isinstance(last_response, Message):
                    assistant_response = last_response.content if isinstance(last_response.content, str) else str(last_response.content)
            
            # 保存对话到记忆系统
            if user_message and assistant_response:
                await self.integrated_memory.save_conversation(
                    user_id, session_id, user_message, assistant_response
            )
            
            # 检查并触发智能洞察分析
            insight_result = await self.check_and_trigger_insights(user_id)
            if insight_result.get("triggered") and insight_result.get("message"):
                logger.info(f"💡 洞察触发成功: {insight_result['message']}")
                # TODO: 可选择将洞察建议推送给用户
            
            # 分析并更新用户偏好
            self._analyze_user_preferences(user_id, messages, response)
            
        except Exception as e:
            logger.warning(f"⚠️ 更新用户记忆失败: {e}")
    
    def _analyze_user_preferences(self, 
                                 user_id: str, 
                                 messages: List[Message], 
                                 response: List[Message]):
        """分析用户偏好"""
        try:
            # 简单的偏好分析逻辑
            # 实际应用中可以使用更复杂的NLP分析
            
            # 检查是否使用了工具
            tool_usage = []
            for msg in response:
                if isinstance(msg, Message) and msg.function_call:
                    tool_usage.append(msg.function_call.name)
            
            if tool_usage:
                # 更新用户工具使用偏好
                # 使用user_manager的update_user_profile方法
                preferences_update = {
                    "preferences": {
                        "preferred_tools": tool_usage,
                        "last_tool_usage": tool_usage[-1] if tool_usage else None
                    }
                }
                self.integrated_memory.user_manager.update_user_profile(
                    user_id, preferences_update
                )
                logger.debug(f"📊 更新用户工具偏好: {user_id} - {tool_usage}")
                
        except Exception as e:
            logger.warning(f"⚠️ 分析用户偏好失败: {e}")
    
    async def set_user_context(self, user_id: str, session_id: str):
        """设置用户上下文"""
        self.current_user_id = user_id
        self.current_session_id = session_id
        logger.info(f"📝 设置用户上下文: user={user_id}, session={session_id}")
    
    async def get_user_summary(self, user_id: str) -> Dict[str, Any]:
        """获取用户摘要"""
        try:
            # 获取用户画像
            profile = self.integrated_memory.user_manager.get_user_profile(user_id)
            
            # 获取最近的记忆洞察
            insights = self.integrated_memory.user_manager.get_memory_insights(user_id, limit=5)
            
            # 统计信息
            conversation_insights = [i for i in insights if i["type"] == "conversation"]
            
            return {
                "user_profile": asdict(profile) if profile else {},
                "total_insights": len(insights),
                "conversation_count": len(conversation_insights),
                "recent_insights": insights
            }
        except Exception as e:
            logger.error(f"❌ 获取用户摘要失败: {e}")
            return {}
    
    async def generate_smart_insights(self, user_id: str) -> Dict[str, Any]:
        """生成智能洞察
        
        基于历史对话洞察，分析用户行为模式，生成个性化建议
        """
        try:
            # 获取最近50条洞察
            insights = self.integrated_memory.user_manager.get_memory_insights(user_id, limit=50)
            
            if not insights:
                logger.info(f"用户 {user_id} 暂无洞察数据")
                return {}
            
            analysis = {
                "topic_distribution": {},      # 话题分布
                "time_patterns": [],           # 时间模式
                "interaction_style": "",       # 交互风格
                "entity_frequency": {},        # 实体频率
                "suggestions": []              # 个性化建议
            }
            
            # 1. 话题分布分析
            topics = []
            intents = []
            entities = []
            time_hours = []
            
            for insight in insights:
                if not isinstance(insight, dict):
                    continue
                    
                insight_type = insight.get('type')
                data = insight.get('data', {})
                
                if insight_type == 'conversation' and isinstance(data, dict):
                    # 提取话题
                    topic = data.get('topic')
                    if topic and topic != '未分类':
                        topics.append(topic)
                    
                    # 提取意图
                    intent = data.get('intent')
                    if intent:
                        intents.append(intent)
                    
                    # 提取实体
                    insight_entities = data.get('entities', [])
                    if isinstance(insight_entities, list):
                        entities.extend(insight_entities)
                    
                    # 提取时间
                    timestamp = data.get('timestamp') or insight.get('created_at')
                    if timestamp:
                        try:
                            dt = datetime.fromisoformat(timestamp)
                            time_hours.append(dt.hour)
                        except:
                            pass
            
            # 统计话题分布
            if topics:
                from collections import Counter
                topic_counts = Counter(topics)
                analysis["topic_distribution"] = dict(topic_counts.most_common(10))
                logger.debug(f"📊 话题分布: {analysis['topic_distribution']}")
            
            # 统计时间模式
            if time_hours:
                from collections import Counter
                hour_counts = Counter(time_hours)
                peak_hours = hour_counts.most_common(3)
                analysis["time_patterns"] = [f"{h}:00" for h, _ in peak_hours]
                logger.debug(f"⏰ 活跃时段: {analysis['time_patterns']}")
            
            # 统计交互风格（基于意图）
            if intents:
                from collections import Counter
                intent_counts = Counter(intents)
                dominant_intent = intent_counts.most_common(1)[0]
                analysis["interaction_style"] = f"{dominant_intent[0]}({dominant_intent[1]}次)"
                logger.debug(f"🎯 交互风格: {analysis['interaction_style']}")
            
            # 统计实体频率
            if entities:
                from collections import Counter
                entity_counts = Counter(entities)
                analysis["entity_frequency"] = dict(entity_counts.most_common(10))
                logger.debug(f"🏷️  实体频率: {analysis['entity_frequency']}")
            
            # 4. 生成个性化建议
            suggestions = []
            
            # 建议1: 基于话题偏好
            if analysis["topic_distribution"]:
                top_topics = list(analysis["topic_distribution"].items())[:3]
                topics_str = "、".join([f"{t}({c}次)" for t, c in top_topics])
                suggestions.append(f"您经常讨论{topics_str}，我可以为您提供这些领域的深度信息")
            
            # 建议2: 基于时间模式
            if analysis["time_patterns"]:
                peak_time = analysis["time_patterns"][0]
                suggestions.append(f"您通常在{peak_time}左右活跃，我可以在这个时间主动提醒重要事项")
            
            # 建议3: 基于实体频率
            if analysis["entity_frequency"]:
                top_entity = list(analysis["entity_frequency"].items())[0]
                suggestions.append(f"您经常提到'{top_entity[0]}'，可以为您设置相关的快捷操作")
            
            # 建议4: 基于对话数量
            conversation_count = len([i for i in insights if i.get('type') == 'conversation'])
            if conversation_count >= 20:
                suggestions.append(f"已记录{conversation_count}次对话，我越来越了解您的需求了")
            
            analysis["suggestions"] = suggestions
            
            # 5. 保存智能洞察
            self.integrated_memory.user_manager.save_memory_insight(
                user_id,
                "smart_analysis",
                analysis,
                confidence=0.9
            )
            
            logger.info(f"🧠 生成智能洞察成功: user={user_id}, 话题数={len(analysis['topic_distribution'])}, 建议数={len(suggestions)}")
            return analysis
            
        except Exception as e:
            logger.error(f"❌ 生成智能洞察失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {}
    
    async def check_and_trigger_insights(self, user_id: str) -> Dict[str, Any]:
        """检查并触发洞察分析
        
        根据对话数量等条件，自动触发智能洞察分析
        """
        try:
            # 获取对话洞察统计
            insights = self.integrated_memory.user_manager.get_memory_insights(user_id)
            conversation_insights = [i for i in insights if i.get('type') == 'conversation']
            conversation_count = len(conversation_insights)
            
            # 检查是否已有智能分析
            smart_insights = [i for i in insights if i.get('type') == 'smart_analysis']
            last_analysis_count = 0
            
            if smart_insights:
                # 获取上次分析时的对话数量（从洞察数据推断）
                last_analysis_count = conversation_count - 10  # 估计值
            
            # 触发条件1: 对话数达到10、20、30...的倍数
            should_trigger = False
            trigger_reason = ""
            
            if conversation_count >= 10 and conversation_count % 10 == 0:
                # 避免重复触发：检查是否刚刚分析过
                if not smart_insights or conversation_count > last_analysis_count:
                    should_trigger = True
                    trigger_reason = f"对话数达到{conversation_count}次"
            
            # 触发条件2: 首次达到5次对话（早期用户）
            if not smart_insights and conversation_count >= 5:
                should_trigger = True
                trigger_reason = "首次洞察分析"
            
            if should_trigger:
                logger.info(f"🔔 触发智能洞察分析: {trigger_reason}")
                smart_insights_data = await self.generate_smart_insights(user_id)
                
                # 返回建议（可选择推送给用户）
                if smart_insights_data.get("suggestions"):
                    return {
                        "triggered": True,
                        "reason": trigger_reason,
                        "conversation_count": conversation_count,
                        "suggestions": smart_insights_data["suggestions"],
                        "message": "💡 我注意到您的一些使用习惯，有几个建议：\n" + 
                                  "\n".join([f"  • {s}" for s in smart_insights_data["suggestions"][:3]])
                    }
                else:
                    return {
                        "triggered": True,
                        "reason": trigger_reason,
                        "conversation_count": conversation_count,
                        "message": f"已分析{conversation_count}次对话，持续学习中..."
                    }
            
            return {
                "triggered": False,
                "conversation_count": conversation_count
            }
            
        except Exception as e:
            logger.error(f"❌ 检查洞察触发失败: {e}")
            return {"triggered": False, "error": str(e)}
    
    async def cleanup(self):
        """清理资源"""
        try:
            logger.info(f"🧹 清理Agent资源: user={self.current_user_id}")
            self.current_user_id = None
            self.current_session_id = None
        except Exception as e:
            logger.error(f"❌ Agent清理失败: {e}")


if __name__ == "__main__":
    # 测试TY记忆智能代理
    import asyncio
    from ty_mem_agent.utils.logger_config import get_logger
    test_logger = get_logger("TYMemoryAgentTest")
    
    async def test_ty_memory_agent():
        """异步测试函数"""
        test_logger.info("🧪 测试TY记忆智能代理...")
        
        try:
            # 创建代理实例
            agent = TYMemoryAgent()
            test_logger.info(f"✅ 代理创建成功: {agent.name}")
            test_logger.info(f"✅ 代理描述: {agent.description}")
            test_logger.info(f"✅ 可用工具: {list(agent.function_map.keys())}")
            
            # 设置用户上下文
            await agent.set_user_context("zhang_san", "test_session")
            test_logger.info("✅ 用户上下文已设置")
            
            # 测试带记忆的对话
            test_messages = [
                Message(role=USER, content="你好，我是张三，我想了解一下今天北京的天气")
            ]
            
            test_logger.info("🎯 测试带记忆的对话...")
            response_count = 0
            async for response in agent.run_with_memory(
                messages=test_messages,
                user_id="zhang_san",
                session_id="test_session"
            ):
                response_count += 1
                if response and len(response) > 0:
                    test_logger.info(f"📝 响应 #{response_count}: {response[-1].content[:100]}...")
            
            test_logger.info(f"✅ 收到 {response_count} 个响应块")
            
            # 测试获取用户摘要
            test_logger.info("🎯 测试获取用户摘要...")
            summary = await agent.get_user_summary("zhang_san")
            test_logger.info(f"✅ 用户摘要: {summary}")
            
            # 测试清理
            test_logger.info("🎯 测试资源清理...")
            await agent.cleanup()
            test_logger.info("✅ 资源清理完成")
            
            test_logger.info("🎉 TY记忆智能代理测试完成！")
            
        except Exception as e:
            test_logger.error(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 运行异步测试
    asyncio.run(test_ty_memory_agent())
