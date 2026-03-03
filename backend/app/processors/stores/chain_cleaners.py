"""
Chain-dispatched post-LLM cleaners.

After clean_llm_result, apply the cleaner for the receipt's chain (by merchant name).
Register chain config keys (e.g. tnt_supermarket_ca) to cleaner functions.
"""
from typing import Dict, Any, Callable, Optional
import logging
from ..validation.store_config_loader import find_chain_id_by_merchant_name
from .tnt_supermarket import clean_tnt_receipt_items

logger = logging.getLogger(__name__)

# Config key (from find_chain_id_by_merchant_name) -> cleaner(result) -> result
_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "tnt_supermarket_ca": clean_tnt_receipt_items,
    "tnt_supermarket_us": clean_tnt_receipt_items,
}


def register_chain_cleaner(config_key: str, cleaner: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    _REGISTRY[config_key] = cleaner


def apply_chain_cleaner(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply the post-LLM cleaner for the receipt's chain. Uses merchant_name to resolve chain.
    If no cleaner is registered for the chain, returns result unchanged.
    """
    receipt = llm_result.get("receipt") or {}
    merchant_name = (receipt.get("merchant_name") or "").strip()
    if not merchant_name:
        return llm_result
    config_key = find_chain_id_by_merchant_name(merchant_name)
    if not config_key:
        return llm_result
    cleaner = _REGISTRY.get(config_key)
    if not cleaner:
        return llm_result
    try:
        return cleaner(llm_result)
    except Exception as e:
        logger.warning(f"Chain cleaner {config_key} failed: {e}")
        return llm_result
