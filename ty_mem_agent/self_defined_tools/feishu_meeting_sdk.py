#!/usr/bin/env python3
"""
飞书会议工具 - 使用官方 SDK 实现
提供会议预约、更新、删除、获取等功能
使用飞书官方 Python SDK (lark-oapi)
参考文档: https://open.feishu.cn/document/server-docs/vc-v1/reserve/apply
"""

import json
import time
from typing import Dict, Any, Optional, List, Union
from datetime import datetime, timedelta
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger
from ty_mem_agent.config.settings import settings

logger = get_logger("FeishuMeetingSDK")

# 导入飞书官方 SDK
try:
    import lark_oapi as lark
    from lark_oapi.api.vc.v1 import *
    from lark_oapi.api.calendar.v4 import *
    from lark_oapi.api.contact.v3 import *
    HAS_LARK_SDK = True
    logger.info("✅ 已成功加载飞书官方 SDK (lark-oapi)")
except ImportError as e:
    HAS_LARK_SDK = False
    logger.error(f"❌ 未安装飞书官方 SDK (lark-oapi): {e}")
    logger.error("请运行: poetry add lark-oapi 或 pip install lark-oapi")


class FeishuMeetingSDKClient:
    """飞书会议 SDK 客户端"""
    
    BASE_URL = "https://open.feishu.cn/open-apis"
    
    def __init__(self, app_id: str, app_secret: str):
        """
        初始化飞书 SDK 客户端
        
        注意：当前使用应用日历+邀请方案，无需 user_access_token（无需OAuth授权）
        
        Args:
            app_id: 飞书应用 App ID
            app_secret: 飞书应用 App Secret
        """
        if not HAS_LARK_SDK:
            raise ImportError("未安装飞书官方 SDK (lark-oapi)，请先安装: pip install lark-oapi")
        
        self.app_id = app_id
        self.app_secret = app_secret
        
        # 应用日历缓存（避免重复查询和创建）
        self._app_calendar_cache: Optional[Dict[str, Any]] = None
        
        # 创建 SDK 客户端（使用 tenant_access_token，无需用户授权）
        self.client = lark.Client.builder() \
            .app_id(app_id) \
            .app_secret(app_secret) \
            .log_level(lark.LogLevel.ERROR) \
            .build()  # 只记录错误日志
        
        logger.info(f"✅ 飞书 SDK 客户端初始化成功 (app_id: {app_id[:8] if app_id else 'None'}...)")
    
    def create_meeting_reserve(
        self,
        owner_id: str,
        start_time: int,
        end_time: int,
        topic: str,
        duration_minutes: int = 60,
        participant_ids: Optional[List[str]] = None,
        user_id_type: str = "open_id",
        password: Optional[str] = None,
        auto_record: bool = False,
    ) -> Dict[str, Any]:
        """
        创建视频会议预约
        
        参考文档：https://open.feishu.cn/document/server-docs/vc-v1/reserve/apply
        
        注意：使用 tenant_access_token（应用身份），无需用户授权
        
        Args:
            owner_id: 会议所有者用户ID
            start_time: 会议开始时间（Unix时间戳，秒级）
            end_time: 会议结束时间（Unix时间戳，秒级）
            topic: 会议主题
            duration_minutes: 会议时长（分钟），默认60分钟
            participant_ids: 参会人用户ID列表（可选）
            user_id_type: 用户ID类型（open_id/user_id/union_id），默认open_id
            password: 会议密码（可选）
            auto_record: 是否自动录制，默认False
            
        Returns:
            包含预约结果的字典
        """
        try:
            # 如果未提供 end_time，根据 duration_minutes 计算
            if not end_time:
                end_time = start_time + (duration_minutes * 60)
            
            # 构建会议设置
            meeting_setting_builder = ReserveMeetingSetting.builder() \
                .topic(topic) \
                .meeting_initial_type(1)  # 1: 多人会议
            
            # 如果设置了自动录制
            if auto_record:
                meeting_setting_builder.auto_record(True)
            
            # 如果设置了会议密码
            if password:
                meeting_setting_builder.password(password)
            
            # 构建参会人设置（如果有）
            if participant_ids:
                # 构建 callee 列表（用于1对1会议或初始参会人）
                # 注意：callee 主要用于1对1会议，多人会议建议通过日历事件添加参会人
                callee_list = []
                for pid in participant_ids[:1]:  # 只取第一个作为初始参会人
                    callee = ReserveCallee.builder() \
                        .id(pid) \
                        .user_type(1) \
                        .build()  # 1: 用户
                    callee_list.append(callee)
                
                if callee_list:
                    call_setting = ReserveCallSetting.builder() \
                        .callee(callee_list[0]) \
                        .build()
                    meeting_setting_builder.call_setting(call_setting)
            
            meeting_settings = meeting_setting_builder.build()
            
            # 构建请求体
            # 注意：根据API文档和示例代码，end_time 和 owner_id 直接在 request_body 中设置
            request_body = ApplyReserveRequestBody.builder() \
                .end_time(str(end_time)) \
                .owner_id(owner_id) \
                .meeting_settings(meeting_settings) \
                .build()
            
            # 构建请求对象
            request = ApplyReserveRequest.builder() \
                .request_body(request_body) \
                .build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 调用API")
            
            # 发起请求
            logger.info(f"📅 创建会议预约: {topic} ({datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M')})")
            response: ApplyReserveResponse = self.client.vc.v1.reserve.apply(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 创建会议预约失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                # 记录详细错误信息
                try:
                    error_detail = json.loads(response.raw.content) if response.raw.content else {}
                    logger.debug(f"错误详情: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
                except:
                    pass
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            reserve_data = response.data.reserve if response.data else None
            
            if not reserve_data:
                logger.error("❌ 响应中未包含预约数据")
                return {
                    "success": False,
                    "error_msg": "响应中未包含预约数据"
                }
            
            # 提取预约信息
            reserve_id = reserve_data.id
            meeting_no = reserve_data.meeting_no
            meeting_url = reserve_data.url
            live_link = reserve_data.live_link if hasattr(reserve_data, 'live_link') else None
            
            logger.info(f"✅ 会议预约创建成功")
            logger.info(f"   - reserve_id: {reserve_id}")
            logger.info(f"   - 会议号: {meeting_no}")
            logger.info(f"   - 会议链接: {meeting_url}")
            
            return {
                "success": True,
                "reserve_id": reserve_id,
                "meeting_no": meeting_no,
                "meeting_url": meeting_url,
                "live_link": live_link,
                "reserve": {
                    "id": reserve_id,
                    "meeting_no": meeting_no,
                    "url": meeting_url,
                    "live_link": live_link,
                    "start_time": str(start_time),
                    "end_time": str(end_time)
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 创建会议预约异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"创建会议预约异常: {str(e)}"
            }
    
    def get_primary_calendar(
        self,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        获取应用主日历（使用 tenant_access_token）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar/primary
        
        注意：
        1. 使用 tenant_access_token 直接获取应用的主日历，无需用户授权
        2. 主日历是应用唯一的，避免创建多个日历的问题
        3. 结果会被缓存在实例中，避免重复查询
        
        Args:
            force_refresh: 是否强制刷新缓存（默认 False）
            
        Returns:
            包含日历信息的字典
        """
        try:
            # 如果有缓存且不强制刷新，直接返回缓存
            if self._app_calendar_cache and not force_refresh:
                logger.info(f"📋 使用缓存的应用主日历: {self._app_calendar_cache.get('calendar_id')}")
                return self._app_calendar_cache
            # 获取应用主日历
            logger.info(f"📋 获取应用主日历...")
            
            # 构建请求
            request = PrimaryCalendarRequest.builder().build()
            
            # 使用 tenant_access_token（默认）获取应用的主日历
            response: PrimaryCalendarResponse = self.client.calendar.v4.calendar.primary(request)
            
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 获取应用主日历失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            # 根据API文档，返回的是 UserCalendar 对象数组
            user_calendars = response.data.calendars if response.data and hasattr(response.data, 'calendars') else []
            
            if not user_calendars or len(user_calendars) == 0:
                logger.error("❌ 获取主日历成功但返回的日历列表为空")
                return {
                    "success": False,
                    "error_msg": "获取主日历成功但返回的日历列表为空"
                }
            
            # 取第一个日历作为主日历
            # UserCalendar 对象包含 calendar 和 user_id 两个属性
            user_calendar = user_calendars[0]
            calendar_obj = getattr(user_calendar, 'calendar', None)
            
            if not calendar_obj:
                logger.error("❌ UserCalendar对象中没有calendar属性")
                return {
                    "success": False,
                    "error_msg": "UserCalendar对象中没有calendar属性"
                }
            
            # 从 Calendar 对象中获取信息
            calendar_id = getattr(calendar_obj, 'calendar_id', None)
            calendar_summary = getattr(calendar_obj, 'summary', None)
            calendar_type = getattr(calendar_obj, 'type_', None)
            
            if not calendar_id:
                logger.error("❌ 获取主日历成功但未返回 calendar_id")
                return {
                    "success": False,
                    "error_msg": "获取主日历成功但未返回 calendar_id"
                }
            
            logger.info(f"✅ 成功获取应用主日历")
            logger.info(f"   - calendar_id: {calendar_id}")
            logger.info(f"   - summary: {calendar_summary}")
            logger.info(f"   - type: {calendar_type}")
            
            result = {
                "success": True,
                "calendar_id": calendar_id,
                "calendar": {
                    "calendar_id": calendar_id,
                    "summary": calendar_summary or "应用主日历",
                    "type": calendar_type if calendar_type else "primary"
                },
                "is_new": False
            }
            # 缓存结果
            self._app_calendar_cache = result
            return result
            
        except Exception as e:
            logger.error(f"❌ 获取应用主日历异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"获取应用主日历异常: {str(e)}"
            }
    
    def create_calendar_event(
        self,
        calendar_id: str,
        topic: str,
        start_time: int,
        end_time: int,
        description: str = "",
        meeting_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建日历事件（使用 tenant_access_token，无需用户授权）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/create
        
        Args:
            calendar_id: 日历ID
            topic: 事件标题
            start_time: 开始时间（Unix时间戳，秒级）
            end_time: 结束时间（Unix时间戳，秒级）
            description: 事件描述
            meeting_url: 会议链接（可选，用于添加到vchat）
            
        Returns:
            包含事件信息的字典
        """
        try:
            # 构建视频会议信息（如果有会议链接）
            vchat = None
            if meeting_url:
                vchat = Vchat.builder() \
                    .vc_type("third_party") \
                    .icon_type("vc") \
                    .description("点击加入会议") \
                    .meeting_url(meeting_url) \
                    .build()
            else:
                vchat = Vchat.builder() \
                    .vc_type("no_meeting") \
                    .icon_type("default") \
                    .description("") \
                    .meeting_url("") \
                    .build()
            
            # 构建事件数据
            event_data = CalendarEvent.builder() \
                .summary(topic) \
                .description(description) \
                .start_time(TimeInfo.builder()
                    .timestamp(str(start_time))
                    .timezone("Asia/Shanghai")
                    .build()) \
                .end_time(TimeInfo.builder()
                    .timestamp(str(end_time))
                    .timezone("Asia/Shanghai")
                    .build()) \
                .vchat(vchat) \
                .visibility("default") \
                .attendee_ability("can_see_others") \
                .free_busy_status("busy") \
                .need_notification(True) \
                .build()
            
            # 构建请求对象
            request = CreateCalendarEventRequest.builder() \
                .calendar_id(calendar_id) \
                .request_body(event_data) \
                .build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 创建日历事件")
            
            # 发起请求
            logger.info(f"📅 创建日历事件: {topic}")
            response: CreateCalendarEventResponse = self.client.calendar.v4.calendar_event.create(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 创建日历事件失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            event_data = response.data.event if response.data and hasattr(response.data, 'event') else None
            
            if not event_data:
                logger.error("❌ 响应中未包含事件数据")
                return {
                    "success": False,
                    "error_msg": "响应中未包含事件数据"
                }
            
            event_id = event_data.event_id if hasattr(event_data, 'event_id') else None
            
            if not event_id:
                logger.error("❌ 响应中未包含 event_id")
                return {
                    "success": False,
                    "error_msg": "响应中未包含 event_id"
                }
            
            logger.info(f"✅ 日历事件创建成功，event_id: {event_id}")
            
            return {
                "success": True,
                "event_id": event_id,
                "event": {
                    "event_id": event_id,
                    "summary": topic
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 创建日历事件异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"创建日历事件异常: {str(e)}"
            }
    
    def add_calendar_event_attendees(
        self,
        calendar_id: str,
        event_id: str,
        attendees: List[Dict[str, Any]],
        user_id_type: str = "open_id",
        need_notification: bool = True
    ) -> Dict[str, Any]:
        """
        添加日历事件参与人（使用 tenant_access_token，无需用户授权）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event-attendee/create
        
        Args:
            calendar_id: 日历ID
            event_id: 事件ID
            attendees: 参与人列表，格式：[{"id": "open_id", "type": "user", "is_optional": False}]
            user_id_type: 用户ID类型
            need_notification: 是否发送bot通知（邀请），默认True
            
        Returns:
            包含结果信息的字典
        """
        try:
            # 构建参与人数据
            attendee_list = []
            for att in attendees:
                attendee_type = att.get("type", "user")
                attendee_id = att.get("id")
                
                # 根据类型设置不同的ID字段
                builder = CalendarEventAttendee.builder() \
                    .type(attendee_type) \
                    .is_optional(att.get("is_optional", False))
                
                if attendee_type == "user":
                    builder = builder.user_id(attendee_id)
                elif attendee_type == "chat":
                    builder = builder.chat_id(attendee_id)
                elif attendee_type == "resource":
                    builder = builder.room_id(attendee_id)
                elif attendee_type == "third_party":
                    builder = builder.third_party_email(attendee_id)
                
                attendee = builder.build()
                attendee_list.append(attendee)
            
            # 构建参与人请求体
            attendee_data = CreateCalendarEventAttendeeRequestBody.builder() \
                .attendees(attendee_list) \
                .need_notification(need_notification) \
                .build()
            
            # 构建请求对象
            request = CreateCalendarEventAttendeeRequest.builder() \
                .calendar_id(calendar_id) \
                .event_id(event_id) \
                .request_body(attendee_data) \
                .user_id_type(user_id_type) \
                .build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 添加参与人")
            
            # 发起请求
            notification_text = "并发送邀请通知" if need_notification else "（不发送通知）"
            logger.info(f"📋 添加 {len(attendees)} 个参与人到日历事件{notification_text}")
            response: CreateCalendarEventAttendeeResponse = self.client.calendar.v4.calendar_event_attendee.create(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.warning(f"⚠️ 添加参与人失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            logger.info(f"✅ 成功添加 {len(attendees)} 个参与人")
            
            return {
                "success": True,
                "attendees_count": len(attendees)
            }
            
        except Exception as e:
            logger.error(f"❌ 添加参与人异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"添加参与人异常: {str(e)}"
            }
    
    def list_calendar_events(
        self,
        calendar_id: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        page_size: int = 50,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询日历事件列表（使用 tenant_access_token，无需用户授权）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/list
        
        Args:
            calendar_id: 日历ID（应用日历）
            start_time: 开始时间（Unix时间戳，秒级，可选）
            end_time: 结束时间（Unix时间戳，秒级，可选）
            page_size: 每页数量，默认50
            page_token: 分页token，可选
            
        Returns:
            包含事件列表的字典
        """
        try:
            # 构建请求对象
            request_builder = ListCalendarEventRequest.builder() \
                .calendar_id(calendar_id) \
                .page_size(page_size)
            
            if page_token:
                request_builder.page_token(page_token)
            
            # 设置时间范围（如果提供）
            # 注意：SDK 的 builder 直接支持 start_time 和 end_time 方法
            if start_time:
                request_builder.start_time(str(start_time))
            if end_time:
                request_builder.end_time(str(end_time))
            
            request = request_builder.build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 查询日历事件列表")
            
            # 发起请求
            logger.info(f"📅 查询日历事件列表: calendar_id={calendar_id}, start_time={start_time}, end_time={end_time}")
            response: ListCalendarEventResponse = self.client.calendar.v4.calendar_event.list(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 查询日历事件列表失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            events = []
            if response.data and hasattr(response.data, 'items'):
                for item in response.data.items:
                    if hasattr(item, 'event'):
                        event = item.event
                        event_data = {
                            "event_id": event.event_id if hasattr(event, 'event_id') else None,
                            "summary": event.summary if hasattr(event, 'summary') else "",
                            "description": event.description if hasattr(event, 'description') else "",
                            "start_time": None,
                            "end_time": None,
                            "start_time_display": None,
                            "end_time_display": None,
                            "meeting_url": None,
                            "attendees": [],
                            "attendees_count": 0
                        }
                        
                        # 解析开始时间
                        if hasattr(event, 'start_time') and event.start_time:
                            if hasattr(event.start_time, 'timestamp'):
                                event_data["start_time"] = int(event.start_time.timestamp)
                                event_data["start_time_display"] = datetime.fromtimestamp(int(event.start_time.timestamp)).strftime('%Y-%m-%d %H:%M:%S')
                        
                        # 解析结束时间
                        if hasattr(event, 'end_time') and event.end_time:
                            if hasattr(event.end_time, 'timestamp'):
                                event_data["end_time"] = int(event.end_time.timestamp)
                                event_data["end_time_display"] = datetime.fromtimestamp(int(event.end_time.timestamp)).strftime('%Y-%m-%d %H:%M:%S')
                        
                        # 解析会议链接
                        if hasattr(event, 'vchat') and event.vchat:
                            if hasattr(event.vchat, 'url'):
                                event_data["meeting_url"] = event.vchat.url
                        
                        # 解析参会人
                        if hasattr(event, 'attendees') and event.attendees:
                            for attendee in event.attendees:
                                attendee_data = {}
                                if hasattr(attendee, 'type_') and attendee.type_ == 1:  # 用户类型
                                    if hasattr(attendee, 'user_id'):
                                        attendee_data["user_id"] = attendee.user_id
                                    if hasattr(attendee, 'open_id'):
                                        attendee_data["open_id"] = attendee.open_id
                                event_data["attendees"].append(attendee_data)
                            event_data["attendees_count"] = len(event_data["attendees"])
                        
                        events.append(event_data)
            
            page_token = response.data.page_token if response.data and hasattr(response.data, 'page_token') else None
            has_more = response.data.has_more if response.data and hasattr(response.data, 'has_more') else False
            
            logger.info(f"✅ 查询日历事件列表成功，找到 {len(events)} 个事件")
            
            return {
                "success": True,
                "events": events,
                "page_token": page_token,
                "has_more": has_more,
                "count": len(events)
            }
            
        except Exception as e:
            logger.error(f"❌ 查询日历事件列表异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"查询日历事件列表异常: {str(e)}"
            }
    
    def get_calendar_event(
        self,
        calendar_id: str,
        event_id: str
    ) -> Dict[str, Any]:
        """
        获取日历事件详情（使用 tenant_access_token，无需用户授权）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/get
        
        Args:
            calendar_id: 日历ID（应用日历）
            event_id: 事件ID
            
        Returns:
            包含事件信息的字典
        """
        try:
            # 构建请求对象
            request = GetCalendarEventRequest.builder() \
                .calendar_id(calendar_id) \
                .event_id(event_id) \
                .build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 获取日历事件")
            
            # 发起请求
            logger.info(f"📅 获取日历事件: calendar_id={calendar_id}, event_id={event_id}")
            response: GetCalendarEventResponse = self.client.calendar.v4.calendar_event.get(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 获取日历事件失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            event_data = response.data.event if response.data and hasattr(response.data, 'event') else None
            
            if not event_data:
                logger.error("❌ 响应中未包含事件数据")
                return {
                    "success": False,
                    "error_msg": "响应中未包含事件数据"
                }
            
            # 提取事件信息
            event_id = event_data.event_id if hasattr(event_data, 'event_id') else None
            summary = event_data.summary if hasattr(event_data, 'summary') else ""
            description = event_data.description if hasattr(event_data, 'description') else ""
            
            # 提取时间信息
            start_time = None
            end_time = None
            if hasattr(event_data, 'start_time') and event_data.start_time:
                start_time = int(event_data.start_time.timestamp) if hasattr(event_data.start_time, 'timestamp') else None
            if hasattr(event_data, 'end_time') and event_data.end_time:
                end_time = int(event_data.end_time.timestamp) if hasattr(event_data.end_time, 'timestamp') else None
            
            # 提取会议链接
            meeting_url = None
            if hasattr(event_data, 'vchat') and event_data.vchat:
                meeting_url = event_data.vchat.meeting_url if hasattr(event_data.vchat, 'meeting_url') else None
            
            # 提取参与人信息
            attendees = []
            if hasattr(event_data, 'attendees') and event_data.attendees:
                for att in event_data.attendees:
                    attendee_info = {}
                    if hasattr(att, 'type'):
                        attendee_info["type"] = att.type
                    if hasattr(att, 'user_id'):
                        attendee_info["user_id"] = att.user_id
                    if hasattr(att, 'is_optional'):
                        attendee_info["is_optional"] = att.is_optional
                    attendees.append(attendee_info)
            
            logger.info(f"✅ 成功获取日历事件: {summary}")
            
            return {
                "success": True,
                "event_id": event_id,
                "summary": summary,
                "description": description,
                "start_time": start_time,
                "end_time": end_time,
                "meeting_url": meeting_url,
                "attendees": attendees,
                "event": {
                    "event_id": event_id,
                    "summary": summary,
                    "description": description,
                    "start_time": start_time,
                    "end_time": end_time,
                    "meeting_url": meeting_url,
                    "attendees_count": len(attendees)
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 获取日历事件异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"获取日历事件异常: {str(e)}"
            }
    
    def update_calendar_event(
        self,
        calendar_id: str,
        event_id: str,
        topic: Optional[str] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        description: Optional[str] = None,
        meeting_url: Optional[str] = None,
        need_notification: bool = True
    ) -> Dict[str, Any]:
        """
        更新日历事件（使用 tenant_access_token，无需用户授权）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/patch
        
        Args:
            calendar_id: 日历ID（应用日历）
            event_id: 事件ID
            topic: 事件标题（可选）
            start_time: 开始时间（Unix时间戳，秒级，可选）
            end_time: 结束时间（Unix时间戳，秒级，可选）
            description: 事件描述（可选）
            meeting_url: 会议链接（可选，用于更新vchat）
            need_notification: 是否发送通知，默认True
            
        Returns:
            包含更新结果的字典
        """
        try:
            # 构建事件数据（只更新提供的字段）
            event_builder = CalendarEvent.builder()
            
            if topic:
                event_builder.summary(topic)
            
            if description is not None:
                event_builder.description(description)
            
            if start_time:
                event_builder.start_time(TimeInfo.builder()
                    .timestamp(str(start_time))
                    .timezone("Asia/Shanghai")
                    .build())
            
            if end_time:
                event_builder.end_time(TimeInfo.builder()
                    .timestamp(str(end_time))
                    .timezone("Asia/Shanghai")
                    .build())
            
            if meeting_url is not None:
                if meeting_url:
                    vchat = Vchat.builder() \
                        .vc_type("third_party") \
                        .icon_type("vc") \
                        .description("点击加入会议") \
                        .meeting_url(meeting_url) \
                        .build()
                else:
                    vchat = Vchat.builder() \
                        .vc_type("no_meeting") \
                        .icon_type("default") \
                        .description("") \
                        .meeting_url("") \
                        .build()
                event_builder.vchat(vchat)
            
            event_builder.need_notification(need_notification)
            
            event_data = event_builder.build()
            
            # 构建请求对象
            request = PatchCalendarEventRequest.builder() \
                .calendar_id(calendar_id) \
                .event_id(event_id) \
                .request_body(event_data) \
                .build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 更新日历事件")
            
            # 发起请求
            notification_text = "并发送通知" if need_notification else "（不发送通知）"
            logger.info(f"📅 更新日历事件: calendar_id={calendar_id}, event_id={event_id}{notification_text}")
            response: PatchCalendarEventResponse = self.client.calendar.v4.calendar_event.patch(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 更新日历事件失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            event_data = response.data.event if response.data and hasattr(response.data, 'event') else None
            
            if not event_data:
                logger.error("❌ 响应中未包含事件数据")
                return {
                    "success": False,
                    "error_msg": "响应中未包含事件数据"
                }
            
            event_id_updated = event_data.event_id if hasattr(event_data, 'event_id') else None
            
            logger.info(f"✅ 日历事件更新成功，event_id: {event_id_updated}")
            
            return {
                "success": True,
                "event_id": event_id_updated,
                "event": {
                    "event_id": event_id_updated,
                    "summary": event_data.summary if hasattr(event_data, 'summary') else None
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 更新日历事件异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"更新日历事件异常: {str(e)}"
            }
    
    def delete_meeting_reserve(
        self,
        reserve_id: str
    ) -> Dict[str, Any]:
        """
        删除会议预约（使用 tenant_access_token）
        
        参考文档：https://open.feishu.cn/document/server-docs/vc-v1/reserve/delete
        
        Args:
            reserve_id: 会议预约ID
            
        Returns:
            包含删除结果的字典
        """
        try:
            from lark_oapi.api.vc.v1 import DeleteReserveRequest, DeleteReserveResponse
            
            # 构建请求对象
            request = DeleteReserveRequest.builder() \
                .reserve_id(reserve_id) \
                .build()
            
            # 使用 tenant_access_token（应用身份）
            logger.debug("🔑 使用 tenant_access_token 删除会议预约")
            
            # 发起请求
            logger.info(f"🗑️ 删除会议预约: reserve_id={reserve_id}")
            response: DeleteReserveResponse = self.client.vc.v1.reserve.delete(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 删除会议预约失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            logger.info(f"✅ 会议预约删除成功，reserve_id: {reserve_id}")
            
            return {
                "success": True,
                "reserve_id": reserve_id,
                "message": "会议预约已删除"
            }
            
        except Exception as e:
            logger.error(f"❌ 删除会议预约异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"删除会议预约异常: {str(e)}"
            }
    
    def delete_calendar_event(
        self,
        calendar_id: str,
        event_id: str,
        need_notification: bool = True
    ) -> Dict[str, Any]:
        """
        删除日历事件（使用 tenant_access_token，无需用户授权）
        
        参考文档：https://open.feishu.cn/document/server-docs/calendar-v4/calendar-event/delete
        
        Args:
            calendar_id: 日历ID（应用日历）
            event_id: 事件ID
            need_notification: 是否发送通知，默认True
            
        Returns:
            包含删除结果的字典
        """
        try:
            # 构建请求对象
            # 注意：根据飞书API文档，删除接口的need_notification是查询参数，且需要字符串类型（"true"/"false"）
            request_builder = DeleteCalendarEventRequest.builder() \
                .calendar_id(calendar_id) \
                .event_id(event_id)
            
            # need_notification 作为查询参数，需要转换为字符串（小写）
            # SDK的need_notification方法接受str类型，API期望"true"或"false"（小写）
            if need_notification is not None:
                need_notification_str = "true" if need_notification else "false"
                request_builder.need_notification(need_notification_str)
            
            request = request_builder.build()
            
            # 使用 tenant_access_token（应用身份，无需用户授权）
            logger.debug("🔑 使用 tenant_access_token 删除日历事件")
            
            # 发起请求
            notification_text = "并发送通知" if need_notification else "（不发送通知）"
            logger.info(f"🗑️ 删除日历事件: calendar_id={calendar_id}, event_id={event_id}{notification_text}")
            response: DeleteCalendarEventResponse = self.client.calendar.v4.calendar_event.delete(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 删除日历事件失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            logger.info(f"✅ 日历事件删除成功，event_id: {event_id}")
            
            return {
                "success": True,
                "event_id": event_id,
                "message": "日历事件已删除"
            }
            
        except Exception as e:
            logger.error(f"❌ 删除日历事件异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"删除日历事件异常: {str(e)}"
            }


class FeishuMeetingBaseTool(BaseTool):
    """飞书会议工具基类，提供统一的 SDK 客户端初始化
    
    注意：所有工具实例共享同一个 SDK 客户端实例，以便缓存应用日历信息
    """
    
    # 类级别的 SDK 客户端实例（所有工具共享）
    _shared_sdk_client: Optional[FeishuMeetingSDKClient] = None
    
    def __init__(self):
        super().__init__()
        self.sdk_client = self._get_shared_sdk_client()
    
    @classmethod
    def _get_shared_sdk_client(cls) -> Optional[FeishuMeetingSDKClient]:
        """
        获取共享的飞书 SDK 客户端实例（单例模式）
        
        Returns:
            FeishuMeetingSDKClient 实例，如果初始化失败则返回 None
        """
        # 如果已存在，直接返回
        if cls._shared_sdk_client is not None:
            return cls._shared_sdk_client
        
        # 初始化新的客户端实例
        if not HAS_LARK_SDK:
            logger.error("❌ 未安装飞书官方 SDK，无法使用此工具")
            return None
        
        app_id = getattr(settings, 'FEISHU_APP_ID', None)
        app_secret = getattr(settings, 'FEISHU_APP_SECRET', None)
        
        if not app_id or not app_secret:
            logger.warning("⚠️ 未配置飞书 APP_ID 或 APP_SECRET")
            return None
        
        try:
            # 注意：使用应用日历+邀请方案（无需OAuth授权）
            cls._shared_sdk_client = FeishuMeetingSDKClient(app_id, app_secret)
            logger.info(f"✅ 创建共享的飞书 SDK 客户端实例")
            return cls._shared_sdk_client
        except Exception as e:
            logger.error(f"❌ 初始化飞书 SDK 客户端失败: {e}")
            return None
    
    @classmethod
    def clear_cache(cls):
        """
        清除共享的 SDK 客户端实例和应用日历缓存
        
        用于：
        1. 重置缓存状态
        2. 强制重新查询应用日历
        3. 解决缓存导致的日历不一致问题
        """
        if cls._shared_sdk_client is not None:
            # 清除 SDK 客户端内部的日历缓存
            if hasattr(cls._shared_sdk_client, '_app_calendar_cache'):
                cls._shared_sdk_client._app_calendar_cache = None
                logger.info("✅ 已清除应用日历缓存")
        
        # 清除共享的 SDK 客户端实例
        cls._shared_sdk_client = None
        logger.info("✅ 已清除共享的 SDK 客户端实例")


class CreateMeetingReserveTool(FeishuMeetingBaseTool):
    """创建视频会议预约工具（使用官方 SDK）"""
    
    name = "create_meeting_reserve"
    description = """使用飞书官方 SDK 创建视频会议预约。
    
支持功能：
- 创建视频会议预约（支持预约最近30天内的会议）
- 设置会议主题、开始时间、时长
- 添加初始参会人（可选，会自动通过日历事件添加并发送邀请）
- 设置会议密码（可选）
- 自动录制（可选）
- 自动创建日历事件，确保会议显示在日历中
- 自动发送邀请通知给所有参会人

⚠️ 重要参数说明：
- owner_id：会议所有者的open_id/user_id（必需）
  - 如果不知道当前用户的open_id，可以先使用find_user_by_department工具查找
  - 或者通过用户配置获取（如果已绑定飞书账号）
- start_time：会议开始时间（必需）
  - 格式：Unix时间戳（秒级），可以是字符串或数字
  - 示例：1762561800 或 "1762561800"
  - 推荐：使用 natural_time_parser 工具解析时间，直接使用返回结果中的 timestamp 字段
  - 不能早于当前时间，不能超过30天
- participant_ids：初始参会人用户ID列表（可选）
  - 格式：["open_id1", "open_id2", ...]
  - 建议：如果只有姓名，先使用find_user_by_department工具查找用户的open_id
  - 注意：参会人会通过日历事件自动添加，并收到邀请通知
- duration：会议时长（分钟），默认60分钟
- user_id_type：用户ID类型，默认open_id
  - open_id：应用内用户的唯一标识（推荐）
  - user_id：租户内用户的唯一标识
  - union_id：多租户场景下用户的统一标识

📋 返回值说明：
创建成功后会返回：
- reserve_id：会议预约ID
- meeting_no：会议号
- meeting_url：会议链接
- calendar_id：应用日历ID（用于后续查询、更新、删除操作）
- calendar_event_id：日历事件ID（用于后续查询、更新、删除操作）
- invitations_sent：是否已发送邀请通知

💡 使用流程建议：
1. 如果不知道参会人的open_id，先使用find_user_by_department工具查找
2. 使用 natural_time_parser 工具解析会议时间，获取 timestamp 字段作为 start_time
3. 调用此工具创建会议，传入owner_id、start_time（使用timestamp字段）、topic、participant_ids等参数
4. 会议创建成功后会自动创建待办事项，并发送邀请通知给所有参会人
5. 保存返回的calendar_id和calendar_event_id，用于后续查询、更新、删除操作

适用场景：
- 用户说"帮我预约一个会议"、"创建会议"、"安排会议"
- 用户提到会议时间、参会人、主题等信息

示例输入：
- "明天下午3点创建一个技术讨论会议，邀请张总和李经理"
- "预约一个会议，主题是项目评审，时间是下周一上午10点，持续1小时"
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "会议主题"
            },
            "start_time": {
                "type": ["string", "integer"],
                "description": "会议开始时间（Unix时间戳，秒级）。可以是字符串或数字，例如：1762561800 或 \"1762561800\"。不能早于当前时间，不能超过30天"
            },
            "duration": {
                "type": "integer",
                "description": "会议时长（分钟），默认60分钟",
                "default": 60
            },
            "owner_id": {
                "type": "string",
                "description": "会议所有者用户ID（open_id/user_id，根据user_id_type确定）。如果不知道当前用户的open_id，可以先使用find_user_by_department工具查找，或从用户配置中获取"
            },
            "participant_ids": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": "初始参会人用户ID列表（可选）。格式：[\"open_id1\", \"open_id2\", ...]。如果只有姓名，先使用find_user_by_department工具查找用户的open_id。参会人会通过日历事件自动添加并收到邀请通知"
            },
            "user_id_type": {
                "type": "string",
                "enum": ["open_id", "user_id", "union_id"],
                "description": "用户ID类型，默认open_id",
                "default": "open_id"
            },
            "password": {
                "type": "string",
                "description": "会议密码（可选）"
            },
            "auto_record": {
                "type": "boolean",
                "description": "是否自动录制，默认False",
                "default": False
            }
        },
        "required": ["topic", "start_time", "owner_id"]
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行创建视频会议预约"""
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                params_dict = {"topic": params}
        else:
            params_dict = params
        
        # 从 kwargs 获取 user_id（用于自动创建待办）
        # 注意：user_id 是应用层的用户ID，不是飞书的 open_id
        user_id = kwargs.get("user_id") or params_dict.get("user_id")
        
        if not self.sdk_client:
            return json.dumps({
                "success": False,
                "error": "飞书 SDK 客户端未初始化，请检查配置和SDK安装"
            }, ensure_ascii=False)
        
        # 获取参数
        topic = params_dict.get("topic")
        start_time_str = params_dict.get("start_time")
        duration = params_dict.get("duration", 60)
        owner_id = params_dict.get("owner_id")
        participant_ids = params_dict.get("participant_ids", [])
        participant_names = params_dict.get("participant_names", [])  # 参会人姓名（用于待办）
        user_id_type = params_dict.get("user_id_type", "open_id")
        password = params_dict.get("password")
        auto_record = params_dict.get("auto_record", False)
        
        # 验证必需参数
        if not topic:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 topic（会议主题）"
            }, ensure_ascii=False)
        
        if not start_time_str:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 start_time（会议开始时间）"
            }, ensure_ascii=False)
        
        if not owner_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 owner_id（会议所有者open_id）"
            }, ensure_ascii=False)
        
        # 解析开始时间
        try:
            start_time = int(start_time_str)
        except (ValueError, TypeError):
            return json.dumps({
                "success": False,
                "error": f"start_time 格式错误，需要Unix时间戳（秒级），当前值: {start_time_str}"
            }, ensure_ascii=False)
        
        # 验证会议时间
        current_time = int(time.time())
        
        # 验证1：会议开始时间不能早于当前时间
        if start_time < current_time:
            return json.dumps({
                "success": False,
                "error": f"会议开始时间不能早于当前时间（当前时间: {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')}）"
            }, ensure_ascii=False)
        
        # 验证2：会议开始时间不能超过30天
        max_start_time = current_time + (30 * 24 * 60 * 60)  # 30天后
        if start_time > max_start_time:
            return json.dumps({
                "success": False,
                "error": f"预约时间超出限制，最多只能预约30天内的会议（当前时间: {datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')}）"
            }, ensure_ascii=False)
        
        # 计算结束时间
        end_time = start_time + (duration * 60)
        
        # 调用 SDK 创建会议预约
        result = self.sdk_client.create_meeting_reserve(
            owner_id=owner_id,
            start_time=start_time,
            end_time=end_time,
            topic=topic,
            duration_minutes=duration,
            participant_ids=participant_ids if participant_ids else None,
            user_id_type=user_id_type,
            password=password,
            auto_record=auto_record,
            # 预约会议使用 tenant_access_token（应用身份，无需用户授权）
        )
        
        if result.get("success"):
            # 会议预约创建成功，尝试创建日历事件
            reserve_id = result.get("reserve_id")
            meeting_no = result.get("meeting_no")
            meeting_url = result.get("meeting_url")
            
            # 创建日历事件，确保会议显示在用户日历中
            # 使用应用日历+邀请方案（无需OAuth授权）
            logger.info("📅 开始创建日历事件，使用应用日历+邀请方案（无需OAuth授权）...")
            calendar_result = self._create_calendar_event_for_meeting(
                sdk_client=self.sdk_client,
                owner_id=owner_id,
                topic=topic,
                start_time=start_time,
                end_time=end_time,
                meeting_url=meeting_url,
                meeting_no=meeting_no,
                participant_ids=participant_ids if participant_ids else [],
                user_id_type=user_id_type
            )
            
            # 格式化返回结果
            reserve = result.get("reserve", {})
            result_data = {
                "success": True,
                "message": f"✅ 会议预约创建成功: {topic}",
                "reserve_id": reserve_id,
                "meeting_no": meeting_no,
                "meeting_url": meeting_url,
                "live_link": result.get("live_link"),
                "start_time_display": datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
                "end_time_display": datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S"),
                "topic": topic,
                "duration_minutes": duration,
                "owner_id": owner_id,
                "participant_count": len(participant_ids) if participant_ids else 0
            }
            
            # 添加日历事件创建结果
            if calendar_result.get("success"):
                result_data["calendar_event_created"] = True
                result_data["calendar_event_id"] = calendar_result.get("event_id")
                result_data["calendar_id"] = calendar_result.get("calendar_id")
                result_data["participants_added_via_calendar"] = calendar_result.get("attendees_added", False)
                result_data["invitations_sent"] = calendar_result.get("invitations_sent", False)
                result_data["note"] = calendar_result.get("note", "✅ 会议已创建并添加到用户日历中，参会人已收到通知")
            else:
                result_data["calendar_event_created"] = False
                result_data["calendar_event_id"] = None
                result_data["calendar_id"] = None
                result_data["participants_added_via_calendar"] = False
                result_data["invitations_sent"] = False
                result_data["note"] = f"⚠️ 会议预约创建成功，但日历事件创建失败: {calendar_result.get('error_msg')}。会议链接仍然可用。"
            
            # 自动创建待办事项
            try:
                todo_created = self._create_todo_for_meeting(
                    topic=topic,
                    start_time=start_time,
                    end_time=end_time,
                    meeting_url=meeting_url,
                    participant_names=participant_names,
                    user_id=user_id,
                    reserve_id=result.get("reserve_id"),
                    event_id=result_data.get("calendar_event_id"),
                    calendar_id=result_data.get("calendar_id")
                )
                if todo_created:
                    result_data["todo_created"] = True
                    result_data["todo_message"] = f"✅ 已自动为您创建会议待办：{datetime.fromtimestamp(start_time).strftime('%Y-%m-%d %H:%M')}-{datetime.fromtimestamp(end_time).strftime('%H:%M')} {topic}"
                else:
                    result_data["todo_created"] = False
            except Exception as e:
                logger.warning(f"⚠️ 自动创建待办失败: {e}")
                result_data["todo_created"] = False
            
            return json.dumps(result_data, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": result.get("error_msg", "未知错误"),
                "error_code": result.get("error_code"),
                "log_id": result.get("log_id")
            }, ensure_ascii=False)
    
    def _create_todo_for_meeting(
        self,
        topic: str,
        start_time: int,
        end_time: int,
        meeting_url: str,
        participant_names: List[str] = None,
        user_id: str = None,
        reserve_id: str = None,
        event_id: str = None,
        calendar_id: str = None
    ) -> bool:
        """
        为会议自动创建待办事项
        
        Args:
            topic: 会议主题
            start_time: 开始时间（Unix时间戳）
            end_time: 结束时间（Unix时间戳）
            meeting_url: 会议链接
            participant_names: 参会人姓名列表
            user_id: 用户ID
            reserve_id: 会议预约ID（保存到待办中，用于后续查询和删除会议）
            event_id: 日历事件ID（保存到待办中，用于后续删除日历事件）
            calendar_id: 日历ID（保存到待办中，用于后续删除日历事件）
        
        Args:
            topic: 会议主题
            start_time: 会议开始时间（Unix时间戳）
            end_time: 会议结束时间（Unix时间戳）
            meeting_url: 会议链接
            participant_names: 参会人姓名列表（可选）
            user_id: 用户ID（可选，如果未提供则跳过创建）
        
        Returns:
            bool: 是否成功创建待办
        """
        if not user_id:
            logger.debug("⚠️ 未提供 user_id，跳过自动创建待办")
            return False
        
        try:
            from ty_mem_agent.memory.todo_manager import get_todo_manager
            
            # 验证 user_id 是字符串类型
            if not isinstance(user_id, str):
                logger.warning(f"⚠️ user_id 类型错误: {type(user_id)}, 值: {user_id}，跳过创建待办")
                return False
            
            todo_manager = get_todo_manager()
            
            # 构建待办描述
            description_parts = [f"会议链接: {meeting_url}"]
            if participant_names:
                description_parts.append(f"参会人: {', '.join(participant_names)}")
            description = "\n".join(description_parts)
            
            # 创建待办（deadline 使用 ISO 格式字符串）
            # 注意：使用文件顶部导入的 datetime，不是重新导入
            deadline_str = datetime.fromtimestamp(start_time).isoformat()
            
            todo_data = {
                "title": topic,
                "description": description,
                "deadline": deadline_str,
                "location": "线上会议",
                "participants": participant_names if participant_names else [],
                "priority": 1,  # 会议待办优先级设为1（高优先级）
                "tags": ["会议", "飞书会议"],
                # 保存会议相关ID，用于后续查询和删除
                "reserve_id": reserve_id if reserve_id else None,
                "event_id": event_id if event_id else None,
                "calendar_id": calendar_id if calendar_id else None
            }
            
            todo = todo_manager.create_todo(user_id, todo_data)
            logger.info(f"✅ 自动创建会议待办成功: {todo.id} - {topic}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 自动创建会议待办失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _create_calendar_event_for_meeting(
        self,
        sdk_client: FeishuMeetingSDKClient,
        owner_id: str,
        topic: str,
        start_time: int,
        end_time: int,
        meeting_url: str,
        meeting_no: str,
        participant_ids: List[str],
        user_id_type: str
    ) -> Dict[str, Any]:
        """
        为会议创建日历事件（使用应用日历+邀请方案，无需OAuth授权）
        
        流程：
        1. 获取或创建应用日历（使用tenant_access_token）
        2. 在应用日历中创建事件（使用tenant_access_token）
        3. 添加参与人并发送邀请通知（使用tenant_access_token，need_notification=true）
        4. 用户收到邀请通知，接受后会议会出现在个人日历中
        
        Args:
            sdk_client: SDK客户端实例
            owner_id: 会议所有者用户ID
            topic: 会议主题
            start_time: 开始时间
            end_time: 结束时间
            meeting_url: 会议链接
            meeting_no: 会议号
            participant_ids: 参会人列表
            user_id_type: 用户ID类型
            
        Returns:
            包含创建结果的字典
        """
        try:
            logger.info("📅 使用应用日历+邀请方案（无需OAuth授权）")
            
            # 步骤1：获取应用主日历
            calendar_result = sdk_client.get_primary_calendar()
            
            if not calendar_result.get("success"):
                return calendar_result
            
            calendar_id = calendar_result.get("calendar_id")
            is_new_calendar = calendar_result.get("is_new", False)
            
            if is_new_calendar:
                logger.info(f"✅ 创建了新的应用日历: {calendar_id}")
            else:
                logger.info(f"✅ 使用已存在的应用日历: {calendar_id}")
            
            # 步骤2：在应用日历中创建事件
            description = f"会议号: {meeting_no}\n会议链接: {meeting_url}"
            if meeting_url:
                description += f"\n\n点击加入会议: {meeting_url}"
            
            event_result = sdk_client.create_calendar_event(
                calendar_id=calendar_id,
                topic=topic,
                start_time=start_time,
                end_time=end_time,
                description=description,
                meeting_url=meeting_url
            )
            
            if not event_result.get("success"):
                return event_result
            
            event_id = event_result.get("event_id")
            
            # 步骤3：添加参与人并发送邀请通知
            attendees = []
            
            # 添加owner
            attendees.append({
                "id": owner_id,
                "type": "user",
                "is_optional": False
            })
            
            # 添加参会人
            for pid in participant_ids:
                if pid != owner_id:
                    attendees.append({
                        "id": pid,
                        "type": "user",
                        "is_optional": False
                    })
            
            if attendees:
                attendees_result = sdk_client.add_calendar_event_attendees(
                    calendar_id=calendar_id,
                    event_id=event_id,
                    attendees=attendees,
                    user_id_type=user_id_type,
                    need_notification=True  # 关键：发送邀请通知
                )
                
                if attendees_result.get("success"):
                    logger.info(f"✅ 成功添加 {len(attendees)} 个参与人并发送邀请通知")
                    logger.info(f"💡 用户会收到邀请通知，接受后会议会出现在个人日历中")
                else:
                    logger.warning(f"⚠️ 添加参与人失败: {attendees_result.get('error_msg')}")
                
                return {
                    "success": True,
                    "event_id": event_id,
                    "calendar_id": calendar_id,
                    "attendees_added": attendees_result.get("success", False),
                    "invitations_sent": attendees_result.get("success", False),
                    "note": "用户会收到邀请通知，接受后会议会出现在个人日历中"
                }
            
            return {
                "success": True,
                "event_id": event_id,
                "calendar_id": calendar_id,
                "attendees_added": False,
                "invitations_sent": False
            }
            
        except Exception as e:
            logger.error(f"❌ 创建日历事件异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"创建日历事件异常: {str(e)}"
            }


class FindUserByDepartmentTool(FeishuMeetingBaseTool):
    """通过部门查找用户工具（使用官方 SDK）"""
    
    name = "find_user_by_department"
    description = """通过部门ID获取该部门的用户列表，使用飞书官方 SDK 实现。
    
支持功能：
- 通过部门ID获取部门下的用户列表
- 支持根部门（department_id="0"）获取所有用户
- 支持分页查询
- 返回用户的基本信息（姓名、open_id、user_id、email、mobile等）

⚠️ 重要参数说明：
- department_id：部门ID（必需）
  - 根部门ID为"0"，可以获取所有用户
  - 如果不知道部门ID，需要先通过其他方式获取
- user_id_type：返回的用户ID类型，默认open_id
  - open_id：应用内用户的唯一标识（推荐，用于创建会议）
  - user_id：租户内用户的唯一标识
  - union_id：多租户场景下用户的统一标识
- page_size：每页返回数量，默认50，最大100
- page_token：分页标记，用于获取下一页数据（可选）

📋 返回值说明：
- success：是否成功
- users：用户列表，每个用户包含：
  - name：用户姓名（可用于匹配）
  - open_id：用户open_id（可用于创建会议的owner_id或participant_ids）
  - user_id：用户user_id
  - email：用户邮箱（如果有）
  - mobile：用户手机号（如果有）
  - id：通用ID字段（等于open_id或user_id，根据user_id_type确定）
- has_more：是否还有更多数据
- page_token：分页标记（如果有更多数据）

💡 使用建议：
1. 如果用户说"找XX"、"邀请XX"，可以使用此工具查找用户的open_id
2. 使用department_id="0"可以获取所有用户，然后根据name字段匹配
3. 返回的open_id可以直接用于create_meeting_reserve的owner_id或participant_ids参数
4. 如果返回的用户很多，可以使用page_token获取下一页

适用场景：
- AI眼镜等语音交互场景，用户可以直接说人名（如"枭楠"、"尚君"）
- 创建会议时需要查找参会人，但不知道手机号或邮箱
- 需要获取某个部门的所有成员
- 需要根据姓名查找用户的open_id

示例输入：
- "查找所有用户"（department_id="0"）
- "获取部门ID为0的所有用户"
- "查找技术部门的成员"（需要先知道技术部门的ID）
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "department_id": {
                "type": "string",
                "description": "部门ID（根部门为'0'，可以获取所有用户）"
            },
            "user_id_type": {
                "type": "string",
                "enum": ["open_id", "user_id", "union_id"],
                "description": "返回的用户ID类型，默认open_id",
                "default": "open_id"
            },
            "department_id_type": {
                "type": "string",
                "enum": ["open_department_id", "department_id"],
                "description": "部门ID类型，默认open_department_id",
                "default": "open_department_id"
            },
            "page_size": {
                "type": "integer",
                "description": "每页返回数量，默认50，最大100",
                "default": 50
            },
            "page_token": {
                "type": "string",
                "description": "分页标记，用于获取下一页数据（可选）"
            }
        },
        "required": ["department_id"]
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行通过部门查找用户"""
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                params_dict = {"department_id": params}
        else:
            params_dict = params
        
        if not self.sdk_client:
            return json.dumps({
                "success": False,
                "error": "飞书 SDK 客户端未初始化，请检查配置和SDK安装"
            }, ensure_ascii=False)
        
        # 获取参数
        department_id = params_dict.get("department_id")
        user_id_type = params_dict.get("user_id_type", "open_id")
        department_id_type = params_dict.get("department_id_type", "open_department_id")
        page_size = params_dict.get("page_size", 50)
        page_token = params_dict.get("page_token")
        
        # 验证必需参数
        if not department_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 department_id（部门ID）"
            }, ensure_ascii=False)
        
        # 验证 page_size
        if page_size > 100:
            page_size = 100
            logger.warning(f"⚠️ page_size 超过最大值100，已调整为100")
        
        try:
            # 使用 SDK 查找用户
            result = self._find_users_by_department(
                department_id=department_id,
                user_id_type=user_id_type,
                department_id_type=department_id_type,
                page_size=page_size,
                page_token=page_token
            )
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 查找用户异常: {e}")
            import traceback
            traceback.print_exc()
            return json.dumps({
                "success": False,
                "error": f"查找用户异常: {str(e)}"
            }, ensure_ascii=False)
    
    def _find_users_by_department(
        self,
        department_id: str,
        user_id_type: str = "open_id",
        department_id_type: str = "open_department_id",
        page_size: int = 50,
        page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        使用飞书官方 SDK 通过部门查找用户
        
        参考文档：https://open.feishu.cn/document/server-docs/contact-v3/user/find_by_department
        
        Args:
            department_id: 部门ID
            user_id_type: 用户ID类型
            department_id_type: 部门ID类型
            page_size: 每页返回数量
            page_token: 分页标记
            
        Returns:
            包含用户列表的字典
        """
        try:
            # 构建请求对象
            request_builder = FindByDepartmentUserRequest.builder() \
                .user_id_type(user_id_type) \
                .department_id_type(department_id_type) \
                .department_id(department_id) \
                .page_size(page_size)
            
            if page_token:
                request_builder.page_token(page_token)
            
            request = request_builder.build()
            
            # 发起请求
            logger.info(f"🔍 通过部门查找用户: department_id={department_id}, page_size={page_size}")
            response: FindByDepartmentUserResponse = self.sdk_client.client.contact.v3.user.find_by_department(request)
            
            # 处理失败返回
            if not response.success():
                error_msg = response.msg
                error_code = response.code
                log_id = response.get_log_id()
                
                logger.error(f"❌ 查找用户失败: {error_msg} (code: {error_code}, log_id: {log_id})")
                
                # 记录详细错误信息
                try:
                    error_detail = json.loads(response.raw.content) if response.raw.content else {}
                    logger.debug(f"错误详情: {json.dumps(error_detail, indent=2, ensure_ascii=False)}")
                except:
                    pass
                
                return {
                    "success": False,
                    "error_msg": error_msg,
                    "error_code": error_code,
                    "log_id": log_id
                }
            
            # 处理业务结果
            data = response.data if response.data else None
            
            if not data:
                logger.error("❌ 响应中未包含数据")
                return {
                    "success": False,
                    "error_msg": "响应中未包含数据"
                }
            
            # 提取用户列表
            users = []
            if hasattr(data, 'items') and data.items:
                for item in data.items:
                    user_info = {
                        "id": getattr(item, user_id_type, None) or getattr(item, 'open_id', None),
                        "name": getattr(item, 'name', ''),
                        "open_id": getattr(item, 'open_id', None),
                        "user_id": getattr(item, 'user_id', None),
                        "union_id": getattr(item, 'union_id', None),
                        "email": getattr(item, 'email', None),
                        "mobile": getattr(item, 'mobile', None),
                        "avatar_url": getattr(item, 'avatar_url', None),
                        "department_ids": getattr(item, 'department_ids', [])
                    }
                    users.append(user_info)
            
            # 获取分页信息
            has_more = getattr(data, 'has_more', False)
            page_token = getattr(data, 'page_token', None)
            
            logger.info(f"✅ 成功获取 {len(users)} 个用户")
            if has_more:
                logger.info(f"   还有更多数据，可以使用 page_token={page_token} 获取下一页")
            
            return {
                "success": True,
                "users": users,
                "has_more": has_more,
                "page_token": page_token,
                "count": len(users),
                "message": f"✅ 成功获取 {len(users)} 个用户"
            }
            
        except Exception as e:
            logger.error(f"❌ 查找用户异常: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error_msg": f"查找用户异常: {str(e)}"
            }


class GetMeetingReserveTool(FeishuMeetingBaseTool):
    """获取会议详情工具（使用官方 SDK）"""
    
    name = "get_meeting_reserve"
    description = """获取会议详情（通过应用日历事件）。
    
支持功能：
- 通过calendar_id和event_id获取会议详情
- 获取会议主题、时间、描述、会议链接
- 获取参会人列表和参会人数量

⚠️ 重要参数说明：
- calendar_id：应用日历ID（必需）
  - 来源：创建会议时（create_meeting_reserve）返回的calendar_id字段
  - 格式：字符串，例如："feishu.cn_xxx@group.calendar.feishu.cn"
- event_id：日历事件ID（必需）
  - 来源：创建会议时（create_meeting_reserve）返回的calendar_event_id字段
  - 格式：字符串，例如："1b555d33-3686-4633-bc05-124a90c45ba1_0"

💡 如何获取calendar_id和event_id：
1. 调用create_meeting_reserve创建会议时，返回值中包含calendar_id和calendar_event_id
2. 需要保存这两个ID，用于后续的查询、更新、删除操作
3. 如果丢失了这些ID，无法直接通过会议主题或时间查询，需要从创建会议时的返回值中获取

📋 返回值说明：
- summary：会议主题
- start_time：开始时间（Unix时间戳）
- end_time：结束时间（Unix时间戳）
- start_time_display：开始时间（可读格式，如"2025-11-08 08:30:00"）
- end_time_display：结束时间（可读格式）
- meeting_url：会议链接
- attendees：参会人列表
- attendees_count：参会人数量

适用场景：
- 用户问"查看会议详情"、"这个会议什么时候开始"
- 需要查看会议的参会人、时间等信息
- 需要验证会议是否创建成功

示例输入：
- "获取会议详情，calendar_id=feishu.cn_xxx@group.calendar.feishu.cn, event_id=1b555d33-3686-4633-bc05-124a90c45ba1_0"
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "应用日历ID（必需）。从create_meeting_reserve创建会议时返回的calendar_id字段获取。格式示例：\"feishu.cn_xxx@group.calendar.feishu.cn\""
            },
            "event_id": {
                "type": "string",
                "description": "日历事件ID（必需）。从create_meeting_reserve创建会议时返回的calendar_event_id字段获取。格式示例：\"1b555d33-3686-4633-bc05-124a90c45ba1_0\""
            }
        },
        "required": ["calendar_id", "event_id"]
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行获取会议详情"""
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                return json.dumps({
                    "success": False,
                    "error": "参数格式错误，需要JSON格式"
                }, ensure_ascii=False)
        else:
            params_dict = params
        
        if not self.sdk_client:
            return json.dumps({
                "success": False,
                "error": "飞书 SDK 客户端未初始化，请检查配置和SDK安装"
            }, ensure_ascii=False)
        
        calendar_id = params_dict.get("calendar_id")
        event_id = params_dict.get("event_id")
        
        if not calendar_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 calendar_id（应用日历ID）"
            }, ensure_ascii=False)
        
        if not event_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 event_id（日历事件ID）"
            }, ensure_ascii=False)
        
        # 调用 SDK 获取日历事件
        result = self.sdk_client.get_calendar_event(
            calendar_id=calendar_id,
            event_id=event_id
        )
        
        if result.get("success"):
            event = result.get("event", {})
            return json.dumps({
                "success": True,
                "message": "✅ 成功获取会议详情",
                "event_id": result.get("event_id"),
                "summary": result.get("summary"),
                "description": result.get("description"),
                "start_time": result.get("start_time"),
                "end_time": result.get("end_time"),
                "meeting_url": result.get("meeting_url"),
                "attendees": result.get("attendees", []),
                "start_time_display": datetime.fromtimestamp(result.get("start_time")).strftime("%Y-%m-%d %H:%M:%S") if result.get("start_time") else None,
                "end_time_display": datetime.fromtimestamp(result.get("end_time")).strftime("%Y-%m-%d %H:%M:%S") if result.get("end_time") else None,
                "attendees_count": len(result.get("attendees", []))
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": result.get("error_msg", "未知错误"),
                "error_code": result.get("error_code"),
                "log_id": result.get("log_id")
            }, ensure_ascii=False)


class UpdateMeetingReserveTool(FeishuMeetingBaseTool):
    """更新会议工具（使用官方 SDK）"""
    
    name = "update_meeting_reserve"
    description = """更新会议信息（通过应用日历事件）。
    
支持功能：
- 更新会议主题（topic）
- 更新会议时间（start_time、end_time）
- 更新会议描述（description）
- 更新会议链接（meeting_url）
- **添加参会人员（participant_ids）** ⭐
- 更新时自动发送通知给所有与会人（need_notification=True）

⚠️ 重要参数说明：
- calendar_id：应用日历ID（必需）
  - 来源：创建会议时（create_meeting_reserve）返回的calendar_id字段
- event_id：日历事件ID（必需）
  - 来源：创建会议时（create_meeting_reserve）返回的calendar_event_id字段
- topic：会议主题（可选）
- start_time：会议开始时间（可选）
  - 格式：Unix时间戳（秒级），字符串或数字
  - 如果更新开始时间，建议同时更新end_time
- end_time：会议结束时间（可选）
  - 格式：Unix时间戳（秒级），字符串或数字
  - 如果更新开始时间，建议同时更新end_time
- description：会议描述（可选）
- meeting_url：会议链接（可选）
- **participant_ids：要添加的参会人员ID列表（可选）** ⭐
  - 格式：["open_id1", "open_id2", ...]
  - 使用 open_id（用户ID），可通过 find_user_by_department 获取
  - 添加参会人员时会自动发送邀请通知
- need_notification：是否发送通知，默认True

💡 使用建议：
1. 至少提供一个要更新的字段（topic/start_time/end_time/description/meeting_url/participant_ids）
2. 如果更新会议时间，建议同时更新start_time和end_time
3. 添加参会人员时，系统会自动发送邀请通知
4. 更新操作会自动发送通知给所有与会人

📋 返回值说明：
- success：是否成功
- event_id：更新后的事件ID
- attendees_added：是否成功添加参会人员
- note：操作说明

适用场景：
- 用户说"修改会议时间"、"更新会议主题"、"更改会议地点"
- 用户说"把会议改到明天下午4点"
- 用户说"会议主题改成XX"
- **用户说"添加参会人员"、"把XX加入会议"** ⭐

示例输入：
- "更新会议，calendar_id=xxx, event_id=xxx, topic=新主题"
- "修改会议时间，calendar_id=xxx, event_id=xxx, start_time=1762585200, end_time=1762588800"
- "添加参会人员，calendar_id=xxx, event_id=xxx, participant_ids=[\"open_id1\", \"open_id2\"]"
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "应用日历ID（必需）。从create_meeting_reserve创建会议时返回的calendar_id字段获取"
            },
            "event_id": {
                "type": "string",
                "description": "日历事件ID（必需）。从create_meeting_reserve创建会议时返回的calendar_event_id字段获取"
            },
            "topic": {
                "type": "string",
                "description": "会议主题（可选）。如果要更新主题，提供此参数"
            },
            "start_time": {
                "type": ["string", "integer"],
                "description": "会议开始时间（可选）。Unix时间戳（秒级），可以是字符串或数字。如果更新开始时间，建议同时更新end_time"
            },
            "end_time": {
                "type": ["string", "integer"],
                "description": "会议结束时间（可选）。Unix时间戳（秒级），可以是字符串或数字。如果更新开始时间，建议同时更新end_time"
            },
            "description": {
                "type": "string",
                "description": "会议描述（可选）"
            },
            "meeting_url": {
                "type": "string",
                "description": "会议链接（可选）"
            },
            "participant_ids": {
                "type": "array",
                "items": {
                    "type": "string"
                },
                "description": "要添加的参会人员ID列表（可选）。使用 open_id（用户ID），可通过 find_user_by_department 获取。添加参会人员时会自动发送邀请通知"
            },
            "need_notification": {
                "type": "boolean",
                "description": "是否发送通知，默认True",
                "default": True
            }
        },
        "required": ["calendar_id", "event_id"]
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行更新会议"""
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                return json.dumps({
                    "success": False,
                    "error": "参数格式错误，需要JSON格式"
                }, ensure_ascii=False)
        else:
            params_dict = params
        
        if not self.sdk_client:
            return json.dumps({
                "success": False,
                "error": "飞书 SDK 客户端未初始化，请检查配置和SDK安装"
            }, ensure_ascii=False)
        
        calendar_id = params_dict.get("calendar_id")
        event_id = params_dict.get("event_id")
        topic = params_dict.get("topic")
        start_time_str = params_dict.get("start_time")
        end_time_str = params_dict.get("end_time")
        description = params_dict.get("description")
        meeting_url = params_dict.get("meeting_url")
        participant_ids = params_dict.get("participant_ids", [])
        need_notification = params_dict.get("need_notification", True)
        
        if not calendar_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 calendar_id（应用日历ID）"
            }, ensure_ascii=False)
        
        if not event_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数 event_id（日历事件ID）"
            }, ensure_ascii=False)
        
        # 解析时间戳
        start_time = None
        end_time = None
        if start_time_str:
            try:
                start_time = int(start_time_str)
            except (ValueError, TypeError):
                return json.dumps({
                    "success": False,
                    "error": f"start_time 格式错误，需要Unix时间戳（秒级），当前值: {start_time_str}"
                }, ensure_ascii=False)
        
        if end_time_str:
            try:
                end_time = int(end_time_str)
            except (ValueError, TypeError):
                return json.dumps({
                    "success": False,
                    "error": f"end_time 格式错误，需要Unix时间戳（秒级），当前值: {end_time_str}"
                }, ensure_ascii=False)
        
        # 检查是否有要更新的字段
        if not any([topic, start_time, end_time, description is not None, meeting_url is not None, participant_ids]):
            return json.dumps({
                "success": False,
                "error": "没有要更新的字段，请至少提供一个更新参数（topic/start_time/end_time/description/meeting_url/participant_ids）"
            }, ensure_ascii=False)
        
        # 1. 更新会议基本信息（如果有）
        result = None
        if any([topic, start_time, end_time, description is not None, meeting_url is not None]):
            result = self.sdk_client.update_calendar_event(
                calendar_id=calendar_id,
                event_id=event_id,
                topic=topic,
                start_time=start_time,
                end_time=end_time,
                description=description,
                meeting_url=meeting_url,
                need_notification=need_notification
            )
            
            if not result.get("success"):
                return json.dumps({
                    "success": False,
                    "error": result.get("error_msg", "未知错误"),
                    "error_code": result.get("error_code"),
                    "log_id": result.get("log_id")
                }, ensure_ascii=False)
            
            # 同步更新待办事项（如果更新了时间或主题）
            user_id = kwargs.get("user_id")
            if user_id and (start_time or end_time or topic):
                try:
                    from ty_mem_agent.memory.todo_manager import get_todo_manager
                    from datetime import datetime
                    
                    todo_manager = get_todo_manager()
                    todo = todo_manager.get_todo_by_event_id(user_id, event_id)
                    
                    if todo:
                        updates = {}
                        
                        # 如果更新了时间，同步更新待办的 deadline
                        if start_time:
                            deadline_str = datetime.fromtimestamp(start_time).isoformat()
                            updates['deadline'] = deadline_str
                            logger.info(f"📅 同步更新待办时间: {deadline_str}")
                        
                        # 如果更新了主题，同步更新待办的 title
                        if topic:
                            updates['title'] = topic
                            logger.info(f"📝 同步更新待办标题: {topic}")
                        
                        # 如果更新了会议链接，同步更新待办的 description
                        if meeting_url:
                            # 更新描述中的会议链接
                            description_parts = []
                            if todo.description:
                                # 保留原有的参会人信息
                                for line in todo.description.split('\n'):
                                    if not line.startswith('会议链接:'):
                                        description_parts.append(line)
                            description_parts.insert(0, f"会议链接: {meeting_url}")
                            updates['description'] = '\n'.join(description_parts)
                            logger.info(f"🔗 同步更新待办会议链接")
                        
                        if updates:
                            success = todo_manager.update_todo(todo.id, user_id, updates)
                            if success:
                                logger.info(f"✅ 待办事项同步更新成功: todo_id={todo.id}")
                            else:
                                logger.warning(f"⚠️ 待办事项同步更新失败: todo_id={todo.id}")
                    else:
                        logger.debug(f"📋 未找到关联的待办事项: event_id={event_id}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ 同步更新待办事项失败: {e}")
                    # 不影响会议更新结果，只记录警告
        
        # 2. 添加参会人员（如果有）
        attendees_added = False
        if participant_ids:
            # 构建参会人列表
            attendees = []
            for pid in participant_ids:
                attendees.append({
                    "id": pid,
                    "type": "user",
                    "is_optional": False
                })
            
            # 调用 SDK 添加参会人员
            attendees_result = self.sdk_client.add_calendar_event_attendees(
                calendar_id=calendar_id,
                event_id=event_id,
                attendees=attendees,
                user_id_type="open_id",
                need_notification=True  # 发送邀请通知
            )
            
            if attendees_result.get("success"):
                attendees_added = True
                logger.info(f"✅ 成功添加 {len(participant_ids)} 个参会人员并发送邀请通知")
            else:
                logger.warning(f"⚠️ 添加参会人员失败: {attendees_result.get('error_msg')}")
                # 如果只是添加参会人员失败，但基本信息更新成功，仍然返回部分成功
                if result and result.get("success"):
                    return json.dumps({
                        "success": True,
                        "message": "✅ 会议基本信息更新成功，但添加参会人员失败",
                        "event_id": result.get("event_id"),
                        "attendees_added": False,
                        "attendees_error": attendees_result.get("error_msg"),
                        "note": "会议信息已更新，但添加参会人员时出错"
                    }, ensure_ascii=False, indent=2)
                else:
                    return json.dumps({
                        "success": False,
                        "error": f"添加参会人员失败: {attendees_result.get('error_msg')}",
                        "error_code": attendees_result.get("error_code"),
                        "log_id": attendees_result.get("log_id")
                    }, ensure_ascii=False)
        
        # 返回结果
        if result and result.get("success"):
            message = "✅ 会议更新成功"
            if attendees_added:
                message += f"，已添加 {len(participant_ids)} 个参会人员并发送邀请通知"
            else:
                message += "，与会人已收到通知"
            
            return json.dumps({
                "success": True,
                "message": message,
                "event_id": result.get("event_id") if result else event_id,
                "attendees_added": attendees_added,
                "attendees_count": len(participant_ids) if attendees_added else 0,
                "note": "会议信息已更新" + (f"，已添加 {len(participant_ids)} 个参会人员" if attendees_added else "")
            }, ensure_ascii=False, indent=2)
        elif attendees_added:
            # 只添加了参会人员，没有更新其他信息
            return json.dumps({
                "success": True,
                "message": f"✅ 成功添加 {len(participant_ids)} 个参会人员并发送邀请通知",
                "event_id": event_id,
                "attendees_added": True,
                "attendees_count": len(participant_ids),
                "note": f"已添加 {len(participant_ids)} 个参会人员，他们已收到邀请通知"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": "更新失败",
                "error_code": result.get("error_code") if result else None,
                "log_id": result.get("log_id") if result else None
            }, ensure_ascii=False)


