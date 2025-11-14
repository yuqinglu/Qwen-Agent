#!/usr/bin/env python3
"""
通用工具包装器模块
提供日志记录、智能降级等功能的工具包装器
"""

import json
import re
from typing import Any, Dict, List, Optional
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("ToolWrapper")


class LoggingToolWrapper(BaseTool):
    """通用工具包装器，用于添加日志记录和智能降级功能"""
    
    def __init__(self, original_tool: BaseTool):
        """
        初始化工具包装器
        
        Args:
            original_tool: 原始工具实例
        """
        self.original_tool = original_tool
        self.name = original_tool.name
        self.description = getattr(original_tool, 'description', '')
        self.parameters = getattr(original_tool, 'parameters', {})
        
        # 增强K线工具的描述，让LLM知道如何根据用户意图选择正确的type参数
        self._enhance_kline_tool_description()
    
    def _enhance_kline_tool_description(self):
        """
        增强K线工具的描述，让LLM知道如何根据用户意图选择正确的type参数
        
        增强规则：
        - 查询"本周"、"周涨幅" → 使用type=1200（周K）
        - 查询"本月"、"上月"、"月涨幅" → 使用type=7200（月K）
        - 查询"今年"、"去年"、"年涨幅" → 使用type=86400（年K）
        - 查询"今天"、"今日"、"日涨幅" → 使用type=240（日K）或直接使用报价工具
        """
        # 检查是否是K线查询工具
        if 'K线' not in self.name and 'kline' not in self.name.lower():
            return
        
        # 增强工具描述
        enhanced_description = f"""{self.description}

【重要提示】根据用户查询的时间范围，选择合适的type参数：
- 查询"本周"、"周涨幅"、"这周"、"上周"等周级别数据 → 使用 type="1200"（周K线）
- 查询"本月"、"上月"、"月涨幅"、"这个月"等月级别数据 → 使用 type="7200"（月K线）
- 查询"今年"、"去年"、"年涨幅"、"本年度"等年级别数据 → 使用 type="86400"（年K线）
- 查询"今天"、"今日"、"日涨幅"等日级别数据 → 使用 type="240"（日K线）或直接使用报价工具
- 查询分钟级别数据 → 使用 type="1"（1分钟）、"5"（5分钟）、"15"（15分钟）、"30"（30分钟）、"60"（60分钟）、"120"（120分钟）

注意：周K线会直接返回本周的涨跌幅数据，不需要手动计算。月K线和年K线同理。"""
        
        self.description = enhanced_description
        
        # 增强type参数的描述
        if isinstance(self.parameters, dict) and 'properties' in self.parameters:
            if 'type' in self.parameters['properties']:
                type_prop = self.parameters['properties']['type']
                original_desc = type_prop.get('description', '')
                
                enhanced_type_desc = f"""{original_desc}

【智能选择指南】根据用户查询意图自动选择：
- 用户问"本周"、"周涨幅"、"这周"、"上周" → 使用 "1200"（周K线）
- 用户问"本月"、"上月"、"月涨幅"、"这个月" → 使用 "7200"（月K线）
- 用户问"今年"、"去年"、"年涨幅"、"本年度" → 使用 "86400"（年K线）
- 用户问"今天"、"今日"、"日涨幅" → 使用 "240"（日K线）
- 用户问分钟级别数据 → 使用 "1"、"5"、"15"、"30"、"60"、"120"（分钟K线）

有效值：1(1分钟), 5(5分钟), 15(15分钟), 30(30分钟), 60(60分钟), 120(120分钟), 240(日K), 1200(周K), 7200(月K), 21600(季K), 43200(半年K), 86400(年K)"""
                
                type_prop['description'] = enhanced_type_desc
    
    def _generate_fallback_cities(self, original_city: str) -> List[str]:
        """
        生成降级城市列表
        例如："重庆市渝中区" -> ["重庆市", "渝中区", "重庆"]
        
        Args:
            original_city: 原始城市名称
            
        Returns:
            降级城市列表
        """
        fallback_cities = []
        city = original_city.strip()
        
        # 策略1: 移除区县，保留城市
        # "重庆市渝中区" -> "重庆市"
        # "北京市朝阳区" -> "北京市"
        match = re.match(r'(.*?[市州盟])(.+[区县市])?', city)
        if match and match.group(1):
            city_only = match.group(1)
            if city_only != city:
                fallback_cities.append(city_only)
        
        # 策略2: 只保留区县
        # "重庆市渝中区" -> "渝中区"
        match = re.search(r'([^市州盟]+[区县市])$', city)
        if match:
            district_only = match.group(1)
            if district_only != city:
                fallback_cities.append(district_only)
        
        # 策略3: 移除"市"后缀
        # "重庆市" -> "重庆"
        if city.endswith('市'):
            city_without_suffix = city[:-1]
            if city_without_suffix not in fallback_cities:
                fallback_cities.append(city_without_suffix)
        
        # 去重并保持顺序
        seen = set()
        unique_cities = []
        for c in fallback_cities:
            if c and c not in seen and c != original_city:
                seen.add(c)
                unique_cities.append(c)
        
        return unique_cities
    
    def _is_empty_result(self, result: Any) -> bool:
        """
        检查结果是否为空
        
        Args:
            result: 工具返回结果
            
        Returns:
            是否为空结果
        """
        if not result:
            return True
        
        if isinstance(result, str):
            try:
                result_dict = json.loads(result)
                # 检查常见的数据结构
                if isinstance(result_dict, dict):
                    # 天气查询结果检查
                    if 'weather' in self.name.lower():
                        return not result_dict.get('city') or not result_dict.get('forecasts')
                    # 通用检查
                    return not any(result_dict.values())
            except:
                return len(result.strip()) == 0
        
        return False
    
    def _apply_fallback_strategy(self, params_dict: Dict[str, Any], **kwargs) -> Any:
        """
        应用降级策略
        
        Args:
            params_dict: 参数字典
            **kwargs: 其他参数
            
        Returns:
            降级后的结果
        """
        # 天气工具的智能降级
        if 'weather' in self.name.lower() and 'city' in params_dict:
            original_city = params_dict['city']
            fallback_cities = self._generate_fallback_cities(original_city)
            
            for i, fallback_city in enumerate(fallback_cities, 1):
                logger.info(f"🔄 降级尝试 {i}/{len(fallback_cities)}: {fallback_city}")
                try:
                    fallback_params = params_dict.copy()
                    fallback_params['city'] = fallback_city
                    result = self.original_tool.call(json.dumps(fallback_params), **kwargs)
                    
                    if not self._is_empty_result(result):
                        logger.info(f"✅ 降级成功！使用 '{fallback_city}' 查询到数据")
                        return result
                except Exception as e:
                    logger.debug(f"降级尝试失败: {e}")
                    continue
        
        return None
    
    def _fix_stock_kline_type(self, params_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        修正股票K线查询工具的type参数
        
        标准K线工具的type参数定义：
        - 1: 1分钟
        - 5: 5分钟
        - 15: 15分钟
        - 30: 30分钟
        - 60: 60分钟
        - 120: 120分钟
        - 240: 日K
        - 1200: 周K
        - 7200: 月K
        - 21600: 季K
        - 43200: 半年K
        - 86400: 年K
        
        修正逻辑：
        1. 只修正明显错误的值（如101-106这种复权工具的值），转换为标准值
        2. 不基于limit参数做自动修正，完全依赖LLM根据用户意图选择正确的type
        3. 如果用户明确说"某一天"、"某月某日"，应该用日K（240），即使limit较大
        4. 如果用户说"本周"、"本月"、"今年"，LLM应该根据工具描述选择对应的周K/月K/年K
        
        注意：A股K线复权工具已被排除，不再需要处理复权工具的特殊情况
        
        Args:
            params_dict: 参数字典
            
        Returns:
            修正后的参数字典
        """
        # 检查是否是K线查询工具
        if 'K线' not in self.name and 'kline' not in self.name.lower():
            return params_dict
        
        # 检查是否有type参数
        if 'type' not in params_dict:
            return params_dict
        
        original_type = params_dict.get('type')
        type_str = str(original_type)
        
        # 标准K线工具的有效type值
        valid_types = ['1', '5', '15', '30', '60', '120', '240', '1200', '7200', '86400', '21600', '43200']
        
        # 只修正明显错误的值（如101-106这种复权工具的值），不基于limit做自动修正
        # 因为limit参数有多种用途：
        # - 查询"本周"时，LLM应该自己选择type=1200（周K），limit可以是1
        # - 查询"2025年10月9日那天"时，应该用type=240（日K），limit可能需要较大值来包含历史数据
        # 所以应该完全依赖LLM根据用户意图选择正确的type，而不是用规则判断
        
        if type_str not in valid_types:
            logger.warning(f"⚠️ [{self.name}] 检测到无效的type参数: {type_str}，尝试智能修正...")
            
            # 如果传入了101（原复权工具的日K），转换为240（标准日K）
            if type_str == '101':
                logger.info(f"🔧 将type从 {type_str} 修正为 240 (日K)")
                params_dict['type'] = '240'
            # 如果传入了102（原复权工具的周K），转换为1200（标准周K）
            elif type_str == '102':
                logger.info(f"🔧 将type从 {type_str} 修正为 1200 (周K)")
                params_dict['type'] = '1200'
            # 如果传入了103（原复权工具的月K），转换为7200（标准月K）
            elif type_str == '103':
                logger.info(f"🔧 将type从 {type_str} 修正为 7200 (月K)")
                params_dict['type'] = '7200'
            # 如果传入了104（原复权工具的季K），转换为21600（标准季K）
            elif type_str == '104':
                logger.info(f"🔧 将type从 {type_str} 修正为 21600 (季K)")
                params_dict['type'] = '21600'
            # 如果传入了105（原复权工具的半年K），转换为43200（标准半年K）
            elif type_str == '105':
                logger.info(f"🔧 将type从 {type_str} 修正为 43200 (半年K)")
                params_dict['type'] = '43200'
            # 如果传入了106（原复权工具的年K），转换为86400（标准年K）
            elif type_str == '106':
                logger.info(f"🔧 将type从 {type_str} 修正为 86400 (年K)")
                params_dict['type'] = '86400'
            # 如果查询"本周"，应该使用周K（1200）
            elif type_str.startswith('10') and len(type_str) == 3:
                # 可能是想查询周K（用户问"本周"时）
                logger.info(f"🔧 将type从 {type_str} 修正为 1200 (周K，推测用户想查询本周数据)")
                params_dict['type'] = '1200'
            # 其他情况，默认使用240（日K）
            else:
                logger.info(f"🔧 将type从 {type_str} 修正为 240 (日K，默认值)")
                params_dict['type'] = '240'
        
        # 不再基于limit参数做自动修正，完全依赖LLM根据用户意图选择正确的type
        # 如果LLM选择了正确的type（如240、1200、7200、86400等），就使用它
        # 如果LLM选择了错误的值（如101-106），上面的逻辑已经修正了
        
        return params_dict
    
    def call(self, params: Any, **kwargs) -> str:
        """
        带日志的工具调用
        
        Args:
            params: 工具参数
            **kwargs: 其他参数
            
        Returns:
            工具执行结果
        """
        # 解析参数
        if isinstance(params, str):
            try:
                params_dict = json.loads(params)
            except:
                params_dict = {'params': params}
        else:
            params_dict = params
        
        # 修正股票K线查询的参数
        params_dict = self._fix_stock_kline_type(params_dict)
        
        # 如果参数被修正了，需要重新序列化为字符串
        if isinstance(params, str):
            try:
                # 尝试解析原始参数，如果成功则使用修正后的参数
                json.loads(params)
                params = json.dumps(params_dict, ensure_ascii=False)
            except:
                pass
        
        # 记录调用开始
        logger.info("=" * 80)
        logger.info(f"🔧 MCP 工具调用: {self.name}")
        logger.info("-" * 80)
        logger.info(f"📥 输入参数:")
        logger.info(json.dumps(params_dict, ensure_ascii=False, indent=2))
        logger.info("-" * 80)
        
        try:
            # 使用修正后的参数调用原始工具
            result = self.original_tool.call(params, **kwargs)
            
            # 检查结果是否为空，如果为空则尝试降级策略
            if self._is_empty_result(result):
                logger.warning(f"⚠️ 工具返回空数据，尝试智能降级...")
                fallback_result = self._apply_fallback_strategy(params_dict, **kwargs)
                if fallback_result:
                    result = fallback_result
            
            # 记录返回结果
            logger.info(f"📤 返回结果:")
            try:
                # 尝试格式化 JSON
                result_dict = json.loads(result) if isinstance(result, str) else result
                logger.info(json.dumps(result_dict, ensure_ascii=False, indent=2))
            except:
                # 如果不是 JSON，直接输出
                result_str = str(result)
                if len(result_str) > 500:
                    logger.info(f"{result_str[:500]}... (共 {len(result_str)} 字符)")
                else:
                    logger.info(result_str)
            
            logger.info("-" * 80)
            logger.info(f"✅ 工具调用成功: {self.name}")
            logger.info("=" * 80 + "\n")
            
            return result
            
        except Exception as e:
            # 记录错误
            logger.error(f"❌ 工具调用失败: {self.name}")
            logger.error(f"错误信息: {str(e)}")
            logger.info("=" * 80 + "\n")
            raise


class RetryToolWrapper(BaseTool):
    """重试工具包装器，用于添加重试机制"""
    
    def __init__(self, original_tool: BaseTool, max_retries: int = 3, retry_delay: float = 1.0):
        """
        初始化重试工具包装器
        
        Args:
            original_tool: 原始工具实例
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        self.original_tool = original_tool
        self.name = original_tool.name
        self.description = getattr(original_tool, 'description', '')
        self.parameters = getattr(original_tool, 'parameters', {})
        self.max_retries = max_retries
        self.retry_delay = retry_delay
    
    def call(self, params: Any, **kwargs) -> str:
        """
        带重试机制的工具调用
        
        Args:
            params: 工具参数
            **kwargs: 其他参数
            
        Returns:
            工具执行结果
        """
        import time
        
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"🔄 重试第 {attempt} 次调用: {self.name}")
                    time.sleep(self.retry_delay)
                
                result = self.original_tool.call(params, **kwargs)
                logger.info(f"✅ 工具调用成功: {self.name} (尝试 {attempt + 1}/{self.max_retries + 1})")
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"⚠️ 工具调用失败: {self.name} (尝试 {attempt + 1}/{self.max_retries + 1}): {e}")
                
                if attempt == self.max_retries:
                    logger.error(f"❌ 工具调用最终失败: {self.name} (已重试 {self.max_retries} 次)")
                    break
        
        raise last_exception


