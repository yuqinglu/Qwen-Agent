#!/usr/bin/env python3
"""
用户画像管理工具
提供专门的用户画像更新功能，让Agent更容易理解和处理用户信息变更
"""

import json
from typing import Dict, Any, Optional
from loguru import logger

from qwen_agent.tools.base import BaseTool, register_tool


@register_tool('update_user_profile')
class UpdateUserProfileTool(BaseTool):
    """更新用户画像工具
    
    当用户明确表示要修改其个人信息时使用此工具。
    
    使用场景：
    - 用户说"我不叫XX，我叫YY"
    - 用户说"修改一下我的姓名/年龄/性别等"
    - 用户说"我的信息不对，应该是..."
    - 用户说"更正一下，我是..."
    
    注意：此工具只更新用户画像，不会修改待办事项
    """
    
    description = """更新用户个人信息（用户画像）的专用工具。

使用时机（重要！）：
1. 当用户明确说"我不叫XX，我叫YY"时 → 使用本工具更新姓名
2. 当用户说"修改我的年龄/性别/职业/地址等"时 → 使用本工具
3. 当用户说"更正一下，我是..."时 → 使用本工具
4. 当用户纠正其个人信息时 → 使用本工具

注意：
- 本工具**只更新用户画像**，不会修改待办事项
- 如果待办事项中有错误的信息，应该使用 update_todo 工具单独修改
- 用户通常只是想更正自己的个人信息，而不是批量修改所有相关内容"""

    parameters = [{
        'name': 'user_id',
        'type': 'string',
        'description': '用户ID（必需，从用户上下文中获取）',
        'required': True
    }, {
        'name': 'name',
        'type': 'string',
        'description': '用户姓名（如需更新）',
        'required': False
    }, {
        'name': 'age',
        'type': 'integer',
        'description': '用户年龄（如需更新）',
        'required': False
    }, {
        'name': 'gender',
        'type': 'string',
        'description': '用户性别（如需更新）',
        'required': False
    }, {
        'name': 'location',
        'type': 'string',
        'description': '用户当前位置或工作地点（如需更新）',
        'required': False
    }, {
        'name': 'home_address',
        'type': 'string',
        'description': '用户家庭住址（如需更新）',
        'required': False
    }, {
        'name': 'occupation',
        'type': 'string',
        'description': '用户职业（如需更新）',
        'required': False
    }, {
        'name': 'interests',
        'type': 'string',
        'description': '用户兴趣爱好，多个兴趣用逗号分隔（如需更新）',
        'required': False
    }, {
        'name': 'phone',
        'type': 'string',
        'description': '用户手机号码（用于打车、预约等服务，用户告知后务必调用本工具保存）',
        'required': False
    }]
    
    def call(self, params: str, **kwargs) -> str:
        """执行用户画像更新"""
        try:
            # 解析参数（user_id 可由 agent 通过 kwargs 注入，无需 LLM 显式传递）
            if isinstance(params, dict):
                params_dict = params
            elif isinstance(params, str) and params.strip():
                try:
                    params_dict = json.loads(params)
                except json.JSONDecodeError:
                    params_dict = {}
            else:
                params_dict = {}
            if not isinstance(params_dict, dict):
                params_dict = {}
            user_id = params_dict.get('user_id') or kwargs.get('user_id')
            
            if not user_id:
                return json.dumps({
                    "success": False,
                    "error": "缺少必需参数: user_id"
                }, ensure_ascii=False)
            
            # 构建更新字段
            updates = {}
            
            # 基本信息字段
            if 'name' in params_dict and params_dict['name']:
                updates['name'] = params_dict['name']
            
            if 'age' in params_dict and params_dict['age']:
                updates['age'] = int(params_dict['age'])
            
            if 'gender' in params_dict and params_dict['gender']:
                updates['gender'] = params_dict['gender']
            
            if 'location' in params_dict and params_dict['location']:
                updates['location'] = params_dict['location']
            
            if 'home_address' in params_dict and params_dict['home_address']:
                updates['home_address'] = params_dict['home_address']
            
            if 'occupation' in params_dict and params_dict['occupation']:
                updates['occupation'] = params_dict['occupation']
            
            if 'interests' in params_dict and params_dict['interests']:
                # 处理兴趣爱好（支持逗号分隔）
                interests_str = params_dict['interests']
                if isinstance(interests_str, str):
                    updates['interests'] = [i.strip() for i in interests_str.split(',') if i.strip()]
                elif isinstance(interests_str, list):
                    updates['interests'] = interests_str
            
            if 'phone' in params_dict and params_dict['phone']:
                updates['phone'] = str(params_dict['phone']).strip()
            
            if not updates:
                return json.dumps({
                    "success": False,
                    "error": "没有提供任何需要更新的字段"
                }, ensure_ascii=False)
            
            # 导入记忆管理器
            from ty_mem_agent.memory.user_memory import get_integrated_memory
            integrated_memory = get_integrated_memory()
            
            # 更新用户画像
            success = integrated_memory.user_manager.update_user_profile(user_id, updates)
            
            if success:
                # 获取更新后的画像
                profile = integrated_memory.user_manager.get_user_profile(user_id)
                
                result = {
                    "success": True,
                    "message": "用户画像更新成功",
                    "updated_fields": list(updates.keys()),
                    "current_profile": {
                        "name": profile.name if profile else None,
                        "age": profile.age if profile else None,
                        "gender": profile.gender if profile else None,
                        "location": profile.location if profile else None,
                        "home_address": profile.home_address if profile else None,
                        "phone": profile.phone if profile else None,
                        "occupation": profile.occupation if profile else None,
                        "interests": profile.interests if profile else []
                    }
                }
                
                logger.info(f"✅ 用户画像更新成功: {user_id} - {updates}")
                return json.dumps(result, ensure_ascii=False)
            else:
                return json.dumps({
                    "success": False,
                    "error": "用户画像更新失败"
                }, ensure_ascii=False)
                
        except json.JSONDecodeError as e:
            error_msg = f"参数解析失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"更新用户画像时出错: {str(e)}"
            logger.error(f"❌ {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)


@register_tool('get_user_profile')
class GetUserProfileTool(BaseTool):
    """获取用户画像工具
    
    用于查询用户的完整个人信息
    """
    
    description = """获取用户个人信息（用户画像）的专用工具。

使用场景：
- 用户询问"你还记得我的信息吗"
- 用户询问"我的资料是什么"
- 需要确认用户信息时

返回内容：
- 姓名、年龄、性别、位置等基本信息
- 职业、兴趣爱好等扩展信息"""

    parameters = [{
        'name': 'user_id',
        'type': 'string',
        'description': '用户ID（必需，从用户上下文中获取）',
        'required': True
    }]
    
    def call(self, params: str, **kwargs) -> str:
        """执行用户画像查询"""
        try:
            # 解析参数（user_id 可由 agent 通过 kwargs 注入，无需 LLM 显式传递）
            if isinstance(params, dict):
                params_dict = params
            elif isinstance(params, str) and params.strip():
                try:
                    params_dict = json.loads(params)
                except json.JSONDecodeError:
                    params_dict = {}
            else:
                params_dict = {}
            if not isinstance(params_dict, dict):
                params_dict = {}
            user_id = params_dict.get('user_id') or kwargs.get('user_id')
            
            if not user_id:
                return json.dumps({
                    "success": False,
                    "error": "缺少必需参数: user_id"
                }, ensure_ascii=False)
            
            # 导入记忆管理器
            from ty_mem_agent.memory.user_memory import get_integrated_memory
            integrated_memory = get_integrated_memory()
            
            # 获取用户画像
            profile = integrated_memory.user_manager.get_user_profile(user_id)
            
            if profile:
                result = {
                    "success": True,
                    "profile": {
                        "user_id": profile.user_id,
                        "name": profile.name,
                        "age": profile.age,
                        "gender": profile.gender,
                        "location": profile.location,
                        "home_address": profile.home_address,
                        "phone": profile.phone,  # 电话号码（用于打车等服务）
                        "occupation": profile.occupation,
                        "interests": profile.interests,
                        "preferences": profile.preferences,
                        "created_at": profile.created_at,
                        "updated_at": profile.updated_at
                    }
                }
                
                logger.info(f"✅ 获取用户画像成功: {user_id}")
                return json.dumps(result, ensure_ascii=False)
            else:
                return json.dumps({
                    "success": False,
                    "error": "未找到用户画像"
                }, ensure_ascii=False)
                
        except json.JSONDecodeError as e:
            error_msg = f"参数解析失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)
        except Exception as e:
            error_msg = f"获取用户画像时出错: {str(e)}"
            logger.error(f"❌ {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            return json.dumps({"success": False, "error": error_msg}, ensure_ascii=False)

