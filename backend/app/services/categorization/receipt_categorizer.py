"""
Receipt Categorizer

主要功能：
1. 读取 receipt_processing_runs.output_payload
2. 标准化商品名、品牌、分类
3. 更新 catalog (products, brands, categories)
4. 保存到 receipt_items, receipt_summaries

匹配逻辑（全部在后端）：
1. Exact：查 product_categorization_rules 表，normalized_name 精确匹配（store-specific 优先）
2. 未命中：用后端维护的 universal 规则表（与 initial_categorization_rules.csv 同源）做 fuzzy match
3. 仍未命中：LLM 建议（若有）
"""
import csv
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

import re
from ..database.supabase_client import (
    _get_client,
    build_merchant_address_from_structured,
    get_store_chain,
    save_receipt_summary,
    update_receipt_summary,
    save_receipt_items,
    enqueue_unmatched_items_to_classification_review,
    _store_name_to_title_case,
    create_store_candidate,
)
from ..standardization.product_normalizer import normalize_name_for_storage

logger = logging.getLogger(__name__)

# UUID v4 pattern (8-4-4-4-12 hex)
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Fuzzy match threshold for backend universal rules (0-100 for rapidfuzz)
_UNIVERSAL_FUZZY_THRESHOLD = 90


def _resolve_store_chain_id_uuid(
    receipt_id: str,
    metadata_chain_id: Optional[str],
    merchant_name: Optional[str],
    merchant_address: Optional[str],
) -> Optional[str]:
    """
    Resolve store_chain_id as UUID for product_categorization_rules lookup.
    metadata.chain_id may be a string tag (e.g. "Trader_Joes") but rules use store_chains.id (UUID).
    """
    supabase = _get_client()
    # 1) If metadata chain_id is already a UUID, use it
    if metadata_chain_id and _UUID_RE.match(str(metadata_chain_id).strip()):
        return str(metadata_chain_id).strip()
    # 2) Prefer existing record_summaries.store_chain_id for this receipt (so re-categorize uses same chain)
    try:
        summary = (
            supabase.table("record_summaries")
            .select("store_chain_id")
            .eq("receipt_id", receipt_id)
            .limit(1)
            .execute()
        )
        if summary.data and summary.data[0].get("store_chain_id"):
            return str(summary.data[0]["store_chain_id"])
    except Exception as e:
        logger.debug(f"Could not read record_summaries for store_chain_id: {e}")
    # 3) Resolve by merchant name + address (same logic as save_receipt_summary)
    if merchant_name:
        try:
            match_result = get_store_chain(merchant_name, merchant_address)
            if match_result.get("matched") and match_result.get("chain_id"):
                return str(match_result["chain_id"])
        except Exception as e:
            logger.debug(f"get_store_chain failed: {e}")
        try:
            chain_row = supabase.table("store_chains").select("id").eq("name", merchant_name).limit(1).execute()
            if chain_row.data and chain_row.data[0].get("id"):
                return str(chain_row.data[0]["id"])
            chains = supabase.table("store_chains").select("id, name").execute()
            if chains.data:
                merchant_lower = (merchant_name or "").lower()
                for c in chains.data:
                    if (c.get("name") or "").lower() == merchant_lower:
                        return str(c["id"])
        except Exception as e:
            logger.debug(f"store_chains lookup failed: {e}")
    return None


# Backend-held universal rules (same effect as initial_categorization_rules.csv), cached
_UNIVERSAL_RULES_CACHE: Optional[List[Dict[str, Any]]] = None


def _get_initial_rules_csv_path() -> Path:
    """Path to backend/data/initial_categorization_rules.csv."""
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent
    return backend_dir / "data" / "initial_categorization_rules.csv"


def _load_universal_rules_for_fuzzy() -> List[Dict[str, Any]]:
    """
    Load universal rules from initial_categorization_rules.csv (store_chain_name = NULL).
    Used for fuzzy match layer. Returns list of {normalized_name, category_path, priority}.
    """
    global _UNIVERSAL_RULES_CACHE
    if _UNIVERSAL_RULES_CACHE is not None:
        return _UNIVERSAL_RULES_CACHE
    path = _get_initial_rules_csv_path()
    if not path.exists():
        logger.warning(f"Initial rules CSV not found: {path}")
        _UNIVERSAL_RULES_CACHE = []
        return _UNIVERSAL_RULES_CACHE
    rules = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(row for row in f if not row.strip().startswith("#"))
            for row in reader:
                store_name = (row.get("store_chain_name") or "").strip()
                if store_name.upper() != "NULL" and store_name:
                    continue
                nn = (row.get("normalized_name") or "").strip().lower()
                if not nn:
                    continue
                cat_path = (row.get("category_path") or "").strip()
                if not cat_path:
                    continue
                try:
                    priority = int(row.get("priority") or 200)
                except (TypeError, ValueError):
                    priority = 200
                rules.append({"normalized_name": nn, "category_path": cat_path, "priority": priority})
        rules.sort(key=lambda r: (r["priority"], r["normalized_name"]))
        _UNIVERSAL_RULES_CACHE = rules
        logger.debug(f"Loaded {len(rules)} universal rules for fuzzy from {path}")
    except Exception as e:
        logger.warning(f"Failed to load initial rules CSV {path}: {e}")
        _UNIVERSAL_RULES_CACHE = []
    return _UNIVERSAL_RULES_CACHE


