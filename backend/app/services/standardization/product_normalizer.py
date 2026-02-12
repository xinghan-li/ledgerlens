"""
Product Name Normalizer

将原始商品名标准化为统一格式

例如：
- "DOLE BANANA" → "banana"
- "Organic Bananas" → "banana"
- "MILK LACTOSE FREE HG LF" → "milk lactose free"
"""
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
_supabase = None

def _get_supabase():
    """Lazy load supabase client"""
    global _supabase
    if _supabase is None:
        from app.services.database.supabase_client import _get_client
        _supabase = _get_client()
    return _supabase


def normalize_product_name(raw_name: str) -> str:
    """
    标准化商品名
    
    规则：
    1. 转小写
    2. 移除多余空格
    3. 移除常见的商品描述词
    4. 单数化（简单版本）
    
    Args:
        raw_name: 原始商品名
        
    Returns:
        标准化后的名称
    """
    if not raw_name:
        return ""
    
    # 1. 转小写
    name = raw_name.lower().strip()
    
    # 2. 移除常见的无意义词汇
    remove_words = [
        'organic', 'fresh', 'premium', 'select', 'choice',
        'natural', 'whole', 'raw', 'pure', 'authentic',
        'each', 'per', 'pack', 'package', 'bag', 'box',
        'frozen', 'refrigerated', 'canned', 'dried',
        'imported', 'local', 'farm', 'homemade',
        'unsweetened', 'sweetened', 'salted', 'unsalted',
        'extra', 'super', 'ultra', 'mega', 'jumbo', 'mini',
        'large', 'medium', 'small', 'regular', 'xl', 'xxl'
    ]
    
    for word in remove_words:
        # 使用 word boundary 确保只移除完整的单词
        name = re.sub(r'\b' + word + r'\b', '', name, flags=re.IGNORECASE)
    
    # 3. 移除多余空格
    name = re.sub(r'\s+', ' ', name).strip()
    
    # 4. 简单的单数化（移除末尾的 's'）
    # 注意：这只是简单版本，复杂的需要 NLP 库
    if name.endswith('es'):
        name = name[:-2]  # "bananas" → "banana", "tomatoes" → "tomat"
    elif name.endswith('s') and len(name) > 3:
        # 避免误伤本身就是 s 结尾的词
        if not name.endswith('ss'):  # "bass" 不变
            name = name[:-1]
    
    return name.strip()


def extract_brand_from_name(raw_name: str) -> Optional[str]:
    """
    从商品名中提取品牌
    
    简单规则：
    - 通常品牌在开头
    - 全大写的词可能是品牌
    
    Args:
        raw_name: 原始商品名
        
    Returns:
        品牌名或 None
    """
    if not raw_name:
        return None
    
    # 已知品牌列表（可以从数据库加载）
    known_brands = [
        'dole', 'chiquita', 'del monte', 'green giant',
        'horizon', 'organic valley', 'tillamook', 'starbucks',
        'kelloggs', 'general mills', 'kraft', 'nestlé', 'nestle',
        'coca-cola', 'pepsi', 'sprite', 'fanta',
        'lays', 'doritos', 'cheetos', 'pringles'
    ]
    
    name_lower = raw_name.lower()
    
    # 检查是否包含已知品牌
    for brand in known_brands:
        if brand in name_lower:
            return brand.title()  # "dole" → "Dole"
    
    # 提取第一个大写词（可能是品牌）
    words = raw_name.split()
    if words and words[0].isupper() and len(words[0]) > 2:
        return words[0].title()
    
    return None


