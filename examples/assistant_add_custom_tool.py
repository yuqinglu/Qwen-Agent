# Copyright 2023 The Qwen team, Alibaba Group. All rights reserved.
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#    http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""An image generation agent implemented by assistant"""

import json
import os
import urllib.parse

import json5

from qwen_agent.agents import Assistant
from qwen_agent.gui import WebUI
from qwen_agent.tools.base import BaseTool, register_tool

ROOT_RESOURCE = os.path.join(os.path.dirname(__file__), 'resource')


# Add a custom tool named my_image_gen：
@register_tool('my_image_gen')
class MyImageGen(BaseTool):
    description = 'AI painting (image generation) service, input text description, and return the image URL drawn based on text information.'
    parameters = [{
        'name': 'prompt',
        'type': 'string',
        'description': 'Detailed description of the desired image content, in English',
        'required': True,
    }]

    def call(self, params: str, **kwargs) -> str:
        prompt = json5.loads(params)['prompt']
        prompt = urllib.parse.quote(prompt)
        return json.dumps(
            {'image_url': f'https://image.pollinations.ai/prompt/{prompt}'},
            ensure_ascii=False,
        )


def init_agent_service():
    # 配置选项1: 使用DashScope（需要DASHSCOPE_API_KEY）
    llm_cfg = {'model': 'qwen-max'}
    
    # 配置选项2: 使用OpenAI（需要OPENAI_API_KEY）
    # llm_cfg = {
    #     'model': 'gpt-4o-mini',
    #     'model_server': 'https://api.openai.com/v1',
    #     'api_key': os.getenv('OPENAI_API_KEY'),
    # }
    
    # 配置选项3: 使用Together.AI免费模型（需要TOGETHER_API_KEY）
    # llm_cfg = {
    #     'model': 'meta-llama/Llama-3.2-3B-Instruct-Turbo',
    #     'model_server': 'https://api.together.xyz/v1',
    #     'api_key': os.getenv('TOGETHER_API_KEY'),
    # }
    
    # 配置选项4: 使用本地Ollama模型（需要先安装Ollama）
    # llm_cfg = {
    #     'model': 'qwen2.5:7b',
    #     'model_server': 'http://localhost:11434/v1', 
    #     'api_key': 'EMPTY',
    # }
    
    system = ("According to the user's request, you first draw a picture and then automatically "
              'run code to download the picture and select an image operation from the given document '
              'to process the image')

    tools = [
        'my_image_gen',
        'code_interpreter',
    ]  # code_interpreter is a built-in tool in Qwen-Agent
    bot = Assistant(
        llm=llm_cfg,
        name='AI painting',
        description='AI painting service',
        system_message=system,
        function_list=tools,
        files=[os.path.join(ROOT_RESOURCE, 'doc.pdf')],
    )

    return bot


def test(query: str = 'draw a dog'):
    # Define the agent
    bot = init_agent_service()

    # Chat
    messages = [{'role': 'user', 'content': query}]
    for response in bot.run(messages=messages):
        print('bot response:', response)


def app_tui():
    # Define the agent
    bot = init_agent_service()

    # Chat
    messages = []
    while True:
        query = input('user question: ')
        messages.append({'role': 'user', 'content': query})
        response = []
        for response in bot.run(messages=messages):
            print('bot response:', response)
        messages.extend(response)


def app_gui():
    # Define the agent
    bot = init_agent_service()
    chatbot_config = {
        'prompt.suggestions': [
            '画一只猫的图片',
            '画一只可爱的小腊肠狗',
            '画一幅风景画，有湖有山有树',
        ]
    }
    WebUI(
        bot,
        chatbot_config=chatbot_config,
    ).run()


if __name__ == '__main__':
    print("=== qwen-agent 自定义工具示例 ===")
    print("当前配置: DashScope (需要DASHSCOPE_API_KEY)")
    print("如果没有API密钥，请:")
    print("1. 申请阿里云DashScope API密钥")
    print("2. 或修改llm_cfg使用其他模型服务")
    print("3. 设置环境变量: export DASHSCOPE_API_KEY='your-key'")
    print("=" * 40)
    
    # test()
    # app_tui()
    app_gui()
