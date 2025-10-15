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
        
        # 记录调用开始
        logger.info("=" * 80)
        logger.info(f"🔧 MCP 工具调用: {self.name}")
        logger.info("-" * 80)
        logger.info(f"📥 输入参数:")
        logger.info(json.dumps(params_dict, ensure_ascii=False, indent=2))
        logger.info("-" * 80)
        
        try:
            # 调用原始工具
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