class CompositeToolWrapper(BaseTool):
    """复合工具包装器，可以组合多个包装器功能"""
    
    def __init__(self, original_tool: BaseTool, wrappers: List[BaseTool] = None):
        """
        初始化复合工具包装器
        
        Args:
            original_tool: 原始工具实例
            wrappers: 包装器列表，按顺序应用
        """
        self.original_tool = original_tool
        self.name = original_tool.name
        self.description = getattr(original_tool, 'description', '')
        self.parameters = getattr(original_tool, 'parameters', {})
        self.wrappers = wrappers or []
    
    def call(self, params: Any, **kwargs) -> str:
        """
        应用所有包装器的工具调用
        
        Args:
            params: 工具参数
            **kwargs: 其他参数
            
        Returns:
            工具执行结果
        """
        current_tool = self.original_tool
        
        # 按顺序应用所有包装器
        for wrapper_class in self.wrappers:
            current_tool = wrapper_class(current_tool)
        
        return current_tool.call(params, **kwargs)


def wrap_tool_with_logging(tool: BaseTool) -> LoggingToolWrapper:
    """
    便捷函数：为工具添加日志包装器
    
    Args:
        tool: 原始工具
        
    Returns:
        带日志功能的工具包装器
    """
    return LoggingToolWrapper(tool)


