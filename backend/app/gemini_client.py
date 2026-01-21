"""
Google Gemini LLM Client: 调用 Google Gemini API 进行收据解析。
"""
import google.generativeai as genai
from .config import settings
from typing import Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)

# 线程安全的状态管理
import asyncio
_lock = asyncio.Lock()
_client_configured = False


async def _configure_client():
    """
    配置 Gemini 客户端（只需调用一次）。
    
    注意：此函数是异步的，使用锁确保线程安全。
    """
    global _client_configured
    
    async with _lock:
        if not _client_configured:
            if not settings.gemini_api_key:
                raise ValueError(
                    "GEMINI_API_KEY environment variable must be set"
                )
            
            genai.configure(api_key=settings.gemini_api_key)
            _client_configured = True
            logger.info("Google Gemini client configured")


async def parse_receipt_with_gemini(
    system_message: str,
    user_message: str,
    model: str = None,
    temperature: float = 0.0
) -> Dict[str, Any]:
    """
    使用 Google Gemini LLM 解析收据。
    
    注意：此函数是异步的，使用锁确保客户端配置的线程安全。
    
    Args:
        system_message: 系统消息
        user_message: 用户消息（包含 raw_text 和 trusted_hints）
        model: 模型名称（如果为 None，使用配置中的默认值）
        temperature: 温度参数
    
    Returns:
        解析后的 JSON 数据
    """
    await _configure_client()
    model = model or settings.gemini_model
    
    # 添加调试日志，确认使用的模型
    logger.info(f"Gemini model from settings: {settings.gemini_model}")
    logger.info(f"Using Gemini model: {model}")
    
    try:
        # 创建 GenerativeModel
        generative_model = genai.GenerativeModel(model)
        
        # 合并 system_message 和 user_message（Gemini 不直接支持 system message）
        # 方案：将 system_message 放在 user_message 开头
        combined_message = f"{system_message}\n\n{user_message}"
        
        # 配置生成参数
        generation_config = {
            "temperature": temperature,
            "response_mime_type": "application/json",  # 强制 JSON 输出
        }
        
        logger.info(f"Calling Google Gemini API with model: {model}")
        
        # 调用 API
        response = generative_model.generate_content(
            combined_message,
            generation_config=generation_config
        )
        
        content = response.text.strip()
        logger.info("Google Gemini API call successful")
        
        # 解析 JSON（Gemini 有时会用 ```json 包裹）
        content = _extract_json_from_response(content)
        
        try:
            parsed_data = json.loads(content)
            return parsed_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from Gemini response: {e}")
            logger.error(f"Response content: {content[:500]}")  # 记录前500字符
            raise ValueError(f"Invalid JSON response from Gemini: {e}")
        
    except Exception as e:
        logger.error(f"Google Gemini API call failed: {e}")
        raise


def _extract_json_from_response(text: str) -> str:
    """
    从响应中提取 JSON（处理可能的 markdown 代码块）。
    
    Gemini 有时会用 ```json 或 ``` 包裹 JSON。
    """
    text = text.strip()
    
    # 检查是否被 ```json 包裹
    if text.startswith('```json'):
        # 找到第一个 ```json 和最后一个 ```
        start = text.find('```json') + 7
        end = text.rfind('```')
        if end > start:
            text = text[start:end].strip()
    elif text.startswith('```'):
        # 检查是否被 ``` 包裹（无语言标识）
        start = text.find('```') + 3
        end = text.rfind('```')
        if end > start:
            text = text[start:end].strip()
    
    return text