def _resolve_category_id_by_path(supabase: Any, category_path: str) -> Optional[str]:
    """Resolve category_path (e.g. Grocery/Dairy/Milk) to category id. DB path is lowercase."""
    if not category_path or not category_path.strip():
        return None
    path_lower = category_path.strip().lower()
    try:
        r = supabase.table("categories").select("id").eq("path", path_lower).limit(1).execute()
        if r.data and r.data[0].get("id"):
            return str(r.data[0]["id"])
    except Exception:
        pass
    return None


def _match_exact_from_db(
    supabase: Any,
    normalized_name: str,
    store_chain_id: Optional[str],
) -> Optional[str]:
    """
    Exact match only: query product_categorization_rules where normalized_name equals
    the given name. Prefer store-specific (store_chain_id set) over universal. Returns category_id or None.
    """
    name_clean = (normalized_name or "").strip().lower()
    if not name_clean:
        return None
    try:
        # Store-specific first
        if store_chain_id:
            r = (
                supabase.table("product_categorization_rules")
                .select("category_id")
                .eq("normalized_name", name_clean)
                .eq("store_chain_id", store_chain_id)
                .limit(1)
                .execute()
            )
            if r.data and r.data[0].get("category_id"):
                return str(r.data[0]["category_id"])
        # Universal
        r = (
            supabase.table("product_categorization_rules")
            .select("category_id")
            .eq("normalized_name", name_clean)
            .is_("store_chain_id", "null")
            .limit(1)
            .execute()
        )
        if r.data and r.data[0].get("category_id"):
            return str(r.data[0]["category_id"])
    except Exception as e:
        logger.debug(f"Exact rule lookup for '{name_clean}': {e}")
    return None


def _match_universal_fuzzy(
    normalized_product: str,
    path_to_id: Dict[str, str],
    supabase: Any,
) -> Optional[str]:
    """
    Match against backend-held universal rules (CSV): 1) contains (rule name in product), longest wins;
    2) else best fuzzy score >= threshold. Returns category_id or None.
    """
    product_lower = normalized_product.lower()
    universal = _load_universal_rules_for_fuzzy()
    if not universal:
        return None
    # 1) Contains: rule normalized_name in product name, prefer longest match
    best_contains: Optional[Tuple[int, str]] = None
    for r in universal:
        rn = r["normalized_name"]
        if len(rn) < 2:
            continue
        if rn in product_lower:
            if best_contains is None or len(rn) > best_contains[0]:
                best_contains = (len(rn), r["category_path"])
    if best_contains:
        path = best_contains[1]
        cid = path_to_id.get(path)
        if not cid and supabase:
            cid = _resolve_category_id_by_path(supabase, path)
            if cid:
                path_to_id[path] = cid
        if cid:
            return cid
    # 2) Fuzzy best match
    try:
        from rapidfuzz import fuzz, process
        best = process.extractOne(
            product_lower,
            [r["normalized_name"] for r in universal],
            scorer=fuzz.ratio,
            score_cutoff=_UNIVERSAL_FUZZY_THRESHOLD,
        )
        if best:
            rule_name, score, _ = best
            for r in universal:
                if r["normalized_name"] == rule_name:
                    path = r["category_path"]
                    cid = path_to_id.get(path)
                    if not cid and supabase:
                        cid = _resolve_category_id_by_path(supabase, path)
                        if cid:
                            path_to_id[path] = cid
                    return cid
    except ImportError:
        pass
    return None


def _match_fuzzy_same_store(
    supabase: Any,
    normalized_name: str,
    store_chain_id: Optional[str],
) -> Optional[str]:
    """
    Fuzzy match (1–2 letter tolerance) against product_categorization_rules for the same store.
    Used when exact match fails. Threshold tuned so 1–2 char diff still matches.
    """
    if not store_chain_id or not normalized_name or len(normalized_name) < 2:
        return None
    try:
        rules = (
            supabase.table("product_categorization_rules")
            .select("normalized_name, category_id")
            .eq("store_chain_id", store_chain_id)
            .execute()
        )
    except Exception as e:
        logger.debug("Fuzzy same-store rules lookup failed: %s", e)
        return None
    if not rules.data:
        return None
    try:
        from rapidfuzz import fuzz, process
        names = [r["normalized_name"] for r in rules.data if r.get("normalized_name")]
        if not names:
            return None
        best = process.extractOne(
            normalized_name.lower(),
            names,
            scorer=fuzz.ratio,
            score_cutoff=85,
        )
        if best:
            matched_name, score, _ = best
            for r in rules.data:
                if r.get("normalized_name") == matched_name and r.get("category_id"):
                    return str(r["category_id"])
    except ImportError:
        pass
    return None


def get_category_id_for_product(
    normalized_name: str, store_chain_id: Optional[str]
) -> Tuple[Optional[str], str]:
    """
    Backend-only matching: 1) exact from product_categorization_rules (store-specific first),
    2) fuzzy same-store (1–2 letter diff) from product_categorization_rules,
    3) universal fuzzy from backend-held rules (CSV).
    Returns (category_id, source) where source is 'rule_exact', 'rule_fuzzy', or '' (no match).
    """
    supabase = _get_client()
    normalized_underscore = (normalized_name or "").strip().replace(" ", "_")
    normalized = (normalized_name or "").strip()
    if not normalized:
        return None, ""
    for name_to_try in (normalized_underscore, normalized):
        cid = _match_exact_from_db(supabase, name_to_try, store_chain_id)
        if cid:
            return cid, "rule_exact"
    cid = _match_fuzzy_same_store(supabase, normalized, store_chain_id)
    if cid:
        return cid, "rule_fuzzy"
    cid = _match_fuzzy_same_store(supabase, normalized_underscore, store_chain_id)
    if cid:
        return cid, "rule_fuzzy"
    path_to_id: Dict[str, str] = {}
    cid = _match_universal_fuzzy(normalized, path_to_id, supabase)
    if cid:
        return cid, "rule_fuzzy"
    if normalized != normalized_underscore:
        cid = _match_universal_fuzzy(normalized_underscore, path_to_id, supabase)
    return (cid, "rule_fuzzy") if cid else (None, "")


