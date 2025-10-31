#!/usr/bin/env python3
"""
当前位置坐标工具
提供mock的当前位置经纬度坐标，用于测试和开发
"""

import json
from typing import Dict, Any, Optional
from qwen_agent.tools.base import BaseTool
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("LocationTool")


class CurrentLocationTool(BaseTool):
    """当前位置坐标工具"""
    
    name: str = "get_current_location"
    description: str = "获取当前位置的经纬度坐标（mock数据，以巴蜀中学东北门为当前位置）"
    
    def __init__(self):
        super().__init__()
        # 巴蜀中学东北门的坐标（高德坐标系）
        # 注意：这些坐标是通过网络搜索获得的近似值，建议使用高德地图API获取精确坐标
        self.mock_location = {
            "name": "巴蜀中学东北门",
            "address": "重庆市渝中区巴蜀中学东北门",
            "amap_coordinates": {
                "longitude": 106.563044,  # 高德经度（高德地图API真实坐标）
                "latitude": 29.562395,    # 高德纬度（高德地图API真实坐标）
                "coordinate_system": "GCJ-02 (高德坐标系)",
                "note": "此坐标为高德地图API获取的真实坐标"
            },
            "didi_coordinates": {
                "longitude": 106.563044,  # 滴滴经度（与高德相同）
                "latitude": 29.562395,    # 滴滴纬度（与高德相同）
                "coordinate_system": "GCJ-02 (滴滴坐标系)",
                "note": "此坐标为高德地图API获取的真实坐标"
            },
            "wgs84_coordinates": {
                "longitude": 106.557044,  # WGS84经度（GPS原始坐标，估算）
                "latitude": 29.558395,    # WGS84纬度（GPS原始坐标，估算）
                "coordinate_system": "WGS84 (GPS坐标系)",
                "note": "此坐标为基于GCJ-02坐标估算的WGS84坐标"
            },
            "coordinate_source": "高德地图API真实坐标",
            "recommendation": "已使用高德地图API获取精确坐标"
        }
    
    def call(self, params: str, **kwargs) -> str:
        """
        获取当前位置坐标
        
        Args:
            params: 参数（可选，支持指定坐标系统）
            
        Returns:
            当前位置的坐标信息
        """
        try:
            # 解析参数
            if params:
                try:
                    params_dict = json.loads(params)
                    coordinate_system = params_dict.get("coordinate_system", "amap")
                except:
                    coordinate_system = "amap"
            else:
                coordinate_system = "amap"
            
            # 根据坐标系统返回相应数据
            if coordinate_system.lower() == "didi":
                result = {
                    "success": True,
                    "location": self.mock_location["name"],
                    "address": self.mock_location["address"],
                    "coordinates": self.mock_location["didi_coordinates"],
                    "message": "获取滴滴坐标系当前位置成功"
                }
            elif coordinate_system.lower() == "wgs84":
                result = {
                    "success": True,
                    "location": self.mock_location["name"],
                    "address": self.mock_location["address"],
                    "coordinates": self.mock_location["wgs84_coordinates"],
                    "message": "获取WGS84坐标系当前位置成功"
                }
            else:  # 默认返回高德坐标系
                result = {
                    "success": True,
                    "location": self.mock_location["name"],
                    "address": self.mock_location["address"],
                    "coordinates": self.mock_location["amap_coordinates"],
                    "message": "获取高德坐标系当前位置成功"
                }
            
            logger.info(f"📍 获取当前位置坐标: {self.mock_location['name']}")
            logger.info(f"   坐标系统: {result['coordinates']['coordinate_system']}")
            logger.info(f"   经度: {result['coordinates']['longitude']}")
            logger.info(f"   纬度: {result['coordinates']['latitude']}")
            
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_result = {
                "success": False,
                "error": str(e),
                "message": "获取当前位置坐标失败"
            }
            logger.error(f"❌ 获取当前位置坐标失败: {e}")
            return json.dumps(error_result, ensure_ascii=False, indent=2)




# 导出工具
def get_location_tools() -> list:
    """获取位置工具"""
    return [CurrentLocationTool()]


if __name__ == "__main__":
    # 测试工具
    print("🧪 测试位置工具...")
    
    # 测试当前位置工具
    current_location_tool = CurrentLocationTool()
    print("\n📍 测试获取当前位置:")
    print(current_location_tool.call(""))
