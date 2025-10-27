"""
自然语言时间解析工具
支持中英文自然语言时间表达转换为标准时间格式
"""

import re
import datetime
from dateutil.relativedelta import relativedelta
import dateparser
from typing import Optional, Dict, Any
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("NaturalTimeParser")

# 星期映射（与Python weekday()方法匹配：周一=0, 周二=1, 周三=2, 周四=3, 周五=4, 周六=5, 周日=6）
WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

# 时间段映射
PERIOD_MAP = {
    "凌晨": 3, "早上": 8, "上午": 9, "中午": 12,
    "下午": 15, "傍晚": 18, "晚上": 20, "夜里": 23,
    "at night": 21, "in the morning": 8, "at noon": 12, "in the afternoon": 15
}

# 中文数字映射（全局定义，避免重复）
CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25, "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29,
    "三十": 30, "三十一": 31, "三十二": 32, "三十三": 33, "三十四": 34, "三十五": 35, "三十六": 36, "三十七": 37, "三十八": 38, "三十九": 39,
    "四十": 40, "四十一": 41, "四十二": 42, "四十三": 43, "四十四": 44, "四十五": 45, "四十六": 46, "四十七": 47, "四十八": 48, "四十九": 49,
    "五十": 50, "五十一": 51, "五十二": 52, "五十三": 53, "五十四": 54, "五十五": 55, "五十六": 56, "五十七": 57, "五十八": 58, "五十九": 59
}


def chinese_to_number(text: str) -> int:
    """将中文数字转换为阿拉伯数字"""
    # 如果是纯数字，直接转换
    if text.isdigit():
        return int(text)
    
    # 处理简单中文数字
    if text in CHINESE_NUMBERS:
        return CHINESE_NUMBERS[text]
    
    # 处理复合中文数字（如"二十八"、"十五"、"零五"等）
    if "十" in text:
        if text == "十":
            return 10
        elif text.startswith("十"):
            # "十五" -> 15
            return 10 + CHINESE_NUMBERS.get(text[1], 0)
        elif text.endswith("十"):
            # "二十" -> 20
            return CHINESE_NUMBERS.get(text[0], 0) * 10
        else:
            # "二十八" -> 28
            parts = text.split("十")
            if len(parts) == 2:
                tens = CHINESE_NUMBERS.get(parts[0], 0) if parts[0] else 1
                ones = CHINESE_NUMBERS.get(parts[1], 0) if parts[1] else 0
                return tens * 10 + ones
    elif "零" in text:
        # 处理"零五"、"零三"等
        if text.startswith("零"):
            if len(text) > 1:
                return CHINESE_NUMBERS.get(text[1], 0)
            else:
                return 0
        else:
            # 其他包含"零"的情况
            return CHINESE_NUMBERS.get(text.replace("零", ""), 0)
    
    # 如果都不匹配，尝试直接转换
    try:
        return int(text)
    except:
        return 0


