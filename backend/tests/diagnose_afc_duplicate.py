"""Diagnose why AFC SOYNILK appears twice - trace item extraction for DELI/AFC/GYG."""
import json
import sys
import logging
from pathlib import Path

# Only show item_extractor logs
logging.basicConfig(level=logging.WARNING, format="%(name)s | %(message)s")
log = logging.getLogger("app.processors.validation.item_extractor")
log.setLevel(logging.INFO)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    fixture_path = Path(__file__).parent / "fixtures" / "20260209_154003_1.json"
    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)
    blocks = fixture.get("blocks", [])

    from app.processors.validation.pipeline import process_receipt_pipeline
    from app.processors.validation.store_config_loader import load_store_config

    store_config = load_store_config("tnt_supermarket_us")
    result = process_receipt_pipeline(blocks, {}, store_config=store_config)

    print("\n=== ITEMS ===")
    for i, it in enumerate(result.get("items", [])):
        print(f"  {i+1}. {it.get('product_name')} -> ${it.get('line_total',0)/100:.2f}")

if __name__ == "__main__":
    main()