def wrap_tool_with_retry(tool: BaseTool, max_retries: int = 3, retry_delay: float = 1.0) -> RetryToolWrapper:
    """
    便捷函数：为工具添加重试包装器
    
    Args:
        tool: 原始工具
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        
    Returns:
        带重试功能的工具包装器
    """
    return RetryToolWrapper(tool, max_retries, retry_delay)


def wrap_tool_with_composite(tool: BaseTool, wrappers: List[BaseTool] = None) -> CompositeToolWrapper:
    """
    便捷函数：为工具添加复合包装器
    
    Args:
        tool: 原始工具
        wrappers: 包装器列表
        
    Returns:
        复合工具包装器
    """
    return CompositeToolWrapper(tool, wrappers)


# 便捷导出
__all__ = [
    'LoggingToolWrapper',
    'RetryToolWrapper', 
    'CompositeToolWrapper',
    'wrap_tool_with_logging',
    'wrap_tool_with_retry',
    'wrap_tool_with_composite',
]


if __name__ == "__main__":
    """测试工具包装器"""
    from ty_mem_agent.utils.logger_config import init_default_logging
    
    init_default_logging()
    
    # 创建一个简单的测试工具
    class TestTool(BaseTool):
        name = "test_tool"
        description = "测试工具"
        parameters = {"type": "object", "properties": {"input": {"type": "string"}}}
        
        def call(self, params, **kwargs):
            return f"测试结果: {params}"
    
    # 测试日志包装器
    logger.info("🧪 测试工具包装器...")
    
    test_tool = TestTool()
    wrapped_tool = wrap_tool_with_logging(test_tool)
    
    result = wrapped_tool.call('{"input": "测试数据"}')
    logger.info(f"结果: {result}")
    
    logger.info("🎉 测试完成！")
