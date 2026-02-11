"""Run pipeline on Canadian T&T receipt and print results."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.store_config_loader import get_store_config_for_receipt
from app.processors.validation.pipeline import process_receipt_pipeline

def main():
    fixture_path = Path(__file__).parent / "fixtures" / "20260209_204418_1.json"
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    blocks = data["blocks"]
    merchant_name = data.get("merchant_name", "TNT Supermarket - Osaka Branch")

    # Get store config (should resolve to tnt_supermarket_ca)
    store_config = get_store_config_for_receipt(merchant_name)
    print(f"merchant_name: {merchant_name}")
    print(f"chain_id: {store_config.get('chain_id') if store_config else None}")
    print()

    # Run pipeline
    result = process_receipt_pipeline(
        blocks, {}, store_config=store_config, merchant_name=merchant_name
    )

    # Output summary
    print("=== RESULT SUMMARY ===")
    print(f"success: {result.get('success')}")
    print(f"chain_id: {result.get('chain_id')}")
    print(f"store: {result.get('store')}")
    print(f"membership: {result.get('membership')}")
    print(f"error_log: {result.get('error_log', [])}")
    print()
    print(f"Items ({len(result.get('items', []))}):")
    for i, it in enumerate(result.get("items", [])[:20]):
        name = (it["product_name"] or "")[:55]
        amt = it.get("line_total", "?")
        print(f"  {i+1:2}. {name:<55} | {amt}c")
    if len(result.get("items", [])) > 20:
        print(f"  ... and {len(result['items']) - 20} more")
    print()
    print("Totals:", result.get("totals"))
    print("Validation:", result.get("validation"))

    # Save full result for inspection
    out_path = Path(__file__).parent / "ca_receipt_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "success": result.get("success"),
            "chain_id": result.get("chain_id"),
            "store": result.get("store"),
            "membership": result.get("membership"),
            "error_log": result.get("error_log"),
            "items": result.get("items"),
            "totals": result.get("totals"),
            "validation": result.get("validation"),
        }, f, indent=2, ensure_ascii=False)
    print(f"\nFull result saved to {out_path.name}")


if __name__ == "__main__":
    main()
