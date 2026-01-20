"""
Extraction Rule Manager: 管理商店特定的价格提取规则。

类似 RAG 系统，从数据库加载商店特定的提取规则，用于价格提取。
"""
from typing import Dict, Any, Optional, List
import logging
import re
from .supabase_client import _get_client
from .config import settings

logger = logging.getLogger(__name__)

# 规则缓存
_rule_cache: Dict[str, Dict[str, Any]] = {}


def get_merchant_extraction_rules(
    merchant_name: Optional[str] = None,
    merchant_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    获取商店特定的提取规则。
    
    Args:
        merchant_name: 商店名称
        merchant_id: 可选的商店 ID
        
    Returns:
        提取规则字典，包含 price_patterns, skip_patterns, special_rules
    """
    # 检查缓存
    cache_key = (merchant_name or "").lower().strip()
    if cache_key in _rule_cache:
        logger.debug(f"Using cached extraction rules for merchant: {merchant_name}")
        return _rule_cache[cache_key]
    
    supabase = _get_client()
    
    try:
        # 从 merchant_prompts 表获取规则
        query = supabase.table("merchant_prompts").select("extraction_rules, merchant_name").eq("is_active", True)
        
        if merchant_id:
            query = query.eq("merchant_id", merchant_id)
        elif merchant_name:
            query = query.ilike("merchant_name", f"%{merchant_name}%")
        else:
            return get_default_extraction_rules()
        
        res = query.order("version", desc=True).limit(1).execute()
        
        if res.data and len(res.data) > 0:
            rules_data = res.data[0].get("extraction_rules")
            if rules_data:
                # 缓存结果
                _rule_cache[cache_key] = rules_data
                logger.info(f"Loaded extraction rules for merchant: {merchant_name}")
                return rules_data
        
        # 如果没有找到，返回默认规则
        logger.warning(f"No custom extraction rules found for merchant: {merchant_name}, using default")
        return get_default_extraction_rules()
        
    except Exception as e:
        logger.error(f"Failed to load extraction rules for merchant {merchant_name}: {e}")
        return get_default_extraction_rules()


def get_default_extraction_rules() -> Dict[str, Any]:
    """
    返回默认的提取规则（通用规则）。
    """
    return {
        "price_patterns": [
            {
                "pattern": r'FP\s+\$(\d+\.\d{2})',
                "priority": 1,
                "description": "FP price format (T&T, etc.)",
                "flags": "IGNORECASE"
            },
            {
                "pattern": r'\$(\d+\.\d{2})',
                "priority": 2,
                "description": "Generic dollar price format"
            },
            {
                "pattern": r'\b(\d+\.\d{2})\b',
                "priority": 3,
                "description": "Plain number price format",
                "requires_context": True  # 需要上下文判断
            }
        ],
        "skip_patterns": [
            r'^TOTAL',
            r'^Subtotal',
            r'^Tax',
            r'^Points',
            r'^Reference',
            r'^Trans:',
            r'^Terminal:',
            r'^CLERK',
            r'^INVOICE:',
            r'^REFERENCE:',
            r'^AMOUNT',
            r'^APPROVED',
            r'^AUTH CODE',
            r'^APPLICATION',
            r'^Visa',
            r'^VISA',
            r'^Mastercard',
            r'^Credit Card',
            r'^CREDIT CARD',
            r'^Customer Copy',
            r'^STORE:',
            r'^Ph:',
            r'^www\.',
            r'^\d{2}/\d{2}/\d{2}',
            r'^\*{3,}',
            r'^Not A Member',
            r'^立即下載',
            r'^Get Exclusive',
            r'^Enjoy Online',
        ],
        "special_rules": {
            "use_global_fp_match": True,
            "min_fp_count": 3,
            "category_identifiers": []
        }
    }


def apply_extraction_rules(
    raw_text: str,
    rules: Dict[str, Any]
) -> List[float]:
    """
    应用提取规则从 raw_text 中提取价格。
    
    Args:
        raw_text: 原始收据文本
        rules: 提取规则字典
        
    Returns:
        提取到的价格列表
    """
    special_rules = rules.get("special_rules", {})
    price_patterns = rules.get("price_patterns", [])
    skip_patterns = rules.get("skip_patterns", [])
    
    # 特殊规则：全局 FP 匹配（T&T 等）
    if special_rules.get("use_global_fp_match", False):
        min_fp_count = special_rules.get("min_fp_count", 3)
        
        # 查找 FP 价格模式（通常是第一个 pattern）
        fp_pattern = None
        for pattern_config in price_patterns:
            if "FP" in pattern_config.get("pattern", ""):
                fp_pattern = pattern_config["pattern"]
                flags = pattern_config.get("flags", "")
                break
        
        if fp_pattern:
            regex_flags = re.IGNORECASE if "IGNORECASE" in flags else 0
            fp_matches = list(re.finditer(fp_pattern, raw_text, regex_flags))
            fp_prices = [float(m.group(1)) for m in fp_matches]
            
            if len(fp_prices) >= min_fp_count:
                logger.info(f"Using global FP match: found {len(fp_prices)} prices")
                return fp_prices
    
    # 否则，逐行分析
    lines = raw_text.split('\n')
    prices = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 检查是否需要跳过
        should_skip = False
        for skip_pattern in skip_patterns:
            if re.match(skip_pattern, line, re.IGNORECASE):
                should_skip = True
                break
        
        if should_skip:
            continue
        
        # 按优先级尝试匹配价格模式
        line_price = None
        for pattern_config in sorted(price_patterns, key=lambda x: x.get("priority", 999)):
            pattern = pattern_config["pattern"]
            flags = pattern_config.get("flags", "")
            requires_context = pattern_config.get("requires_context", False)
            
            regex_flags = re.IGNORECASE if "IGNORECASE" in flags else 0
            
            if requires_context:
                # 需要上下文判断（如包含字母）
                if not re.search(r'[A-Za-z]', line):
                    continue
            
            matches = list(re.finditer(pattern, line, regex_flags))
            if matches:
                # 如果有多个匹配，取最后一个（通常是行总计）
                line_price = float(matches[-1].group(1))
                
                # 验证价格范围
                if 0.01 <= line_price <= 999.99:
                    break
                else:
                    line_price = None
        
        if line_price is not None:
            prices.append(line_price)
    
    # 去重
    unique_prices = []
    seen = set()
    for price in prices:
        rounded = round(price, 2)
        if rounded not in seen:
            seen.add(rounded)
            unique_prices.append(price)
    
    logger.info(f"Extracted {len(unique_prices)} prices using extraction rules")
    return unique_prices
