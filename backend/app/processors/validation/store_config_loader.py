"""
Store receipt config loader for the config-driven pipeline.

Loads JSON configs from backend/config/store_receipts/ by chain_id or by matching
merchant name (primary_name / aliases / match_keywords).
Supports config inheritance via "extends" (e.g. tnt_supermarket_ca extends tnt_supermarket_us).
For Costco: disambiguates US vs Canada by scanning blocks for address (WA/OR vs ON/BC).
"""
from pathlib import Path
from typing import Dict, Any, Optional, List
import json
import logging
import re

logger = logging.getLogger(__name__)

# US state codes (2-letter) - used to disambiguate Costco US vs Canada
US_STATE_PATTERN = re.compile(
    r"\b(WA|OR|CA|TX|FL|NY|IL|PA|OH|GA|NC|MI|NJ|VA|AZ|MA|TN|IN|MO|MD|WI|CO|MN|SC|AL|LA|KY|CT|OK|IA|UT|NV|AR|MS|KS|NM|NE|ID|WV|HI|NH|ME|RI|MT|DE|SD|ND|AK|VT|WY)\s+[0-9]{5}",
    re.I
)
# Canadian province patterns
CA_PROVINCE_PATTERN = re.compile(
    r"\b(ON|BC|AB|QC|MB|SK|NS|NB|NL|PE|NT|YT)\s+[A-Z0-9]\s*[A-Z0-9]\s*[A-Z0-9]\s*[A-Z0-9]|\b(ON|BC|AB|QC)\b",
    re.I
)

# Directory containing store_receipts/*.json (relative to backend/)
CONFIG_DIR_NAME = "config/store_receipts"


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge overrides into base. Overrides take precedence. Returns new dict."""
    out = dict(base)
    for k, v in overrides.items():
        if k == "extends":
            continue  # Skip extends key
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _get_config_dir() -> Path:
    """Resolve backend/config/store_receipts from this file's location."""
    # .../backend/app/processors/validation/store_config_loader.py -> backend/
    backend = Path(__file__).resolve().parents[3]
    return backend / CONFIG_DIR_NAME


def load_store_config(chain_id: str) -> Optional[Dict[str, Any]]:
    """
    Load store config JSON by chain_id (filename without .json).
    If config has "extends", merges with base config (overrides take precedence).
    
    Args:
        chain_id: e.g. "island_gourmet_markets"
    Returns:
        Config dict or None if not found
    """
    path = _get_config_dir() / f"{chain_id}.json"
    if not path.exists():
        logger.debug(f"Store config not found: {path}")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load store config {path}: {e}")
        return None
    extends = cfg.pop("extends", None)
    if extends:
        base = load_store_config(extends)
        if base:
            cfg = _deep_merge(base, cfg)
        else:
            logger.warning(f"Base config '{extends}' not found for {chain_id}")
    return cfg


def find_chain_id_by_merchant_name(merchant_name: str) -> Optional[str]:
    """
    Scan all store configs and return config key (filename stem) if any identification matches.
    Returns path.stem (e.g. "costco_canada_digital") for load_store_config to load the correct file.
    The loaded config's chain_id (e.g. "Costco_Canada") is used for display/result.
    
    Args:
        merchant_name: Raw merchant name from receipt/OCR
    Returns:
        Config key (filename without .json) or None
    """
    if not merchant_name or not merchant_name.strip():
        return None
    config_dir = _get_config_dir()
    if not config_dir.exists():
        return None
    merchant_upper = merchant_name.upper().strip()
    paths = sorted(config_dir.glob("*.json"), key=lambda p: p.name)
    for path in paths:
        if path.name.startswith("schema") or path.name.startswith("aggregated"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            continue
        ident = cfg.get("identification", {})
        primary = (ident.get("primary_name") or "").upper()
        aliases = [a.upper() for a in ident.get("aliases", [])]
        keywords = ident.get("match_keywords", [])
        if primary and primary in merchant_upper:
            return path.stem  # Use filename stem for loading, not cfg["chain_id"]
        if any(a in merchant_upper for a in aliases):
            return path.stem
        if any(kw.upper() in merchant_upper for kw in keywords):
            return path.stem
    return None


def _is_costco_us_from_blocks(blocks: List[Dict[str, Any]]) -> Optional[bool]:
    """
    Scan blocks for address to disambiguate Costco US vs Canada.
    Returns True if US (e.g. WA, Lynnwood), False if Canada (ON, BC), None if unclear.
    """
    if not blocks:
        return None
    combined = " ".join(b.get("text", "") or "" for b in blocks).upper()
    if CA_PROVINCE_PATTERN.search(combined):
        return False
    if US_STATE_PATTERN.search(combined):
        return True
    # Lynnwood, 33rd Ave etc. without zip: assume US
    if re.search(r"\bLYNNWOOD\b|\b33RD\s+AVE\b|\bWA\s+98037\b", combined, re.I):
        return True
    return None


def _is_costco_us_digital_from_blocks(blocks: List[Dict[str, Any]]) -> bool:
    """
    Check if Costco US receipt is digital (Orders & Purchases PDF) vs physical.
    Returns True if digital (Orders & Purchases), False if physical (Bottom of Basket, BOB Count).
    """
    if not blocks:
        return False
    combined = " ".join(b.get("text", "") or "" for b in blocks)
    if "Orders & Purchases" in combined or "Orders & Purchases | Costco" in combined:
        return True
    if "Bottom of Basket" in combined or "BOB Count" in combined:
        return False
    # Default: when unclear, assume physical (original US processor)
    return False


def get_store_config_for_receipt(
    merchant_name: Optional[str],
    chain_id_hint: Optional[str] = None,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get store config: by chain_id_hint if provided, else by matching merchant_name.
    For Costco: when blocks provided, disambiguates US vs Canada by address.
    
    Args:
        merchant_name: From receipt/OCR
        chain_id_hint: If caller already knows chain (e.g. from user/store selection)
        blocks: Optional OCR blocks for Costco US/CA disambiguation
    Returns:
        Config dict or None
    """
    if chain_id_hint:
        cfg = load_store_config(chain_id_hint)
        if cfg:
            return cfg
    if merchant_name:
        cid = find_chain_id_by_merchant_name(merchant_name)
        if cid and "costco" in cid.lower():
            is_us = _is_costco_us_from_blocks(blocks) if blocks else None
            if is_us is True:
                is_digital = _is_costco_us_digital_from_blocks(blocks) if blocks else False
                cfg = load_store_config("costco_usa_digital" if is_digital else "costco_usa_physical")
                if cfg:
                    return cfg
            if is_us is False or (is_us is None and "canada" in cid.lower()):
                cfg = load_store_config("costco_canada_digital")
                if cfg:
                    return cfg
            # Fallback: load whatever matched
        if cid:
            return load_store_config(cid)
    return None