def parse_chinese_english_datetime(text: str, reference_datetime: Optional[str] = None, 
                                 timezone: str = "Asia/Shanghai", language: str = "auto") -> Dict[str, Any]:
    """
    支持中英文自然语言日期时间解析：
    - 中文如：下下周六早上八点半、前天晚上九点一刻、下个月底、本月最后一个周五、十分钟后、两小时后
    - 英文如：next Friday at 9pm, in 3 days, 2 hours later, end of next month, last Friday of this month
    
    Args:
        text: 自然语言时间表达
        reference_datetime: 参考时间，默认为当前时间
        timezone: 时区，默认为Asia/Shanghai
        language: 语言，auto/zh/en
        
    Returns:
        包含解析结果的字典
    """
    if reference_datetime is None:
        ref = datetime.datetime.now()
    else:
        ref = datetime.datetime.fromisoformat(reference_datetime)

    t = text.strip().lower()

    # ============= STEP 1: 英文/中文语言识别 =============
    if language == "auto":
        language = "zh" if re.search(r"[\u4e00-\u9fa5]", t) else "en"

    # ============= STEP 2: 相对时间偏移解析 =============
    delta = datetime.timedelta()
    
    # 中文复合时间表达（如"两小时三十分钟后"）
    zh_complex_relative = re.findall(r"([一二两三四五六七八九十\d]+)(小时|天|周|星期|月|年)([一二两三四五六七八九十\d]+)(分钟|小时|天|周|星期|月|年)后", t)
    if zh_complex_relative:
        num1_str, unit1, num2_str, unit2 = zh_complex_relative[0]
        num1 = chinese_to_number(num1_str)
        num2 = chinese_to_number(num2_str)
        
        # 计算总时间
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
            elif "月" in unit:
                ref = ref + relativedelta(months=num)
            elif "年" in unit:
                ref = ref + relativedelta(years=num)
        
        if total_minutes > 0:
            delta = datetime.timedelta(minutes=total_minutes)
        t = re.sub(r"[一二两三四五六七八九十\d]+(小时|天|周|星期|月|年)[一二两三四五六七八九十\d]+(分钟|小时|天|周|星期|月|年)后", "", t)
    
    # 中文相对时间匹配（处理"X周后的周Y"格式）
    elif re.search(r"([一二两三四五六七八九十\d]+)(周|星期)后的?([一二三四五六日天])", t):
        zh_week_relative = re.findall(r"([一二两三四五六七八九十\d]+)(周|星期)后的?([一二三四五六日天])", t)
        num_str, unit, weekday_str = zh_week_relative[0]
        num = chinese_to_number(num_str)
        target_wd = WEEKDAY_MAP[weekday_str]
        
        # 先计算到目标星期几
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:  # 如果是今天，则选择下个星期
            days_until_target = 7
        ref = ref + datetime.timedelta(days=days_until_target)
        
        # 再添加周数偏移
        week_offset = num
        t = re.sub(r"[一二两三四五六七八九十\d]+(周|星期)后的?[一二三四五六日天]", "", t)
    
    # 中文相对时间匹配（处理"X周后周Y"格式）
    elif re.search(r"([一二两三四五六七八九十\d]+)(周|星期)后([一二三四五六日天])", t):
        zh_week_relative2 = re.findall(r"([一二两三四五六七八九十\d]+)(周|星期)后([一二三四五六日天])", t)
        num_str, unit, weekday_str = zh_week_relative2[0]
        num = chinese_to_number(num_str)
        target_wd = WEEKDAY_MAP[weekday_str]
        
        # 先计算到目标星期几
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:  # 如果是今天，则选择下个星期
            days_until_target = 7
        ref = ref + datetime.timedelta(days=days_until_target)
        
        # 再添加周数偏移
        week_offset = num
        t = re.sub(r"[一二两三四五六七八九十\d]+(周|星期)后[一二三四五六日天]", "", t)
    
    # 中文相对时间匹配（普通格式）
    elif re.search(r"([一二两三四五六七八九十\d]+)(分钟|小时|天|周|星期|月|年)后", t):
        zh_relative = re.findall(r"([一二两三四五六七八九十\d]+)(分钟|小时|天|周|星期|月|年)后", t)
        num_str, unit = zh_relative[0]
        num = chinese_to_number(num_str)
        
        if "分钟" in unit:
            delta = datetime.timedelta(minutes=num)
        elif "小时" in unit:
            delta = datetime.timedelta(hours=num)
        elif "天" in unit:
            delta = datetime.timedelta(days=num)
        elif "周" in unit or "星期" in unit:
            delta = datetime.timedelta(weeks=num)
        elif "月" in unit:
            ref = ref + relativedelta(months=num)
        elif "年" in unit:
            ref = ref + relativedelta(years=num)
        t = re.sub(r"[一二两三四五六七八九十\d]+(分钟|小时|天|周|星期|月|年)后", "", t)
    
    # 英文相对时间匹配
    elif re.search(r"(in|after)\s*(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)", t):
        en_relative = re.findall(r"(in|after)\s*(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)", t)
        _, num, unit = en_relative[0]
        num = int(num)
        
        if "minute" in unit:
            delta = datetime.timedelta(minutes=num)
        elif "hour" in unit:
            delta = datetime.timedelta(hours=num)
        elif "day" in unit:
            delta = datetime.timedelta(days=num)
        elif "week" in unit:
            delta = datetime.timedelta(weeks=num)
        elif "month" in unit:
            ref = ref + relativedelta(months=num)
        elif "year" in unit:
            ref = ref + relativedelta(years=num)
        t = re.sub(r"(in|after)\s*\d+\s*(minutes?|hours?|days?|weeks?|months?|years?)", "", t)
    
    # 英文 "X later" 格式
    elif re.search(r"(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)\s*later", t):
        en_relative_later = re.findall(r"(\d+)\s*(minutes?|hours?|days?|weeks?|months?|years?)\s*later", t)
        num, unit = en_relative_later[0]
        num = int(num)
        
        if "minute" in unit:
            delta = datetime.timedelta(minutes=num)
        elif "hour" in unit:
            delta = datetime.timedelta(hours=num)
        elif "day" in unit:
            delta = datetime.timedelta(days=num)
        elif "week" in unit:
            delta = datetime.timedelta(weeks=num)
        elif "month" in unit:
            ref = ref + relativedelta(months=num)
        elif "year" in unit:
            ref = ref + relativedelta(years=num)
        t = re.sub(r"\d+\s*(minutes?|hours?|days?|weeks?|months?|years?)\s*later", "", t)

    # ============= STEP 3: 特殊中文表达扩展 =============
    # "上上周" "下下周" "下下周三"
    week_offset = 0
    if "上上周" in t: 
        week_offset = -2
        t = t.replace("上上周", "")
    elif "上周" in t: 
        week_offset = -1
        t = t.replace("上周", "")
    elif "本周" in t: 
        week_offset = 0
        t = t.replace("本周", "")
    elif "下下周三" in t:
        # 处理"周三"部分 - 直接计算两周后的周三
        target_wd = WEEKDAY_MAP["三"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:  # 如果是今天，则直接加14天
            ref = ref + datetime.timedelta(days=14)
        else:  # 否则先找到下个目标星期几，再加7天
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周三", "")
    elif "下下周二" in t:
        target_wd = WEEKDAY_MAP["二"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:
            ref = ref + datetime.timedelta(days=14)
        else:
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周二", "")
    elif "下下周一" in t:
        target_wd = WEEKDAY_MAP["一"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:
            ref = ref + datetime.timedelta(days=14)
        else:
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周一", "")
    elif "下下周四" in t:
        target_wd = WEEKDAY_MAP["四"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:
            ref = ref + datetime.timedelta(days=14)
        else:
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周四", "")
    elif "下下周五" in t:
        target_wd = WEEKDAY_MAP["五"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:
            ref = ref + datetime.timedelta(days=14)
        else:
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周五", "")
    elif "下下周六" in t:
        target_wd = WEEKDAY_MAP["六"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:
            ref = ref + datetime.timedelta(days=14)
        else:
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周六", "")
    elif "下下周日" in t:
        target_wd = WEEKDAY_MAP["日"]
        days_until_target = (target_wd - ref.weekday()) % 7
        if days_until_target == 0:
            ref = ref + datetime.timedelta(days=14)
        else:
            ref = ref + datetime.timedelta(days=days_until_target + 7)
        t = t.replace("下下周日", "")
    elif "下下周" in t: 
        week_offset = 2
        t = t.replace("下下周", "")
    elif "下周" in t: 
        week_offset = 1
        t = t.replace("下周", "")
    
    # 处理中文日期表达
    if language == "zh":
        # 匹配 "明天"、"后天"、"大后天" 等
        if "大后天" in t:
            ref = ref + datetime.timedelta(days=3)
            t = t.replace("大后天", "")
        elif "后天" in t:
            ref = ref + datetime.timedelta(days=2)
            t = t.replace("后天", "")
        elif "明天" in t:
            ref = ref + datetime.timedelta(days=1)
            t = t.replace("明天", "")
        elif "今天" in t:
            # 今天不需要修改ref
            t = t.replace("今天", "")
    
    # 处理英文星期表达
    if language == "en":
        # 匹配 "next Friday", "next Monday" 等
        next_weekday = re.search(r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", t)
        if next_weekday:
            target_day = next_weekday.group(1)
            # 计算下个目标星期几
            days_ahead = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }
            target_weekday = days_ahead[target_day]
            days_until_target = (target_weekday - ref.weekday()) % 7
            if days_until_target == 0:  # 如果是今天，则选择下个星期
                days_until_target = 7
            # 直接设置日期偏移，而不是week_offset
            ref = ref + datetime.timedelta(days=days_until_target)
            t = re.sub(r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", "", t)

    # "下个月底""本月最后一个周五"
    if "月底" in t:
        month_add = 1 if "下个月" in t else 0
        base = ref + relativedelta(months=month_add)
        next_month = base.replace(day=28) + datetime.timedelta(days=4)
        last_day = next_month - datetime.timedelta(days=next_month.day)
        ref = datetime.datetime.combine(last_day, datetime.time(0, 0))
        t = re.sub(r"(下个月|本月)?底", "", t)
    elif "最后一个" in t and ("星期" in t or "周" in t):
        wd = re.search(r"(星期|周)([一二三四五六日天])", t)
        if wd:
            target_wd = WEEKDAY_MAP[wd.group(2)]
            base = ref.replace(day=1) + relativedelta(months=1)
            last_day = base - datetime.timedelta(days=1)
            delta_back = (last_day.isoweekday() - target_wd) % 7
            last_target = last_day - datetime.timedelta(days=delta_back)
            ref = datetime.datetime.combine(last_target, datetime.time(0, 0))
            t = ""

    # ============= STEP 4: 时间段修饰（中英文） =============
    hour_guess = None
    minute_guess = None
    
    # 处理中文时间表达中的具体时间（如"七点二十八"）
    if language == "zh":
        time_match_zh = re.search(r"([一二两三四五六七八九十零\d]+)点([一二两三四五六七八九十零\d]+)", t)
        if time_match_zh:
            hour_str = time_match_zh.group(1)
            minute_str = time_match_zh.group(2)
            
            hour = chinese_to_number(hour_str)
            minute = chinese_to_number(minute_str)
            
            hour_guess = hour
            minute_guess = minute
            t = re.sub(r"[一二两三四五六七八九十\d]+点[一二两三四五六七八九十\d]+", "", t)
    
    # 处理时间段修饰
    period_hour = None
    for k, v in PERIOD_MAP.items():
        if k in t:
            period_hour = v
            t = t.replace(k, "")
            break
    
    # 如果既有具体时间又有时间段修饰，需要结合处理
    if hour_guess is not None and period_hour is not None:
        # 具体时间的小时需要根据时间段修饰调整
        if period_hour >= 12:  # 下午、晚上等
            if hour_guess < 12:  # 具体时间的小时小于12
                hour_guess += 12  # 转换为24小时制
        elif period_hour < 12:  # 早上、上午等
            if hour_guess >= 12:  # 具体时间的小时大于等于12
                hour_guess -= 12  # 转换为12小时制
    elif hour_guess is None and period_hour is not None:
        # 只有时间段修饰，没有具体时间
        hour_guess = period_hour
    
    # 处理英文时间表达中的具体时间
    if language == "en":
        # 匹配带秒的格式 "at 3:15:30pm"
        time_match_seconds = re.search(r"at\s+(\d{1,2}):(\d{2}):(\d{2})(am|pm)", t)
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
                t = re.sub(r"at\s+\d{1,2}:\d{2}:\d{2}(am|pm)", "", t)
        
        # 匹配带分钟的格式 "at 3:45pm"
        elif re.search(r"at\s+(\d{1,2}):(\d{2})(am|pm)", t):
            time_match_minutes = re.search(r"at\s+(\d{1,2}):(\d{2})(am|pm)", t)
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
                t = re.sub(r"at\s+\d{1,2}:\d{2}(am|pm)", "", t)
        
        # 匹配简单格式 "at 3pm"
        elif re.search(r"at\s+(\d{1,2})(am|pm)", t):
            time_match = re.search(r"at\s+(\d{1,2})(am|pm)", t)
            hour = int(time_match.group(1))
            period = time_match.group(2)
            if 1 <= hour <= 12:
                if period == "pm" and hour != 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
                hour_guess = hour
                t = re.sub(r"at\s+\d{1,2}(am|pm)", "", t)
        
        # 匹配24小时制格式 "at 15:00"
        elif re.search(r"at\s+(\d{1,2}):?(\d{0,2})", t):
            time_match_24 = re.search(r"at\s+(\d{1,2}):?(\d{0,2})", t)
            hour = int(time_match_24.group(1))
            minute = int(time_match_24.group(2)) if time_match_24.group(2) else 0
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                hour_guess = hour
                minute_guess = minute
                t = re.sub(r"at\s+\d{1,2}:?\d{0,2}", "", t)

    # ============= STEP 5: 用 dateparser 主解析器处理剩余字符串 =============
    dt = dateparser.parse(t, languages=[language],
                          settings={"RELATIVE_BASE": ref,
                                    "TIMEZONE": timezone,
                                    "RETURN_AS_TIMEZONE_AWARE": False})

    if dt is None:
        # 如果没解析出时间，尝试处理一些特殊情况
        if language == "en":
            # 处理英文特殊情况
            if "tomorrow" in t:
                dt = ref + datetime.timedelta(days=1)
            elif "the day after tomorrow" in t:
                dt = ref + datetime.timedelta(days=2)
            elif "next week" in t:
                dt = ref + datetime.timedelta(weeks=1)
            elif "next month" in t:
                dt = ref + relativedelta(months=1)
            elif "next year" in t:
                dt = ref + relativedelta(years=1)
            else:
                dt = ref
        else:
            # 中文特殊情况
            if "明天" in t:
                dt = ref + datetime.timedelta(days=1)
            elif "后天" in t:
                dt = ref + datetime.timedelta(days=2)
            elif "大后天" in t:
                dt = ref + datetime.timedelta(days=3)
            elif "下周" in t:
                dt = ref + datetime.timedelta(weeks=1)
            elif "下个月" in t:
                dt = ref + relativedelta(months=1)
            elif "明年" in t:
                dt = ref + relativedelta(years=1)
            else:
                dt = ref
    else:
        # 检查解析结果是否合理
        if dt < ref:
            # 如果解析结果早于参考时间，可能是解析错误
            # 尝试重新解析，使用更宽松的设置
            dt_retry = dateparser.parse(t, languages=[language],
                                      settings={"RELATIVE_BASE": ref,
                                                "TIMEZONE": timezone,
                                                "RETURN_AS_TIMEZONE_AWARE": False,
                                                "PREFER_DAY_OF_MONTH": "first",
                                                "PREFER_DATES_FROM": "future"})
            if dt_retry is not None and dt_retry >= ref:
                dt = dt_retry

    # ============= STEP 6: 应用额外偏移与时段修饰 =============
    result = dt + delta
    if week_offset != 0:
        result = result + datetime.timedelta(weeks=week_offset)
    
    # 应用时间段修饰
    if hour_guess is not None and 0 <= hour_guess <= 23:
        result = result.replace(hour=hour_guess, minute=0, second=0)
        if minute_guess is not None and 0 <= minute_guess <= 59:
            result = result.replace(minute=minute_guess)

    return {
        "parsed_datetime": result.strftime("%Y-%m-%dT%H:%M:%S"),
        "input_text": text,
        "language": language,
        "reference_datetime": ref.strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": timezone,
        "note": "支持中英文自然语言解析"
    }


class NaturalTimeParserTool(BaseTool):
    """自然语言时间解析工具"""
    
    def __init__(self):
        self.name = "natural_time_parser"
        self.description = (
            "解析自然语言时间表达，支持中英文复杂时间描述。"
            "例如：'下周三'、'本月最后一个周五'、'两小时后'、'next Friday at 9pm'等。"
            "返回标准ISO格式时间字符串。"
        )
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
                
        Returns:
            解析结果，包含parsed_datetime等字段
        """
        try:
            import json
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
            
            result = parse_chinese_english_datetime(
                text=text,
                reference_datetime=reference_datetime,
                timezone=timezone,
                language=language
            )
            
            logger.info(f"🕐 时间解析成功: '{text}' → {result['parsed_datetime']}")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_msg = f"时间解析失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return json.dumps({
                "error": error_msg,
                "input_text": params_dict.get('text', ''),
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


# =========== 测试样例 ===========
if __name__ == "__main__":
    examples = [
        "下下周六早上八点半",
        "前天晚上九点一刻", 
        "下个月底",
        "本月最后一个周五",
        "3天后晚上八点",
        "两小时后",
        "十分钟后",
        "next Friday at 9pm",
        "in 3 days at night",
        "2 hours later"
    ]
    
    print("🧪 自然语言时间解析测试:")
    print("=" * 50)
    
    for ex in examples:
        result = parse_chinese_english_datetime(ex, '2025-10-23T10:00:00')
        print(f"输入: {ex}")
        print(f"输出: {result['parsed_datetime']}")
        print(f"语言: {result['language']}")
        print("-" * 30)