def _enrich_items_category_from_rules(
    items_data: List[Dict[str, Any]],
    store_chain_id: Optional[str],
) -> None:
    """
    1. Exact: lookup product_categorization_rules (normalized_name exact match), store-specific first.
    2. Unmatched: fuzzy match against backend universal rules (initial_categorization_rules.csv).
    3. Still unmatched: left for LLM (called separately). Mutates items_data in place.
    """
    if not items_data:
        return
    for item in items_data:
        if item.get("category_id"):
            continue
        product_name = item.get("product_name") or item.get("original_product_name")
        if not product_name or not isinstance(product_name, str):
            continue
        normalized = normalize_name_for_storage(product_name.strip())
        if not normalized:
            continue
        try:
            cid, source = get_category_id_for_product(normalized, store_chain_id)
            if cid and source:
                item["category_id"] = cid
                item["_category_source"] = source
                logger.debug(f"Rule match for '{product_name}' -> {cid} (source={source})")
        except Exception as e:
            logger.debug(f"Rule lookup for '{product_name}': {e}")


async def _enrich_items_category_from_llm(
    items_data: List[Dict[str, Any]],
    store_chain_name: Optional[str],
) -> None:
    """
    For items still without category_id, call LLM to suggest category and set item['category_id']
    when the suggested path resolves to an existing level-3 category. Mutates items_data in place.
    Must be awaited when called from async context (e.g. smart-categorize API). When called from sync
    context in a worker thread (e.g. categorize_receipt via asyncio.to_thread), use _enrich_items_category_from_llm_sync.
    """
    still_unmatched = [
        (i, it) for i, it in enumerate(items_data)
        if not it.get("category_id") and (it.get("product_name") or it.get("original_product_name"))
    ]
    if not still_unmatched:
        return
    names = [
        (it.get("product_name") or it.get("original_product_name") or "").strip()
        for _, it in still_unmatched
    ]
    try:
        from ..admin.classification_llm import suggest_classifications
        suggestions = await suggest_classifications(names, store_chain_name)
    except Exception as e:
        logger.warning(f"LLM category suggestion failed: %s", e)
        return
    by_name: Dict[str, Dict[str, Any]] = {s["raw_product_name"].strip(): s for s in suggestions if s.get("raw_product_name")}
    for idx, item in still_unmatched:
        name = (item.get("product_name") or item.get("original_product_name") or "").strip()
        sug = by_name.get(name)
        if sug and sug.get("category_id"):
            items_data[idx]["category_id"] = str(sug["category_id"])
            items_data[idx]["_category_source"] = "llm"
            logger.debug(f"LLM suggested category for '%s' -> category_id %s", name, items_data[idx]["category_id"])


def _enrich_items_category_from_llm_sync(
    items_data: List[Dict[str, Any]],
    store_chain_name: Optional[str],
) -> None:
    """
    Sync wrapper for _enrich_items_category_from_llm. Use from sync code that runs in a thread
    (e.g. categorize_receipt via asyncio.to_thread), where asyncio.run() is safe (no running loop).
    """
    import asyncio
    asyncio.run(_enrich_items_category_from_llm(items_data, store_chain_name))


