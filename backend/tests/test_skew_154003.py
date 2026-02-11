"""Test skew correction on 20260209_154003."""
import json
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(name)s | %(message)s")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    p = Path(__file__).parent / "fixtures" / "20260209_154003_1.json"
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    blocks = d["blocks"]
    from app.processors.validation.store_config_loader import load_store_config
    from app.processors.validation.pipeline import process_receipt_pipeline
    from app.processors.validation.skew_corrector import correct_skew
    from app.processors.validation.receipt_structures import TextBlock

    store = load_store_config("tnt_supermarket_us")
    tbs = [TextBlock.from_dict(b, i) for i, b in enumerate(blocks)]
    half = 0.011

    out, err = correct_skew(tbs, half, store)
    date_b = next(b for b in out if "01/25" in (b.text or ""))
    d0_b = next(b for b in out if b.text and b.text.strip() == "$0.00" and b.center_y < 0.6)
    pear_b = next(b for b in out if "GOLDEN" in (b.text or ""))
    fp_b = next(b for b in out if "7.72" in (b.text or ""))

    print("After skew (same-row ref date+Meichen):")
    print("  date cy:", round(date_b.center_y, 4))
    print("  $0.00 cy:", round(d0_b.center_y, 4))
    print("  PEAR cy:", round(pear_b.center_y, 4))
    print("  FP $7.72 cy:", round(fp_b.center_y, 4))
    print("  PEAR-FP diff:", round(pear_b.center_y - fp_b.center_y, 4))

    r = process_receipt_pipeline(blocks, {}, store_config=store)
    items = r.get("items", [])
    print("\nItems:", [i["product_name"] for i in items])
    print("JSP found:", any("JAPANESE" in i.get("product_name", "") for i in items))

if __name__ == "__main__":
    main()
