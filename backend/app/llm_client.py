"""
OpenAI LLM Client: 调用 OpenAI API 进行收据解析。
"""
from openai import OpenAI
from .config import settings
from typing import Dict, Any, Optional
import logging
import json

logger = logging.getLogger(__name__)

# Singleton OpenAI client
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    """获取或创建 OpenAI 客户端。"""
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable must be set"
            )
        
        _client = OpenAI(api_key=settings.openai_api_key)
        logger.info("OpenAI client initialized")
    
    return _client


def parse_receipt_with_llm(
    system_message: str,
    user_message: str,
    model: str = None,
    temperature: float = 0.0
) -> Dict[str, Any]:
    """
    使用 OpenAI LLM 解析收据。
    
    Args:
        system_message: 系统消息
        user_message: 用户消息（包含 raw_text 和 trusted_hints）
        model: 模型名称（如果为 None，使用配置中的默认值）
        temperature: 温度参数
        
    Returns:
        解析后的 JSON 数据
    """
    client = _get_client()
    model = model or settings.openai_model
    
    try:
        logger.info(f"Calling OpenAI API with model: {model}")
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            temperature=temperature,
            response_format={"type": "json_object"},  # 强制 JSON 输出
        )
        
        content = response.choices[0].message.content
        logger.info("OpenAI API call successful")
        
        # 解析 JSON
        try:
            parsed_data = json.loads(content)
            return parsed_data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from OpenAI response: {e}")
            logger.error(f"Response content: {content[:500]}")  # 记录前500字符
            raise ValueError(f"Invalid JSON response from OpenAI: {e}")
        
    except Exception as e:
        logger.error(f"OpenAI API call failed: {e}")
        raise