class DeleteMeetingReserveTool(FeishuMeetingBaseTool):
    """删除会议工具（使用官方 SDK）"""
    
    name = "delete_meeting_reserve"
    description = """完整删除飞书会议（会议预约+日历事件+待办）

💡 **标准删除流程（必须遵循）**：
1. 先使用 list_meeting_reserve 查询会议，获取 todo_id
2. 再使用本工具删除会议，传入 todo_id 参数
3. 系统会自动完整删除：会议预约 + 日历事件 + 待办

⚠️ **关键提示**：
- **必须传入 todo_id 参数**，否则待办事项不会被删除
- 从 list_meeting_reserve 的返回结果中获取 todo_id
- todo_id 在返回结果的每个会议对象中都有

本工具会完整删除会议的所有相关信息：
1. 会议预约（reserve_id）- 删除飞书会议预约
2. 日历事件（event_id + calendar_id）- 从飞书日历中移除并通知参会人
3. 待办事项（todo_id）- 删除关联的待办任务

💡 正确使用方式：
**标准方式（必须使用）：**
```json
{"todo_id": "123"}
```
- todo_id：从 list_meeting_reserve 返回结果中的 todo_id 字段获取
- 系统会自动从待办中提取 reserve_id、event_id、calendar_id
- 完整删除会议预约、日历事件和待办

**备用方式（不推荐，不会删除待办）：**
```json
{"reserve_id": "xxx", "event_id": "xxx", "calendar_id": "xxx"}
```
- 仅在特殊情况下使用
- ⚠️ 此方式不会删除待办事项

参数说明：
- **todo_id**：会议待办ID（必须使用）
  - 从 list_meeting_reserve 的 meetings[].todo_id 获取
  - 使用此参数会完整删除所有相关信息
- reserve_id：会议预约ID（仅在不使用todo_id时需要）
- event_id：日历事件ID（可选）
- calendar_id：日历ID（可选）
- need_notification：是否通知参会人（默认True）

适用场景及标准流程：
- "取消明天上午的会议" → 1. 查询会议获取todo_id → 2. 传入todo_id删除
- "删除关于产品讨论的会议" → 1. 查询会议获取todo_id → 2. 传入todo_id删除
- "把XX会议取消了" → 1. 查询会议获取todo_id → 2. 传入todo_id删除
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "todo_id": {
                "type": "string",
                "description": "会议待办ID（必须使用）。从 list_meeting_reserve 返回结果的 meetings[].todo_id 字段获取。使用此参数会完整删除会议预约、日历事件和待办"
            },
            "reserve_id": {
                "type": "string",
                "description": "会议预约ID。如果不提供 todo_id，则必需提供此参数"
            },
            "event_id": {
                "type": "string",
                "description": "日历事件ID（可选）。用于删除飞书日历事件"
            },
            "calendar_id": {
                "type": "string",
                "description": "日历ID（可选）。如果提供 event_id 则需要此参数"
            },
            "need_notification": {
                "type": "boolean",
                "description": "是否发送通知（默认True）。删除日历事件时是否通知参会人",
                "default": True
            }
        },
        "required": []  # todo_id 和 reserve_id 二选一，但不强制要求
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行完整删除会议（会议预约+日历事件+待办）"""
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                return json.dumps({
                    "success": False,
                    "error": "参数格式错误，需要JSON格式"
                }, ensure_ascii=False)
        else:
            params_dict = params
        
        if not self.sdk_client:
            return json.dumps({
                "success": False,
                "error": "飞书 SDK 客户端未初始化，请检查配置和SDK安装"
            }, ensure_ascii=False)
        
        # 获取参数
        todo_id = params_dict.get("todo_id")
        reserve_id = params_dict.get("reserve_id")
        event_id = params_dict.get("event_id")
        calendar_id = params_dict.get("calendar_id")
        need_notification = params_dict.get("need_notification", True)
        user_id = kwargs.get("user_id")
        
        # 如果提供了 todo_id，从待办中获取会议信息
        if todo_id:
            try:
                from ty_mem_agent.memory.todo_manager import get_todo_manager
                todo_manager = get_todo_manager()
                
                if not user_id:
                    return json.dumps({
                        "success": False,
                        "error": "使用 todo_id 删除会议时需要提供 user_id"
                    }, ensure_ascii=False)
                
                # 获取待办信息
                todo = todo_manager.get_todo(int(todo_id), user_id)
                if not todo:
                    return json.dumps({
                        "success": False,
                        "error": f"未找到待办 ID: {todo_id}"
                    }, ensure_ascii=False)
                
                # 从待办中提取会议信息
                reserve_id = getattr(todo, 'reserve_id', None) or reserve_id
                event_id = getattr(todo, 'event_id', None) or event_id
                calendar_id = getattr(todo, 'calendar_id', None) or calendar_id
                
                logger.info(f"📋 从待办中获取会议信息: reserve_id={reserve_id}, event_id={event_id}, calendar_id={calendar_id}")
                
            except Exception as e:
                logger.error(f"❌ 从待办获取会议信息失败: {e}")
                return json.dumps({
                    "success": False,
                    "error": f"从待办获取会议信息失败: {str(e)}"
                }, ensure_ascii=False)
        
        # 验证必需参数
        if not reserve_id and not event_id:
            return json.dumps({
                "success": False,
                "error": "缺少必需参数：请提供 todo_id 或 reserve_id/event_id"
            }, ensure_ascii=False)
        
        # 执行删除操作
        deleted_items = []
        errors = []
        
        # 1. 删除会议预约
        if reserve_id:
            logger.info(f"🗑️ 开始删除会议预约: {reserve_id}")
            reserve_result = self.sdk_client.delete_meeting_reserve(reserve_id)
            if reserve_result.get("success"):
                deleted_items.append("会议预约")
                logger.info(f"✅ 会议预约删除成功")
            else:
                errors.append(f"会议预约删除失败: {reserve_result.get('error_msg')}")
                logger.warning(f"⚠️ 会议预约删除失败: {reserve_result.get('error_msg')}")
        
        # 2. 删除日历事件
        if event_id and calendar_id:
            logger.info(f"🗑️ 开始删除日历事件: {event_id}")
            calendar_result = self.sdk_client.delete_calendar_event(
                calendar_id=calendar_id,
                event_id=event_id,
                need_notification=need_notification
            )
            if calendar_result.get("success"):
                deleted_items.append("日历事件")
                logger.info(f"✅ 日历事件删除成功")
            else:
                errors.append(f"日历事件删除失败: {calendar_result.get('error_msg')}")
                logger.warning(f"⚠️ 日历事件删除失败: {calendar_result.get('error_msg')}")
        
        # 3. 删除待办事项
        if todo_id and user_id:
            try:
                from ty_mem_agent.memory.todo_manager import get_todo_manager
                todo_manager = get_todo_manager()
                logger.info(f"🗑️ 开始删除待办事项: {todo_id}")
                todo_manager.delete_todo(int(todo_id), user_id)
                deleted_items.append("待办事项")
                logger.info(f"✅ 待办事项删除成功")
            except Exception as e:
                errors.append(f"待办事项删除失败: {str(e)}")
                logger.warning(f"⚠️ 待办事项删除失败: {str(e)}")
        
        # 返回结果
        if deleted_items:
            message_parts = [f"✅ 会议已删除"]
            message_parts.append(f"已删除: {', '.join(deleted_items)}")
            if errors:
                message_parts.append(f"部分失败: {'; '.join(errors)}")
            
            return json.dumps({
                "success": True,
                "message": "\n".join(message_parts),
                "deleted_items": deleted_items,
                "errors": errors if errors else None,
                "note": "会议删除完成，所有与会人已收到取消通知" if need_notification else "会议删除完成"
            }, ensure_ascii=False, indent=2)
        else:
            return json.dumps({
                "success": False,
                "error": "删除失败",
                "errors": errors
            }, ensure_ascii=False)


