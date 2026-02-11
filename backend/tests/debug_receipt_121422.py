"""
Debug script for 20260209_121422_1 (GOLDEN DEW PEAR receipt).
Runs pipeline with verbose DEBUG logging.
"""
import json
import sys
import logging
from pathlib import Path

# Setup DEBUG logging before any imports
logging.basicConfig(
    level=logging.DEBUG,
    format="%(name)s | %(levelname)s | %(message)s",
    stream=sys.stdout,
    force=True,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    fixture_path = Path(__file__).parent / "fixtures" / "20260209_121422_1.json"
    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    blocks = fixture.get("blocks", [])
    print(f"\n=== Loaded {len(blocks)} blocks from fixture ===\n")

    from app.processors.validation.pipeline import process_receipt_pipeline
    from app.processors.validation.store_config_loader import load_store_config

    chain_id = fixture.get("chain_id", "tnt_supermarket_us")
    store_config = load_store_config(chain_id)
    result = process_receipt_pipeline(blocks, {}, store_config=store_config)

    print("\n=== RESULT ===")
    print(f"Success: {result.get('success')}")
    print(f"Items: {len(result.get('items', []))}")
    for i, item in enumerate(result.get("items", []), 1):
        print(f"  {i}. {item.get('product_name')} qty={item.get('quantity')} unit={item.get('unit')} up={item.get('unit_price')} total={item.get('line_total')}")

if __name__ == "__main__":
    main()
