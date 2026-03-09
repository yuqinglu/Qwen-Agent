# -*- coding: utf-8 -*-
"""
聊天附件文本提取器

将上传到 UGC 的附件（文档/图片）转换为纯文本，供注入 LLM 上下文。

支持格式：
  - .txt / .md / .csv / .tsv     直接 decode
  - .pdf                          pdfminer + pdfplumber（qwen_agent 已有）
  - .docx / Word                  python-docx（qwen_agent 已有）
  - .pptx / PowerPoint            python-pptx（qwen_agent 已有）
  - 图片（jpg/png/gif/bmp/webp）   DashScope qwen-vl-ocr 模型（专用 OCR，非通用多模态对话）
"""

import asyncio
import base64
import os
import tempfile
from typing import Optional

from loguru import logger

# --- MIME / 扩展名分类 ---

_IMAGE_CONTENT_TYPES = frozenset({
    "image/jpeg", "image/jpg", "image/png",
    "image/gif", "image/bmp", "image/webp", "image/tiff",
})

_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff",
})

_TEXT_LIKE_EXTENSIONS = frozenset({".txt", ".md", ".csv", ".tsv"})

_MIME_TO_EXT = {
    "image/jpeg": "jpeg",
    "image/jpg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/webp": "webp",
    "image/tiff": "tiff",
}


# ----------------------------------------------------------------
# 公开 API
# ----------------------------------------------------------------

async def extract_text_from_bytes(
    content: bytes,
    content_type: str,
    file_name: str,
    max_chars: int = 8000,
) -> str:
    """
    从文件二进制内容中提取纯文本。

    Args:
        content: 文件二进制内容
        content_type: MIME 类型，如 "application/pdf"、"image/png"
        file_name: 文件名（用于判断扩展名和日志）
        max_chars: 返回文本的最大字符数，超出截断并附说明

    Returns:
        提取到的纯文本字符串；失败时返回说明性占位字符串
    """
    ext = os.path.splitext(file_name.lower())[1] if file_name else ""
    ct_lower = (content_type or "").lower().split(";")[0].strip()

    is_image = (ct_lower in _IMAGE_CONTENT_TYPES) or (ext in _IMAGE_EXTENSIONS)

    if is_image:
        text = await _ocr_image(content, file_name, ct_lower)
    else:
        text = await asyncio.to_thread(_parse_document_sync, content, file_name, ext)

    if not text or not text.strip():
        return "(文件内容为空或无法提取)"

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n…（内容过长已截断，文件共约 {len(text)} 字符）"

    return text


# ----------------------------------------------------------------
# 文档解析（在线程池中同步执行）
# ----------------------------------------------------------------

def _parse_document_sync(content: bytes, file_name: str, ext: str) -> str:
    """
    同步解析文档，写临时文件后调用 qwen_agent 的 simple_doc_parser 解析器。
    在 asyncio.to_thread 中运行，不阻塞事件循环。
    """
    try:
        from qwen_agent.tools.simple_doc_parser import (  # type: ignore
            get_plain_doc,
            parse_pdf,
            parse_ppt,
            parse_txt,
            parse_word,
        )
    except ImportError as exc:
        logger.warning(f"导入 simple_doc_parser 失败: {exc}")
        return _decode_as_text(content)

    suffix = ext if ext else ".bin"
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        if ext == ".pdf":
            pages = parse_pdf(tmp_path)
        elif ext == ".docx":
            pages = parse_word(tmp_path)
        elif ext == ".pptx":
            pages = parse_ppt(tmp_path)
        elif ext in _TEXT_LIKE_EXTENSIONS:
            pages = parse_txt(tmp_path)
        else:
            # 未知扩展名，尝试按 UTF-8 解码
            return _decode_as_text(content)

        return get_plain_doc(pages)

    except Exception as exc:
        logger.warning(f"文档解析失败 ({file_name}): {exc}")
        # 兜底：尝试按纯文本读取
        return _decode_as_text(content)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _decode_as_text(content: bytes) -> str:
    """尝试将二进制内容当作 UTF-8 / GBK 纯文本解码"""
    for encoding in ("utf-8", "gbk", "latin-1"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


# ----------------------------------------------------------------
# 图片 OCR（使用 DashScope qwen-vl-ocr，目的专一：提取文字）
# ----------------------------------------------------------------

async def _ocr_image(content: bytes, file_name: str, ct_lower: str) -> str:
    """异步包装：调用 DashScope OCR 识别图片中的文字"""
    try:
        return await asyncio.to_thread(_ocr_image_sync, content, file_name, ct_lower)
    except Exception as exc:
        logger.warning(f"图片 OCR 失败 ({file_name}): {exc}")
        return f"(图片 OCR 失败: {exc})"


def _ocr_image_sync(content: bytes, file_name: str, ct_lower: str) -> str:
    """
    同步 OCR：使用 DashScope qwen-vl-ocr 模型（专用 OCR 模型，非通用多模态对话）。
    在 asyncio.to_thread 中运行。
    """
    try:
        import dashscope  # type: ignore
        from dashscope import MultiModalConversation  # type: ignore
    except ImportError as exc:
        raise RuntimeError("缺少 dashscope 依赖，无法进行图片 OCR") from exc

    # 判断图片 MIME 类型用于 data URI
    ext = os.path.splitext(file_name.lower())[1].lstrip(".") if file_name else ""
    mime = (
        ct_lower
        if ct_lower in _IMAGE_CONTENT_TYPES
        else f"image/{_MIME_TO_EXT.get(ext, ext or 'jpeg')}"
    )

    b64 = base64.b64encode(content).decode("ascii")
    data_uri = f"data:{mime};base64,{b64}"

    response = MultiModalConversation.call(
        model="qwen-vl-ocr",
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": data_uri},
                    {
                        "text": (
                            "请将图片中所有文字原文提取出来，保持原有排列顺序，"
                            "不要添加任何解释、总结或额外内容。"
                        )
                    },
                ],
            }
        ],
    )

    if response.status_code == 200:
        choices = response.output.get("choices", [])
        if choices:
            msg_content = choices[0].get("message", {}).get("content", [])
            parts = [
                part.get("text", "")
                for part in msg_content
                if isinstance(part, dict) and "text" in part
            ]
            return "\n".join(parts).strip()
        return "(OCR 返回内容为空)"
    else:
        raise RuntimeError(
            f"DashScope OCR 返回错误 [{response.status_code}]: {response.message}"
        )