def classify_product_category(
    raw_name: str,
    normalized_name: str,
    store_chain_id: Optional[str] = None
) -> Dict[str, Optional[str]]:
    """
    商品分类（规则优先，关键词 fallback）
    
    分类策略:
    1. 查询规则表（精确匹配 + 模糊匹配，store-specific 优先）
    2. 如果没有规则，使用关键词匹配（fallback）
    
    Args:
        raw_name: 原始商品名
        normalized_name: 标准化后的名称
        store_chain_id: 商店链 ID（可选，用于 store-specific 规则）
        
    Returns:
        {
            "category_l1": "Grocery",
            "category_l2": "Produce",
            "category_l3": "Fruit"
        }
    """
    # Step 1: 尝试从规则表查询
    try:
        supabase = _get_supabase()
        
        # 调用数据库函数查找匹配规则（支持 store-specific）
        rpc_params = {
            'p_normalized_name': normalized_name,
            'p_threshold': 0.90
        }
        
        if store_chain_id:
            rpc_params['p_store_chain_id'] = store_chain_id
        
        result = supabase.rpc('find_categorization_rule', rpc_params).execute()
        
        if result.data and len(result.data) > 0:
            rule = result.data[0]
            category_id = rule['category_id']
            
            # 查询 category 层级结构
            category_data = supabase.table("categories")\
                .select("id, name, level, parent_id")\
                .eq("id", category_id)\
                .single()\
                .execute()
            
            if category_data.data:
                # 构建完整的层级路径
                cat = category_data.data
                levels = {cat['level']: cat['name']}
                
                # 向上查找 parent
                current_parent_id = cat['parent_id']
                while current_parent_id:
                    parent = supabase.table("categories")\
                        .select("id, name, level, parent_id")\
                        .eq("id", current_parent_id)\
                        .single()\
                        .execute()
                    
                    if parent.data:
                        levels[parent.data['level']] = parent.data['name']
                        current_parent_id = parent.data['parent_id']
                    else:
                        break
                
                # 更新规则匹配统计
                try:
                    supabase.rpc('update_rule_match_stats', {'p_rule_id': rule['rule_id']}).execute()
                except Exception:
                    pass  # 忽略统计更新失败
                
                # 返回层级结构
                return {
                    "category_l1": levels.get(1),
                    "category_l2": levels.get(2),
                    "category_l3": levels.get(3)
                }
    
    except Exception as e:
        logger.warning(f"Failed to query categorization rules: {e}")
        # 失败则 fallback 到关键词匹配
    
    # Step 2: Fallback - 关键词匹配
    name_lower = (raw_name + " " + normalized_name).lower()
    
    # 简单的关键词匹配
    # 注意：这只是 MVP，后续可以用 ML 模型
    
    # Produce - Fruit
    if any(word in name_lower for word in ['banana', 'apple', 'orange', 'grape', 'berry', 'melon', 'mango', 'pear', 'peach', 'plum']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Produce",
            "category_l3": "Fruit"
        }
    
    # Produce - Vegetables
    if any(word in name_lower for word in ['lettuce', 'tomato', 'potato', 'carrot', 'onion', 'pepper', 'spinach', 'broccoli', 'cauliflower']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Produce",
            "category_l3": "Vegetables"
        }
    
    # Dairy - Milk
    if any(word in name_lower for word in ['milk', 'cream', 'half and half', 'lactose']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Dairy",
            "category_l3": "Milk"
        }
    
    # Dairy - Cheese
    if any(word in name_lower for word in ['cheese', 'cheddar', 'mozzarella', 'parmesan', 'gouda']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Dairy",
            "category_l3": "Cheese"
        }
    
    # Dairy - Yogurt
    if 'yogurt' in name_lower or 'yoghurt' in name_lower:
        return {
            "category_l1": "Grocery",
            "category_l2": "Dairy",
            "category_l3": "Yogurt"
        }
    
    # Meat & Seafood
    if any(word in name_lower for word in ['chicken', 'beef', 'pork', 'turkey', 'salmon', 'tuna', 'shrimp', 'fish']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Meat & Seafood",
            "category_l3": None
        }
    
    # Bakery
    if any(word in name_lower for word in ['bread', 'bagel', 'muffin', 'croissant', 'bun', 'roll', 'naan', 'tortilla']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Bakery",
            "category_l3": None
        }
    
    # Beverages - Coffee
    if any(word in name_lower for word in ['coffee', 'espresso', 'latte', 'cappuccino']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Beverages",
            "category_l3": "Coffee & Tea"
        }
    
    # Frozen
    if any(word in name_lower for word in ['frozen', 'ice cream', 'popsicle', 'dumpling']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Frozen",
            "category_l3": None
        }
    
    # Snacks
    if any(word in name_lower for word in ['chip', 'cracker', 'cookie', 'popcorn', 'pretzel']):
        return {
            "category_l1": "Grocery",
            "category_l2": "Snacks",
            "category_l3": None
        }
    
    # Default: Grocery - Other
    return {
        "category_l1": "Grocery",
        "category_l2": None,
        "category_l3": None
    }


def standardize_product(item_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    完整的商品标准化
    
    Args:
        item_data: 原始商品数据
        {
            "product_name": "DOLE BANANA",
            "quantity": 5,
            "unit_price": 0.23,
            "line_total": 1.15,
            "store_chain_id": "uuid-xxx"  # optional
        }
        
    Returns:
        标准化后的数据
        {
            "original_name": "DOLE BANANA",
            "normalized_name": "banana",
            "brand": "Dole",
            "category_l1": "Grocery",
            "category_l2": "Produce",
            "category_l3": "Fruit",
            "quantity": 5,
            "unit_price": 0.23,
            "line_total": 1.15
        }
    """
    raw_name = item_data.get("product_name", "")
    store_chain_id = item_data.get("store_chain_id")
    
    # 1. 标准化名称
    normalized = normalize_product_name(raw_name)
    
    # 2. 提取品牌
    brand = extract_brand_from_name(raw_name)
    
    # 3. 分类（支持 store-specific）
    category = classify_product_category(raw_name, normalized, store_chain_id)
    
    # 4. 组合结果
    result = {
        "original_name": raw_name,
        "normalized_name": normalized,
        "brand": brand,
        "category_l1": category.get("category_l1"),
        "category_l2": category.get("category_l2"),
        "category_l3": category.get("category_l3"),
        "quantity": item_data.get("quantity"),
        "unit": item_data.get("unit"),
        "unit_price": item_data.get("unit_price"),
        "line_total": item_data.get("line_total"),
        "is_on_sale": item_data.get("is_on_sale", False)
    }
    
    return result
