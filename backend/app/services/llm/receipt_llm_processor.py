"""
Receipt LLM Processor: Complete workflow integrating Document AI + LLM.

Workflow:
1. Call Document AI to get raw_text and entities
2. Extract high-confidence fields (confidence >= 0.95) as trusted_hints
3. Get corresponding prompt based on merchant_name
4. Call LLM for structured reconstruction
5. Backend mathematical validation
6. Return final JSON
"""
from typing import Dict, Any, Optional, List, Tuple
import logging
import re
from ...services.ocr.documentai_client import parse_receipt_documentai
from ...prompts.prompt_manager import get_merchant_prompt, format_prompt
from .llm_client import parse_receipt_with_llm
from .gemini_client import parse_receipt_with_gemini
from ...services.database.supabase_client import get_store_chain
from ...prompts.extraction_rule_manager import get_merchant_extraction_rules, apply_extraction_rules
from ...services.ocr.ocr_normalizer import normalize_ocr_result, extract_unified_info
from ...config import settings

logger = logging.getLogger(__name__)


async def process_receipt_with_llm_from_docai(
    docai_result: Dict[str, Any],
    merchant_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process Document AI results with LLM (backward-compatible wrapper function).
    
    Args:
        docai_result: Complete JSON result returned by Document AI
        merchant_name: Optional merchant name (if known)
        
    Returns:
        Structured receipt data
    """
    # Normalize OCR result
    normalized = normalize_ocr_result(docai_result, provider="google_documentai")
    
    # Call unified processing function (default uses OpenAI)
    return await process_receipt_with_llm_from_ocr(normalized, merchant_name=merchant_name, llm_provider="openai")


async def process_receipt_with_llm_from_ocr(
    ocr_result: Dict[str, Any],
    merchant_name: Optional[str] = None,
    ocr_provider: str = "unknown",
    llm_provider: str = "openai",
    receipt_id: Optional[str] = None,
    initial_parse_result: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Unified LLM processing function that accepts any normalized OCR result.
    
    Core advantages:
    1. Unified extraction based on raw_text (not dependent on OCR-specific format)
    2. Unified validation logic (regardless of OCR source)
    3. Merchant-specific rules only need one set (targeting raw_text)
    4. Support multiple LLM providers (OpenAI, Gemini)
    5. Can use initial parse result (rule-based extraction) to guide LLM
    
    Args:
        ocr_result: OCR result (can be any format, will be automatically normalized)
        merchant_name: Optional merchant name (if known)
        ocr_provider: OCR provider (for auto-detection, e.g., "google_documentai", "aws_textract")
        llm_provider: LLM provider ("openai" or "gemini")
        receipt_id: Optional receipt ID for database tracking
        initial_parse_result: Optional rule-based extraction result to guide LLM
        
    Returns:
        Structured receipt data
    """
    # Step 1: Normalize OCR result (if not already normalized)
    if "metadata" not in ocr_result or "ocr_provider" not in ocr_result.get("metadata", {}):
        normalized = normalize_ocr_result(ocr_result, provider=ocr_provider)
    else:
        normalized = ocr_result
    
    # Step 2: Extract unified information
    unified_info = extract_unified_info(normalized)
    
    raw_text = unified_info["raw_text"]
    trusted_hints = unified_info["trusted_hints"]
    
    # If merchant_name not provided, try to get from normalized result
    if not merchant_name:
        merchant_name = unified_info.get("merchant_name")
    
    # Step 1: Try to match store from OCR result (first attempt)
    # Don't create candidate yet - wait until after LLM processing
    ocr_chain_id = None
    ocr_location_id = None
    ocr_suggested_chain_id = None
    ocr_suggested_location_id = None
    ocr_confidence_score = None
    ocr_matched = False
    
    if merchant_name:
        # Try to get store address from OCR result for better matching
        store_address = unified_info.get("merchant_address")
        ocr_store_match = get_store_chain(merchant_name, store_address)
        
        if ocr_store_match.get("matched"):
            # High confidence match from OCR - use directly
            ocr_chain_id = ocr_store_match.get("chain_id")
            ocr_location_id = ocr_store_match.get("location_id")
            ocr_matched = True
            logger.info(f"OCR stage: Matched store: {merchant_name} -> chain_id={ocr_chain_id}, location_id={ocr_location_id}")
        else:
            # Not matched in OCR stage - save suggestion info for later
            ocr_suggested_chain_id = ocr_store_match.get("suggested_chain_id")
            ocr_suggested_location_id = ocr_store_match.get("suggested_location_id")
            ocr_confidence_score = ocr_store_match.get("confidence_score")
            
            if ocr_suggested_chain_id:
                logger.info(f"OCR stage: Low confidence match for store: {merchant_name} -> suggested_chain_id={ocr_suggested_chain_id}, confidence={ocr_confidence_score:.2f}")
            else:
                logger.info(f"OCR stage: Store not found: {merchant_name}, will retry after LLM processing")
    
    # Use OCR match results for prompt (if available)
    chain_id = ocr_chain_id
    location_id = ocr_location_id
    
    # Step 3: Get merchant-specific prompt (only for prompt content, not for model selection)
    logger.info(f"Step 3: Loading prompt for merchant: {merchant_name}")
    # Extract country_code from merchant address if available (for country-specific prompts)
    country_code = None
    if unified_info.get("merchant_address"):
        # Try to extract country from address (simple heuristic)
        address = unified_info.get("merchant_address", "").upper()
        if "CANADA" in address or "BC" in address or "ONTARIO" in address:
            country_code = "CA"
        elif "USA" in address or "US" in address or any(state in address for state in ["CA", "WA", "NY", "TX"]):
            country_code = "US"
    
    prompt_config = get_merchant_prompt(
        merchant_name or "default", 
        merchant_id=chain_id,  # chain_id is passed as merchant_id
        location_id=location_id,
        country_code=country_code
    )
    
    # Step 4: Format prompt (with tag-based RAG support)
    # Extract location info for location-based RAG matching
    location_state = None
    location_country = None
    if location_id:
        # Try to get state and country from location_id
        try:
            from ..database.supabase_client import _get_client
            supabase = _get_client()
            location_response = supabase.table("store_locations").select("state, country_code").eq("id", location_id).limit(1).execute()
            if location_response.data:
                location_state = location_response.data[0].get("state")
                location_country = location_response.data[0].get("country_code")
        except Exception as e:
            logger.warning(f"Failed to get location info for RAG: {e}")
    
    # Also try to extract from unified_info
    if not location_state and unified_info.get("merchant_address"):
        address = unified_info.get("merchant_address", "").upper()
        # Try to extract state from address
        us_states = ["CA", "WA", "NY", "TX", "HI", "FL", "OR", "NV", "AZ", "UT", "CO", "NM"]
        ca_provinces = ["BC", "ON", "QC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"]
        for state in us_states + ca_provinces:
            if state in address:
                location_state = state
                break
        if any(state in address for state in us_states):
            location_country = "US"
        elif any(province in address for province in ca_provinces):
            location_country = "CA"
    
    system_message, user_message, rag_metadata = format_prompt(
        raw_text=raw_text,
        trusted_hints=trusted_hints,
        prompt_config=prompt_config,
        merchant_name=merchant_name,
        store_chain_id=chain_id,
        location_id=location_id,
        state=location_state,
        country_code=location_country,
        initial_parse_result=initial_parse_result  # Pass initial parse result to prompt
    )
    
    # Step 5: Call LLM (read corresponding config from environment variables based on llm_provider)
    logger.info(f"Step 4: Calling {llm_provider.upper()} LLM...")
    if llm_provider.lower() == "gemini":
        # Read Gemini model config from environment variables
        model = settings.gemini_model
        logger.info(f"Using Gemini model from settings: {model}")
        logger.info(f"Settings.gemini_model value: {settings.gemini_model}")
        llm_result = await parse_receipt_with_gemini(
            system_message=system_message,
            user_message=user_message,
            model=model,
            temperature=prompt_config.get("temperature", 0.0)
        )
    else:
        # Default to OpenAI, read OpenAI model config from environment variables
        model = settings.openai_model
        logger.info(f"Using OpenAI model from .env: {model}")
        llm_result = parse_receipt_with_llm(
            system_message=system_message,
            user_message=user_message,
            model=model,
            temperature=prompt_config.get("temperature", 0.0)
        )
    
    # Step 6: Extract prices from raw_text for validation (not dependent on LLM, not dependent on OCR source)
    # Key: This function is already based on raw_text and can be used with any OCR!
    logger.info("Step 5: Extracting prices from raw_text for validation (OCR-agnostic)...")
    line_items = unified_info.get("line_items", [])
    extracted_line_totals = extract_line_totals_from_raw_text(
        raw_text=raw_text,
        unified_line_items=line_items,  # Normalized line_items (from any OCR), use if available; otherwise fallback to regex
        merchant_name=merchant_name,
        chain_id=chain_id  # Pass chain_id for tag-based extraction rules
    )
    
    # Step 7: Backend mathematical validation (unified validation logic, not dependent on OCR)
    logger.info("Step 6: Performing backend mathematical validation...")
    llm_result = _validate_llm_result(llm_result, extracted_line_totals=extracted_line_totals)
    
    # Step 8: Try to match store again using LLM-extracted data (second attempt)
    # LLM may extract more accurate merchant_name and address
    llm_chain_id = chain_id  # Start with OCR match result
    llm_location_id = location_id
    llm_suggested_chain_id = ocr_suggested_chain_id
    llm_suggested_location_id = ocr_suggested_location_id
    llm_confidence_score = ocr_confidence_score
    llm_matched = ocr_matched
    
    # Extract merchant info from LLM result
    llm_merchant_name = None
    llm_merchant_address = None
    if llm_result and "receipt" in llm_result:
        receipt_data = llm_result["receipt"]
        llm_merchant_name = receipt_data.get("merchant_name")
        llm_merchant_address = receipt_data.get("merchant_address")
    
    # If LLM extracted merchant info, try matching again (LLM may be more accurate)
    # Always retry with LLM data if available, even if OCR matched (LLM might have better info)
    if llm_merchant_name:
        llm_store_match = get_store_chain(llm_merchant_name, llm_merchant_address)
        
        if llm_store_match.get("matched"):
            # High confidence match from LLM - use this instead (prefer LLM results)
            llm_chain_id = llm_store_match.get("chain_id")
            llm_location_id = llm_store_match.get("location_id")
            llm_matched = True
            llm_suggested_chain_id = None  # Clear suggestions if matched
            llm_suggested_location_id = None
            llm_confidence_score = llm_store_match.get("confidence_score")
            logger.info(f"LLM stage: Matched store: {llm_merchant_name} -> chain_id={llm_chain_id}, location_id={llm_location_id}")
        else:
            # Not matched in LLM stage - update suggestion info from LLM attempt
            llm_suggested_chain_id = llm_store_match.get("suggested_chain_id")
            llm_suggested_location_id = llm_store_match.get("suggested_location_id")
            llm_confidence_score = llm_store_match.get("confidence_score")
            
            if llm_suggested_chain_id:
                logger.info(f"LLM stage: Low confidence match for store: {llm_merchant_name} -> suggested_chain_id={llm_suggested_chain_id}, confidence={llm_confidence_score:.2f}")
            else:
                logger.info(f"LLM stage: Store not found: {llm_merchant_name}")
    
    # Use LLM match results (prefer LLM results if matched)
    final_chain_id = llm_chain_id
    final_location_id = llm_location_id
    final_merchant_name = llm_merchant_name or merchant_name
    
    # Step 9: Add metadata with final match results and RAG usage
    llm_result["_metadata"] = {
        "merchant_name": final_merchant_name,
        "chain_id": final_chain_id,
        "location_id": final_location_id,
        "ocr_provider": normalized.get("metadata", {}).get("ocr_provider", "unknown"),
        "llm_provider": llm_provider.lower(),
        "entities": normalized.get("entities", {}),
        "validation_status": llm_result.get("_metadata", {}).get("validation_status", "unknown"),
        "rag_metadata": rag_metadata  # Add RAG usage statistics
    }
    
    # Step 10: Create store candidate ONLY if both OCR and LLM failed to match
    if final_merchant_name and not final_chain_id and receipt_id:
        from ..database.supabase_client import create_store_candidate
        try:
            create_store_candidate(
                chain_name=final_merchant_name,
                receipt_id=receipt_id,
                source="llm",
                llm_result=llm_result,
                suggested_chain_id=llm_suggested_chain_id,
                suggested_location_id=llm_suggested_location_id,
                confidence_score=llm_confidence_score
            )
            logger.info(f"Created store candidate for '{final_merchant_name}' (OCR and LLM both failed to match) with receipt_id={receipt_id}, confidence={llm_confidence_score}")
        except Exception as e:
            logger.warning(f"Failed to create store candidate: {e}")
    elif final_chain_id:
        logger.info(f"Store matched successfully (chain_id={final_chain_id}, location_id={final_location_id}), no candidate created")
    
    logger.info(f"Receipt processing completed successfully (OCR: {normalized.get('metadata', {}).get('ocr_provider', 'unknown')}, LLM: {llm_provider})")
    return llm_result


def _extract_trusted_hints(docai_result: Dict[str, Any], confidence_threshold: float = 0.95) -> Dict[str, Any]:
    """
    Extract high-confidence fields from Document AI result.
    
    Args:
        docai_result: Result returned by Document AI
        confidence_threshold: Confidence threshold (default 0.95)
        
    Returns:
        Dictionary of high-confidence fields
    """
    trusted_hints = {}
    entities = docai_result.get("entities", {})
    
    for entity_type, entity_data in entities.items():
        confidence = entity_data.get("confidence")
        value = entity_data.get("value")
        
        if confidence is not None and confidence >= confidence_threshold and value is not None:
            # Map to standard field name
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
    Validate mathematical correctness of LLM returned result.
    
    Validation items:
    1. Each item: If quantity and unit_price both exist, validate quantity × unit_price ≈ line_total
    2. Sum validation: Sum of all items' line_total ≈ receipt.total
    
    TODO: These validation data will be used for:
    - Training data quality assessment
    - Model performance monitoring
    - Auto-correction and completion (use extracted_line_totals to complete missing items)
    - Generate validation reports and statistics
    
    Args:
        llm_result: Complete result returned by LLM
        tolerance: Allowed error range (default 0.01)
        extracted_line_totals: List of prices extracted from raw_text (for comparison validation)
        
    Returns:
        Updated llm_result with validation results
    """
    receipt = llm_result.get("receipt", {})
    items = llm_result.get("items", [])
    tbd = llm_result.get("tbd", {})
    
    # Initialize tbd structure (if not exists)
    if "items_with_inconsistent_price" not in tbd:
        tbd["items_with_inconsistent_price"] = []
    if "total_mismatch" not in tbd:
        tbd["total_mismatch"] = None
    
    validation_errors = []
    calculated_total = 0.0
    
    # Validation 1: Each item's quantity × unit_price ≈ line_total
    for item in items:
        line_total = item.get("line_total")
        quantity = item.get("quantity")
        unit_price = item.get("unit_price")
        
        # If line_total exists, accumulate to total
        if line_total is not None:
            calculated_total += float(line_total)
        
        # If quantity and unit_price both exist, validate calculation
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
    
    # Update items_with_inconsistent_price (merge LLM detected and backend validated)
    existing_errors = {err.get("product_name"): err for err in tbd["items_with_inconsistent_price"]}
    for error in validation_errors:
        product_name = error.get("product_name")
        if product_name not in existing_errors:
            tbd["items_with_inconsistent_price"].append(error)
    
    # Validation 2: Sum validation
    documented_total = receipt.get("total")
    if documented_total is not None:
        documented_total = float(documented_total)
        difference = abs(calculated_total - documented_total)
        
        # If prices extracted from raw_text are provided, also compare
        if extracted_line_totals:
            extracted_total = sum(extracted_line_totals)
            extracted_diff = abs(extracted_total - documented_total)
            
            logger.info(
                f"Price comparison: LLM calculated={calculated_total:.2f}, "
                f"raw_text extracted={extracted_total:.2f}, documented={documented_total:.2f}"
            )
            
            # If raw_text extracted sum is closer to documented_total, LLM may have missed items
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
            
            # Update validation_status
            if "_metadata" not in llm_result:
                llm_result["_metadata"] = {}
            llm_result["_metadata"]["validation_status"] = "needs_review"
            
            logger.warning(
                f"Total mismatch detected: calculated={calculated_total:.2f}, "
                f"documented={documented_total:.2f}, diff={difference:.2f}"
            )
        else:
            # Validation passed, clear any existing error markers
            if tbd.get("total_mismatch"):
                tbd["total_mismatch"] = None
            
            # If no other errors, mark as passed
            if not validation_errors and not tbd.get("items_with_inconsistent_price"):
                if "_metadata" not in llm_result:
                    llm_result["_metadata"] = {}
                llm_result["_metadata"]["validation_status"] = "pass"
    
    # Update tbd
    llm_result["tbd"] = tbd
    
    # Record validation statistics
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
    unified_line_items: Optional[List[Dict[str, Any]]] = None,
    merchant_name: Optional[str] = None,
    chain_id: Optional[str] = None
) -> List[float]:
    """
    Extract all items' line_total from raw_text, not dependent on LLM.
    
    Strategy (by priority):
    1. Prefer using normalized line_items (if available and high confidence)
    2. Use regex to match various price patterns
    3. Filter out non-item prices (total, tax, subtotal, etc.) through context
    
    TODO: These extracted data will be used for:
    - Compare and validate with LLM results
    - Auto-complete missing items
    - Training data quality assessment
    - Generate validation reports
    
    Args:
        raw_text: Original receipt text
        unified_line_items: Normalized line_items (from any OCR, optional)
        merchant_name: Merchant name (can be used for format optimization)
        
    Returns:
        List of all items' line_total
    """
    line_totals = []
    
    # Strategy 1: Prefer using normalized line_items
    if unified_line_items:
        for item in unified_line_items:
            line_total = item.get("line_total")
            if line_total is not None:
                try:
                    line_totals.append(float(line_total))
                except (ValueError, TypeError):
                    continue
    
    # If normalized line_items extracted enough, return directly
    if len(line_totals) >= 3:  # At least 3 items to be considered reliable
        logger.info(f"Using unified line_items: found {len(line_totals)} items")
        return line_totals
    
    # Strategy 2: Extract from raw_text using regex (with merchant-specific rules)
    logger.info("Falling back to regex extraction from raw_text with merchant-specific rules")
    
    # Get merchant-specific extraction rules (similar to RAG)
    # Note: chain_id might be None if store wasn't matched, that's okay
    extraction_rules = get_merchant_extraction_rules(
        merchant_name=merchant_name,
        merchant_id=chain_id,
        raw_text=raw_text
    )
    
    # Apply rules to extract prices
    line_totals = apply_extraction_rules(raw_text, extraction_rules)
    
    return line_totals


def _extract_prices_with_regex(raw_text: str, merchant_name: Optional[str] = None) -> List[float]:
    """
    Extract item prices from raw_text using regex.
    
    Supports multiple formats:
    - T&T: "FP $X.XX" (single or multi-line)
    - Generic: "$X.XX"
    - Unsigned: "X.XX" (in item line)
    - Weight items: "X.XX lb @ $X.XX/lb FP $X.XX" (take the last one)
    
    Filter rules:
    - Exclude obvious total lines (TOTAL, Subtotal, Tax)
    - Exclude payment information (Visa, Reference#)
    - Exclude address, phone, etc.
    - Exclude category identifier lines (GROCERY, PRODUCE, DELI when alone on a line)
    
    Note: In T&T receipts, items may span multiple lines:
    - Item name on one line
    - Quantity/unit price on one line (optional)
    - "FP $X.XX" on one line
    We prioritize matching "FP $X.XX" format as it's most reliable.
    """
    # First match all "FP $X.XX" format in entire text (most reliable)
    fp_prices = []
    fp_matches = re.finditer(r'FP\s+\$(\d+\.\d{2})', raw_text, re.IGNORECASE)
    for match in fp_matches:
        price = float(match.group(1))
        fp_prices.append(price)
    
    # If found enough FP prices (at least 3), use directly
    if len(fp_prices) >= 3:
        logger.info(f"Found {len(fp_prices)} FP prices, using them directly")
        return fp_prices
    
    # Otherwise, analyze line by line (fallback)
    lines = raw_text.split('\n')
    prices = []
    
    # Define patterns to skip
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
        r'^\d{2}/\d{2}/\d{2}',  # Date
        r'^\*{3,}',  # Membership number, etc.
        r'^Not A Member',
        r'^立即下載',  # Chinese text: "Download Now"
        r'^Get Exclusive',
        r'^Enjoy Online',
        r'^GROCERY$',  # Standalone category identifier line
        r'^PRODUCE$',
        r'^DELI$',
        r'^FOOD$',
    ]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Skip obvious non-item lines
        should_skip = False
        for pattern in skip_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                should_skip = True
                break
        
        if should_skip:
            continue
        
        # Try to match price
        line_price = None
        
        # Prioritize matching FP format (T&T)
        fp_match = re.search(r'FP\s+\$(\d+\.\d{2})', line, re.IGNORECASE)
        if fp_match:
            line_price = float(fp_match.group(1))
        else:
            # Match generic $X.XX format
            dollar_matches = list(re.finditer(r'\$(\d+\.\d{2})', line))
            if dollar_matches:
                # If multiple prices, take the last one (usually line total)
                line_price = float(dollar_matches[-1].group(1))
            else:
                # Try to match unsigned price (but needs more context judgment)
                # Only match lines that look like item lines (contain letters and numbers)
                if re.search(r'[A-Za-z]', line):  # Contains letters, might be item name
                    plain_matches = list(re.finditer(r'\b(\d+\.\d{2})\b', line))
                    if plain_matches:
                        # Take the last one, but need to validate range (item prices usually 0.01 - 999.99)
                        candidate = float(plain_matches[-1].group(1))
                        if 0.01 <= candidate <= 999.99:
                            line_price = candidate
        
        if line_price is not None:
            prices.append(line_price)
    
    # Merge FP prices and other prices, deduplicate
    all_prices = fp_prices + prices
    unique_prices = []
    seen = set()
    for price in all_prices:
        # Use rounding to cents for deduplication
        rounded = round(price, 2)
        if rounded not in seen:
            seen.add(rounded)
            unique_prices.append(price)
    
    logger.info(f"Extracted {len(unique_prices)} prices from raw_text using regex (FP: {len(fp_prices)}, other: {len(prices)})")
    return unique_prices


def _map_entity_to_standard_field(entity_type: str) -> Optional[str]:
    """
    Map Document AI's entity_type to standard field names.
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
