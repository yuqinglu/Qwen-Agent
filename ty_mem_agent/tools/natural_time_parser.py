"""
自然语言时间解析工具 - 优化版本
使用开源库 + LLM 混合方案，简化代码并提升效果

支持方案：
1. JioNLP（中文时间解析）
2. dateparser（英文时间解析）  
3. LLM（复杂情况fallback）
"""

import re
import json
import datetime
from typing import Optional, Dict, Any
from qwen_agent.tools.base import BaseTool
from qwen_agent.llm.schema import Message, USER, ASSISTANT
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("NaturalTimeParser")

# 时间段映射（与V1保持一致）
PERIOD_MAP = {
    "凌晨": 3, "早上": 8, "上午": 9, "中午": 12,
    "下午": 15, "傍晚": 18, "晚上": 20, "夜里": 23,
    "at night": 21, "in the morning": 8, "at noon": 12, "in the afternoon": 15,
    "evening": 18, "morning": 8, "afternoon": 15, "night": 20
}

# 中文数字映射（用于提取具体时间点）
CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24
}

def chinese_to_number(text: str) -> int:
    """将中文数字转换为阿拉伯数字"""
    if text.isdigit():
        return int(text)
    
    if text in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[text]
    
    if "十" in text:
        if text == "十":
            return 10
        elif text.startswith("十"):
            return 10 + CHINESE_NUMBERS.get(text[1], 0)
        elif text.endswith("十"):
            return CHINESE_NUMBERS.get(text[0], 0) * 10
        else:
            parts = text.split("十")
            if len(parts) == 2:
                tens = CHINESE_NUMBERS.get(parts[0], 0) if parts[0] else 1
                ones = CHINESE_NUMBERS.get(parts[1], 0) if parts[1] else 0
                return tens * 10 + ones
    
    try:
        return int(text)
    except:
        return 0