def _ensure_dict(value: Any) -> Dict[str, Any]:
    """Ensure value is a dict; if it's a JSON string, parse it. Otherwise return {}."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value) if value.strip() else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _single_row(data: Any) -> Optional[Dict[str, Any]]:
    """Normalize Supabase .data: single row as dict or list of one -> dict."""
    if data is None:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and len(data) == 1:
        return data[0] if isinstance(data[0], dict) else None
    return None


def _cents_to_dollars(val: Any) -> Any:
    """Convert amount from cents (integer) to dollars (float). LLM and store pipelines both output cents."""
    if val is None:
        return None
    try:
        return round(int(val) / 100.0, 2)
    except (TypeError, ValueError):
        return val


def _payload_already_in_dollars(receipt_data: Dict[str, Any], items_data: List[Dict[str, Any]]) -> bool:
    """
    Detect if amounts are already in dollars (e.g. 12.04, 5.85) to avoid x100 error.
    Contract: pipeline should output cents (1204, 585); some LLM/store outputs dollars (12.04, 5.85).
    Heuristic: total >= 1000 -> cents; total < 100 -> dollars; 100 <= total < 1000 and has decimal -> dollars.
    """
    total = receipt_data.get("total")
    if total is None:
        # Fallback: check max line_total
        amounts = [it.get("line_total") for it in (items_data or []) if it.get("line_total") is not None]
        if not amounts:
            return False
        total = max(amounts) if amounts else None
    if total is None:
        return False
    try:
        t = float(total)
    except (TypeError, ValueError):
        return False
    if t >= 1000:
        return False  # 1204 -> cents
    if t < 100:
        return True  # 12.04, 50 -> dollars
    # 100 <= t < 1000: integer like 199 -> cents ($1.99); with decimal 199.99 -> dollars
    if t != int(round(t)):
        return True  # has decimal part -> dollars
    return False


def _is_quantity_x100(val: Any) -> bool:
    """True if value looks like quantity stored as x100 (e.g. 100 = 1.0, 200 = 2.0)."""
    if val is None:
        return False
    try:
        v = int(val)
        return 100 <= v <= 10000 and v % 10 == 0
    except (TypeError, ValueError):
        return False


def _normalize_amount_to_dollars(val: Any, from_cents: bool) -> Any:
    """Convert to dollars: if from_cents then /100 and round(2); else round(2)."""
    if val is None:
        return None
    try:
        f = float(val)
        if from_cents:
            return round(f / 100.0, 2)
        return round(f, 2)
    except (TypeError, ValueError):
        return val


def _normalize_output_payload_to_dollars(
    receipt_data: Dict[str, Any],
    items_data: List[Dict[str, Any]],
    transaction_info: Optional[Dict[str, Any]] = None,
    merchant_phone_top: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Normalize amounts to dollars. Pipeline contract is cents; some outputs are already dollars (x100 error).
    When payload is already in dollars we only round; otherwise convert cents -> dollars.
    """
    receipt = dict(receipt_data)
    # Merge cashier, purchase_time, (and merchant_phone below) from transaction_info / top-level (e.g. Trader Joe's)
    if transaction_info:
        if receipt.get("cashier") is None and transaction_info.get("cashier"):
            receipt["cashier"] = transaction_info.get("cashier")
        if receipt.get("purchase_time") is None and transaction_info.get("datetime"):
            dt = transaction_info.get("datetime")
            if isinstance(dt, str) and " " in dt:
                receipt["purchase_time"] = dt.split(" ", 1)[1].strip()
            elif dt:
                receipt["purchase_time"] = dt
    if merchant_phone_top and receipt.get("merchant_phone") is None:
        receipt["merchant_phone"] = merchant_phone_top

    already_dollars = _payload_already_in_dollars(receipt, items_data or [])
    for key in ("subtotal", "tax", "total"):
        v = receipt.get(key)
        if v is not None:
            receipt[key] = _normalize_amount_to_dollars(v, from_cents=not already_dollars)
    fees = receipt.get("fees")
    if isinstance(fees, list):
        receipt["fees"] = [_normalize_amount_to_dollars(x, not already_dollars) for x in fees]
    elif fees is not None:
        receipt["fees"] = _normalize_amount_to_dollars(fees, not already_dollars)

    items = []
    for it in items_data or []:
        item = dict(it)
        # 部分 vision/LLM 输出用 amount 表示行金额，统一当作 line_total 参与后续归一化
        if item.get("line_total") is None and item.get("amount") is not None:
            item["line_total"] = item["amount"]
        for key in ("line_total", "unit_price", "original_price", "discount_amount"):
            v = item.get(key)
            if v is not None:
                item[key] = _normalize_amount_to_dollars(v, from_cents=not already_dollars)
        q = item.get("quantity")
        if already_dollars:
            if q is not None:
                try:
                    item["quantity"] = round(float(q), 2)
                except (TypeError, ValueError):
                    item["quantity"] = q
        elif _is_quantity_x100(q):
            item["quantity"] = int(q) / 100.0
        items.append(item)
    return receipt, items


