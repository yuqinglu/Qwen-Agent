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
    
    def _parse_datetime_naive(self, dt_str: str) -> datetime:
        """
        安全地解析ISO格式时间字符串为naive datetime
        
        处理各种时区格式：
        - 2024-12-24T10:00:00
        - 2024-12-24T10:00:00Z
        - 2024-12-24T10:00:00+08:00
        - 2024-12-24T10:00:00-05:00
        
        返回：naive datetime（移除所有时区信息）
        """
        if not dt_str:
            return None
        
        try:
            # 先尝试解析为aware datetime
            # replace('Z', '+00:00') 处理 Z 结尾的情况
            dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
            
            # 如果是aware datetime，转换为naive（移除时区信息）
            if dt.tzinfo is not None:
                # 转换为UTC时间，然后移除时区信息
                dt = dt.replace(tzinfo=None)
            
            return dt
        except Exception as e:
            logger.warning(f"解析时间字符串失败: {dt_str}, 错误: {e}")
            # 尝试更激进的处理：手动移除时区信息
            try:
                # 移除所有可能的时区后缀
                # 格式: +08:00, -05:00, Z
                import re
                clean_str = re.sub(r'[+-]\d{2}:\d{2}$', '', dt_str)
                clean_str = clean_str.replace('Z', '')
                dt = datetime.fromisoformat(clean_str)
                return dt
            except Exception as e2:
                logger.error(f"彻底解析时间失败: {dt_str}, 错误: {e2}")
                return None
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行待办提取（仅提取信息，不创建待办）
        
        注意：此工具只负责从自然语言中提取待办的结构化信息。
        创建待办需要使用日历MCP工具（如createOneTimeEvent）。
        """
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except:
                params_dict = {"text": params}
        else:
            params_dict = params
        
        text = params_dict.get("text", "")
        user_id = params_dict.get("user_id", kwargs.get("user_id", "default_user"))
        
        logger.info(f"🔍 提取待办信息: {text}")
        
        try:
            # 使用LLM提取结构化信息
            extracted_info = self._extract_with_llm(text)
            logger.debug(f"提取后的信息: {extracted_info}")
            
            # 转换为日历MCP工具所需的格式
            # 优先使用start_time，如果没有则使用deadline
            from datetime import datetime, timedelta
            
            duration = extracted_info.get('duration', 60)  # 默认0小时
            
            # 确定开始时间（使用安全的解析方法）
            start_dt = None
            if extracted_info.get('start_time'):
                start_str = extracted_info['start_time']
                try:
                    start_dt = self._parse_datetime_naive(start_str)
                except Exception as e:
                    logger.warning(f"解析start_time失败: {e}")
            
            if not start_dt and extracted_info.get('deadline'):
                deadline_str = extracted_info['deadline']
                try:
                    start_dt = self._parse_datetime_naive(deadline_str)
                except Exception as e:
                    logger.warning(f"解析deadline失败: {e}")
            
            if start_dt:
                # eventDateTime: ISO8601格式字符串（如 '2024-01-01T12:00:00'）
                # 格式：YYYY-MM-DDTHH:MM:SS
                event_date_time = start_dt.strftime('%Y-%m-%dT%H:%M:%S')
                
                logger.debug(f"📅 时间格式转换: {start_dt.isoformat()} -> eventDateTime={event_date_time}")
                
                # 计算duration：优先使用end_time，如果没有则使用提供的duration
                # 注意：MCP服务要求duration为秒数，不是分钟数
                if extracted_info.get('end_time'):
                    end_str = extracted_info['end_time']
                    try:
                        end_dt = self._parse_datetime_naive(end_str)
                        if end_dt:
                            duration_seconds = (end_dt - start_dt).total_seconds()
                            duration = max(900, int(duration_seconds))  # 至少15分钟（900秒）
                            logger.debug(f"⏱️ Duration计算（基于end_time）: {duration}秒 ({duration/60:.1f}分钟)")
                        else:
                            logger.warning(f"解析end_time失败，使用提供的duration")
                    except Exception as e:
                        logger.warning(f"解析end_time失败: {e}，使用提供的duration")
                elif extracted_info.get('duration'):
                    # 使用提供的duration（假设LLM返回的是分钟数，需要转换为秒）
                    duration_minutes = int(extracted_info['duration'])
                    duration = duration_minutes * 60  # 转换为秒
                    logger.debug(f"⏱️ Duration转换: {duration_minutes}分钟 -> {duration}秒")
                else:
                    # 默认1小时（3600秒）
                    duration = 3600
                    logger.debug(f"⏱️ Duration使用默认值: {duration}秒 (1小时)")
            else:
                logger.warning("无法确定开始时间，使用当前时间")
                now = datetime.now()
                event_date_time = now.strftime('%Y-%m-%dT%H:%M:%S')
                duration = 3600  # 默认1小时（3600秒）
                logger.debug(f"📅 使用当前时间: eventDateTime={event_date_time}, duration={duration}秒")
            
            # 构建描述信息
            description_parts = []
            if extracted_info.get('description'):
                description_parts.append(extracted_info['description'])
            if extracted_info.get('participants'):
                participants = extracted_info['participants']
                if isinstance(participants, list):
                    description_parts.append(f"参与人: {', '.join(participants)}")
                elif isinstance(participants, str):
                    description_parts.append(f"参与人: {participants}")
            if extracted_info.get('tags'):
                tags = extracted_info['tags']
                if isinstance(tags, list):
                    description_parts.append(f"标签: {', '.join(tags)}")
            
            description = "\n".join(description_parts) if description_parts else None
            
            # 判断是否为重复事件
            is_recurring = extracted_info.get('is_recurring', False)
            rrule = extracted_info.get('rrule')
            
            # 处理提醒时间，转换为 iCalendar RFC 5545 格式的 alarmTrigger
            alarm_trigger = None
            if extracted_info.get('reminder_time') and start_dt:
                try:
                    reminder_str = extracted_info['reminder_time']
                    # 使用安全的解析方法，确保返回 naive datetime
                    reminder_dt = self._parse_datetime_naive(reminder_str)
                    
                    if not reminder_dt:
                        logger.warning(f"无法解析提醒时间: {reminder_str}")
                    else:
                        # 计算提醒时间与事件开始时间的时间差
                        # 现在两者都是 naive datetime，可以安全相减
                        time_diff = start_dt - reminder_dt
                        
                        # 转换为分钟数
                        minutes_before = int(time_diff.total_seconds() / 60)
                        
                        if minutes_before > 0:
                            # 转换为 iCalendar 格式
                            # 如果大于等于1440分钟(1天)，使用天数表示
                            if minutes_before >= 1440:
                                days = minutes_before // 1440
                                remaining_minutes = minutes_before % 1440
                                if remaining_minutes > 0:
                                    hours = remaining_minutes // 60
                                    mins = remaining_minutes % 60
                                    if hours > 0 and mins > 0:
                                        alarm_trigger = f"-P{days}DT{hours}H{mins}M"
                                    elif hours > 0:
                                        alarm_trigger = f"-P{days}DT{hours}H"
                                    else:
                                        alarm_trigger = f"-P{days}DT{mins}M"
                                else:
                                    alarm_trigger = f"-P{days}D"
                            # 如果大于等于60分钟，使用小时表示
                            elif minutes_before >= 60:
                                hours = minutes_before // 60
                                mins = minutes_before % 60
                                if mins > 0:
                                    alarm_trigger = f"-PT{hours}H{mins}M"
                                else:
                                    alarm_trigger = f"-PT{hours}H"
                            # 否则使用分钟表示
                            else:
                                alarm_trigger = f"-PT{minutes_before}M"
                            
                            logger.debug(f"⏰ 提醒时间转换: reminder_time={reminder_str}, start_time={start_dt.isoformat()}, alarmTrigger={alarm_trigger}")
                except Exception as e:
                    logger.warning(f"处理提醒时间失败: {e}")
            
            # 构建基础参数
            base_params = {
                "title": extracted_info.get('title', '未命名事件'),
                "description": description,
                "location": extracted_info.get('location'),
                "timezone": "Asia/Shanghai",
                "alarm_trigger": alarm_trigger  # 添加提醒触发器
            }
            
            # 根据是否为重复事件，构建不同的参数
            if is_recurring and rrule:
                # 重复事件参数
                calendar_event_params = {
                    **base_params,
                    "rrule": rrule,
                    "duration": duration
                }
                if event_date_time:
                    calendar_event_params["eventDateTime"] = event_date_time
                
                tool_name = "calendar-service-createRecurringEvent"
                instruction = "请使用日历MCP工具（calendar-service-createRecurringEvent）创建此重复事件"
            else:
                # 一次性事件参数
                calendar_event_params = {
                    **base_params,
                    "duration": duration
                }
                if event_date_time:
                    calendar_event_params["eventDateTime"] = event_date_time
                
                tool_name = "calendar-service-createOneTimeEvent"
                instruction = "请使用日历MCP工具（calendar-service-createOneTimeEvent）创建此事件"
            
            # 返回提取的信息，格式化为日历MCP工具可用的格式
            result = {
                "success": True,
                "extracted_info": extracted_info,
                "calendar_event_params": calendar_event_params,
                "is_recurring": is_recurring,
                "recommended_tool": tool_name,
                "message": f"✅ 已提取待办信息: {extracted_info.get('title', '未命名事件')}",
                "instruction": instruction
            }
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 提取待办失败: {e}")
            import traceback
            logger.error(f"详细错误:\n{traceback.format_exc()}")
            return json.dumps({
                "success": False,
                "error": str(e),
                "message": f"❌ 提取待办信息失败: {e}"
            }, ensure_ascii=False)
    
    def _extract_with_llm(self, text: str) -> Dict[str, Any]:
        """使用LLM提取结构化信息"""
        prompt = f"""请从以下文本中提取待办事项的结构化信息：