class ListMeetingReserveTool(FeishuMeetingBaseTool):
    """查询会议列表工具（通过待办事项）"""
    
    name = "list_meeting_reserve"
    description = """查询飞书会议列表（通过待办事项）

💡 查询方式：
本工具通过查询待办事项来获取会议列表。创建会议时会自动创建待办，待办中保存了完整的会议信息（reserve_id、event_id、calendar_id等）。

⚠️ 技术说明：
由于飞书API的限制，使用应用权限（tenant_access_token）无法直接查询用户个人日历中的会议，因此采用待办事项作为会议管理的中介。

支持的查询条件：
- start_time：查询开始时间（Unix时间戳，秒级）
  - 用于筛选该时间之后的会议
- end_time：查询结束时间（Unix时间戳，秒级）
  - 与start_time配合，筛选时间范围内的会议
- topic_keyword：会议主题关键词
  - 在待办标题中搜索包含该关键词的会议

返回值：
- meetings：会议列表，每个会议包含：
  - title：会议主题
  - deadline：会议时间
  - description：会议描述（包含会议链接）
  - reserve_id：会议预约ID
  - event_id：日历事件ID  
  - calendar_id：日历ID
  - todo_id：待办ID（用于删除会议）
- count：找到的会议数量

使用建议：
1. 推荐先使用 natural_time_parser 解析时间
2. 返回的会议包含完整ID信息，可直接用于删除
3. 会议信息来源于待办，与飞书日历完全同步

示例场景：
- "明天有什么会议？" → 使用start_time和end_time查询明天的会议
- "下周的产品讨论会" → 使用topic_keyword="产品讨论"筛选
- "本周所有会议" → 使用本周的start_time和end_time

⚠️ 重要参数说明：
- calendar_id：应用日历ID（可选）
  - 如果不提供，会自动获取或创建应用日历
  - 格式：字符串，例如："feishu.cn_xxx@group.calendar.feishu.cn"
- start_time：查询开始时间（可选）
  - 格式：Unix时间戳（秒级），可以是字符串或数字
  - 示例：1762561800 或 "1762561800"
  - 推荐：使用 natural_time_parser 工具解析时间，使用返回结果中的 timestamp 字段
- end_time：查询结束时间（可选）
  - 格式：Unix时间戳（秒级），可以是字符串或数字
  - 如果只提供 start_time，默认查询 start_time 之后24小时内的会议
- topic_keyword：主题关键词（可选）
  - 用于在返回结果中筛选包含该关键词的会议
  - 注意：这是客户端筛选，不是API筛选
- owner_id：会议所有者用户ID（可选）
  - 用于在返回结果中筛选该用户创建的会议
  - 格式：open_id 或 user_id
  - 注意：这是客户端筛选，需要检查事件的参会人列表

📋 返回值说明：
- events：匹配的会议列表，每个会议包含：
  - event_id：事件ID（用于后续的更新、删除操作）
  - calendar_id：日历ID（用于后续的更新、删除操作）
  - summary：会议主题
  - start_time：开始时间（Unix时间戳）
  - end_time：结束时间（Unix时间戳）
  - start_time_display：开始时间（可读格式）
  - end_time_display：结束时间（可读格式）
  - meeting_url：会议链接
  - attendees：参会人列表
  - attendees_count：参会人数量
- count：匹配的会议数量

💡 使用流程建议：
1. 如果用户说"取消后天上午的会议"或"删除后天上午的会议"，应该：
   - 第一步：使用 natural_time_parser 解析"后天上午"的时间，获取 timestamp 字段（例如：1762909200）
   - 第二步：使用 find_user_by_department 查找用户的 open_id（因为需要筛选"我的会议"）
   - 第三步：调用此工具查询会议，参数：
     * start_time：从 natural_time_parser 获取的 timestamp（字符串格式，例如："1762909200"）
     * end_time：start_time + 4小时（例如："1762923600"，覆盖整个上午）
     * owner_id：从 find_user_by_department 获取的 open_id（用于筛选用户的会议）
   - 第四步：根据返回的 events 列表，找到匹配的会议（检查 start_time_display 是否在"上午"时间段）
   - 第五步：使用返回的 calendar_id 和 event_id 调用 delete_meeting_reserve 删除会议
2. 如果用户说"查看明天的会议"，可以：
   - 使用 natural_time_parser 解析"明天"的时间范围，获取 timestamp
   - 调用此工具查询该时间范围内的所有会议（可以传入 owner_id 筛选用户的会议）
   - 返回会议列表给用户

⚠️ 重要提示：
- 如果用户说"我的会议"、"我创建的会议"或"我的会议预约"，必须使用 find_user_by_department 查找用户的 open_id，然后传入 owner_id 参数
- 时间范围建议：
  * 如果用户说"后天上午"，设置 start_time 为后天上午的开始时间（例如 9:00），end_time 为后天中午的时间（例如 13:00，即 +4小时）
  * 如果用户说"明天"，设置 start_time 为明天的 00:00，end_time 为明天的 23:59:59
- 此工具返回的 events 列表中，每个事件都包含 calendar_id 和 event_id，可以直接用于 delete_meeting_reserve 或 update_meeting_reserve

适用场景：
- 用户说"取消明天的会议"、"删除后天上午的会议"
- 用户说"查看我的会议"、"列出明天的会议"
- 用户说"修改明天下午的会议时间"

示例输入：
- "查询会议列表，start_time=1762561800, end_time=1762648200"
- "查询明天的会议，start_time=1762561800, end_time=1762648200"
- "查询会议列表，topic_keyword=硬件需求"
"""
    
    parameters = {
        "type": "object",
        "properties": {
            "calendar_id": {
                "type": "string",
                "description": "应用日历ID（可选）。如果不提供，会自动获取或创建应用日历"
            },
            "start_time": {
                "type": "string",
                "description": "查询开始时间（可选）。Unix时间戳（秒级），字符串格式。推荐使用 natural_time_parser 的 timestamp 字段转换为字符串"
            },
            "end_time": {
                "type": "string",
                "description": "查询结束时间（可选）。Unix时间戳（秒级），字符串格式。如果只提供 start_time，默认查询 start_time 之后24小时内的会议"
            },
            "topic_keyword": {
                "type": "string",
                "description": "主题关键词（可选）。用于筛选包含该关键词的会议"
            },
            "owner_id": {
                "type": "string",
                "description": "会议所有者用户ID（可选）。用于筛选该用户创建的会议（open_id 或 user_id）"
            }
        },
        "required": []
    }
    
    def call(self, params: Union[str, Dict], **kwargs) -> str:
        """执行查询会议列表"""
        logger.info("🔍 开始查询会议列表...")
        
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except json.JSONDecodeError:
                logger.error("❌ 参数格式错误，需要JSON格式")
                return json.dumps({
                    "success": False,
                    "error": "参数格式错误，需要JSON格式"
                }, ensure_ascii=False)
        else:
            params_dict = params
        
        logger.debug(f"📥 接收到的参数: {params_dict}")
        
        if not self.sdk_client:
            logger.error("❌ 飞书 SDK 客户端未初始化")
            return json.dumps({
                "success": False,
                "error": "飞书 SDK 客户端未初始化，请检查配置和SDK安装"
            }, ensure_ascii=False)
        
        calendar_id = params_dict.get("calendar_id")
        start_time_str = params_dict.get("start_time")
        end_time_str = params_dict.get("end_time")
        topic_keyword = params_dict.get("topic_keyword")
        owner_id = params_dict.get("owner_id")
        
        # 如果没有提供 owner_id，尝试从 kwargs 获取 user_id（用于查找用户的 open_id）
        # 注意：这里只是记录，实际筛选时需要使用 open_id
        user_id = kwargs.get("user_id")
        if user_id and not owner_id:
            logger.debug(f"📝 检测到 user_id={user_id}，但需要 open_id 才能筛选，建议先使用 find_user_by_department 查找 open_id")
        
        # ⚠️  改进方案：通过待办事项查询会议
        # 由于飞书API限制，无法直接查询用户个人日历，因此从待办中获取会议信息
        
        logger.info("💡 通过待办事项查询会议列表")
        
        if not user_id:
            logger.warning("⚠️  未提供 user_id，无法查询待办中的会议")
            return json.dumps({
                "success": False,
                "error": "需要 user_id 才能查询会议列表"
            }, ensure_ascii=False)
        
        try:
            from ty_mem_agent.memory.todo_manager import get_todo_manager
            from datetime import datetime
            
            todo_manager = get_todo_manager()
            
            # 获取所有待办（不限时间范围）
            all_todos = todo_manager.get_todos_by_range(
                user_id=user_id,
                start_date=None,
                end_date=None,
                status=None  # 不筛选状态，获取所有未删除的待办
            )
            
            # 筛选会议待办（包含 reserve_id 的待办）
            meeting_todos = [
                todo for todo in all_todos
                if hasattr(todo, 'reserve_id') and getattr(todo, 'reserve_id', None)
            ]
            
            logger.info(f"📋 找到 {len(meeting_todos)} 个会议待办")
            
            # 解析时间参数
            start_time = None
            end_time = None
            
            if start_time_str:
                try:
                    start_time = int(start_time_str) if isinstance(start_time_str, str) else start_time_str
                except (ValueError, TypeError):
                    logger.warning(f"⚠️  start_time 格式错误: {start_time_str}")
            
            if end_time_str:
                try:
                    end_time = int(end_time_str) if isinstance(end_time_str, str) else end_time_str
                except (ValueError, TypeError):
                    logger.warning(f"⚠️  end_time 格式错误: {end_time_str}")
            
            # 应用筛选条件
            filtered_meetings = []
            
            for todo in meeting_todos:
                # 解析deadline
                deadline_str = getattr(todo, 'deadline', None)
                if not deadline_str:
                    continue
                
                try:
                    if isinstance(deadline_str, str):
                        deadline_dt = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                    else:
                        deadline_dt = deadline_str
                    
                    deadline_timestamp = int(deadline_dt.timestamp())
                    
                    # 时间范围筛选
                    if start_time and deadline_timestamp < start_time:
                        continue
                    if end_time and deadline_timestamp > end_time:
                        continue
                    
                    # 主题关键词筛选
                    if topic_keyword:
                        title = getattr(todo, 'title', '')
                        if topic_keyword not in title:
                            continue
                    
                    # 构建会议信息
                    meeting_info = {
                        "todo_id": getattr(todo, 'id', None),
                        "title": getattr(todo, 'title', ''),
                        "deadline": deadline_str,
                        "deadline_timestamp": deadline_timestamp,
                        "deadline_display": deadline_dt.strftime('%Y-%m-%d %H:%M:%S'),
                        "description": getattr(todo, 'description', ''),
                        "reserve_id": getattr(todo, 'reserve_id', None),
                        "event_id": getattr(todo, 'event_id', None),
                        "calendar_id": getattr(todo, 'calendar_id', None),
                        "status": getattr(todo, 'status', 'pending')
                    }
                    
                    filtered_meetings.append(meeting_info)
                    
                except Exception as e:
                    logger.warning(f"⚠️  解析待办时间失败: {e}")
                    continue
            
            # 按时间排序
            filtered_meetings.sort(key=lambda x: x['deadline_timestamp'])
            
            logger.info(f"✅ 查询完成，找到 {len(filtered_meetings)} 个匹配的会议")
            
            return json.dumps({
                "success": True,
                "meetings": filtered_meetings,
                "count": len(filtered_meetings),
                "note": f"从待办事项中找到 {len(filtered_meetings)} 个会议"
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 查询会议失败: {e}")
            import traceback
            traceback.print_exc()
            return json.dumps({
                "success": False,
                "error": f"查询会议失败: {str(e)}"
            }, ensure_ascii=False)
        
        # 解析时间参数
        start_time = None
        end_time = None
        
        if start_time_str:
            try:
                # 支持字符串和数字格式
                start_time = int(start_time_str) if isinstance(start_time_str, str) else start_time_str
            except (ValueError, TypeError):
                return json.dumps({
                    "success": False,
                    "error": f"start_time 格式错误: {start_time_str}"
                }, ensure_ascii=False)
        
        if end_time_str:
            try:
                # 支持字符串和数字格式
                end_time = int(end_time_str) if isinstance(end_time_str, str) else end_time_str
            except (ValueError, TypeError):
                return json.dumps({
                    "success": False,
                    "error": f"end_time 格式错误: {end_time_str}"
                }, ensure_ascii=False)
        
        # 如果只提供了 start_time，默认查询之后24小时
        if start_time and not end_time:
            end_time = start_time + 24 * 3600
        
        # 调用 SDK 查询日历事件列表
        logger.info(f"📅 查询日历事件: calendar_id={calendar_id}, start_time={start_time}, end_time={end_time}")
        result = self.sdk_client.list_calendar_events(
            calendar_id=calendar_id,
            start_time=start_time,
            end_time=end_time
        )
        
        if not result.get("success"):
            error_msg = result.get("error_msg", "未知错误")
            logger.error(f"❌ 查询日历事件列表失败: {error_msg}")
            return json.dumps(result, ensure_ascii=False, indent=2)
        
        logger.info(f"✅ SDK 查询成功，找到 {result.get('count', 0)} 个事件")
        
        # 客户端筛选
        events = result.get("events", [])
        filtered_events = []
        
        for event in events:
            # 根据主题关键词筛选
            if topic_keyword:
                summary = event.get("summary", "")
                if topic_keyword not in summary:
                    continue
            
            # 根据 owner_id 筛选（检查参会人列表中是否包含 owner_id）
            # 注意：如果未提供 owner_id，则不过滤，返回所有事件
            if owner_id:
                attendees = event.get("attendees", [])
                found_owner = False
                for attendee in attendees:
                    attendee_open_id = attendee.get("open_id")
                    attendee_user_id = attendee.get("user_id")
                    # 检查是否匹配 owner_id（支持 open_id 或 user_id）
                    if attendee_open_id == owner_id or attendee_user_id == owner_id:
                        found_owner = True
                        break
                if not found_owner:
                    continue
            
            # 添加 calendar_id 到每个事件（用于后续操作）
            event["calendar_id"] = calendar_id
            filtered_events.append(event)
        
        result["events"] = filtered_events
        result["count"] = len(filtered_events)
        result["filtered"] = len(events) != len(filtered_events)
        
        if topic_keyword or owner_id:
            result["note"] = f"已根据条件筛选，从 {len(events)} 个事件中筛选出 {len(filtered_events)} 个匹配的会议"
        
        logger.info(f"✅ 查询完成，最终返回 {len(filtered_events)} 个匹配的会议")
        if len(filtered_events) > 0:
            for i, event in enumerate(filtered_events[:3]):  # 只记录前3个
                logger.debug(f"  会议 {i+1}: {event.get('summary')} ({event.get('start_time_display')})")
        
        return json.dumps(result, ensure_ascii=False, indent=2)


def get_feishu_meeting_sdk_tools() -> List[BaseTool]:
    """获取飞书会议 SDK 工具列表"""
    if not HAS_LARK_SDK:
        logger.warning("⚠️ 未安装飞书官方 SDK，无法提供会议工具")
        return []
    
    return [
        CreateMeetingReserveTool(),
        ListMeetingReserveTool(),
        GetMeetingReserveTool(),
        UpdateMeetingReserveTool(),
        DeleteMeetingReserveTool(),
        FindUserByDepartmentTool()
    ]

