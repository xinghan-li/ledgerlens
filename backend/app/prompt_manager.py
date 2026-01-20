"""
Prompt Manager: 管理商店特定的 RAG prompts。

从 Supabase 中检索和缓存 merchant-specific prompts。
"""
from supabase import create_client, Client
from .config import settings
from typing import Optional, Dict, Any
import logging
import json

logger = logging.getLogger(__name__)

# Singleton Supabase client
_supabase: Optional[Client] = None

# In-memory cache for prompts
_prompt_cache: Dict[str, Dict[str, Any]] = {}


def _get_client() -> Client:
    """Get or create the Supabase client."""
    global _supabase
    if _supabase is None:
        if not settings.supabase_url or not settings.supabase_anon_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in environment"
            )
        
        key = settings.supabase_service_role_key or settings.supabase_anon_key
        _supabase = create_client(settings.supabase_url, key)
        logger.info("Supabase client initialized for prompt manager")
    
    return _supabase


def get_merchant_prompt(merchant_name: str, merchant_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    获取商店特定的 prompt。
    
    Args:
        merchant_name: 商店名称
        merchant_id: 可选的商店 ID（如果已知）
        
    Returns:
        Prompt 配置字典，包含 prompt_template, system_message, model_name 等
    """
    # 检查缓存
    cache_key = merchant_name.lower().strip()
    if cache_key in _prompt_cache:
        logger.debug(f"Using cached prompt for merchant: {merchant_name}")
        return _prompt_cache[cache_key]
    
    supabase = _get_client()
    
    try:
        # 先尝试通过 merchant_id 查找
        query = supabase.table("merchant_prompts").select("*").eq("is_active", True)
        
        if merchant_id:
            query = query.eq("merchant_id", merchant_id)
        else:
            # 通过 merchant_name 查找
            query = query.ilike("merchant_name", f"%{merchant_name}%")
        
        res = query.order("version", desc=True).limit(1).execute()
        
        if res.data and len(res.data) > 0:
            prompt_data = res.data[0]
            # 如果数据库中没有设置 model_name，使用环境变量中的默认值
            if not prompt_data.get("model_name"):
                prompt_data["model_name"] = settings.openai_model
            # 缓存结果
            _prompt_cache[cache_key] = prompt_data
            logger.info(f"Loaded prompt for merchant: {merchant_name} (ID: {prompt_data.get('id')})")
            return prompt_data
        
        # 如果没有找到，返回默认 prompt
        logger.warning(f"No custom prompt found for merchant: {merchant_name}, using default")
        return get_default_prompt()
        
    except Exception as e:
        logger.error(f"Failed to load prompt for merchant {merchant_name}: {e}")
        return get_default_prompt()


def get_default_prompt() -> Dict[str, Any]:
    """
    返回默认的 prompt 模板。
    
    当没有找到商店特定的 prompt 时使用。
    """
    return {
        "prompt_template": _get_default_prompt_template(),
        "system_message": _get_default_system_message(),
        "model_name": settings.openai_model,
        "temperature": 0.0,
        "output_schema": _get_default_output_schema(),
    }


def _get_default_system_message() -> str:
    """默认系统消息。"""
    return """You are a receipt parsing expert. Your task is to extract structured information from receipt text and trusted hints from Document AI.

Key requirements:
1. Output ONLY valid JSON, no additional text
2. Follow the exact schema provided
3. Perform validation: quantity × unit_price ≈ line_total (tolerance: ±0.01)
4. Sum of all line_totals must ≈ total (tolerance: ±0.01)
5. If information is missing or uncertain, set to null and document in tbd
6. Do not hallucinate or guess values"""


def _get_default_prompt_template() -> str:
    """默认 prompt 模板。"""
    return """Parse the following receipt text and extract structured information.

## Raw Text:
{raw_text}

## Trusted Hints (high confidence fields from Document AI):
{trusted_hints}

## Output Schema:
{output_schema}

## Instructions:
1. Extract receipt-level fields (merchant, date, time, amounts, payment method)
2. Extract all line items from raw_text, ensuring each item has:
   - product_name (cleaned, no extra formatting)
   - quantity and unit (if available)
   - unit_price (if available)
   - line_total (must match quantity × unit_price if both are present)
3. Validate calculations:
   - For each item: if quantity and unit_price exist, verify: quantity × unit_price ≈ line_total (±0.01)
   - Sum all line_totals and verify: sum ≈ total (±0.01)
4. Document any issues in the "tbd" section:
   - Items with inconsistent price calculations
   - Field conflicts between raw_text and trusted_hints
   - Missing information

## Currency Logic:
- If address is in USA, default currency is USD
- If address is in Canada, default currency is CAD
- If currency is explicitly mentioned in raw_text, use that

## Important:
- If raw_text conflicts with trusted_hints, prefer raw_text and document conflict in tbd
- Do not invent or guess values - use null if information is not available
- Output must be valid JSON matching the schema exactly

Output the JSON now:"""


def _get_default_output_schema() -> Dict[str, Any]:
    """默认输出 schema。"""
    return {
        "receipt": {
            "merchant_name": "string or null",
            "merchant_address": "string or null",
            "merchant_phone": "string or null",
            "country": "string or null",
            "currency": "string (USD, CAD, etc.)",
            "purchase_date": "string (YYYY-MM-DD) or null",
            "purchase_time": "string (HH:MM:SS) or null",
            "subtotal": "number or null",
            "tax": "number or null",
            "total": "number",
            "payment_method": "string or null",
            "card_last4": "string or null"
        },
        "items": [
            {
                "raw_text": "string",
                "product_name": "string or null",
                "quantity": "number or null",
                "unit": "string or null",
                "unit_price": "number or null",
                "line_total": "number or null",
                "is_on_sale": "boolean",
                "category": "string or null"
            }
        ],
        "tbd": {
            "items_with_inconsistent_price": [
                {
                    "raw_text": "string",
                    "product_name": "string or null",
                    "reason": "string (e.g., 'quantity × unit_price (X.XX) does not equal line_total (Y.YY)' or 'Unable to match product name with correct price')"
                }
            ],
            "field_conflicts": {
                "field_name": {
                    "from_raw_text": "value or null",
                    "from_trusted_hints": "value or null",
                    "reason": "string"
                }
            },
            "missing_info": [
                "string (description of missing information)"
            ],
            "total_mismatch": {
                "calculated_total": "number (sum of all line_totals)",
                "documented_total": "number (from receipt total)",
                "difference": "number",
                "reason": "string"
            }
        }
    }


def format_prompt(
    raw_text: str,
    trusted_hints: Dict[str, Any],
    prompt_config: Optional[Dict[str, Any]] = None
) -> tuple[str, str]:
    """
    格式化 prompt，准备发送给 LLM。
    
    Args:
        raw_text: 原始收据文本
        trusted_hints: 高置信度的字段（confidence >= 0.95）
        prompt_config: Prompt 配置（如果为 None，使用默认）
        
    Returns:
        (system_message, user_message) 元组
    """
    if prompt_config is None:
        prompt_config = get_default_prompt()
    
    system_message = prompt_config.get("system_message") or _get_default_system_message()
    
    # 格式化 trusted_hints
    trusted_hints_str = json.dumps(trusted_hints, indent=2, ensure_ascii=False)
    
    # 格式化 output_schema
    output_schema = prompt_config.get("output_schema")
    if isinstance(output_schema, str):
        # 如果已经是字符串，直接使用
        output_schema_str = output_schema
    else:
        # 如果是 dict，转换为 JSON 字符串
        output_schema = output_schema or _get_default_output_schema()
        output_schema_str = json.dumps(output_schema, indent=2, ensure_ascii=False)
    
    # 格式化 user message
    user_message = prompt_config.get("prompt_template", _get_default_prompt_template()).format(
        raw_text=raw_text,
        trusted_hints=trusted_hints_str,
        output_schema=output_schema_str
    )
    
    return system_message, user_message


def clear_cache():
    """清除 prompt 缓存（用于测试或更新 prompts 后）。"""
    global _prompt_cache
    _prompt_cache.clear()
    logger.info("Prompt cache cleared")