def extract_time_info_from_text(text: str, language: str = "auto") -> Dict[str, Any]:
    """
    从文本中提取时间段和具体时间点信息
    
    Returns:
        {
            "hour_guess": int or None,  # 提取的小时（0-23）
            "minute_guess": int or None,  # 提取的分钟（0-59）
            "period_hour": int or None,  # 时间段对应的小时
        }
    """
    if language == "auto":
        language = "zh" if re.search(r'[\u4e00-\u9fa5]', text) else "en"
    
    hour_guess = None
    minute_guess = None
    period_hour = None
    
    # 处理中文时间表达中的具体时间（如"七点二十八"、"下午2点"）
    if language == "zh":
        # 匹配"X点Y分"格式（如"下午2点"、"早上8点"、"七点二十八"、"八点"）
        # 注意：要匹配"八点"、"九点"等，避免匹配"下周二"中的"二"
        # 策略：使用更精确的匹配，确保匹配到正确的时间点
        # 对于"下周二八点"，应该匹配"八点"而不是"二八点"
        # 方法：从右到左查找所有"点"，然后向前匹配单个数字或中文数字（非贪婪）
        
        # 首先尝试匹配单独的数字+点（避免匹配到复合数字）
        # 使用负向前瞻：确保"点"前面的数字不是"周"或"星期"的一部分
        # 模式1：匹配"点"前的单独数字（1-23的合法小时）
        # 优先匹配：数字+点+可选分钟，且数字前面不是"周"或"星期"后的单独数字
        time_patterns = [
            # 匹配"八点"、"九点"、"9点"等（8-23），肯定不会和星期冲突
            # 包括中文数字（八九十）和阿拉伯数字（单个数字8-9，两位数字10-23）
            r"([八九十]|([8-9])|([1-2][0-3])|(2[0-4])|(1[4-9]))点([一二两三四五六七八九十零\d]+分?)?",
            # 匹配"一点"到"七点"（包括"两点"、"2点"），但要排除"周X点"的情况
            # 改进：更精确的负向前瞻，只排除紧邻"周"或"星期"后的数字
            r"(?<!周[一二三四五六七八九十\d])(?<!星期[一二三四五六七八九十\d])([一二两三四五六七]|[1-7])点([一二两三四五六七八九十零\d]+分?)?",
        ]
        
        hour_guess = None
        minute_guess = None
        
        for pattern in time_patterns:
            time_match_zh = re.search(pattern, text)
            if time_match_zh:
                # 对于第一个模式，可能有多个捕获组，需要找到第一个非None的组
                hour_str = None
                if pattern.startswith(r"([八九十]|"):
                    # 第一个模式：找到第一个非None的组作为小时部分
                    groups = time_match_zh.groups()
                    for g in groups:
                        if g:
                            hour_str = g
                            break
                    # 分钟部分是最后一个组（如果有的话）
                    minute_str = groups[-1] if len(groups) > 0 and groups[-1] and groups[-1] != hour_str else None
                    # 如果最后一个组是小时部分，说明没有分钟部分
                    if minute_str == hour_str:
                        minute_str = None
                else:
                    # 第二个模式：正常的组结构
                    hour_str = time_match_zh.group(1)
                    minute_str = time_match_zh.group(2) if len(time_match_zh.groups()) >= 2 and time_match_zh.group(2) else None
                
                hour = chinese_to_number(hour_str) if hour_str else None
                if hour is None:
                    continue
                
                # 验证：小时必须是1-23之间的合法值
                if 1 <= hour <= 23:
                    if minute_str:
                        # 移除"分"字
                        minute_str = minute_str.replace("分", "")
                        minute = chinese_to_number(minute_str) if minute_str else 0
                    else:
                        # 处理"刻"、"半"等特殊表达
                        match_start = time_match_zh.start()
                        match_end = time_match_zh.end()
                        text_around = text[max(0, match_start-3):min(len(text), match_end+5)]
                        if "一刻" in text_around:
                            minute = 15
                        elif "半" in text_around or "三十分" in text_around:
                            minute = 30
                        else:
                            minute = 0
                    
                    hour_guess = hour
                    minute_guess = minute
                    break  # 找到第一个有效的时间点就停止
        
        # 处理时间段修饰（如"早上"、"下午"、"晚上"）
        # 先处理复合词（如"明晚"、"今晚"、"明早"、"今早"）
        if "明晚" in text or "今晚" in text:
            period_hour = PERIOD_MAP.get("晚上", 20)  # 晚上对应20点
        elif "明早" in text or "今早" in text:
            period_hour = PERIOD_MAP.get("早上", 8)  # 早上对应8点
        else:
            # 检查完整的时间段词
            for period, hour in PERIOD_MAP.items():
                if period in text and period in ["凌晨", "早上", "上午", "中午", "下午", "傍晚", "晚上", "夜里"]:
                    period_hour = hour
                    break
        
        # 如果既有具体时间又有时间段修饰，需要结合处理
        # 修复：先提取具体时间点（如"两点"=2），然后根据时间段转换为24小时制
        # 参考V1的逻辑：下午2点 = 2 + 12 = 14:00，晚上9点 = 9 + 12 = 21:00
        if hour_guess is not None and period_hour is not None:
            # 关键修复：当有具体时间点（如"2点"）和时间段修饰（如"下午"）时，
            # 应该使用具体时间点，并根据时间段修饰确定是上午还是下午
            # 例如："下午2点" = 14:00（不是15:00），"晚上9点" = 21:00（不是20:00）
            if period_hour >= 12:  # 下午、晚上等（PM时段）
                # 对于PM时段，如果小时数 < 12，需要加12转换为24小时制
                # 例如："下午2点" → 2 + 12 = 14:00
                if hour_guess < 12:
                    hour_guess += 12  # 转换为24小时制
                # 如果已经是24小时制（>= 12），则保持不变
                # 例如："下午14点" → 14:00（已经是24小时制）
            elif period_hour < 12:  # 早上、上午、凌晨等（AM时段）
                # 对于AM时段，如果小时数 >= 12，需要减12转换为12小时制
                # 例如："早上14点" → 14 - 12 = 2:00（AM）
                if hour_guess >= 12:
                    hour_guess -= 12
                # 如果已经是12小时制（< 12），则保持不变
                # 例如："早上8点" → 8:00（已经是12小时制）
        elif hour_guess is None and period_hour is not None:
            # 只有时间段修饰，没有具体时间
            # 例如："下午" → 15:00（下午默认时间），"凌晨" → 3:00
            hour_guess = period_hour
    
    # 处理英文时间表达
    elif language == "en":
        # 匹配带秒的格式 "at 3:15:30pm"
        time_match_seconds = re.search(r"at\s+(\d{1,2}):(\d{2}):(\d{2})(am|pm)", text)
        if time_match_seconds:
            hour = int(time_match_seconds.group(1))
            minute = int(time_match_seconds.group(2))
            period = time_match_seconds.group(4)
            if 1 <= hour <= 12 and 0 <= minute <= 59:
                if period == "pm" and hour != 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
                hour_guess = hour
                minute_guess = minute
        
        # 匹配带分钟的格式 "at 3:45pm"
        elif re.search(r"at\s+(\d{1,2}):(\d{2})(am|pm)", text):
            time_match_minutes = re.search(r"at\s+(\d{1,2}):(\d{2})(am|pm)", text)
            hour = int(time_match_minutes.group(1))
            minute = int(time_match_minutes.group(2))
            period = time_match_minutes.group(3)
            if 1 <= hour <= 12 and 0 <= minute <= 59:
                if period == "pm" and hour != 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
                hour_guess = hour
                minute_guess = minute
        
        # 匹配简单格式 "at 3pm"
        elif re.search(r"at\s+(\d{1,2})(am|pm)", text):
            time_match = re.search(r"at\s+(\d{1,2})(am|pm)", text)
            hour = int(time_match.group(1))
            period = time_match.group(2)
            if 1 <= hour <= 12:
                if period == "pm" and hour != 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
                hour_guess = hour
        
        # 匹配24小时制格式 "at 15:00"
        elif re.search(r"at\s+(\d{1,2}):?(\d{0,2})", text):
            time_match_24 = re.search(r"at\s+(\d{1,2}):?(\d{0,2})", text)
            hour = int(time_match_24.group(1))
            minute = int(time_match_24.group(2)) if time_match_24.group(2) else 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                hour_guess = hour
                minute_guess = minute
        
        # 处理时间段修饰（如"morning"、"afternoon"、"evening"、"night"）
        for period, hour in PERIOD_MAP.items():
            if period in text and period in ["morning", "afternoon", "evening", "night", "at noon", "in the morning", "in the afternoon", "at night"]:
                period_hour = hour
                break
        
        # 如果只有时间段修饰，没有具体时间
        if hour_guess is None and period_hour is not None:
            hour_guess = period_hour
    
    return {
        "hour_guess": hour_guess,
        "minute_guess": minute_guess,
        "period_hour": period_hour
    }

# 尝试导入可选依赖
try:
    import jionlp as jio
    HAS_JIONLP = True
except ImportError:
    HAS_JIONLP = False
    logger.warning("⚠️ JioNLP未安装，中文时间解析功能受限。安装: pip install jionlp")

try:
    import dateparser
    HAS_DATEPARSER = True
except ImportError:
    HAS_DATEPARSER = False
    logger.warning("⚠️ dateparser未安装，英文时间解析功能受限。安装: pip install dateparser")

try:
    import parsedatetime
    HAS_PARSEDATETIME = True
except ImportError:
    HAS_PARSEDATETIME = False
    logger.warning("⚠️ parsedatetime未安装，英文时间解析功能受限。安装: pip install parsedatetime")


