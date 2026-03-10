#!/usr/bin/env python3
"""
智能分句器
用于TTS的智能句子分割，避免在小数点、省略号等位置错误断句
"""

import re
from typing import List, Optional
from loguru import logger
from qwen_agent.llm import get_chat_model
from qwen_agent.llm.schema import Message, USER
from ty_mem_agent.config.settings import get_llm_config, settings


class SmartSentenceSplitter:
    """
    智能句子分割器
    
    使用LLM进行智能句子分割，避免简单正则表达式分割带来的问题：
    - 小数点（如17.5）
    - 省略号（...）
    - 引号内的句号
    - 特殊标点符号
    """
    
    def __init__(self, use_ai: Optional[bool] = None):
        """
        初始化分句器
        
        Args:
            use_ai: 是否使用AI进行智能分句（None则从配置文件读取）
                   True=准确但慢，False=快速但可能不够准确
        """
        # 如果未指定，则从配置文件读取
        self.use_ai = use_ai if use_ai is not None else settings.SENTENCE_SPLITTER_USE_AI
        
        if self.use_ai:
            # 初始化LLM用于智能分句
            llm_config = get_llm_config()
            # 使用快速模型进行分句
            llm_config['model'] = 'qwen-plus'  # 使用较快的模型
            self.llm = get_chat_model(llm_config)
            logger.info("✅ 智能分句器初始化完成（AI模式）")
        else:
            self.llm = None
            logger.info("✅ 智能分句器初始化完成（规则模式）")
    
    def split_sentences_simple(self, text: str) -> List[str]:
        """
        简单规则分句（快速但可能不准确）
        
        Args:
            text: 输入文本
            
        Returns:
            句子列表
        """
        if not text or not text.strip():
            return []
        
        # 使用改进的正则表达式，避免常见误分割
        # 1. 不在数字之间分割（避免小数点问题）
        # 2. 考虑多个标点符号连续的情况（如：...、。。。）
        # 3. 考虑引号内的标点符号
        
        sentences = []
        current = []
        
        i = 0
        while i < len(text):
            char = text[i]
            current.append(char)
            
            # 检查是否是句子结束标点
            if char in '。！？!?.;；':
                # 向前看：检查是否是小数点
                if char == '.' and i > 0 and i < len(text) - 1:
                    prev_char = text[i - 1]
                    next_char = text[i + 1]
                    if prev_char.isdigit() and next_char.isdigit():
                        # 这是小数点，不断句
                        i += 1
                        continue
                
                # 向后看：检查是否有连续的标点符号（如...）
                j = i + 1
                while j < len(text) and text[j] in '。！？!?.;；':
                    current.append(text[j])
                    j += 1
                i = j
                
                # 完成一个句子
                sentence = ''.join(current).strip()
                if sentence:
                    sentences.append(sentence)
                current = []
                continue
            
            i += 1
        
        # 处理剩余内容
        if current:
            sentence = ''.join(current).strip()
            if sentence:
                sentences.append(sentence)
        
        return sentences
    
    def split_sentences_ai(self, text: str) -> List[str]:
        """
        使用AI进行智能分句（准确但较慢）
        
        Args:
            text: 输入文本
            
        Returns:
            句子列表
        """
        if not text or not text.strip():
            return []
        
        # 对于短文本，直接返回
        if len(text) <= 50:
            return [text]
        
        # 构建提示词
        prompt = f"""请将以下文本分割成适合TTS（文字转语音）朗读的句子。

要求：
1. 在合适的位置断句，每个句子应该是完整的语义单元
2. 小数点（如17.5）不应断开
3. 省略号（...）、连续标点符号应保持在同一句子中
4. 引号内的内容尽量保持完整
5. 每个句子不宜过长（建议20-40字）或过短（建议至少5字）

请直接输出分句结果，每行一个句子，不要添加序号或其他标记。

原文本：
{text}

分句结果："""
        
        try:
            messages = [Message(role=USER, content=prompt)]
            
            # 调用LLM
            response = []
            for chunk in self.llm.chat(messages=messages, stream=False):
                response = chunk
            
            if not response:
                logger.warning("⚠️ AI分句返回空结果，使用简单分句")
                return self.split_sentences_simple(text)
            
            # 解析LLM返回的结果
            content = response[0].content if response else ""
            
            # 按行分割
            sentences = [s.strip() for s in content.strip().split('\n') if s.strip()]
            
            # 过滤掉可能的序号
            sentences = [re.sub(r'^\d+[\.\、\s]+', '', s) for s in sentences]
            
            # 验证分句结果
            joined = ''.join(sentences)
            if len(joined) < len(text) * 0.8:  # 如果丢失了超过20%的内容
                logger.warning("⚠️ AI分句可能丢失内容，使用简单分句")
                return self.split_sentences_simple(text)
            
            logger.debug(f"✅ AI分句完成: {len(text)} chars -> {len(sentences)} sentences")
            return sentences
            
        except Exception as e:
            logger.error(f"❌ AI分句失败: {e}，使用简单分句")
            return self.split_sentences_simple(text)
    
    def split(self, text: str) -> List[str]:
        """
        分割句子（主接口）
        
        Args:
            text: 输入文本
            
        Returns:
            句子列表
        """
        if not text or not text.strip():
            return []
        
        if self.use_ai:
            return self.split_sentences_ai(text)
        else:
            return self.split_sentences_simple(text)


# 全局单例（AI模式）
_smart_splitter_ai = None

# 全局单例（规则模式）
_smart_splitter_simple = None


def get_sentence_splitter(use_ai: Optional[bool] = None) -> SmartSentenceSplitter:
    """
    获取句子分割器单例
    
    Args:
        use_ai: 是否使用AI模式（None则从配置文件读取）
        
    Returns:
        分句器实例
    """
    global _smart_splitter_ai, _smart_splitter_simple
    
    # 如果未指定，则从配置文件读取
    actual_use_ai = use_ai if use_ai is not None else settings.SENTENCE_SPLITTER_USE_AI
    
    if actual_use_ai:
        if _smart_splitter_ai is None:
            _smart_splitter_ai = SmartSentenceSplitter(use_ai=True)
        return _smart_splitter_ai
    else:
        if _smart_splitter_simple is None:
            _smart_splitter_simple = SmartSentenceSplitter(use_ai=False)
        return _smart_splitter_simple


# ==================== 测试代码 ====================

def test_sentence_splitter():
    """测试分句器"""
    test_cases = [
        "今天的温度是17.5度，明天会下雨吗？我想知道后天的天气。",
        "这是第一句...这是第二句！这是第三句？",
        "她说：\"你好，很高兴见到你。\"然后她就走了。",
        "订单号是123.456，金额为99.99元。请在3天内完成支付。",
        "这个项目很重要，我们需要认真对待。首先，我们要分析需求；其次，设计方案；最后，实施开发。",
    ]
    
    print("=" * 60)
    print("智能分句器测试")
    print("=" * 60)
    
    # 测试规则模式
    print("\n【规则模式】")
    splitter_simple = get_sentence_splitter(use_ai=False)
    for i, text in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {text}")
        sentences = splitter_simple.split(text)
        for j, sent in enumerate(sentences, 1):
            print(f"  {j}. {sent}")
    
    # 测试AI模式
    print("\n\n【AI模式】")
    splitter_ai = get_sentence_splitter(use_ai=True)
    for i, text in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {text}")
        sentences = splitter_ai.split(text)
        for j, sent in enumerate(sentences, 1):
            print(f"  {j}. {sent}")


if __name__ == "__main__":
    test_sentence_splitter()

