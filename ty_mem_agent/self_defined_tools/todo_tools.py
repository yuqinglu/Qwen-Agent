#!/usr/bin/env python3
"""
待办事项管理工具
提供待办的创建、查询、更新等功能
"""

import json
import re
from datetime import datetime, timedelta
from typing import Dict, Union, Any, List

from qwen_agent.tools.base import BaseTool
from qwen_agent.llm import get_chat_model
from qwen_agent.llm.schema import Message, USER

from ty_mem_agent.memory.todo_manager import get_todo_manager, TodoStatus
from ty_mem_agent.config.settings import get_llm_config
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("TodoTools")


class TodoExtractorTool(BaseTool):
    """待办信息提取工具
    
    从自然语言中提取待办的结构化信息
    """
    
    name = "extract_todo"
    description = """从用户的自然语言描述中提取待办事项的结构化信息。
    
能够识别：
- 时间信息（如"明天上午8点半"、"下周五下午3点"）
- 地点信息（如"综合体育馆"、"会议室A"）
- 参与人信息（如"张总"、"李经理"）
- 事件内容（如"技术升级讨论"、"打篮球"）
- 优先级（如"紧急"、"重要"）

适用场景：
- 创建新的待办事项
- 用户说"帮我记个待办"、"添加待办"等

示例输入：
- "帮我建个待办，明天上午8点半与张总进行技术升级讨论"
- "明天下午6点半需要去综体打篮球"
- "下周一提醒我给客户发邮件"
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "用户的原始描述文本"
            },
            "user_id": {
                "type": "string",
                "description": "用户ID",
                "default": "default_user"
            }
        },
        "required": ["text"]
    }
    
    def __init__(self):
        super().__init__()
        self.llm = None
    
    def _get_llm(self):
        """延迟初始化LLM"""
        if self.llm is None:
            llm_config = get_llm_config()
            self.llm = get_chat_model(llm_config)
        return self.llm
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行待办提取"""
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except:
                params_dict = {"text": params}
        else:
            params_dict = params
        
        text = params_dict.get("text", "")
        user_id = params_dict.get("user_id", "default_user")
        
        logger.info(f"🔍 提取待办信息: {text}")
        
        try:
            # 使用LLM提取结构化信息
            extracted_info = self._extract_with_llm(text)
            logger.debug(f"提取后的信息: {extracted_info}")
            
            # 创建待办
            todo_manager = get_todo_manager()
            todo = todo_manager.create_todo(user_id, extracted_info)
            logger.debug(f"创建的待办: {todo}")
            
            # 检查时间冲突
            conflicts = []
            if extracted_info.get('deadline'):
                conflicts = todo_manager.check_conflicts(
                    user_id, 
                    extracted_info['deadline'],
                    duration_minutes=60,
                    exclude_todo_id=todo.id  # 排除当前待办，避免自己与自己冲突
                )
            
            # 转换为字典
            try:
                todo_dict = todo.to_dict()
                logger.debug(f"待办字典: {todo_dict}")
            except Exception as dict_error:
                logger.error(f"to_dict() 失败: {dict_error}")
                logger.error(f"待办对象: {todo}")
                raise
            
            result = {
                "success": True,
                "todo": todo_dict,
                "message": f"✅ 已创建待办: {todo.title}",
                "conflicts": [c.to_dict() for c in conflicts] if conflicts else []
            }
            
            if conflicts:
                result["message"] += f"\n⚠️ 发现 {len(conflicts)} 个时间冲突"
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 提取待办失败: {e}")
            import traceback
            logger.error(f"详细错误:\n{traceback.format_exc()}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "message": f"❌ 创建待办失败: {e}"
            }, ensure_ascii=False)
    
    def _extract_with_llm(self, text: str) -> Dict[str, Any]:
        """使用LLM提取结构化信息"""
        prompt = f"""请从以下文本中提取待办事项的结构化信息：

文本: {text}

当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

请以JSON格式返回，包含以下字段：
- title: 待办标题（简短概括，如"与张总讨论技术升级"）
- description: 详细描述（可选）
- deadline: 截止时间（ISO 8601格式，如"2025-10-15T08:30:00"）
- reminder_time: 提醒时间（ISO 8601格式，可选）
- location: 地点（可选）
- participants: 参与人列表（数组，如["张总"]）
- priority: 优先级（0-低，1-中，2-高）
- tags: 标签列表（数组，如["会议", "技术"]）

注意：
1. 时间解析要准确，"明天"、"下周"等相对时间要转换为绝对时间
2. 如果没有明确的截止时间，可以根据事件性质设置合理的时间，如果无法确定，可以设置为None
3. 只返回JSON，不要其他解释

示例：
输入: "明天上午8点半与张总进行技术升级讨论"
输出:
{{
  "title": "与张总讨论技术升级",
  "description": "技术升级讨论会议",
  "deadline": "2025-10-15T08:30:00",
  "participants": ["张总"],
  "priority": 1,
  "tags": ["会议", "技术"]
}}
"""
        
        messages = [Message(role=USER, content=prompt)]
        
        # 调用LLM
        llm = self._get_llm()
        response = None
        for chunk in llm.chat(messages=messages, stream=False):
            response = chunk
        
        if not response:
            raise ValueError("LLM未返回结果")
        
        # 解析LLM响应
        # response 是一个 Message 对象列表
        if isinstance(response, list):
            # response 是列表，取最后一个消息
            if len(response) > 0:
                last_message = response[len(response) - 1]
                response_text = last_message.content
            else:
                raise ValueError("LLM返回了空列表")
        elif hasattr(response, 'content'):
            # response 本身就是一个 Message 对象
            response_text = response.content
        else:
            raise ValueError(f"LLM响应格式错误: {type(response)}")
        
        # 提取JSON
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                extracted_info = json.loads(json_match.group())
                logger.debug(f"提取的待办信息: {extracted_info}")
                
                # 验证和清理数据
                cleaned_info = self._clean_extracted_info(extracted_info)
                return cleaned_info
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                logger.error(f"LLM响应: {response_text}")
                raise ValueError(f"JSON解析失败: {e}")
        else:
            logger.error(f"无法从LLM响应中提取JSON: {response_text}")
            raise ValueError("无法从LLM响应中提取JSON")
    
    def _clean_extracted_info(self, info: Dict[str, Any]) -> Dict[str, Any]:
        """清理和验证提取的信息"""
        cleaned = {}
        
        # 确保所有键都是字符串
        for key, value in info.items():
            if isinstance(key, str):
                cleaned[key] = value
            else:
                logger.warning(f"跳过非字符串键: {key} (类型: {type(key)})")
        
        # 确保必要字段存在
        if 'title' not in cleaned:
            cleaned['title'] = '未命名待办'
        
        # 🔧 修复：处理deadline时间设置问题
        # 当deadline只有日期没有具体时间（即00:00:00）时，改成前一天的23:59:59
        # 例如：2025-10-24T00:00:00 -> 2025-10-23T23:59:59
        if 'deadline' in cleaned and cleaned['deadline']:
            deadline_str = str(cleaned['deadline'])
            try:
                # 检查是否是00:00:00或00:00
                if 'T00:00:00' in deadline_str or ('T00:00' in deadline_str and 'T00:00:' not in deadline_str):
                    # 解析为datetime对象
                    from datetime import datetime, timedelta
                    
                    # 尝试解析ISO格式
                    try:
                        deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    except:
                        # 如果失败，尝试不带时区的格式
                        deadline_dt = datetime.fromisoformat(deadline_str.split('+')[0].split('Z')[0])
                    
                    # 减去1天，并设置为23:59:59
                    corrected_dt = deadline_dt - timedelta(days=1)
                    corrected_dt = corrected_dt.replace(hour=23, minute=59, second=59, microsecond=0)
                    
                    # 格式化为ISO字符串
                    cleaned['deadline'] = corrected_dt.strftime('%Y-%m-%dT%H:%M:%S')
                    
                    logger.info(f"⏰ 修正deadline时间: {deadline_str} -> {cleaned['deadline']} (前一天23:59:59)")
            except Exception as e:
                logger.warning(f"处理deadline时间时出错: {e}，保持原值")
        
        # 确保participants是列表
        if 'participants' in cleaned and not isinstance(cleaned['participants'], list):
            if isinstance(cleaned['participants'], str):
                try:
                    cleaned['participants'] = json.loads(cleaned['participants'])
                except:
                    cleaned['participants'] = [cleaned['participants']]
            else:
                cleaned['participants'] = []
        
        # 确保tags是列表
        if 'tags' in cleaned and not isinstance(cleaned['tags'], list):
            if isinstance(cleaned['tags'], str):
                try:
                    cleaned['tags'] = json.loads(cleaned['tags'])
                except:
                    cleaned['tags'] = [cleaned['tags']]
            else:
                cleaned['tags'] = []
        
        # 确保priority是整数
        if 'priority' in cleaned:
            try:
                cleaned['priority'] = int(cleaned['priority'])
            except:
                cleaned['priority'] = 0
        
        return cleaned