def parse_time_with_jionlp(text: str, reference_time: Optional[datetime.datetime] = None) -> Optional[Dict[str, Any]]:
    """使用JioNLP解析中文时间"""
    if not HAS_JIONLP:
        return None
    
    try:
        if reference_time is None:
            reference_time = datetime.datetime.now()
        
        # JioNLP的parse_time方法
        result = jio.parse_time(text, time_base=reference_time)
        
        if result and isinstance(result, dict):
            # JioNLP返回格式: {'type': 'time_point', 'definition': 'accurate', 'time': ['2025-11-04 00:00:00', '2025-11-04 23:59:59']}
            time_list = result.get('time')
            if time_list and isinstance(time_list, list) and len(time_list) > 0:
                # 使用第一个时间点（开始时间）
                time_str = time_list[0]
                if isinstance(time_str, str):
                    try:
                        # 解析时间字符串 "2025-11-04 00:00:00"
                        parsed_time = datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                        # 修复2&3: 检查是否有时间点或时间段描述
                        # 先提取时间信息（用于检查是否有明确的时间点，如"八点"）
                        time_info_jio = extract_time_info_from_text(text, "zh")
                        has_time_point = time_info_jio.get("hour_guess") is not None
                        has_time_period = bool(
                            re.search(r'(明晚|今晚|明早|今早|早上|上午|中午|下午|傍晚|晚上|夜里|凌晨|morning|afternoon|evening|night|noon)', text, re.IGNORECASE)
                        )
                        
                        if parsed_time.hour == 0 and parsed_time.minute == 0 and parsed_time.second == 0:
                            if has_time_point:
                                # 如果有明确的时间点（如"八点"），应用提取的时间
                                hour = time_info_jio.get("hour_guess")
                                minute = time_info_jio.get("minute_guess")
                                if hour is not None and isinstance(hour, int):
                                    parsed_time = parsed_time.replace(hour=hour)
                                if minute is not None and isinstance(minute, int):
                                    parsed_time = parsed_time.replace(minute=minute)
                                if hour is not None or minute is not None:
                                    parsed_time = parsed_time.replace(second=0)
                            elif has_time_period:
                                # 如果有时间段描述但没有明确时间点，保留参考时间的时分秒
                                parsed_time = parsed_time.replace(
                                    hour=reference_time.hour,
                                    minute=reference_time.minute,
                                    second=reference_time.second
                                )
                            # 如果既没有时间点也没有时间段描述，保持00:00:00（只有日期，没有时间）
                        elif has_time_point:
                            # 如果JioNLP已经解析了时间，但文本中有更明确的时间点，应用提取的时间
                            hour = time_info_jio.get("hour_guess")
                            minute = time_info_jio.get("minute_guess")
                            if hour is not None and isinstance(hour, int):
                                parsed_time = parsed_time.replace(hour=hour)
                            if minute is not None and isinstance(minute, int):
                                parsed_time = parsed_time.replace(minute=minute)
                        
                        return {
                            "parsed_datetime": parsed_time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "method": "jionlp",
                            "confidence": 0.9
                        }
                    except ValueError as e:
                        logger.debug(f"JioNLP时间解析失败: {e}")
            elif isinstance(time_list, datetime.datetime):
                # 如果直接返回datetime对象
                return {
                    "parsed_datetime": time_list.strftime("%Y-%m-%dT%H:%M:%S"),
                    "method": "jionlp",
                    "confidence": 0.9
                }
    except Exception as e:
        logger.debug(f"JioNLP解析失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
    
    return None


# 注意：preprocess_english_expressions函数已删除，因为parsedatetime和dateparser已经能够很好地处理这些表达，不需要预处理

def parse_time_with_parsedatetime(text: str, reference_time: Optional[datetime.datetime] = None) -> Optional[Dict[str, Any]]:
    """使用parsedatetime解析英文时间（更强大的英文时间解析库）"""
    if not HAS_PARSEDATETIME:
        return None
    
    try:
        if reference_time is None:
            reference_time = datetime.datetime.now()
        
        cal = parsedatetime.Calendar()
        result_dt, status = cal.parseDT(text, sourceTime=reference_time)
        
        # status: 0=失败, 1=仅日期, 2=仅时间, 3=日期+时间
        if status > 0:
            # 修复2&3: 如果只解析了日期（status=1），检查是否有时间点或时间段描述
            # 修复3: 如果没有时间点也没有时间段描述，保持00:00:00（只有日期，没有时间）
            if status == 1:  # 仅日期
                # 检查是否有明确的时间点（如"at 8am"、"8点"等）
                time_info_en = extract_time_info_from_text(text, "en")
                has_time_point = time_info_en.get("hour_guess") is not None
                has_time_period = bool(
                    re.search(r'(morning|afternoon|evening|night|noon|明晚|今晚|明早|今早|早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)', text, re.IGNORECASE)
                )
                
                if has_time_point:
                    # 如果有明确的时间点，应用提取的时间
                    hour = time_info_en.get("hour_guess")
                    minute = time_info_en.get("minute_guess")
                    if hour is not None and isinstance(hour, int):
                        result_dt = result_dt.replace(hour=hour)
                    if minute is not None and isinstance(minute, int):
                        result_dt = result_dt.replace(minute=minute)
                    if hour is not None or minute is not None:
                        result_dt = result_dt.replace(second=0)
                elif has_time_period:
                    # 如果有时间段描述但没有明确时间点，保留参考时间的时分秒
                    result_dt = result_dt.replace(
                        hour=reference_time.hour,
                        minute=reference_time.minute,
                        second=reference_time.second
                    )
                # 如果既没有时间点也没有时间段描述，保持00:00:00（只有日期，没有时间）
            
            return {
                "parsed_datetime": result_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "parsedatetime",
                "confidence": 0.85 if status >= 2 else 0.75  # 有时间信息时置信度更高
            }
    except Exception as e:
        logger.debug(f"parsedatetime解析失败: {e}")
    
    return None


def parse_time_with_dateparser(text: str, reference_time: Optional[datetime.datetime] = None, 
                               language: str = 'auto') -> Optional[Dict[str, Any]]:
    """使用dateparser解析时间（通用，支持多语言）"""
    if not HAS_DATEPARSER:
        return None
    
    try:
        if reference_time is None:
            reference_time = datetime.datetime.now()
        
        # dateparser的parse方法
        parsed_dt = dateparser.parse(text, languages=[language] if language != "auto" else None, 
                                   settings={'RELATIVE_BASE': reference_time})
        
        if parsed_dt:
            # 修复2&3: 如果解析结果的时间为00:00:00（可能只解析了日期）
            # 检查文本中是否有明确的时间指示（如"3pm"、"点"、":"等）或时间段描述（如"上午"、"下午"等）
            time_info_dp = extract_time_info_from_text(text, language)
            has_time_point = time_info_dp.get("hour_guess") is not None
            has_explicit_time = bool(
                re.search(r'(pm|am|点|:|小时)', text, re.IGNORECASE) or
                re.search(r'\d{1,2}:\d{2}', text)
            )
            has_time_period = bool(
                re.search(r'(明晚|今晚|明早|今早|早上|上午|中午|下午|傍晚|晚上|夜里|凌晨|morning|afternoon|evening|night|noon)', text, re.IGNORECASE)
            )
            
            if parsed_dt.hour == 0 and parsed_dt.minute == 0 and parsed_dt.second == 0:
                if has_time_point:
                    # 如果有明确的时间点（如"八点"、"at 8am"），应用提取的时间
                    hour = time_info_dp.get("hour_guess")
                    minute = time_info_dp.get("minute_guess")
                    if hour is not None and isinstance(hour, int):
                        parsed_dt = parsed_dt.replace(hour=hour)
                    if minute is not None and isinstance(minute, int):
                        parsed_dt = parsed_dt.replace(minute=minute)
                    if hour is not None or minute is not None:
                        parsed_dt = parsed_dt.replace(second=0)
                elif has_explicit_time:
                    # 有明确时间指示，应该使用解析出的时间（虽然可能是00:00:00，但保持原样）
                    pass
                elif has_time_period:
                    # 有时间段描述但没有明确时间点，保留参考时间的时分秒
                    parsed_dt = parsed_dt.replace(
                        hour=reference_time.hour,
                        minute=reference_time.minute,
                        second=reference_time.second
                    )
                # 如果既没有时间点，也没有明确时间指示，也没有时间段描述，保持00:00:00（只有日期，没有时间）
            
            return {
                "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "dateparser",
                "confidence": 0.8
            }
    except Exception as e:
        logger.debug(f"dateparser解析失败: {e}")
    
    return None


def parse_time_with_llm(text: str, reference_time: Optional[datetime.datetime] = None, 
                        llm=None) -> Optional[Dict[str, Any]]:
    """使用LLM解析复杂时间表达（fallback方案，同步版本）"""
    if llm is None:
        try:
            from ty_mem_agent.config.settings import get_llm_config
            from qwen_agent.llm import get_chat_model
            llm_config = get_llm_config()
            llm = get_chat_model(llm_config)
        except Exception as e:
            logger.error(f"无法初始化LLM: {e}")
            return None
    
    try:
        if reference_time is None:
            reference_time = datetime.datetime.now()
        
        ref_str = reference_time.strftime("%Y-%m-%dT%H:%M:%S")
        
        prompt = f"""请将以下自然语言时间表达解析为标准ISO格式时间（YYYY-MM-DDTHH:MM:SS）。

当前参考时间：{ref_str}

用户输入：{text}

请严格按照以下JSON格式返回，只返回JSON，不要其他内容：
{{
    "parsed_datetime": "解析后的时间，ISO格式（YYYY-MM-DDTHH:MM:SS）",
    "confidence": 0.0-1.0之间的置信度
}}

注意：
1. 如果是相对时间（如"下周二"），基于当前参考时间计算
2. 如果无法解析，confidence设为0.0
3. 只返回JSON，不要其他文字说明"""

        messages = [Message(role=USER, content=prompt)]
        
        # 调用LLM（同步）
        response_content = ""
        for chunk in llm.chat(messages=messages):
            if chunk:
                response_content = chunk[-1].content
        
        if response_content:
            # 提取JSON
            json_str = response_content.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            
            result = json.loads(json_str)
            result["method"] = "llm"
            return result
            
    except Exception as e:
        logger.warning(f"LLM解析失败: {e}")
    
    return None


def parse_chinese_english_datetime(
    text: str, 
    reference_datetime: Optional[str] = None,
    timezone: str = "Asia/Shanghai",
    language: str = "auto",
    llm=None
) -> Dict[str, Any]:
    """
    优化版时间解析 - 使用混合方案
    
    解析策略（按优先级）：
    
    中文时间表达：
    1. JioNLP（中文专用，准确率高）
    2. dateparser（作为补充）
    3. LLM（复杂情况fallback）
    
    英文时间表达：
    1. parsedatetime（英文专用，支持"next Friday"等表达，比dateparser更强大）
    2. dateparser（作为补充，支持多语言）
    3. LLM（复杂情况fallback）
    
    Args:
        text: 自然语言时间表达
        reference_datetime: 参考时间，ISO格式
        timezone: 时区
        language: 语言，auto/zh/en
        llm: LLM实例（可选）
        
    Returns:
        解析结果字典
    """
    if reference_datetime is None:
        ref_time = datetime.datetime.now()
    else:
        ref_time = datetime.datetime.fromisoformat(reference_datetime)
    
    # 识别语言
    if language == "auto":
        language = "zh" if re.search(r'[\u4e00-\u9fa5]', text) else "en"
    
    result = {
        "input_text": text,
        "language": language,
        "reference_datetime": ref_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": timezone
    }
    
    # 先提取时间段信息（无论哪种方案都要应用）
    time_info = extract_time_info_from_text(text, language)
    hour_guess = time_info.get("hour_guess")
    minute_guess = time_info.get("minute_guess")
    
    # ============= 修复1: 优先处理"月底"、"年底"等特殊表达 =============
    # 参考V1的逻辑，在调用库之前先处理这些特殊表达
    if language == "zh":
        # 处理"月底"、"年底"
        if "年底" in text:
            # 判断是"今年"、"明年"、"去年"等
            year_offset = 0
            if "明年" in text or "来年" in text:
                year_offset = 1
            elif "去年" in text or "上年" in text:
                year_offset = -1
            # 计算目标年份的最后一天（12月31日）
            target_year = ref_time.year + year_offset
            parsed_dt = datetime.datetime(target_year, 12, 31, 0, 0, 0)
            
            result.update({
                "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "month_end_year_end",
                "confidence": 0.95,
            })
            logger.info(f"🕐 [年底] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            return result
        elif "月底" in text:
            # 判断是"下个月底"、"本月底"、"这个月底"等
            from dateutil.relativedelta import relativedelta
            month_add = 0
            if "下个月" in text or "下月" in text:
                month_add = 1
            # 计算目标月份的最后一天
            base = ref_time + relativedelta(months=month_add)
            # 使用V1的算法：day=28 + 4天 = 下个月1日，然后减去天数得到本月最后一天
            next_month = base.replace(day=28) + datetime.timedelta(days=4)
            last_day = next_month - datetime.timedelta(days=next_month.day)
            parsed_dt = datetime.datetime.combine(last_day, datetime.time(0, 0, 0))
            
            result.update({
                "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "month_end_year_end",
                "confidence": 0.95,
            })
            logger.info(f"🕐 [月底] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            return result
    
    # ============= 改进1: 优先处理相对时间表达（如"十分钟后"、"两小时后"、"两小时三十分钟后"）=============
    # 参考V1的逻辑，在调用库之前先检查相对时间
    relative_time_parsed = False
    
    # 中文复合相对时间（如"两小时三十分钟后"）
    if language == "zh":
        zh_complex_relative = re.findall(r"([一二两三四五六七八九十\d]+)(小时|天|周|星期|月|年)([一二两三四五六七八九十\d]+)(分钟|小时|天|周|星期|月|年)后", text)
        if zh_complex_relative:
            num1_str, unit1, num2_str, unit2 = zh_complex_relative[0]
            num1 = chinese_to_number(num1_str)
            num2 = chinese_to_number(num2_str)
            
            from dateutil.relativedelta import relativedelta
            
            # 计算总时间（转换为分钟）
            total_minutes = 0
            for num, unit in [(num1, unit1), (num2, unit2)]:
                if "分钟" in unit:
                    total_minutes += num
                elif "小时" in unit:
                    total_minutes += num * 60
                elif "天" in unit:
                    total_minutes += num * 24 * 60
                elif "周" in unit or "星期" in unit:
                    total_minutes += num * 7 * 24 * 60
            
            # 处理月和年（需要单独处理）
            has_month_year = False
            parsed_dt = ref_time
            for num, unit in [(num1, unit1), (num2, unit2)]:
                if "月" in unit:
                    parsed_dt = parsed_dt + relativedelta(months=num)
                    has_month_year = True
                elif "年" in unit:
                    parsed_dt = parsed_dt + relativedelta(years=num)
                    has_month_year = True
            
            if has_month_year:
                # 如果有年月，直接使用parsed_dt，不再加分钟
                relative_time_parsed = True
            elif total_minutes > 0:
                parsed_dt = ref_time + datetime.timedelta(minutes=total_minutes)
                relative_time_parsed = True
            
            if relative_time_parsed:
                # 应用时间段信息（如果有）
                if hour_guess is not None and 0 <= hour_guess <= 23:
                    parsed_dt = parsed_dt.replace(hour=hour_guess, minute=0, second=0)
                    if minute_guess is not None and 0 <= minute_guess <= 59:
                        parsed_dt = parsed_dt.replace(minute=minute_guess)
                
                result.update({
                    "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "method": "relative_time",
                    "confidence": 0.95,
                })
                logger.info(f"🕐 [相对时间-复合] 解析成功: '{text}' → {result.get('parsed_datetime')}")
                return result
    
    # 中文相对时间匹配（普通格式）- 优先处理月份和年份（需要在JioNLP之前）
    # 特别是"一个月后"、"两个月后"等，需要在JioNLP之前处理以保持日期
    # 修复正则表达式：匹配"一"、"二"、"两"等中文数字，以及"个月"、"个年"
    month_year_pattern = r"([一二两三四五六七八九十\d]+)(个?月|年)后"
    if language == "zh" and not relative_time_parsed and re.search(month_year_pattern, text):
        zh_month_year = re.findall(month_year_pattern, text)
        if zh_month_year:
            num_str, unit = zh_month_year[0]
            num = chinese_to_number(num_str)
            
            from dateutil.relativedelta import relativedelta
            
            if "月" in unit:
                # 修复1: 使用relativedelta保持日期（例如：10月31日 + 1个月 = 11月30日，而不是11月1日）
                parsed_dt = ref_time + relativedelta(months=num)
                # 注意：如果目标月份没有该日期（如11月31日），relativedelta会自动调整到下个月1日
                # 这是Python标准行为，符合用户期望（尽量保持日期）
                relative_time_parsed = True
            elif "年" in unit:
                parsed_dt = ref_time + relativedelta(years=num)
                relative_time_parsed = True
            
            if relative_time_parsed:
                # 修复2: 检查是否有时间段描述，如果没有，时间设为00:00:00
                has_time_period = bool(
                    re.search(r'(早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)', text)
                )
                if not has_time_period:
                    parsed_dt = parsed_dt.replace(hour=0, minute=0, second=0)
                
                result.update({
                    "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "method": "relative_time",
                    "confidence": 0.95,
                })
                logger.info(f"🕐 [相对时间-月/年] 解析成功: '{text}' → {result.get('parsed_datetime')}")
                return result
    
    # 中文相对时间匹配（普通格式 - 其他单位：分钟、小时、天、周）
    if language == "zh" and not relative_time_parsed and re.search(r"([一二两三四五六七八九十\d]+)(分钟|小时|天|周|星期)后", text):
        zh_relative = re.findall(r"([一二两三四五六七八九十\d]+)(分钟|小时|天|周|星期)后", text)
        if zh_relative:
            num_str, unit = zh_relative[0]
            num = chinese_to_number(num_str)
            
            if "分钟" in unit:
                parsed_dt = ref_time + datetime.timedelta(minutes=num)
                relative_time_parsed = True
            elif "小时" in unit:
                parsed_dt = ref_time + datetime.timedelta(hours=num)
                relative_time_parsed = True
            elif "天" in unit:
                parsed_dt = ref_time + datetime.timedelta(days=num)
                relative_time_parsed = True
            elif "周" in unit or "星期" in unit:
                parsed_dt = ref_time + datetime.timedelta(weeks=num)
                relative_time_parsed = True
            
            if relative_time_parsed:
                # 应用时间段信息（如果有）
                if hour_guess is not None and 0 <= hour_guess <= 23:
                    parsed_dt = parsed_dt.replace(hour=hour_guess, minute=0, second=0)
                    if minute_guess is not None and 0 <= minute_guess <= 59:
                        parsed_dt = parsed_dt.replace(minute=minute_guess)
                
                result.update({
                    "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "method": "relative_time",
                    "confidence": 0.95,
                })
                logger.info(f"🕐 [相对时间] 解析成功: '{text}' → {result.get('parsed_datetime')}")
                return result
    
    # 英文相对时间匹配（"in X minutes/hours" 或 "X minutes/hours later"）
    if language == "en":
        # "in X minutes/hours/days"
        in_match = re.search(r"in\s+(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)", text.lower())
        if in_match:
            num = int(in_match.group(1))
            unit = in_match.group(2)
            
            if "minute" in unit:
                parsed_dt = ref_time + datetime.timedelta(minutes=num)
                relative_time_parsed = True
            elif "hour" in unit:
                parsed_dt = ref_time + datetime.timedelta(hours=num)
                relative_time_parsed = True
            elif "day" in unit:
                parsed_dt = ref_time + datetime.timedelta(days=num)
                relative_time_parsed = True
            elif "week" in unit:
                parsed_dt = ref_time + datetime.timedelta(weeks=num)
                relative_time_parsed = True
            elif "month" in unit:
                from dateutil.relativedelta import relativedelta
                parsed_dt = ref_time + relativedelta(months=num)
                relative_time_parsed = True
            elif "year" in unit:
                from dateutil.relativedelta import relativedelta
                parsed_dt = ref_time + relativedelta(years=num)
                relative_time_parsed = True
        
        # "X minutes/hours/days later"
        elif re.search(r"(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)\s*later", text.lower()):
            later_match = re.search(r"(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)\s*later", text.lower())
            num = int(later_match.group(1))
            unit = later_match.group(2)
            
            if "minute" in unit:
                parsed_dt = ref_time + datetime.timedelta(minutes=num)
                relative_time_parsed = True
            elif "hour" in unit:
                parsed_dt = ref_time + datetime.timedelta(hours=num)
                relative_time_parsed = True
            elif "day" in unit:
                parsed_dt = ref_time + datetime.timedelta(days=num)
                relative_time_parsed = True
            elif "week" in unit:
                parsed_dt = ref_time + datetime.timedelta(weeks=num)
                relative_time_parsed = True
            elif "month" in unit:
                from dateutil.relativedelta import relativedelta
                parsed_dt = ref_time + relativedelta(months=num)
                relative_time_parsed = True
            elif "year" in unit:
                from dateutil.relativedelta import relativedelta
                parsed_dt = ref_time + relativedelta(years=num)
                relative_time_parsed = True
        
        if relative_time_parsed:
            # 应用时间段信息（如果有）
            if hour_guess is not None and 0 <= hour_guess <= 23:
                parsed_dt = parsed_dt.replace(hour=hour_guess, minute=0, second=0)
                if minute_guess is not None and 0 <= minute_guess <= 59:
                    parsed_dt = parsed_dt.replace(minute=minute_guess)
            
            result.update({
                "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "relative_time",
                "confidence": 0.95,
            })
            logger.info(f"🕐 [相对时间] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            return result
    
    # ============= 预处理中文复合时间表达（如"两小时后晚上八点"） =============
    # 这类表达需要先解析相对时间，再应用绝对时间点
    if language == "zh":
        # 匹配"X小时后Y点"、"X天后Y点"等格式
        compound_match = re.search(r"([一二两三四五六七八九十\d]+)(小时|天|分钟)后([\u4e00-\u9fa5]+)?([一二两三四五六七八九十\d]+)?点", text)
        if compound_match:
            time_unit = compound_match.group(2)
            relative_num_str = compound_match.group(1)
            relative_num = chinese_to_number(relative_num_str)
            
            # 计算相对时间偏移后的参考时间
            if time_unit == "小时":
                adjusted_ref = ref_time + datetime.timedelta(hours=relative_num)
            elif time_unit == "天":
                adjusted_ref = ref_time + datetime.timedelta(days=relative_num)
            elif time_unit == "分钟":
                adjusted_ref = ref_time + datetime.timedelta(minutes=relative_num)
            else:
                adjusted_ref = ref_time
            
            # 从剩余文本中提取时间点信息（已经通过extract_time_info_from_text提取）
            # 使用调整后的参考时间和提取的时间点信息构建结果
            if hour_guess is not None:
                parsed_dt = adjusted_ref.replace(hour=hour_guess, minute=0, second=0)
                if minute_guess is not None:
                    parsed_dt = parsed_dt.replace(minute=minute_guess)
                result.update({
                    "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                    "method": "compound_time",
                    "confidence": 0.9,
                    "time_info_applied": True
                })
                logger.info(f"🕐 [复合时间] 解析成功: '{text}' → {result.get('parsed_datetime')}")
                return result
    
    # ============= 方案1: JioNLP（仅中文，中文优先，但跳过相对时间表达） =============
    # 注意：JioNLP专门处理中文，英文会跳过此步骤
    # 如果已经有相对时间解析结果，跳过JioNLP
    # 同时跳过"X个月后"、"X年后"等相对时间表达（由我们的逻辑处理）
    if language == "zh" and HAS_JIONLP and not relative_time_parsed:
        jio_result = parse_time_with_jionlp(text, ref_time)
        if jio_result:
            result.update(jio_result)
            # 修复2: 应用时间段信息，特别是明确指定的时间点（如"八点"）
            parsed_dt = datetime.datetime.fromisoformat(result.get('parsed_datetime'))
            
            # 重新提取时间信息（因为parse_time_with_jionlp中可能提取不正确，重新提取一次）
            # 修复2: 重新提取时间点信息，确保能正确识别"下周二八点"中的"八点"
            time_info_recheck = extract_time_info_from_text(text, "zh")
            hour_recheck = time_info_recheck.get("hour_guess")
            minute_recheck = time_info_recheck.get("minute_guess")
            
            # 优先使用重新提取的时间信息，如果没有则使用之前提取的
            final_hour = hour_recheck if hour_recheck is not None else hour_guess
            final_minute = minute_recheck if minute_recheck is not None else minute_guess
            
            if final_hour is not None and 0 <= final_hour <= 23:
                # 如果有明确的时间点（如"八点"），必须应用，不能忽略
                parsed_dt = parsed_dt.replace(hour=final_hour, minute=0, second=0)
                if final_minute is not None and 0 <= final_minute <= 59:
                    parsed_dt = parsed_dt.replace(minute=final_minute)
                result['parsed_datetime'] = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
                result['time_info_applied'] = True
                logger.info(f"🕐 [JioNLP+时间点] 解析成功: '{text}' → {result.get('parsed_datetime')} (应用了时间点)")
            else:
                # 没有明确时间点，检查是否有时间段描述来决定是否保留时间
                has_time_period = bool(
                    re.search(r'(明晚|今晚|明早|今早|早上|上午|中午|下午|傍晚|晚上|夜里|凌晨)', text)
                )
                if not has_time_period and parsed_dt.hour == 0 and parsed_dt.minute == 0:
                    # 既没有时间点也没有时间段描述，确保时间为00:00:00
                    parsed_dt = parsed_dt.replace(hour=0, minute=0, second=0)
                    result['parsed_datetime'] = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
                    logger.info(f"🕐 [JioNLP] 解析成功: '{text}' → {result.get('parsed_datetime')} (只有日期)")
                else:
                    logger.info(f"🕐 [JioNLP] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            
            return result
    
    # ============= 方案2: parsedatetime（英文专用，比dateparser更强大） =============
    # parsedatetime 专门针对英文，对"next Friday"、"tomorrow evening"等表达支持更好
    if language == "en" and HAS_PARSEDATETIME:
        pdt_result = parse_time_with_parsedatetime(text, ref_time)
        if pdt_result:
            result.update(pdt_result)
            # 修复3: 应用时间段信息和时间点，并检查是否应该只有日期
            parsed_dt = datetime.datetime.fromisoformat(result.get('parsed_datetime'))
            
            # 先检查是否有明确的时间点
            if hour_guess is not None and 0 <= hour_guess <= 23:
                # 如果有明确的时间点，应用提取的时间
                parsed_dt = parsed_dt.replace(hour=hour_guess, minute=0, second=0)
                if minute_guess is not None and 0 <= minute_guess <= 59:
                    parsed_dt = parsed_dt.replace(minute=minute_guess)
                result['parsed_datetime'] = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
                result['time_info_applied'] = True
                logger.info(f"🕐 [parsedatetime+时间点] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            else:
                # 没有明确时间点，检查是否有时间段描述
                has_time_period = bool(
                    re.search(r'(morning|afternoon|evening|night|noon)', text, re.IGNORECASE)
                )
                if not has_time_period:
                    # 修复3: 如果没有时间段描述，确保时间为00:00:00（只有日期，没有时间）
                    parsed_dt = parsed_dt.replace(hour=0, minute=0, second=0)
                    result['parsed_datetime'] = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
                    logger.info(f"🕐 [parsedatetime] 解析成功: '{text}' → {result.get('parsed_datetime')} (只有日期)")
                else:
                    logger.info(f"🕐 [parsedatetime] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            
            return result
    
    # ============= 方案3: dateparser（通用，支持中英文，作为补充） =============
    # dateparser 支持多语言，作为 parsedatetime 的补充
    if HAS_DATEPARSER:
        dp_result = parse_time_with_dateparser(text, ref_time, language)
        if dp_result:
            result.update(dp_result)
            # 应用时间段信息
            parsed_dt = datetime.datetime.fromisoformat(result.get('parsed_datetime'))
            if hour_guess is not None and 0 <= hour_guess <= 23:
                parsed_dt = parsed_dt.replace(hour=hour_guess, minute=0, second=0)
                if minute_guess is not None and 0 <= minute_guess <= 59:
                    parsed_dt = parsed_dt.replace(minute=minute_guess)
                result['parsed_datetime'] = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
                if hour_guess is not None or minute_guess is not None:
                    result['time_info_applied'] = True
            
            logger.info(f"🕐 [dateparser] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            return result
    
    # ============= 方案4: LLM（复杂情况fallback） =============
    llm_result = parse_time_with_llm(text, ref_time, llm)
    if llm_result and llm_result.get('confidence', 0) > 0.5:
        result.update(llm_result)
        # 应用时间段信息（LLM可能已经解析了时间，但如果没有，我们就应用提取的信息）
        parsed_dt = datetime.datetime.fromisoformat(result.get('parsed_datetime'))
        if hour_guess is not None and 0 <= hour_guess <= 23:
            parsed_dt = parsed_dt.replace(hour=hour_guess, minute=0, second=0)
            if minute_guess is not None and 0 <= minute_guess <= 59:
                parsed_dt = parsed_dt.replace(minute=minute_guess)
            result['parsed_datetime'] = parsed_dt.strftime("%Y-%m-%dT%H:%M:%S")
            if hour_guess is not None or minute_guess is not None:
                result['time_info_applied'] = True
        
        logger.info(f"🕐 [LLM] 解析成功: '{text}' → {result.get('parsed_datetime')}")
        return result
    
    # ============= 如果都失败，尝试应用时间段信息 =============
    # 修复：即使所有库都失败，如果文本中有时间段描述（如"凌晨"），也要应用
    if language == "zh":
        # 检查是否有相对时间描述（如"明天"、"后天"等）
        days_offset = 0
        if "明天" in text or "明日" in text:
            days_offset = 1
        elif "后天" in text:
            days_offset = 2
        elif "大后天" in text:
            days_offset = 3
        elif "今天" in text or "今日" in text:
            days_offset = 0
        elif "昨天" in text or "昨日" in text:
            days_offset = -1
        elif "前天" in text:
            days_offset = -2
        
        # 计算基础日期
        if days_offset != 0:
            base_time = ref_time + datetime.timedelta(days=days_offset)
        else:
            base_time = ref_time
        
        # 应用时间段信息
        if hour_guess is not None:
            parsed_dt = base_time.replace(hour=hour_guess, minute=0, second=0)
            if minute_guess is not None:
                parsed_dt = parsed_dt.replace(minute=minute_guess)
            result.update({
                "parsed_datetime": parsed_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": "fallback_with_time_period",
                "confidence": 0.6,
                "note": "解析库失败，但成功应用时间段信息"
            })
            logger.info(f"🕐 [Fallback+时间段] 解析成功: '{text}' → {result.get('parsed_datetime')}")
            return result
    
    # 如果连时间段信息都没有，返回参考时间
    logger.warning(f"⚠️ 无法解析时间: '{text}'，使用参考时间")
    result.update({
        "parsed_datetime": ref_time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": "fallback",
        "confidence": 0.0,
        "note": "解析失败，使用参考时间作为默认值"
    })
    
    return result


class NaturalTimeParserTool(BaseTool):
    """自然语言时间解析工具"""
    
    def __init__(self, llm=None):
        self.name = "natural_time_parser"
        self.description = (
            "解析自然语言时间表达，支持中英文复杂时间描述。"
            "使用JioNLP + dateparser + LLM混合方案，提供更准确的解析结果。"
            "例如：'下周三'、'本月最后一个周五'、'两小时后'、'next Friday at 9pm'等。"
            "返回标准ISO格式时间字符串。"
        )
        self.llm = llm
        super().__init__()
    
    def call(self, params: str, **kwargs) -> str:
        """
        解析自然语言时间表达
        
        Args:
            params: JSON字符串，包含以下字段：
                - text: 自然语言时间表达（必需）
                - reference_datetime: 参考时间，可选，默认为当前时间
                - timezone: 时区，可选，默认为Asia/Shanghai
                - language: 语言，可选，auto/zh/en，默认为auto
        """
        try:
            import asyncio
            
            params_dict = json.loads(params) if isinstance(params, str) else params
            
            text = params_dict.get('text', '')
            if not text:
                return json.dumps({
                    "error": "缺少必需参数 'text'",
                    "usage": "请提供自然语言时间表达，如：'下周三'、'两小时后'、'next Friday'"
                }, ensure_ascii=False, indent=2)
            
            reference_datetime = params_dict.get('reference_datetime')
            timezone = params_dict.get('timezone', 'Asia/Shanghai')
            language = params_dict.get('language', 'auto')
            
            # 调用解析函数（同步版本）
            result = parse_chinese_english_datetime(
                text=text,
                reference_datetime=reference_datetime,
                timezone=timezone,
                language=language,
                llm=self.llm
            )
            
            # 添加 Unix 时间戳字段（便于直接用于 create_meeting_reserve 等工具）
            if 'parsed_datetime' in result and result.get('parsed_datetime'):
                try:
                    from datetime import datetime
                    parsed_dt = datetime.fromisoformat(result['parsed_datetime'].replace('Z', '+00:00'))
                    # 转换为 Unix 时间戳（秒级）
                    result['timestamp'] = int(parsed_dt.timestamp())
                except Exception as e:
                    logger.debug(f"⚠️ 无法转换时间戳: {e}")
            
            logger.info(f"🕐 时间解析成功: '{text}' → {result.get('parsed_datetime')} (方法: {result.get('method', 'unknown')})")
            if 'timestamp' in result:
                logger.debug(f"   Unix时间戳: {result.get('timestamp')}")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_msg = f"时间解析失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            return json.dumps({
                "error": error_msg,
                "input_text": params_dict.get('text', '') if 'params_dict' in locals() else '',
                "usage": "请提供有效的时间表达，如：'下周三'、'两小时后'、'next Friday'"
            }, ensure_ascii=False, indent=2)
    
    @property
    def parameters(self) -> Dict[str, Any]:
        """工具参数定义"""
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "自然语言时间表达，支持中英文复杂描述"
                },
                "reference_datetime": {
                    "type": "string",
                    "description": "参考时间，ISO格式，可选，默认为当前时间"
                },
                "timezone": {
                    "type": "string",
                    "description": "时区，可选，默认为Asia/Shanghai"
                },
                "language": {
                    "type": "string",
                    "enum": ["auto", "zh", "en"],
                    "description": "语言设置，auto自动识别，zh中文，en英文"
                }
            },
            "required": ["text"]
        }


# =========== 测试代码 ===========
if __name__ == "__main__":
    examples = [
        "下周二",
        "下下周六早上八点半",
        "本月最后一个周五",
        "两小时后",
        "next Friday at 9pm",
        "in 3 days"
    ]
    
    print("🧪 自然语言时间解析测试（优化版）:")
    print("=" * 50)
    
    for ex in examples:
        result = parse_chinese_english_datetime(ex, '2025-10-31T10:21:48')
        print(f"输入: {ex}")
        print(f"输出: {result.get('parsed_datetime')}")
        print(f"方法: {result.get('method', 'unknown')}")
        print(f"语言: {result.get('language')}")
        print("-" * 30)