文本: {text}

当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

请以JSON格式返回，包含以下字段：
- title: 待办标题（简短概括，如"与张总讨论技术升级"）
- description: 详细描述（可选）
- start_time: 开始时间（ISO 8601格式，如"2025-10-15T08:30:00"）
- end_time: 结束时间（ISO 8601格式，如"2025-10-15T10:00:00"）
- deadline: 截止时间（ISO 8601格式，如"2025-10-15T08:30:00"，如果没有start_time则使用此字段）
- duration: 持续时间（整数，单位：分钟，如60表示1小时，可选）【注意：此字段仅用于辅助，实际会被转换为秒数】
- reminder_time: 提醒时间（ISO 8601格式，仅当用户明确提到"提醒"、"提前XX分钟/小时"时才填写，如"提前30分钟提醒"则计算出提醒时间点）
- location: 地点（可选）
- participants: 参与人列表（数组，如["张总"]）
- priority: 优先级（0-低，1-中，2-高）
- tags: 标签列表（数组，如["会议", "技术"]）
- is_recurring: 是否重复事件（布尔值，默认false）
- rrule: 重复规则（字符串，仅当is_recurring为true时需要，遵循RFC 5545标准）

**rrule格式说明（重要！）：**
- 每天重复: "FREQ=DAILY;INTERVAL=1"
- 每周重复（指定星期几）: "FREQ=WEEKLY;BYDAY=MO,WE,FR" （周一、三、五）
- 每周重复（所有星期）: "FREQ=WEEKLY;INTERVAL=1"
- 每月重复: "FREQ=MONTHLY;INTERVAL=1"
- 每年重复: "FREQ=YEARLY;INTERVAL=1"
- 每N天重复: "FREQ=DAILY;INTERVAL=N" （N为数字）
- 每N周重复: "FREQ=WEEKLY;INTERVAL=N"
- 每N月重复: "FREQ=MONTHLY;INTERVAL=N"

