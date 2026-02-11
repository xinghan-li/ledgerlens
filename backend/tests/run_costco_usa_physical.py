"""Run pipeline on Costco USA physical receipt."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.store_config_loader import get_store_config_for_receipt, load_store_config
from app.processors.validation.pipeline import process_receipt_pipeline


def main():
    fixture_path = None
    if len(sys.argv) > 1:
        fixture_path = Path(sys.argv[1])
    if not fixture_path or not fixture_path.exists():
        fixture_dir = Path(__file__).parent / "fixtures"
        candidates = [
            fixture_dir / "20260210_114024_1.json",
            fixture_dir / "receipt1.json",
        ]
        for p in candidates:
            if p.exists():
                fixture_path = p
                break
    if not fixture_path or not fixture_path.exists():
        print("No Costco USA physical fixture found. Usage: python run_costco_usa_physical.py <fixture.json>")
        return

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    blocks = data.get("blocks")
    if not blocks:
        print("No blocks in fixture")
        return

    merchant_name = data.get("merchant_name") or data.get("store") or "COSTCO WHOLESALE"
    if isinstance(merchant_name, str) and "\n" in merchant_name:
        merchant_name = merchant_name.replace("\n", " ")

    store_config = get_store_config_for_receipt(merchant_name, blocks=blocks)
    if not store_config:
        store_config = load_store_config("costco_usa_physical")  # file: costco_usa_physical.json, layout: costco_us_physical

    print(f"merchant_name: {merchant_name}")
    print(f"chain_id: {store_config.get('chain_id') if store_config else None}")
    print()

    result = process_receipt_pipeline(
        blocks, {}, store_config=store_config, merchant_name=merchant_name
    )

    print("=== RESULT ===")
    print(f"success: {result.get('success')}")
    print(f"method: {result.get('method')}")
    print(f"chain_id: {result.get('chain_id')}")
    print(f"store: {result.get('store')}")
    print(f"address: {result.get('address')}")
    print(f"currency: {result.get('currency')}")
    print(f"membership: {result.get('membership')}")
    print(f"error_log: {result.get('error_log')}")
    print(f"Items: {len(result.get('items', []))}")
    for i, it in enumerate(result.get("items", [])[:15]):
        print(f"  {i+1}. {(it['product_name'] or '')[:40]} | {it.get('line_total')}c")
    if len(result.get("items", [])) > 15:
        print(f"  ... +{len(result['items'])-15} more")
    print("Totals:", result.get("totals"))
    print("Validation:", result.get("validation"))

    out_path = Path(__file__).parent / "costco_us_physical_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "success": result.get("success"),
            "method": result.get("method"),
            "chain_id": result.get("chain_id"),
            "store": result.get("store"),
            "address": result.get("address"),
            "currency": result.get("currency"),
            "membership": result.get("membership"),
            "error_log": result.get("error_log"),
            "items": result.get("items"),
            "totals": result.get("totals"),
            "validation": result.get("validation"),
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path.name}")


if __name__ == "__main__":
    main()