async def smart_categorize_receipt_items(
    receipt_id: str,
    user_id: str,
    item_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    For this receipt, run rules + LLM to suggest category and update record_items.
    - If item_ids is provided (non-empty): fetch only those items and re-run on them (overwrite category).
    - Otherwise: only items with no category_id (unchanged behavior). Returns { "success", "updated_count", "message" }.
    """
    supabase = _get_client()
    rec = (
        supabase.table("receipt_status")
        .select("id")
        .eq("id", receipt_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not rec.data:
        return {"success": False, "updated_count": 0, "message": "Receipt not found or access denied"}

    summary = (
        supabase.table("record_summaries")
        .select("store_chain_id, store_name")
        .eq("receipt_id", receipt_id)
        .limit(1)
        .execute()
    )
    store_chain_id_uuid = None
    store_name = None
    if summary.data:
        store_chain_id_uuid = summary.data[0].get("store_chain_id")
        store_name = summary.data[0].get("store_name")

    if store_chain_id_uuid is None and store_name:
        store_chain_id_uuid = _resolve_store_chain_id_uuid(
            receipt_id, None, store_name, None
        )

    if item_ids:
        items_rows = (
            supabase.table("record_items")
            .select("id, product_name, quantity, unit, unit_price, line_total, on_sale, original_price, discount_amount")
            .eq("receipt_id", receipt_id)
            .in_("id", item_ids)
            .order("item_index")
            .execute()
        )
    else:
        items_rows = (
            supabase.table("record_items")
            .select("id, product_name, quantity, unit, unit_price, line_total, on_sale, original_price, discount_amount")
            .eq("receipt_id", receipt_id)
            .is_("category_id", "null")
            .order("item_index")
            .execute()
        )
    if not items_rows.data:
        return {"success": True, "updated_count": 0, "message": "No items to categorize" if item_ids else "No uncategorized items"}

    items_data = []
    for row in items_rows.data:
        items_data.append({
            "id": row.get("id"),
            "product_name": row.get("product_name") or "",
            "original_product_name": row.get("product_name") or "",
            "quantity": row.get("quantity"),
            "unit": row.get("unit"),
            "unit_price": row.get("unit_price"),
            "line_total": row.get("line_total"),
            "on_sale": row.get("on_sale"),
            "original_price": row.get("original_price"),
            "discount_amount": row.get("discount_amount"),
            "category_id": None,
        })

    _enrich_items_category_from_rules(items_data, store_chain_id_uuid)
    await _enrich_items_category_from_llm(items_data, store_name)

    updated = 0
    for it in items_data:
        cid = it.get("category_id")
        if not cid or not it.get("id"):
            continue
        source = (it.get("_category_source") or "").strip()
        if source not in ("rule_exact", "rule_fuzzy", "llm", "user_override", "crowd_assigned"):
            source = ""
        payload: Dict[str, Any] = {"category_id": str(cid)}
        if source:
            payload["category_source"] = source
        try:
            supabase.table("record_items").update(payload).eq("id", it["id"]).eq("receipt_id", receipt_id).execute()
            updated += 1
        except Exception as e:
            logger.warning(f"Failed to update record_item {it.get('id')}: {e}")

    logger.info(f"Smart categorize receipt {receipt_id}: updated {updated} items")
    return {"success": True, "updated_count": updated, "message": f"Updated {updated} item(s)"}


def can_categorize_receipt(receipt_id: str) -> Tuple[bool, str]:
    """
    检查小票是否可以被 categorize
    
    条件：
    1. Receipt 必须存在
    2. Current_status 为 'success' 或 'needs_review'（needs_review 时也写入解析结果，供前端人工复核页展示/编辑）
    3. 必须有 receipt_processing_runs 记录：vision_b 用 stage in (vision_primary, vision_escalation)；否则 stage=llm
    4. output_payload 必须有效
    
    Returns:
        (可以 categorize, 原因)
    """
    supabase = _get_client()
    
    try:
        # 检查 receipt 状态（pipeline_version 来自 migration 048，若无则视为 legacy_a）
        try:
            receipt = supabase.table("receipt_status")\
                .select("id, user_id, current_status, current_stage, pipeline_version")\
                .eq("id", receipt_id)\
                .single()\
                .execute()
        except Exception as sel_err:
            logger.info(f"[CAT_DEBUG] can_categorize receipt {receipt_id}: select receipt_status failed (pipeline_version column missing?): {sel_err}")
            receipt = supabase.table("receipt_status")\
                .select("id, user_id, current_status, current_stage")\
                .eq("id", receipt_id)\
                .single()\
                .execute()
        
        receipt_data = _single_row(receipt.data)
        if not receipt_data:
            logger.info(f"[CAT_DEBUG] can_categorize receipt {receipt_id}: receipt not found")
            return False, f"Receipt {receipt_id} not found"
        
        # success：通过 sum check；needs_review：未通过但需把解析结果写入 DB 供前端编辑
        status = receipt_data.get("current_status")
        pipeline = (receipt_data.get("pipeline_version") or "legacy_a")
        logger.info(f"[CAT_DEBUG] can_categorize receipt {receipt_id}: current_status={status!r}, pipeline_version={pipeline!r}")
        if status not in ("success", "needs_review"):
            return False, f"Receipt status is '{status}', must be 'success' or 'needs_review'"
        
        # 根据 pipeline 选择 run：vision_b 用 vision_primary/vision_store_specific/vision_escalation，否则用 llm
        if pipeline == "vision_b":
            runs = supabase.table("receipt_processing_runs")\
                .select("id, stage, status, output_payload")\
                .eq("receipt_id", receipt_id)\
                .in_("stage", ["vision_primary", "vision_store_specific", "vision_escalation"])\
                .eq("status", "pass")\
                .order("created_at", desc=True)\
                .limit(1)\
                .execute()
        else:
            runs = supabase.table("receipt_processing_runs")\
                .select("id, stage, status, output_payload")\
                .eq("receipt_id", receipt_id)\
                .eq("stage", "llm")\
                .eq("status", "pass")\
                .order("created_at", desc=True)\
                .limit(1)\
                .execute()
        
        if not runs.data:
            logger.info(f"[CAT_DEBUG] can_categorize receipt {receipt_id}: no run found (pipeline={pipeline}, looked for {'vision_primary/vision_store_specific/vision_escalation' if pipeline == 'vision_b' else 'llm'})")
            return False, f"No successful {'vision' if pipeline == 'vision_b' else 'LLM'} processing run found"
        
        run_data = runs.data[0] if isinstance(runs.data, list) else runs.data
        run_stage = run_data.get("stage") if isinstance(run_data, dict) else None
        logger.info(f"[CAT_DEBUG] can_categorize receipt {receipt_id}: found run stage={run_stage!r}")
        output_payload = _ensure_dict(run_data.get("output_payload") if isinstance(run_data, dict) else None)
        
        if not output_payload:
            return False, "output_payload is empty"
        
        # 检查必需字段
        if "receipt" not in output_payload or "items" not in output_payload:
            return False, "output_payload missing 'receipt' or 'items' fields"
        
        return True, "OK"
        
    except Exception as e:
        logger.error(f"Error checking receipt {receipt_id}: {e}", exc_info=True)
        return False, f"Error: {str(e)}"


def categorize_receipt(receipt_id: str, force: bool = False) -> Dict[str, Any]:
    """
    对小票进行分类和标准化
    
    Args:
        receipt_id: Receipt ID (UUID string)
        force: 如果为 True，即使已经 categorize 过也重新处理
        
    Returns:
        {
            "success": bool,
            "receipt_id": str,
            "summary_id": str or None,
            "items_count": int,
            "message": str
        }
    """
    logger.info(f"Starting categorization for receipt {receipt_id} (force={force})")
    
    supabase = _get_client()
    
    # 1. 检查是否可以 categorize
    can_categorize, reason = can_categorize_receipt(receipt_id)
    logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: can_categorize={can_categorize}, reason={reason!r}")
    if not can_categorize:
        logger.warning(f"Cannot categorize receipt {receipt_id}: {reason}")
        return {
            "success": False,
            "receipt_id": receipt_id,
            "message": f"Cannot categorize: {reason}"
        }
    
    # 2. 检查是否已经完整 categorize 过（既有 summary 又有 record_items）
    #    若仅有 summary 无 record_items（例如之前写入 summary 后 items 失败/回滚失败），则继续补写 items
    if not force:
        existing_summary = supabase.table("record_summaries")\
            .select("id")\
            .eq("receipt_id", receipt_id)\
            .execute()
        existing_items = supabase.table("record_items")\
            .select("id")\
            .eq("receipt_id", receipt_id)\
            .limit(1)\
            .execute()
        has_summary = bool(existing_summary.data)
        has_items = bool(existing_items.data)
        if has_summary and has_items:
            logger.info(f"Receipt {receipt_id} already categorized (summary + items present)")
            return {
                "success": True,
                "receipt_id": receipt_id,
                "message": "Already categorized (use force=true to re-categorize)"
            }
        if has_summary and not has_items:
            logger.info(f"Receipt {receipt_id} has summary but no record_items; will backfill items from run")
    
    # 3. 读取 receipt 和 processing run（vision_b 用 vision_primary/vision_escalation，否则用 llm）
    try:
        receipt = supabase.table("receipt_status")\
            .select("id, user_id, pipeline_version")\
            .eq("id", receipt_id)\
            .single()\
            .execute()
    except Exception as sel_err:
        logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: select with pipeline_version failed: {sel_err}, retrying without")
        receipt = supabase.table("receipt_status")\
            .select("id, user_id")\
            .eq("id", receipt_id)\
            .single()\
            .execute()
    
    receipt_row = _single_row(receipt.data)
    if not receipt_row:
        return {"success": False, "receipt_id": receipt_id, "message": "Receipt not found"}
    user_id = receipt_row.get("user_id")
    pipeline = receipt_row.get("pipeline_version")
    # When pipeline_version was missing (e.g. retry after "Server disconnected"), avoid defaulting to legacy_a:
    # try vision_b run first, then fall back to llm so we don't mis-use the wrong run.
    if not pipeline:
        _vision_run = supabase.table("receipt_processing_runs")\
            .select("id")\
            .eq("receipt_id", receipt_id)\
            .in_("stage", ["vision_primary", "vision_store_specific", "vision_escalation"])\
            .eq("status", "pass")\
            .limit(1)\
            .execute()
        pipeline = "vision_b" if (_vision_run.data and len(_vision_run.data) > 0) else "legacy_a"
        logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: pipeline_version missing, inferred pipeline={pipeline!r}")
    else:
        pipeline = pipeline or "legacy_a"
    logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: pipeline={pipeline!r}, querying run...")

    if pipeline == "vision_b":
        run = supabase.table("receipt_processing_runs")\
            .select("output_payload")\
            .eq("receipt_id", receipt_id)\
            .in_("stage", ["vision_primary", "vision_store_specific", "vision_escalation"])\
            .eq("status", "pass")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()
    else:
        run = supabase.table("receipt_processing_runs")\
            .select("output_payload")\
            .eq("receipt_id", receipt_id)\
            .eq("stage", "llm")\
            .eq("status", "pass")\
            .order("created_at", desc=True)\
            .limit(1)\
            .execute()

    if not run.data:
        logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: no run data (pipeline={pipeline})")
        return {"success": False, "receipt_id": receipt_id, "message": "No processing run found"}
    run_row = run.data[0] if isinstance(run.data, list) else run.data
    output_payload = _ensure_dict(run_row.get("output_payload") if isinstance(run_row, dict) else None)
    n_items = len(output_payload.get("items") or []) if output_payload else 0
    logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: got output_payload, items={n_items}")
    transaction_info = output_payload.get("transaction_info") or {}
    receipt_data, items_data = _normalize_output_payload_to_dollars(
        output_payload.get("receipt", {}),
        output_payload.get("items", []),
        transaction_info=transaction_info,
        merchant_phone_top=output_payload.get("merchant_phone"),
    )
    # Prefer address built from structured fields (address_line1, address_line2, city, state, zip_code) so DB gets correct split
    built_addr = build_merchant_address_from_structured(receipt_data)
    if built_addr:
        receipt_data["merchant_address"] = built_addr
    # 店名统一为首字母大写；若 receipt 里无店名则用 _metadata.merchant_name（LLM 阶段必有），保证 record_summaries 有店名、列表不显示 Unknown store
    if not (receipt_data.get("merchant_name") or "").strip():
        receipt_data["merchant_name"] = (output_payload.get("_metadata", {}) or {}).get("merchant_name") or ""
    if receipt_data.get("merchant_name"):
        receipt_data["merchant_name"] = _store_name_to_title_case(receipt_data["merchant_name"]) or receipt_data["merchant_name"]
    metadata = output_payload.get("_metadata", {})
    chain_id = metadata.get("chain_id")
    location_id = metadata.get("location_id")
    _rec = output_payload.get("receipt", {})
    _addr = _rec.get("merchant_address") or ""
    _addr_preview = (_addr[:100] + "...") if len(_addr) > 100 else _addr
    logger.info(
        "[STORE_DEBUG] categorize_receipt from run: chain_id=%s, location_id=%s, receipt.merchant_address=%r",
        chain_id,
        location_id,
        _addr_preview,
    )
    store_chain_id_uuid = _resolve_store_chain_id_uuid(
        receipt_id,
        chain_id,
        receipt_data.get("merchant_name"),
        receipt_data.get("merchant_address"),
    )
    if store_chain_id_uuid and store_chain_id_uuid != (chain_id or ""):
        logger.info(f"Resolved store_chain_id for rules: {chain_id!r} -> {store_chain_id_uuid}")

    # 若 run 的 _metadata 没有 location_id（例如 vision 管线未写），用 get_store_chain 再匹配一次；
    # 只要在 store_locations 有 match（含 1–2 字母 fuzzy），就不应进 store_candidate，且 summary 应带上该 location。
    resolved_chain_id: Optional[str] = None
    resolved_location_id: Optional[str] = None
    if receipt_data.get("merchant_name") and (not chain_id or not location_id):
        try:
            match_result = get_store_chain(
                receipt_data.get("merchant_name"),
                receipt_data.get("merchant_address"),
            )
            if match_result.get("matched"):
                resolved_chain_id = match_result.get("chain_id")
                resolved_location_id = match_result.get("location_id")
                if resolved_chain_id or resolved_location_id:
                    logger.info(
                        "[STORE_DEBUG] categorize_receipt: get_store_chain matched (metadata missing store ids): chain_id=%s, location_id=%s",
                        resolved_chain_id,
                        resolved_location_id,
                    )
        except Exception as e:
            logger.debug("get_store_chain in categorizer (resolve location): %s", e)

    effective_chain_id = store_chain_id_uuid or chain_id or resolved_chain_id
    effective_location_id = location_id or resolved_location_id

    logger.info(f"Retrieved output_payload: {len(items_data)} items (normalized to dollars)")

    # Subtotal correction: if sum(items) + tax + fees ≈ total, always use sum(items) as subtotal so we never persist a wrong subtotal from the model
    if items_data:
        items_sum = sum((item.get("line_total") or 0) for item in items_data)
        tax_val = receipt_data.get("tax") or 0
        total_val = receipt_data.get("total") or 0
        fees_val = receipt_data.get("fees") or 0
        if items_sum > 0 and total_val and abs((items_sum + tax_val + fees_val) - total_val) <= 0.03:
            old_subtotal = receipt_data.get("subtotal")
            receipt_data["subtotal"] = round(items_sum, 2)
            if old_subtotal is not None and abs(float(old_subtotal) - receipt_data["subtotal"]) > 0.01:
                logger.info(
                    "[CAT_DEBUG] categorize_receipt: set receipt.subtotal = sum(items) = %.2f (was %.2f) so stored summary is consistent",
                    receipt_data["subtotal"],
                    old_subtotal,
                )
    
    # 4a. Enrich items with category_id from product_categorization_rules (use UUID, not string tag)
    _enrich_items_category_from_rules(items_data, effective_chain_id)
    # 4b. For items still without category_id, call LLM to suggest category (so record_items get category_id when level-3 exists)
    _enrich_items_category_from_llm_sync(items_data, receipt_data.get("merchant_name"))
    
    # 4. 如果 force=True，删除旧数据
    if force:
        try:
            supabase.table("record_items").delete().eq("receipt_id", receipt_id).execute()
            supabase.table("record_summaries").delete().eq("receipt_id", receipt_id).execute()
            logger.info(f"Deleted existing categorization data for {receipt_id}")
        except Exception as e:
            logger.warning(f"Failed to delete old data: {e}")

    # 4b. 保证 receipt 有 total，避免 save_receipt_summary 因缺 total 抛错导致整条链路不写 record_items
    if not receipt_data.get("total") and items_data:
        items_sum = sum((item.get("line_total") or 0) for item in items_data)
        if items_sum > 0:
            receipt_data["total"] = round(items_sum + (receipt_data.get("tax") or 0) + (receipt_data.get("fees") or 0), 2)
            logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: derived receipt_data.total={receipt_data['total']} from items+tax+fees")
    if not receipt_data.get("total"):
        st, tx, fe = receipt_data.get("subtotal") or 0, receipt_data.get("tax") or 0, receipt_data.get("fees") or 0
        if st or tx or fe:
            receipt_data["total"] = round((st or 0) + (tx or 0) + (fe or 0), 2)
            logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: derived receipt_data.total={receipt_data['total']} from subtotal+tax+fees")
    
    # 5. 保存或更新 receipt_summary（有 summary 无 items 时只更新 summary 并补写 items，不重复 insert）
    summary_id = None
    summary_created_in_this_run = False
    try:
        if has_summary and not has_items:
            logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: backfill items path — calling update_receipt_summary")
            summary_id = update_receipt_summary(
                receipt_id=receipt_id,
                user_id=user_id,
                receipt_data=receipt_data,
                chain_id=effective_chain_id,
                location_id=effective_location_id,
                items_data=items_data,
            )
            if summary_id:
                logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: ✅ update_receipt_summary OK")
        if summary_id is None:
            logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: calling save_receipt_summary (items={len(items_data)})")
            summary_id = save_receipt_summary(
                receipt_id=receipt_id,
                user_id=user_id,
                receipt_data=receipt_data,
                chain_id=effective_chain_id,
                location_id=effective_location_id,
                items_data=items_data,
            )
            summary_created_in_this_run = True
            logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: ✅ save_receipt_summary OK, summary_id={summary_id}")
    except Exception as e:
        logger.error(f"[CAT_DEBUG] categorize_receipt {receipt_id}: ❌ save/update summary failed: {e}", exc_info=True)
        return {
            "success": False,
            "receipt_id": receipt_id,
            "message": f"Failed to save summary: {str(e)}"
        }

    # 5b. 仅当在 store_locations 中既无 match 也无 fuzzy match（即 effective 仍缺 chain 或 location）时才创建 store_candidate。
    #     若 get_store_chain 已匹配到门店（含 1–2 字母 fuzzy），effective_chain_id 与 effective_location_id 已在上文填好，不建 candidate。
    merchant_name = (receipt_data.get("merchant_name") or "").strip()
    need_candidate = merchant_name and (not effective_chain_id or not effective_location_id)
    if need_candidate:
        try:
            existing = supabase.table("store_candidates").select("id").eq("receipt_id", receipt_id).limit(1).execute()
            if not (existing.data and len(existing.data) > 0):
                match_result = get_store_chain(merchant_name, receipt_data.get("merchant_address"))
                candidate_id = create_store_candidate(
                    chain_name=merchant_name,
                    receipt_id=receipt_id,
                    source="llm",
                    llm_result={"receipt": receipt_data},
                    suggested_chain_id=match_result.get("suggested_chain_id") or effective_chain_id,
                    suggested_location_id=match_result.get("suggested_location_id"),
                    confidence_score=match_result.get("confidence_score"),
                )
                if candidate_id:
                    logger.info(
                        f"[CAT_DEBUG] categorize_receipt {receipt_id}: created store_candidate {candidate_id} for {merchant_name!r} (no location or no chain)"
                    )
        except Exception as e:
            logger.warning(f"[CAT_DEBUG] create_store_candidate for receipt {receipt_id} failed: {e}")

    # 6. 保存 receipt_items
    item_ids = []
    try:
        logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: calling save_receipt_items (items={len(items_data)})")
        item_ids = save_receipt_items(
            receipt_id=receipt_id,
            user_id=user_id,
            items_data=items_data
        )
        logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: ✅ save_receipt_items OK, count={len(item_ids)}")
    except Exception as e:
        logger.error(f"[CAT_DEBUG] categorize_receipt {receipt_id}: ❌ save_receipt_items failed: {e}", exc_info=True)
        # 仅当本次 run 新建了 summary 时才回滚；若本次只是补写 items（已有 summary）则不删 summary
        if summary_created_in_this_run and summary_id:
            try:
                supabase.table("record_summaries").delete().eq("id", summary_id).execute()
                logger.info(f"[CAT_DEBUG] categorize_receipt {receipt_id}: rolled back summary {summary_id}")
            except Exception as rollback_error:
                logger.warning(f"Failed to rollback summary {summary_id}: {rollback_error}")
        return {
            "success": False,
            "receipt_id": receipt_id,
            "message": f"Failed to save items: {str(e)}"
        }

    # 6b. Enqueue unmatched items (no category_id) and universal-only matched items to classification_review
    universal_only_ids: List[str] = []
    if item_ids and items_data:
        idx = 0
        for item in items_data:
            if not item.get("product_name"):
                continue
            lt = item.get("line_total")
            if lt is None:
                continue
            try:
                if int(round(float(lt) * 100)) < 0:
                    continue
            except (TypeError, ValueError):
                continue
            if idx < len(item_ids) and item.get("_from_universal_only"):
                universal_only_ids.append(item_ids[idx])
            idx += 1
    try:
        enqueued = enqueue_unmatched_items_to_classification_review(
            receipt_id, universal_only_record_item_ids=universal_only_ids or None
        )
        if enqueued:
            logger.info(f"✅ Enqueued {enqueued} unmatched/universal-only items to classification_review")
    except Exception as e:
        logger.warning(f"Failed to enqueue unmatched items to classification_review: {e}")

    # 7. 返回成功结果
    result = {
        "success": True,
        "receipt_id": receipt_id,
        "summary_id": summary_id,
        "items_count": len(item_ids),
        "message": "Categorization completed successfully"
    }
    
    logger.info(f"✅ Categorization completed: {result}")
    return result


def categorize_receipts_batch(
    receipt_ids: List[str],
    force: bool = False
) -> Dict[str, Any]:
    """
    批量 categorize 多张小票
    
    Args:
        receipt_ids: List of receipt IDs
        force: 如果为 True，重新处理已经 categorize 过的
        
    Returns:
        {
            "success": int,
            "failed": int,
            "results": List[Dict]
        }
    """
    logger.info(f"Starting batch categorization for {len(receipt_ids)} receipts")
    
    results = []
    success_count = 0
    failed_count = 0
    
    for receipt_id in receipt_ids:
        try:
            result = categorize_receipt(receipt_id, force=force)
            results.append(result)
            
            if result.get("success"):
                success_count += 1
            else:
                failed_count += 1
        except Exception as e:
            logger.error(f"Error categorizing {receipt_id}: {e}")
            results.append({
                "success": False,
                "receipt_id": receipt_id,
                "message": f"Error: {str(e)}"
            })
            failed_count += 1
    
    summary = {
        "total": len(receipt_ids),
        "success": success_count,
        "failed": failed_count,
        "results": results
    }
    
    logger.info(f"Batch categorization completed: {success_count} success, {failed_count} failed")
    return summary