**星期几代码：**
- MO=周一, TU=周二, WE=周三, TH=周四, FR=周五, SA=周六, SU=周日

**示例rrule：**
- "每周一三五" → "FREQ=WEEKLY;BYDAY=MO,WE,FR"
- "每天" → "FREQ=DAILY;INTERVAL=1"
- "每周一" → "FREQ=WEEKLY;BYDAY=MO"
- "每两周" → "FREQ=WEEKLY;INTERVAL=2"
- "每月1号" → "FREQ=MONTHLY;BYMONTHDAY=1"

注意：
1. 时间解析要准确，"明天"、"下周"等相对时间要转换为绝对时间
2. 优先使用start_time和end_time，如果没有则使用deadline
3. 如果提供了start_time和end_time，duration会自动计算；如果只提供了start_time或deadline，duration默认为60分钟（1小时）
4. 对于重复事件，必须提供rrule字段，且格式必须符合RFC 5545标准
5. 如果没有明确的截止时间，可以根据事件性质设置合理的时间，如果无法确定，可以设置为None
6. 只返回JSON，不要其他解释

示例1（一次性事件）：
输入: "明天上午8点半与张总进行技术升级讨论"
输出:
{{
  "title": "与张总讨论技术升级",
  "description": "技术升级讨论会议",
  "start_time": "2025-10-15T08:30:00",
  "end_time": "2025-10-15T09:30:00",
  "duration": 60,
  "participants": ["张总"],
  "priority": 1,
  "tags": ["会议", "技术"],
  "is_recurring": false
}}

