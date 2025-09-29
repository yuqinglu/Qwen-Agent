#!/usr/bin/env python3
"""
QwenAgent风格的滴滴叫车工具
完全按照QwenAgent设计理念实现
"""

import os
from typing import Dict, Optional, Union
import requests
from loguru import logger

# 模拟QwenAgent的BaseTool
class BaseTool:
    """模拟QwenAgent的BaseTool基类"""
    def __init__(self, cfg: Optional[Dict] = None):
        self.cfg = cfg or {}
        self.name = getattr(self, 'name', self.__class__.__name__.lower())
        self.description = getattr(self, 'description', '')
        self.parameters = getattr(self, 'parameters', {})
        self.file_access = getattr(self, 'file_access', False)
    
    def _verify_json_format_args(self, params: Union[str, dict]) -> dict:
        """验证JSON格式参数"""
        if isinstance(params, str):
            try:
                import json
                return json.loads(params)
            except:
                return {"destination": params}  # 简单处理
        return params

def register_tool(tool_name: str):
    """模拟QwenAgent的register_tool装饰器"""
    def decorator(cls):
        cls.name = tool_name
        return cls
    return decorator


@register_tool('didi_ride')
class QwenStyleDidiService(BaseTool):
    """QwenAgent风格的滴滴叫车工具"""
    
    description = '滴滴叫车服务，支持预约出租车、快车、专车等'
    parameters = {
        'type': 'object',
        'properties': {
            'destination': {
                'description': '目的地地址',
                'type': 'string',
            },
            'origin': {
                'description': '出发地地址（可选）',
                'type': 'string',
            },
            'car_type': {
                'description': '车型选择：快车、专车、出租车（可选）',
                'type': 'string',
            }
        },
        'required': ['destination'],
    }

    def __init__(self, cfg: Optional[Dict] = None):
        super().__init__(cfg)
        
        # 模拟的API配置
        self.api_key = self.cfg.get('api_key', os.environ.get('DIDI_API_KEY', ''))
        if not self.api_key:
            logger.warning("⚠️ 滴滴API密钥未配置，请设置DIDI_API_KEY环境变量")
        
        # 模拟的车型配置
        self.car_types = {
            "快车": {"base_price": 8, "per_km": 2.5, "description": "经济实惠"},
            "专车": {"base_price": 15, "per_km": 3.5, "description": "舒适体验"},
            "出租车": {"base_price": 10, "per_km": 2.8, "description": "传统出行"}
        }
        
        logger.info("✅ 成功创建QwenAgent风格滴滴叫车工具")

    def call(self, params: Union[str, dict], **kwargs) -> str:
        """执行叫车服务"""
        try:
            params = self._verify_json_format_args(params)
            destination = params.get('destination', '')
            origin = params.get('origin', '当前位置')
            car_type = params.get('car_type', '快车')
            
            if not destination:
                return "❌ 请提供目的地地址"
            
            if not self.api_key:
                return "❌ 滴滴API密钥未配置，请设置DIDI_API_KEY环境变量"
            
            # 模拟叫车流程
            result = self._simulate_ride_booking(destination, origin, car_type)
            logger.info(f"🚗 叫车服务成功: {result}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 叫车服务失败: {e}")
            return f"❌ 叫车服务失败: {str(e)}"
    
    def _simulate_ride_booking(self, destination: str, origin: str, car_type: str) -> str:
        """模拟叫车预订流程"""
        try:
            # 模拟距离计算
            distance = self._estimate_distance(origin, destination)
            
            # 获取车型信息
            car_info = self.car_types.get(car_type, self.car_types["快车"])
            
            # 计算价格
            price = self._calculate_price(distance, car_info)
            
            # 模拟司机匹配
            driver_info = self._match_driver(car_type)
            
            # 生成订单
            order_id = f"DIDI{hash(destination + str(distance)) % 10000:04d}"
            
            result = f"🚗 叫车成功！\n"
            result += f"📍 出发地: {origin}\n"
            result += f"🎯 目的地: {destination}\n"
            result += f"🚙 车型: {car_type} ({car_info['description']})\n"
            result += f"📏 距离: {distance:.1f}公里\n"
            result += f"💰 预估费用: {price:.1f}元\n"
            result += f"👨‍💼 司机: {driver_info['name']} ({driver_info['rating']}⭐)\n"
            result += f"🚗 车牌: {driver_info['plate']}\n"
            result += f"📱 订单号: {order_id}\n"
            result += f"⏰ 预计到达: {driver_info['eta']}分钟"
            
            return result
            
        except Exception as e:
            return f"❌ 叫车预订失败: {str(e)}"
    
    def _estimate_distance(self, origin: str, destination: str) -> float:
        """估算距离"""
        # 简单的距离估算（实际应用中应该调用地图API）
        import random
        base_distance = 5.0
        variation = random.uniform(0.5, 3.0)
        return base_distance + variation
    
    def _calculate_price(self, distance: float, car_info: Dict) -> float:
        """计算价格"""
        base_price = car_info['base_price']
        per_km = car_info['per_km']
        return base_price + (distance * per_km)
    
    def _match_driver(self, car_type: str) -> Dict:
        """匹配司机"""
        import random
        
        drivers = {
            "快车": [
                {"name": "张师傅", "rating": 4.8, "plate": "京A12345", "eta": 3},
                {"name": "李师傅", "rating": 4.9, "plate": "京B67890", "eta": 5},
                {"name": "王师傅", "rating": 4.7, "plate": "京C11111", "eta": 2}
            ],
            "专车": [
                {"name": "陈师傅", "rating": 4.9, "plate": "京D22222", "eta": 4},
                {"name": "刘师傅", "rating": 5.0, "plate": "京E33333", "eta": 6}
            ],
            "出租车": [
                {"name": "赵师傅", "rating": 4.6, "plate": "京F44444", "eta": 3},
                {"name": "孙师傅", "rating": 4.8, "plate": "京G55555", "eta": 4}
            ]
        }
        
        available_drivers = drivers.get(car_type, drivers["快车"])
        return random.choice(available_drivers)


if __name__ == "__main__":
    # 测试QwenAgent风格的滴滴叫车工具
    from ty_mem_agent.utils.logger_config import get_logger
    test_logger = get_logger("QwenStyleDidiServiceTest")
    
    # 创建工具实例
    didi_tool = QwenStyleDidiService()
    
    # 测试叫车服务
    test_logger.info("🧪 测试QwenAgent风格的滴滴叫车工具...")
    
    # 测试快车
    result1 = didi_tool.call({"destination": "北京首都机场", "car_type": "快车"})
    test_logger.info(f"🚗 快车叫车: {result1}")
    
    # 测试专车
    result2 = didi_tool.call({"destination": "上海虹桥机场", "car_type": "专车"})
    test_logger.info(f"🚗 专车叫车: {result2}")
    
    # 测试字符串参数
    result3 = didi_tool.call("广州南站")
    test_logger.info(f"🚗 默认叫车: {result3}")
    
    test_logger.info("🎉 测试完成！")
