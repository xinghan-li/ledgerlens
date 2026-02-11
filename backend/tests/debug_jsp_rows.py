"""Debug: why is $1.83 in amount-only row, splitting from JSP?"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.store_config_loader import load_store_config
from app.processors.validation.receipt_structures import TextBlock
from app.processors.validation.skew_corrector import correct_skew
from app.processors.validation.row_reconstructor import build_physical_rows

def main():
    p = Path(__file__).parent / "fixtures" / "20260209_154003_1.json"
    with open(p, encoding="utf-8") as f:
        d = json.load(f)
    blocks = d["blocks"]
    store = load_store_config("tnt_supermarket_us")
    tbs = [TextBlock.from_dict(b, i) for i, b in enumerate(blocks)]
    half = 0.011

    # After skew
    out, _ = correct_skew(tbs, half, store)
    jsp = next(b for b in out if "JAPANESE" in (b.text or ""))
    fp183 = next(b for b in out if "1.83" in (b.text or "") and b.center_x > 0.6)
    lb92 = next(b for b in out if "0.92 lb" in (b.text or ""))

    print("After skew correction (date+Meichen):")
    print("  JSP:        cy=%.4f x=%.4f" % (jsp.center_y, jsp.center_x))
    print("  FP $1.83:   cy=%.4f x=%.4f" % (fp183.center_y, fp183.center_x))
    print("  0.92 lb:    cy=%.4f x=%.4f" % (lb92.center_y, lb92.center_x))
    print("  JSP-FP diff: %.4f" % abs(jsp.center_y - fp183.center_y))
    print("  Row eps (max): 0.012 -> JSP+FP same row?", abs(jsp.center_y - fp183.center_y) <= 0.012)

    rows = build_physical_rows(out)
    for i, row in enumerate(rows):
        texts = [b.text[:30] for b in row.blocks]
        if any("JAPANESE" in t or "1.83" in t or "0.92" in t for t in texts):
            left = [b for b in row.blocks if b.center_x < 0.53]
            print("  Row %d: left=%s | all=%s" % (i, [b.text[:25] for b in left], texts))

if __name__ == "__main__":
    main()
