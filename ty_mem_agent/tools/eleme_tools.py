#!/usr/bin/env python3
"""
饿了么外卖工具
提供餐厅搜索、菜单查询、购物车管理、订单管理等功能
适配智能眼镜场景，返回精简的文字信息
"""

import json
import time
import hashlib
import requests
from typing import Dict, Any, Optional, List
from qwen_agent.tools.base import BaseTool, register_tool
from ty_mem_agent.utils.logger_config import get_logger

logger = get_logger("ElemeTool")


class ElemeAPIClient:
    """饿了么 API 客户端"""
    
    def __init__(self, app_key: str, app_secret: str, mode: str = "sandbox"):
        """
        初始化饿了么 API 客户端
        
        Args:
            app_key: 饿了么应用 Key
            app_secret: 饿了么应用 Secret
            mode: 运行模式，"sandbox" 或 "production"
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.mode = mode
        
        # 根据模式选择 API 基础 URL
        if mode == "sandbox":
            self.base_url = "https://open-api-sandbox.ele.me"  # 测试环境
            logger.info("🔧 使用饿了么测试环境")
        else:
            self.base_url = "https://open-api.ele.me"  # 生产环境
            logger.info("🚀 使用饿了么生产环境")
    
    def _calculate_sign(self, params: Dict[str, Any]) -> str:
        """
        计算请求签名
        
        签名规则：
        1. 按照参数名的字典序排序
        2. 拼接为 key1value1key2value2... 格式
        3. 在开头和结尾添加 app_secret
        4. 计算 MD5 哈希值，转为大写
        
        Args:
            params: 请求参数
            
        Returns:
            签名字符串
        """
        # 排序参数
        sorted_params = sorted(params.items())
        
        # 拼接字符串
        sign_str = self.app_secret
        for key, value in sorted_params:
            sign_str += str(key) + str(value)
        sign_str += self.app_secret
        
        # 计算 MD5
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
        
        return sign
    
    def _make_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        发起 API 请求
        
        Args:
            method: API 方法名，如 "eleme.restaurant.search"
            params: 业务参数
            
        Returns:
            API 响应数据
        """
        # 系统级参数
        system_params = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            "format": "json",
            "v": "1.0",
            "method": method,
        }
        
        # 合并系统参数和业务参数
        all_params = {**system_params, **params}
        
        # 计算签名
        sign = self._calculate_sign(all_params)
        all_params["sign"] = sign
        
        # 发起请求
        try:
            logger.debug(f"🌐 调用饿了么 API: {method}")
            logger.debug(f"   参数: {params}")
            
            response = requests.post(
                f"{self.base_url}/api/v1",
                data=all_params,
                timeout=10
            )
            response.raise_for_status()
            
            result = response.json()
            
            # 检查是否有错误
            if "error_response" in result:
                error = result["error_response"]
                logger.error(f"❌ 饿了么 API 错误: {error.get('msg', '未知错误')}")
                return {
                    "success": False,
                    "error_code": error.get("code"),
                    "error_msg": error.get("msg", "未知错误")
                }
            
            logger.info(f"✅ 饿了么 API 调用成功: {method}")
            return {
                "success": True,
                "data": result
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 饿了么 API 请求失败: {e}")
            return {
                "success": False,
                "error_msg": f"网络请求失败: {str(e)}"
            }
        except Exception as e:
            logger.error(f"❌ 饿了么 API 调用异常: {e}")
            return {
                "success": False,
                "error_msg": f"调用异常: {str(e)}"
            }


@register_tool("search_restaurants")
class SearchRestaurantsTool(BaseTool):
    """搜索附近餐厅工具"""
    
    description: str = "根据地理位置搜索附近的餐厅，支持按距离、评分等排序"
    parameters: List[Dict] = [{
        'name': 'latitude',
        'type': 'number',
        'description': '纬度坐标',
        'required': True
    }, {
        'name': 'longitude',
        'type': 'number',
        'description': '经度坐标',
        'required': True
    }, {
        'name': 'keyword',
        'type': 'string',
        'description': '搜索关键词，如餐厅名称、菜品等（可选）',
        'required': False
    }, {
        'name': 'limit',
        'type': 'integer',
        'description': '返回餐厅数量，默认10家',
        'required': False
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """搜索餐厅"""
        try:
            params_dict = json.loads(params)
            latitude = params_dict.get('latitude')
            longitude = params_dict.get('longitude')
            keyword = params_dict.get('keyword', '')
            limit = params_dict.get('limit', 10)
            
            # 调用饿了么 API
            api_params = {
                'latitude': latitude,
                'longitude': longitude,
                'offset': 0,
                'limit': limit
            }
            if keyword:
                api_params['keyword'] = keyword
            
            result = self.client._make_request('eleme.restaurant.search', api_params)
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"搜索失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            # 提取并精简餐厅信息（适配智能眼镜）
            restaurants = result['data'].get('restaurants', [])
            simplified_restaurants = []
            
            for restaurant in restaurants[:limit]:
                simplified_restaurants.append({
                    "id": restaurant.get('id'),
                    "name": restaurant.get('name'),
                    "rating": restaurant.get('rating', 0),
                    "distance": f"{restaurant.get('distance', 0) / 1000:.1f}km",
                    "delivery_time": f"{restaurant.get('delivery_time', 0)}分钟",
                    "delivery_fee": f"¥{restaurant.get('float_delivery_fee', 0)}",
                    "min_price": f"¥{restaurant.get('float_minimum_order_amount', 0)}",
                    "status": "营业中" if restaurant.get('is_premium', False) else "休息中"
                })
            
            logger.info(f"🔍 搜索到 {len(simplified_restaurants)} 家餐厅")
            
            return json.dumps({
                "success": True,
                "message": f"找到{len(simplified_restaurants)}家餐厅",
                "restaurants": simplified_restaurants
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 搜索餐厅失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"搜索失败: {str(e)}"
            }, ensure_ascii=False)


@register_tool("get_restaurant_info")
class GetRestaurantInfoTool(BaseTool):
    """查询餐厅详情工具"""
    
    description: str = "获取餐厅的详细信息，包括公告、营业时间、支持的活动等"
    parameters: List[Dict] = [{
        'name': 'restaurant_id',
        'type': 'string',
        'description': '餐厅ID',
        'required': True
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """查询餐厅信息"""
        try:
            params_dict = json.loads(params)
            restaurant_id = params_dict.get('restaurant_id')
            
            result = self.client._make_request('eleme.restaurant.get', {
                'restaurant_id': restaurant_id
            })
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"查询失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            # 精简餐厅信息（适配智能眼镜）
            restaurant = result['data']
            simplified_info = {
                "name": restaurant.get('name'),
                "rating": restaurant.get('rating', 0),
                "notice": restaurant.get('description', '暂无公告'),
                "business_hours": restaurant.get('opening_hours', []),
                "phone": restaurant.get('phone', ''),
                "address": restaurant.get('address', ''),
                "delivery_time": f"{restaurant.get('delivery_time', 0)}分钟",
                "min_price": f"¥{restaurant.get('float_minimum_order_amount', 0)}"
            }
            
            logger.info(f"🏪 获取餐厅信息: {simplified_info['name']}")
            
            return json.dumps({
                "success": True,
                "restaurant": simplified_info
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 查询餐厅信息失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"查询失败: {str(e)}"
            }, ensure_ascii=False)


@register_tool("get_restaurant_menu")
class GetRestaurantMenuTool(BaseTool):
    """查询餐厅菜单工具"""
    
    description: str = "获取餐厅的菜单信息，包括菜品名称、价格、描述等"
    parameters: List[Dict] = [{
        'name': 'restaurant_id',
        'type': 'string',
        'description': '餐厅ID',
        'required': True
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """查询餐厅菜单"""
        try:
            params_dict = json.loads(params)
            restaurant_id = params_dict.get('restaurant_id')
            
            result = self.client._make_request('eleme.restaurant.menu.get', {
                'restaurant_id': restaurant_id
            })
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"查询菜单失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            # 精简菜单信息（适配智能眼镜）
            categories = result['data'].get('categories', [])
            simplified_menu = []
            
            for category in categories:
                category_info = {
                    "category_name": category.get('name'),
                    "foods": []
                }
                
                for food in category.get('foods', []):
                    category_info['foods'].append({
                        "id": food.get('id'),
                        "name": food.get('name'),
                        "price": f"¥{food.get('specfoods', [{}])[0].get('price', 0)}",
                        "description": food.get('description', ''),
                        "monthly_sales": food.get('month_sales', 0)
                    })
                
                simplified_menu.append(category_info)
            
            logger.info(f"📋 获取菜单，共 {len(categories)} 个分类")
            
            return json.dumps({
                "success": True,
                "menu": simplified_menu
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 查询菜单失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"查询失败: {str(e)}"
            }, ensure_ascii=False)


@register_tool("create_cart")
class CreateCartTool(BaseTool):
    """创建购物车工具"""
    
    description: str = "根据选择的菜品创建购物车"
    parameters: List[Dict] = [{
        'name': 'restaurant_id',
        'type': 'string',
        'description': '餐厅ID',
        'required': True
    }, {
        'name': 'foods',
        'type': 'array',
        'description': '菜品列表，每个菜品包含 food_id 和 quantity',
        'required': True
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """创建购物车"""
        try:
            params_dict = json.loads(params)
            restaurant_id = params_dict.get('restaurant_id')
            foods = params_dict.get('foods', [])
            
            result = self.client._make_request('eleme.cart.create', {
                'restaurant_id': restaurant_id,
                'foods': json.dumps(foods)
            })
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"创建购物车失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            cart = result['data']
            
            # 精简购物车信息
            simplified_cart = {
                "cart_id": cart.get('id'),
                "total_price": f"¥{cart.get('total', 0)}",
                "delivery_fee": f"¥{cart.get('deliver_amount', 0)}",
                "items_count": len(foods),
                "message": "购物车创建成功"
            }
            
            logger.info(f"🛒 购物车创建成功: {simplified_cart['cart_id']}")
            
            return json.dumps({
                "success": True,
                "cart": simplified_cart
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 创建购物车失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"创建失败: {str(e)}"
            }, ensure_ascii=False)


@register_tool("create_order")
class CreateOrderTool(BaseTool):
    """创建订单工具"""
    
    description: str = "根据购物车信息创建订单"
    parameters: List[Dict] = [{
        'name': 'cart_id',
        'type': 'string',
        'description': '购物车ID',
        'required': True
    }, {
        'name': 'address_id',
        'type': 'string',
        'description': '收货地址ID',
        'required': True
    }, {
        'name': 'phone',
        'type': 'string',
        'description': '联系电话',
        'required': True
    }, {
        'name': 'remark',
        'type': 'string',
        'description': '订单备注（可选）',
        'required': False
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """创建订单"""
        try:
            params_dict = json.loads(params)
            cart_id = params_dict.get('cart_id')
            address_id = params_dict.get('address_id')
            phone = params_dict.get('phone')
            remark = params_dict.get('remark', '')
            
            api_params = {
                'cart_id': cart_id,
                'address_id': address_id,
                'phone': phone
            }
            if remark:
                api_params['remark'] = remark
            
            result = self.client._make_request('eleme.order.create', api_params)
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"下单失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            order = result['data']
            
            # 精简订单信息
            simplified_order = {
                "order_id": order.get('id'),
                "order_sn": order.get('unique_id'),
                "total_price": f"¥{order.get('total_amount', 0)}",
                "delivery_time": order.get('deliver_time', ''),
                "status": "待支付",
                "message": "订单创建成功"
            }
            
            logger.info(f"📝 订单创建成功: {simplified_order['order_id']}")
            
            return json.dumps({
                "success": True,
                "order": simplified_order
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 创建订单失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"下单失败: {str(e)}"
            }, ensure_ascii=False)


@register_tool("get_order_status")
class GetOrderStatusTool(BaseTool):
    """查询订单状态工具"""
    
    description: str = "查询订单的当前状态和详细信息"
    parameters: List[Dict] = [{
        'name': 'order_id',
        'type': 'string',
        'description': '订单ID',
        'required': True
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """查询订单状态"""
        try:
            params_dict = json.loads(params)
            order_id = params_dict.get('order_id')
            
            result = self.client._make_request('eleme.order.status.get', {
                'order_id': order_id
            })
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"查询失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            order = result['data']
            
            # 状态映射（精简）
            status_map = {
                '1': '待支付',
                '2': '已确认',
                '3': '配送中',
                '4': '已送达',
                '5': '已取消',
                '6': '已退款'
            }
            
            # 精简订单状态信息
            simplified_status = {
                "order_id": order_id,
                "status": status_map.get(str(order.get('status')), '未知'),
                "delivery_time": order.get('deliver_time', ''),
                "courier_phone": order.get('courier_phone', ''),
                "message": "订单状态查询成功"
            }
            
            logger.info(f"📦 订单状态: {simplified_status['status']}")
            
            return json.dumps({
                "success": True,
                "order_status": simplified_status
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"❌ 查询订单状态失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"查询失败: {str(e)}"
            }, ensure_ascii=False)


@register_tool("remind_order")
class RemindOrderTool(BaseTool):
    """订单催单工具"""
    
    description: str = "催促商家尽快处理订单"
    parameters: List[Dict] = [{
        'name': 'order_id',
        'type': 'string',
        'description': '订单ID',
        'required': True
    }]
    
    def __init__(self, client: ElemeAPIClient):
        super().__init__()
        self.client = client
    
    def call(self, params: str, **kwargs) -> str:
        """催单"""
        try:
            params_dict = json.loads(params)
            order_id = params_dict.get('order_id')
            
            result = self.client._make_request('eleme.order.remind', {
                'order_id': order_id
            })
            
            if not result['success']:
                return json.dumps({
                    "success": False,
                    "message": f"催单失败: {result.get('error_msg', '未知错误')}"
                }, ensure_ascii=False)
            
            logger.info(f"🔔 订单催单成功: {order_id}")
            
            return json.dumps({
                "success": True,
                "message": "已成功催单，请耐心等待"
            }, ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"❌ 催单失败: {e}")
            return json.dumps({
                "success": False,
                "message": f"催单失败: {str(e)}"
            }, ensure_ascii=False)


def get_eleme_tools(app_key: str, app_secret: str, mode: str = "sandbox") -> List[BaseTool]:
    """
    获取饿了么工具列表
    
    Args:
        app_key: 饿了么应用 Key
        app_secret: 饿了么应用 Secret
        mode: 运行模式，"sandbox" 或 "production"
        
    Returns:
        饿了么工具列表
    """
    client = ElemeAPIClient(app_key, app_secret, mode)
    
    tools = [
        SearchRestaurantsTool(client),
        GetRestaurantInfoTool(client),
        GetRestaurantMenuTool(client),
        CreateCartTool(client),
        CreateOrderTool(client),
        GetOrderStatusTool(client),
        RemindOrderTool(client)
    ]
    
    logger.info(f"✅ 饿了么工具初始化成功，共 {len(tools)} 个工具")
    return tools


if __name__ == "__main__":
    # 测试工具
    print("🧪 测试饿了么工具...")
    
    # 注意：需要配置真实的 app_key 和 app_secret
    # tools = get_eleme_tools("your_app_key", "your_app_secret", "sandbox")
    
    print("✅ 饿了么工具模块加载成功")
    print("⚠️  使用前请配置 ELEME_APP_KEY 和 ELEME_APP_SECRET")