class TodoQueryTool(BaseTool):
    """待办查询工具"""
    
    name = "query_todos"
    description = """查询用户的待办事项列表。
    
支持以下查询方式：
- 查询今天/明天/指定日期的待办
- 查询本周/下周的待办
- 查询未完成的待办
- 按时间升序排列

适用场景：
- 用户问"我今天有什么事？"
- 用户问"明天的日程安排"
- 用户问"本周的待办事项"
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "用户ID"
            },
            "date": {
                "type": "string",
                "description": "查询日期（YYYY-MM-DD格式），可选"
            },
            "query_type": {
                "type": "string",
                "enum": ["today", "tomorrow", "this_week", "pending", "date"],
                "description": "查询类型：today-今天, tomorrow-明天, this_week-本周, pending-未完成, date-指定日期",
                "default": "pending"
            },
            "limit": {
                "type": "integer",
                "description": "返回数量限制",
                "default": 10
            }
        },
        "required": ["user_id"]
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行待办查询"""
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except:
                params_dict = {"user_id": params}
        else:
            params_dict = params
        
        user_id = params_dict.get("user_id", "default_user")
        query_type = params_dict.get("query_type", "pending")
        date_str = params_dict.get("date")
        limit = params_dict.get("limit", 10)
        
        logger.info(f"🔍 查询待办: user_id={user_id}, type={query_type}")
        
        try:
            todo_manager = get_todo_manager()
            todos = []
            
            if query_type == "today":
                date_str = datetime.now().strftime("%Y-%m-%d")
                todos = todo_manager.get_todos_by_date(user_id, date_str, TodoStatus.PENDING)
            
            elif query_type == "tomorrow":
                tomorrow = datetime.now() + timedelta(days=1)
                date_str = tomorrow.strftime("%Y-%m-%d")
                todos = todo_manager.get_todos_by_date(user_id, date_str, TodoStatus.PENDING)
            
            elif query_type == "this_week":
                start_date = datetime.now().strftime("%Y-%m-%dT00:00:00")
                end_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%dT23:59:59")
                todos = todo_manager.get_todos_by_range(
                    user_id, start_date, end_date, TodoStatus.PENDING
                )
            
            elif query_type == "date" and date_str:
                todos = todo_manager.get_todos_by_date(user_id, date_str, TodoStatus.PENDING)
            
            else:  # pending
                todos = todo_manager.get_pending_todos(user_id, limit)
            
            # 格式化返回结果
            result = {
                "success": True,
                "count": len(todos),
                "todos": [todo.to_dict() for todo in todos],
                "message": f"找到 {len(todos)} 个待办事项"
            }
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 查询待办失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "message": f"❌ 查询待办失败: {e}"
            }, ensure_ascii=False)


