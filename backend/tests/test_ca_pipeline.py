"""Test Canadian T&T pipeline: verify CA config is used and pipeline runs correctly."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.store_config_loader import (
    get_store_config_for_receipt,
    load_store_config,
    find_chain_id_by_merchant_name,
)


def test_ca_config_resolution():
    """Verify TNT Supermarket - Osaka Branch resolves to tnt_supermarket_ca."""
    merchant = "TNT Supermarket - Osaka Branch"
    cid = find_chain_id_by_merchant_name(merchant)
    assert cid == "tnt_supermarket_ca", f"Expected tnt_supermarket_ca, got {cid}"
    cfg = get_store_config_for_receipt(merchant)
    assert cfg is not None
    assert cfg.get("chain_id") == "tnt_supermarket_ca"
    assert cfg.get("pipeline", {}).get("skew_correction") is False
    assert cfg.get("wash_data", {}).get("fee_row_patterns")
    print("[OK] CA config resolution")


def test_us_config_resolution():
    """Verify US store resolves to tnt_supermarket_us."""
    merchant = "T&T Supermarket US - Lynnwood Store"
    cid = find_chain_id_by_merchant_name(merchant)
    assert cid == "tnt_supermarket_us", f"Expected tnt_supermarket_us, got {cid}"
    cfg = get_store_config_for_receipt(merchant)
    assert cfg is not None
    assert cfg.get("chain_id") == "tnt_supermarket_us"
    assert cfg.get("pipeline", {}).get("skew_correction") is True
    print("[OK] US config resolution")


def test_config_extends():
    """Verify CA config inherits from US and overrides correctly."""
    ca = load_store_config("tnt_supermarket_ca")
    assert ca.get("items", {}).get("layout", {}).get("amount_suffixes") == ["FP", "P", "W"]
    assert "GROCERY" in (ca.get("items", {}).get("section_headers") or [])
    assert "Env fee \\(CRF\\)" in (ca.get("wash_data", {}).get("fee_row_patterns") or [])
    print("[OK] Config extends")


def test_pipeline_with_ca_config():
    """Run pipeline with CA config on a fixture (uses US receipt - just verify no crash)."""
    from app.processors.validation.pipeline import process_receipt_pipeline

    fixture_dir = Path(__file__).parent / "fixtures"
    fixture = fixture_dir / "20260209_154003_1.json"
    if not fixture.exists():
        print("[SKIP] No fixture for pipeline test")
        return
    data = json.loads(fixture.read_text(encoding="utf-8"))
    blocks = data.get("blocks", [])
    if not blocks:
        print("[SKIP] Fixture has no blocks")
        return
    ca_config = load_store_config("tnt_supermarket_ca")
    result = process_receipt_pipeline(blocks, {}, store_config=ca_config)
    assert result.get("chain_id") == "tnt_supermarket_ca"
    # CA has skew disabled - should not have skew error
    errs = result.get("error_log", [])
    skew_errs = [e for e in errs if "skew" in e.lower()]
    assert not skew_errs, f"CA should have skew disabled, got: {skew_errs}"
    print("[OK] Pipeline with CA config (skew disabled)")


if __name__ == "__main__":
    test_ca_config_resolution()
    test_us_config_resolution()
    test_config_extends()
    test_pipeline_with_ca_config()
    print("\nAll tests passed.")