示例2（重复事件）：
输入: "每周一三五上午9点晨跑"
输出:
{{
  "title": "晨跑",
  "start_time": "2025-10-15T09:00:00",
  "end_time": "2025-10-15T10:00:00",
  "duration": 60,
  "is_recurring": true,
  "rrule": "FREQ=WEEKLY;BYDAY=MO,WE,FR"
}}
"""
        
        messages = [Message(role=USER, content=prompt)]
        
        # 调用LLM
        llm = self._get_llm()
        response = None
        for chunk in llm.chat(messages=messages, stream=True):
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
                    
                    # 使用安全的解析方法
                    deadline_dt = self._parse_datetime_naive(deadline_str)
                    
                    if not deadline_dt:
                        # 如果解析失败，保持原值
                        logger.warning(f"无法解析 deadline: {deadline_str}")
                        return cleaned
                    
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
        
        # 确保is_recurring是布尔值
        if 'is_recurring' in cleaned:
            if isinstance(cleaned['is_recurring'], bool):
                pass  # 已经是布尔值
            elif isinstance(cleaned['is_recurring'], str):
                cleaned['is_recurring'] = cleaned['is_recurring'].lower() in ('true', '1', 'yes', '是')
            else:
                cleaned['is_recurring'] = bool(cleaned['is_recurring'])
        else:
            cleaned['is_recurring'] = False
        
        # 验证rrule格式（如果是重复事件）
        if cleaned.get('is_recurring') and cleaned.get('rrule'):
            rrule = cleaned['rrule']
            # 基本验证：应该包含FREQ=
            if 'FREQ=' not in rrule:
                logger.warning(f"rrule格式可能不正确: {rrule}")
        elif cleaned.get('is_recurring') and not cleaned.get('rrule'):
            logger.warning("重复事件缺少rrule字段，将作为一次性事件处理")
            cleaned['is_recurring'] = False
        
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

**重要**：如果用户提到的日期是自然语言（如"星期天"、"下周五"、"这个周末"），工具会自动解析为具体日期。

适用场景：
- 用户问"我今天有什么事？"
- 用户问"明天的日程安排"
- 用户问"这个星期天的待办事项"
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
                "description": "查询日期（YYYY-MM-DD格式，或自然语言如'星期天'、'下周五'），可选。如果是自然语言，工具会自动解析"
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
    
    def _parse_natural_date(self, date_text: str) -> str:
        """解析自然语言日期为YYYY-MM-DD格式"""
        try:
            # 检查是否已经是YYYY-MM-DD格式
            if re.match(r'^\d{4}-\d{2}-\d{2}$', date_text):
                return date_text
            
            # 导入自然语言时间解析器
            try:
                from ty_mem_agent.tools.natural_time_parser import parse_chinese_english_datetime
            except ImportError:
                logger.warning(f"⚠️ 无法导入时间解析器，将直接使用原始日期")
                return date_text
            
            # 解析自然语言日期
            result = parse_chinese_english_datetime(text=date_text)
            
            if result and result.get("parsed_datetime"):
                # 提取日期部分（YYYY-MM-DD）
                parsed_datetime = result["parsed_datetime"]
                if isinstance(parsed_datetime, str):
                    # 如果返回的是字符串，提取日期部分
                    date_part = parsed_datetime.split("T")[0]
                    logger.info(f"🕐 解析自然语言日期: '{date_text}' -> {date_part}")
                    return date_part
                elif hasattr(parsed_datetime, 'strftime'):
                    # 如果返回的是datetime对象
                    date_part = parsed_datetime.strftime("%Y-%m-%d")
                    logger.info(f"🕐 解析自然语言日期: '{date_text}' -> {date_part}")
                    return date_part
            
            logger.warning(f"⚠️ 无法解析日期: '{date_text}'，将尝试直接使用")
            return date_text
            
        except Exception as e:
            logger.warning(f"⚠️ 日期解析失败: {e}，将尝试直接使用原始日期")
            return date_text
    
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
        
        logger.info(f"🔍 查询待办: user_id={user_id}, type={query_type}, date={date_str}")
        
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
                # 🔧 优化：如果date_str是自然语言（如"星期天"、"下周五"），先解析为具体日期
                date_str = self._parse_natural_date(date_str)
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