class TodoUpdateTool(BaseTool):
    """待办更新工具"""
    
    name = "update_todo"
    description = """更新待办事项的状态或信息。
    
支持操作：
- 标记待办为已完成
- 修改待办的时间、地点等信息
- 删除待办

适用场景：
- 用户说"把XX待办标记为完成"
- 用户说"删除XX待办"
- 用户说"修改待办时间"
- 用户说"对了，地点是XX"（补充地点信息）
- 用户说"补充一下，时间是XX"（补充时间信息）
- 用户说"还有，参与人包括XX"（补充参与人信息）

重要：当用户使用"对了"、"补充一下"、"还有"、"修改"等词语时，通常是在更新刚创建的待办，应该调用此工具。

⚠️ 关键要求：
- todo_id必须是正确的待办ID，不能使用硬编码的1、2等
- 如果刚创建了待办，从工具调用结果中获取返回的todo_id
- 如果无法确定ID，先调用query_todos工具查询待办列表

可更新的字段：
- deadline: 截止时间（ISO 8601格式，如"2025-10-24T17:30:00"）
- reminder_time: 提醒时间（ISO 8601格式）
- location: 地点
- participants: 参与人列表（数组）
- title: 标题
- description: 描述
- priority: 优先级（0-2）
- tags: 标签列表（数组）
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "用户ID"
            },
            "todo_id": {
                "type": "integer",
                "description": "待办ID"
            },
            "action": {
                "type": "string",
                "enum": ["complete", "delete", "update"],
                "description": "操作类型：complete-完成, delete-删除, update-更新"
            },
            "updates": {
                "type": "object",
                "description": "更新的字段（action为update时使用）。支持字段：deadline（截止时间）、reminder_time（提醒时间）、location（地点）、participants（参与人）、title（标题）、description（描述）、priority（优先级）、tags（标签）",
                "properties": {
                    "deadline": {
                        "type": "string",
                        "description": "截止时间（ISO 8601格式，如2025-10-24T17:30:00）"
                    },
                    "reminder_time": {
                        "type": "string", 
                        "description": "提醒时间（ISO 8601格式）"
                    },
                    "location": {
                        "type": "string",
                        "description": "地点"
                    },
                    "participants": {
                        "type": "array",
                        "description": "参与人列表"
                    },
                    "title": {
                        "type": "string",
                        "description": "标题"
                    },
                    "description": {
                        "type": "string",
                        "description": "描述"
                    },
                    "priority": {
                        "type": "integer",
                        "description": "优先级（0-2）"
                    },
                    "tags": {
                        "type": "array",
                        "description": "标签列表"
                    }
                }
            }
        },
        "required": ["user_id", "todo_id", "action"]
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行待办更新"""
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except:
                return json.dumps({
                    "success": False,
                    "error": "参数格式错误"
                }, ensure_ascii=False)
        else:
            params_dict = params
        
        user_id = params_dict.get("user_id", "default_user")
        todo_id = params_dict.get("todo_id")
        action = params_dict.get("action")
        updates = params_dict.get("updates", {})
        
        logger.info(f"🔧 更新待办: id={todo_id}, action={action}")
        
        try:
            todo_manager = get_todo_manager()
            success = False
            
            if action == "complete":
                success = todo_manager.complete_todo(todo_id, user_id)
                message = "✅ 待办已标记为完成" if success else "❌ 更新失败"
            
            elif action == "delete":
                success = todo_manager.delete_todo(todo_id, user_id)
                message = "✅ 待办已删除" if success else "❌ 删除失败"
            
            elif action == "update":
                success = todo_manager.update_todo(todo_id, user_id, updates)
                message = "✅ 待办已更新" if success else "❌ 更新失败"
            
            else:
                return json.dumps({
                    "success": False,
                    "error": f"不支持的操作: {action}"
                }, ensure_ascii=False)
            
            return json.dumps({
                "success": success,
                "message": message
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 更新待办失败: {e}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "message": f"❌ 更新待办失败: {e}"
            }, ensure_ascii=False)


# 导出工具
__all__ = [
    'TodoExtractorTool',
    'TodoQueryTool',
    'TodoUpdateTool',
]

