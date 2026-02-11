"""
Diagnose Y offsets for DELI/$4.99 vs AFC/$5.99, and trace why GYG matches $20.53.
"""
import json
from pathlib import Path

sys_path = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(sys_path))

def main():
    fixture_path = Path(__file__).parent / "fixtures" / "20260209_121422_1.json"
    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    blocks = fixture.get("blocks", [])
    # Build block list with center_y
    for i, b in enumerate(blocks):
        cy = b.get("center_y") or b.get("y", 0)
        cx = b.get("center_x") or b.get("x", 0)
        text = (b.get("text") or "")[:50]
        if "DELI" in text or "4.99" in text or "5.99" in text or "AFC" in text or "GYG" in text or "20.53" in text or "Points" in text:
            print(f"  block {i}: y={cy:.4f} x={cx:.4f} text='{text}'")

    # Compute half_line from avg height
    heights = [b.get("height") for b in blocks if b.get("height") and b.get("height") > 0]
    half_line = (sum(heights) / len(heights)) * 0.5 if heights else 0.006
    print(f"\nHalf-line eps (tolerance): {half_line:.4f}")

    # Key blocks
    def find(text_substr):
        for b in blocks:
            if text_substr in (b.get("text") or ""):
                return b.get("center_y") or b.get("y")
        return None

    y_deli = find("DELI")
    y_499 = find("4.99")
    y_afc = find("AFC")
    y_599 = find("5.99")
    y_gyg = find("GYG")
    y_2053 = find("20.53")
    y_points = find("Points")

    print("\n=== Key Y coordinates (normalized 0-1) ===")
    for name, y in [("DELI", y_deli), ("$4.99", y_499), ("AFC SOY", y_afc), ("$5.99", y_599), ("GYG", y_gyg), ("$20.53", y_2053), ("Points", y_points)]:
        if y is not None:
            print(f"  {name}: {y:.4f}")

    print("\n=== Offsets (Y distance) ===")
    if y_499 and y_afc:
        d_499_afc = abs(y_499 - y_afc)
        print(f"  $4.99 to AFC: {d_499_afc:.4f}  (half_line={half_line:.4f}, ratio={d_499_afc/half_line:.2f}x)")
    if y_599 and y_afc:
        d_599_afc = abs(y_599 - y_afc)
        print(f"  $5.99 to AFC: {d_599_afc:.4f}  (half_line={half_line:.4f}, ratio={d_599_afc/half_line:.2f}x)")
    if y_2053 and y_gyg:
        d_2053_gyg = abs(y_2053 - y_gyg)
        print(f"  $20.53 to GYG: {d_2053_gyg:.4f}  (half_line={half_line:.4f}, ratio={d_2053_gyg/half_line:.2f}x)")
    if y_2053 and y_points:
        d_2053_pts = abs(y_2053 - y_points)
        print(f"  $20.53 to Points: {d_2053_pts:.4f}")

    # Region split - which rows are items vs totals
    from app.processors.validation.pipeline import process_receipt_pipeline
    from app.processors.validation.store_config_loader import load_store_config
    from app.processors.validation.row_reconstructor import build_physical_rows
    from app.processors.validation.region_splitter import split_regions
    from app.processors.validation.receipt_structures import TextBlock

    text_blocks = [TextBlock.from_dict(b, i) for i, b in enumerate(blocks)]
    rows = build_physical_rows(text_blocks)
    store_config = load_store_config("tnt_supermarket_us")
    regions = split_regions(rows, store_config=store_config)

    print("\n=== Item rows (last 5) - which contain $20.53? ===")
    for r in regions.item_rows[-5:]:
        amts = [f"${b.amount:.2f}" for b in r.get_amount_blocks()]
        left = [b.text[:20] for b in r.blocks if not b.is_amount or b.amount is None]
        print(f"  row {r.row_id}: y_center={r.y_center:.4f} amounts={amts} left={left}")

    print("\n=== Totals rows ===")
    for r in regions.totals_rows:
        amts = [f"${b.amount:.2f}" for b in r.get_amount_blocks()]
        print(f"  row {r.row_id}: y_center={r.y_center:.4f} text='{r.text[:60]}' amounts={amts}")

    # Find which item row has $20.53
    for r in regions.item_rows:
        for b in r.get_amount_blocks():
            if b.amount and abs(b.amount - 20.53) < 0.01:
                print(f"\n!!! $20.53 is in ITEM row {r.row_id} (y={r.y_center:.4f}) - this row should be in TOTALS!")
                print(f"    Row text: '{r.text[:80]}'")
                print(f"    Row blocks: {[(b.text[:20], b.center_y) for b in r.blocks]}")

if __name__ == "__main__":
    main()
