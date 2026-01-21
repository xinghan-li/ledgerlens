"""
Receipt LLM Processor: 整合 Document AI + LLM 的完整流程。

流程：
1. 调用 Document AI 获取 raw_text 和 entities
2. 提取高置信度字段（confidence >= 0.95）作为 trusted_hints
3. 根据 merchant_name 获取对应的 prompt
4. 调用 LLM 进行结构化重建
5. 后端数学验证
6. 返回最终 JSON
"""
from typing import Dict, Any, Optional, List, Tuple
import logging
import re
from .documentai_client import parse_receipt_documentai
from .prompt_manager import get_merchant_prompt, format_prompt
from .llm_client import parse_receipt_with_llm
from .gemini_client import parse_receipt_with_gemini
from .supabase_client import get_or_create_merchant
from .extraction_rule_manager import get_merchant_extraction_rules, apply_extraction_rules
from .ocr_normalizer import normalize_ocr_result, extract_unified_info
from .config import settings

logger = logging.getLogger(__name__)


def process_receipt_with_llm_from_docai(
    docai_result: Dict[str, Any],
    merchant_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 LLM 处理 Document AI 的结果（向后兼容的包装函数）。
    
    Args:
        docai_result: Document AI 返回的完整 JSON 结果
        merchant_name: 可选的商店名称（如果已知）
        
    Returns:
        结构化的收据数据
    """
    # 标准化 OCR 结果
    normalized = normalize_ocr_result(docai_result, provider="google_documentai")
    
    # 调用统一的处理函数（默认使用 OpenAI）
    return process_receipt_with_llm_from_ocr(normalized, merchant_name=merchant_name, llm_provider="openai")


def process_receipt_with_llm_from_ocr(
    ocr_result: Dict[str, Any],
    merchant_name: Optional[str] = None,
    ocr_provider: str = "unknown",
    llm_provider: str = "openai"
) -> Dict[str, Any]:
    """
    统一的 LLM 处理函数，接受任何标准化后的 OCR 结果。
    
    核心优势：
    1. 基于 raw_text 的统一提取（不依赖 OCR 特定格式）
    2. 统一的验证逻辑（不管 OCR 来源）
    3. 商店特定的规则只需一套（针对 raw_text）
    4. 支持多个 LLM 提供商（OpenAI, Gemini）
    
    Args:
        ocr_result: OCR 结果（可以是任何格式，会自动标准化）
        merchant_name: 可选的商店名称（如果已知）
        ocr_provider: OCR 提供商（用于自动检测，如 "google_documentai", "aws_textract"）
        llm_provider: LLM 提供商（"openai" 或 "gemini"）
        
    Returns:
        结构化的收据数据
    """
    # Step 1: 标准化 OCR 结果（如果还没标准化）
    if "metadata" not in ocr_result or "ocr_provider" not in ocr_result.get("metadata", {}):
        normalized = normalize_ocr_result(ocr_result, provider=ocr_provider)
    else:
        normalized = ocr_result
    
    # Step 2: 提取统一信息
    unified_info = extract_unified_info(normalized)
    
    raw_text = unified_info["raw_text"]
    trusted_hints = unified_info["trusted_hints"]
    
    # 如果没有提供 merchant_name，尝试从标准化结果中获取
    if not merchant_name:
        merchant_name = unified_info.get("merchant_name")
    
    # 获取或创建 merchant
    merchant_id = None
    if merchant_name:
        merchant_id = get_or_create_merchant(merchant_name)
        logger.info(f"Merchant: {merchant_name} (ID: {merchant_id})")
    
    # Step 3: 获取商店特定的 prompt（只用于 prompt 内容，不用于模型选择）
    logger.info(f"Step 3: Loading prompt for merchant: {merchant_name}")
    prompt_config = get_merchant_prompt(merchant_name or "default", merchant_id)
    
    # Step 4: 格式化 prompt
    system_message, user_message = format_prompt(
        raw_text=raw_text,
        trusted_hints=trusted_hints,
        prompt_config=prompt_config
    )
    
    # Step 5: 调用 LLM（根据 llm_provider 从环境变量读取对应配置）
    logger.info(f"Step 4: Calling {llm_provider.upper()} LLM...")
    if llm_provider.lower() == "gemini":
        # 从环境变量读取 Gemini 模型配置
        model = settings.gemini_model
        logger.info(f"Using Gemini model from settings: {model}")
        logger.info(f"Settings.gemini_model value: {settings.gemini_model}")
        llm_result = parse_receipt_with_gemini(
            system_message=system_message,
            user_message=user_message,
            model=model,
            temperature=prompt_config.get("temperature", 0.0)
        )
    else:
        # 默认使用 OpenAI，从环境变量读取 OpenAI 模型配置
        model = settings.openai_model
        logger.info(f"Using OpenAI model from .env: {model}")
        llm_result = parse_receipt_with_llm(
            system_message=system_message,
            user_message=user_message,
            model=model,
            temperature=prompt_config.get("temperature", 0.0)
        )
    
    # Step 6: 从 raw_text 提取价格用于验证（不依赖 LLM，不依赖 OCR 来源）
    # 关键：这个函数已经是基于 raw_text 的，可以用于任何 OCR！
    logger.info("Step 5: Extracting prices from raw_text for validation (OCR-agnostic)...")
    line_items = unified_info.get("line_items", [])
    extracted_line_totals = extract_line_totals_from_raw_text(
        raw_text=raw_text,
        docai_line_items=line_items,  # 如果有，使用；没有也没关系，会 fallback 到 regex
        merchant_name=merchant_name
    )
    
    # Step 7: 后端数学验证（统一的验证逻辑，不依赖 OCR）
    logger.info("Step 6: Performing backend mathematical validation...")
    llm_result = _validate_llm_result(llm_result, extracted_line_totals=extracted_line_totals)
    
    # Step 8: 添加元数据
    llm_result["_metadata"] = {
        "merchant_name": merchant_name,
        "merchant_id": merchant_id,
        "ocr_provider": normalized.get("metadata", {}).get("ocr_provider", "unknown"),
        "llm_provider": llm_provider.lower(),
        "entities": normalized.get("entities", {}),
        "validation_status": llm_result.get("_metadata", {}).get("validation_status", "unknown")
    }
    
    logger.info(f"Receipt processing completed successfully (OCR: {normalized.get('metadata', {}).get('ocr_provider', 'unknown')}, LLM: {llm_provider})")
    return llm_result


def _extract_trusted_hints(docai_result: Dict[str, Any], confidence_threshold: float = 0.95) -> Dict[str, Any]:
    """
    从 Document AI 结果中提取高置信度字段。
    
    Args:
        docai_result: Document AI 返回的结果
        confidence_threshold: 置信度阈值（默认 0.95）
        
    Returns:
        高置信度字段字典
    """
    trusted_hints = {}
    entities = docai_result.get("entities", {})
    
    for entity_type, entity_data in entities.items():
        confidence = entity_data.get("confidence")
        value = entity_data.get("value")
        
        if confidence is not None and confidence >= confidence_threshold and value is not None:
            # 映射到标准字段名
            mapped_key = _map_entity_to_standard_field(entity_type)
            if mapped_key:
                trusted_hints[mapped_key] = {
                    "value": value,
                    "confidence": confidence,
                    "source": "documentai"
                }
    
    logger.info(f"Extracted {len(trusted_hints)} trusted hints (confidence >= {confidence_threshold})")
    return trusted_hints


def _validate_llm_result(
    llm_result: Dict[str, Any],
    tolerance: float = 0.01,
    extracted_line_totals: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    验证 LLM 返回的结果的数学正确性。
    
    验证项：
    1. 每个 item：如果 quantity 和 unit_price 都存在，验证 quantity × unit_price ≈ line_total
    2. 总和验证：所有 items 的 line_total 总和 ≈ receipt.total
    
    TODO: 这些验证数据未来会用于：
    - 训练数据质量评估
    - 模型性能监控
    - 自动纠错和补全（使用 extracted_line_totals 补全缺失商品）
    - 生成验证报告和统计
    
    Args:
        llm_result: LLM 返回的完整结果
        tolerance: 允许的误差范围（默认 0.01）
        extracted_line_totals: 从 raw_text 提取的价格列表（用于对比验证）
        
    Returns:
        更新后的 llm_result，包含验证结果
    """
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    tbd = llm_result.get("tbd", {})
    
    # 初始化 tbd 结构（如果不存在）
    if "items_with_inconsistent_price" not in tbd:
        tbd["items_with_inconsistent_price"] = []
    if "total_mismatch" not in tbd:
        tbd["total_mismatch"] = None
    
    validation_errors = []
    calculated_total = 0.0
    
    # 验证 1: 每个 item 的 quantity × unit_price ≈ line_total
    for item in items:
        line_total = item.get("line_total")
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")
        
        # 如果 line_total 存在，累加到总和
        if line_total is not None:
            calculated_total += float(line_total)
        
        # 如果 quantity 和 unit_price 都存在，验证计算
        if quantity is not None and unit_price is not None and line_total is not None:
            expected_total = float(quantity) * float(unit_price)
            actual_total = float(line_total)
            difference = abs(expected_total - actual_total)
            
            if difference > tolerance:
                error_info = {
                    "raw_text": item.get("raw_text", ""),
                    "product_name": item.get("product_name"),
                    "reason": (
                        f"quantity × unit_price ({expected_total:.2f}) does not equal "
                        f"line_total ({actual_total:.2f}). Difference: {difference:.2f}"
                    ),
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "expected_line_total": round(expected_total, 2),
                    "actual_line_total": actual_total,
                    "difference": round(difference, 2)
                }
                validation_errors.append(error_info)
                logger.warning(
                    f"Item price mismatch: {item.get('product_name')} - "
                    f"expected {expected_total:.2f}, got {actual_total:.2f}"
                )
    
    # 更新 items_with_inconsistent_price（合并 LLM 检测的和后端验证的）
    existing_errors = {err.get("product_name"): err for err in tbd["items_with_inconsistent_price"]}
    for error in validation_errors:
        product_name = error.get("product_name")
        if product_name not in existing_errors:
            tbd["items_with_inconsistent_price"].append(error)
    
    # 验证 2: 总和验证
    documented_total = receipt.get("total")
    if documented_total is not None:
        documented_total = float(documented_total)
        difference = abs(calculated_total - documented_total)
        
        # 如果提供了从 raw_text 提取的价格，也进行对比
        if extracted_line_totals:
            extracted_total = sum(extracted_line_totals)
            extracted_diff = abs(extracted_total - documented_total)
            
            logger.info(
                f"Price comparison: LLM calculated={calculated_total:.2f}, "
                f"raw_text extracted={extracted_total:.2f}, documented={documented_total:.2f}"
            )
            
            # 如果 raw_text 提取的总和更接近 documented_total，可能 LLM 遗漏了商品
            if extracted_diff < difference and abs(extracted_total - documented_total) < tolerance:
                logger.warning(
                    f"Raw text extraction ({extracted_total:.2f}) matches total better than "
                    f"LLM result ({calculated_total:.2f}). Possible missing items in LLM output."
                )
        
        if difference > tolerance:
            tbd["total_mismatch"] = {
                "calculated_total": round(calculated_total, 2),
                "documented_total": round(documented_total, 2),
                "difference": round(difference, 2),
                "reason": (
                    f"Sum of line_totals ({calculated_total:.2f}) does not match "
                    f"receipt total ({documented_total:.2f}). Difference: {difference:.2f}"
                )
            }
            
            # 更新 validation_status
            if "_metadata" not in llm_result:
                llm_result["_metadata"] = {}
            llm_result["_metadata"]["validation_status"] = "needs_review"
            
            logger.warning(
                f"Total mismatch detected: calculated={calculated_total:.2f}, "
                f"documented={documented_total:.2f}, diff={difference:.2f}"
            )
        else:
            # 验证通过，清除可能存在的错误标记
            if tbd.get("total_mismatch"):
                tbd["total_mismatch"] = None
            
            # 如果没有其他错误，标记为通过
            if not validation_errors and not tbd.get("items_with_inconsistent_price"):
                if "_metadata" not in llm_result:
                    llm_result["_metadata"] = {}
                llm_result["_metadata"]["validation_status"] = "pass"
    
    # 更新 tbd
    llm_result["tbd"] = tbd
    
    # 记录验证统计
    total_mismatch_status = "N/A"
    if documented_total is not None:
        total_diff = abs(calculated_total - documented_total)
        total_mismatch_status = "Yes" if total_diff > tolerance else "No"
    
    logger.info(
        f"Validation completed: {len(validation_errors)} item errors, "
        f"total mismatch: {total_mismatch_status}"
    )
    
    return llm_result


def extract_line_totals_from_raw_text(
    raw_text: str,
    docai_line_items: Optional[List[Dict[str, Any]]] = None,
    merchant_name: Optional[str] = None
) -> List[float]:
    """
    从 raw_text 中提取所有商品的行总计（line_total），不依赖 LLM。
    
    策略（按优先级）：
    1. 优先使用 Document AI 的 line_items（如果可用且置信度高）
    2. 使用正则表达式匹配多种价格模式
    3. 通过上下文过滤排除非商品价格（total, tax, subtotal 等）
    
    TODO: 这些提取的数据未来会用于：
    - 与 LLM 结果对比验证
    - 自动补全缺失的商品
    - 训练数据质量评估
    - 生成验证报告
    
    Args:
        raw_text: 原始收据文本
        docai_line_items: Document AI 提取的 line_items（可选）
        merchant_name: 商店名称（可用于格式优化）
        
    Returns:
        所有商品 line_total 的列表
    """
    line_totals = []
    
    # 策略 1: 优先使用 Document AI 的 line_items
    if docai_line_items:
        for item in docai_line_items:
            line_total = item.get("line_total")
            if line_total is not None:
                try:
                    line_totals.append(float(line_total))
                except (ValueError, TypeError):
                    continue
    
    # 如果 Document AI 提取的数量足够，直接返回
    if len(line_totals) >= 3:  # 至少 3 个商品才认为可信
        logger.info(f"Using Document AI line_items: found {len(line_totals)} items")
        return line_totals
    
    # 策略 2: 从 raw_text 中使用正则表达式提取（使用商店特定的规则）
    logger.info("Falling back to regex extraction from raw_text with merchant-specific rules")
    
    # 获取商店特定的提取规则（类似 RAG）
    extraction_rules = get_merchant_extraction_rules(merchant_name=merchant_name)
    
    # 应用规则提取价格
    line_totals = apply_extraction_rules(raw_text, extraction_rules)
    
    return line_totals


def _extract_prices_with_regex(raw_text: str, merchant_name: Optional[str] = None) -> List[float]:
    """
    使用正则表达式从 raw_text 中提取商品价格。
    
    支持多种格式：
    - T&T: "FP $X.XX" (单行或多行)
    - 通用: "$X.XX"
    - 无符号: "X.XX" (在商品行中)
    - 重量商品: "X.XX lb @ $X.XX/lb FP $X.XX" (取最后一个)
    
    过滤规则：
    - 排除明显的总计行（TOTAL, Subtotal, Tax）
    - 排除支付信息（Visa, Reference#）
    - 排除地址、电话等
    - 排除类别标识行（GROCERY, PRODUCE, DELI 等单独一行时）
    
    注意：T&T 收据中，商品可能跨多行：
    - 商品名一行
    - 数量/单价一行（可选）
    - "FP $X.XX" 一行
    我们优先匹配 "FP $X.XX" 格式，因为它最可靠。
    """
    # 首先在整个文本中匹配所有 "FP $X.XX" 格式（最可靠）
    fp_prices = []
    fp_matches = re.finditer(r'FP\s+\$(\d+\.\d{2})', raw_text, re.IGNORECASE)
    for match in fp_matches:
        price = float(match.group(1))
        fp_prices.append(price)
    
    # 如果找到足够多的 FP 价格（至少 3 个），直接使用
    if len(fp_prices) >= 3:
        logger.info(f"Found {len(fp_prices)} FP prices, using them directly")
        return fp_prices
    
    # 否则，逐行分析（fallback）
    lines = raw_text.split('\n')
    prices = []
    
    # 定义需要跳过的行模式
    skip_patterns = [
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
        r'^\d{2}/\d{2}/\d{2}',  # 日期
        r'^\*{3,}',  # 会员号等
        r'^Not A Member',
        r'^立即下載',
        r'^Get Exclusive',
        r'^Enjoy Online',
        r'^GROCERY$',  # 单独的类别标识行
        r'^PRODUCE$',
        r'^DELI$',
        r'^FOOD$',
    ]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # 跳过明显的非商品行
        should_skip = False
        for pattern in skip_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                should_skip = True
                break
        
        if should_skip:
            continue
        
        # 尝试匹配价格
        line_price = None
        
        # 优先匹配 FP 格式（T&T）
        fp_match = re.search(r'FP\s+\$(\d+\.\d{2})', line, re.IGNORECASE)
        if fp_match:
            line_price = float(fp_match.group(1))
        else:
            # 匹配通用 $X.XX 格式
            dollar_matches = list(re.finditer(r'\$(\d+\.\d{2})', line))
            if dollar_matches:
                # 如果有多个价格，取最后一个（通常是行总计）
                line_price = float(dollar_matches[-1].group(1))
            else:
                # 尝试匹配无符号价格（但需要更多上下文判断）
                # 只匹配看起来像商品行的（包含字母和数字）
                if re.search(r'[A-Za-z]', line):  # 包含字母，可能是商品名
                    plain_matches = list(re.finditer(r'\b(\d+\.\d{2})\b', line))
                    if plain_matches:
                        # 取最后一个，但需要验证范围（商品价格通常在 0.01 - 999.99）
                        candidate = float(plain_matches[-1].group(1))
                        if 0.01 <= candidate <= 999.99:
                            line_price = candidate
        
        if line_price is not None:
            prices.append(line_price)
    
    # 合并 FP 价格和其他价格，去重
    all_prices = fp_prices + prices
    unique_prices = []
    seen = set()
    for price in all_prices:
        # 使用四舍五入到分来去重
        rounded = round(price, 2)
        if rounded not in seen:
            seen.add(rounded)
            unique_prices.append(price)
    
    logger.info(f"Extracted {len(unique_prices)} prices from raw_text using regex (FP: {len(fp_prices)}, other: {len(prices)})")
    return unique_prices


def _map_entity_to_standard_field(entity_type: str) -> Optional[str]:
    """
    将 Document AI 的 entity_type 映射到标准字段名。
    """
    mapping = {
        "supplier_name": "merchant_name",
        "merchant_name": "merchant_name",
        "supplier_address": "merchant_address",
        "supplier_phone": "merchant_phone",
        "supplier_city": "merchant_city",
        "receipt_date": "purchase_date",
        "transaction_date": "purchase_date",
        "purchase_time": "purchase_time",
        "total_amount": "total",
        "net_amount": "total",
        "subtotal_amount": "subtotal",
        "tax_amount": "tax",
        "total_tax_amount": "tax",
        "payment_type": "payment_method",
        "card_number": "card_last4",
        "credit_card_last_four_digits": "card_last4",
        "currency": "currency",
    }
    
    return mapping.get(entity_type)
