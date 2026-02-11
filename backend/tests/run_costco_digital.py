"""Run pipeline on Costco digital CA receipt."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.store_config_loader import get_store_config_for_receipt, load_store_config
from app.processors.validation.pipeline import process_receipt_pipeline


def _parse_amount_from_text(text: str):
    """Parse amount from text like '218.44' or '8.99 N'."""
    import re
    m = re.search(r'\$?\s*(\d+\.\d{2})', text or "")
    return float(m.group(1)) if m else None


def _extract_blocks_from_receipt1(receipt_path: Path) -> list:
    """Extract and normalize blocks from receipt1-style pipeline output (ocr_and_regions)."""
    data = json.loads(receipt_path.read_text(encoding="utf-8"))
    if "blocks" in data and data["blocks"]:
        return data["blocks"]

    blocks = []
    section_detail = data.get("ocr_and_regions", {}).get("section_rows_detail", [])
    scale = 10000.0
    for section in section_detail:
        for row in section.get("rows", []):
            for blk in row.get("blocks", []):
                x = blk.get("x", 0) / scale
                y = blk.get("y", 0) / scale
                text = blk.get("text", "")
                is_amt = blk.get("is_amount", False)
                amt = blk.get("amount")
                if amt is None and is_amt:
                    amt = _parse_amount_from_text(text)
                blocks.append({
                    "text": text,
                    "x": x, "y": y,
                    "center_x": x + 0.01, "center_y": y + 0.005,
                    "width": 0.02, "height": 0.01,
                    "is_amount": is_amt,
                    "amount": amt,
                    "page_number": 1,
                })
    return blocks


def main():
    import sys
    fixture_path = None
    if len(sys.argv) > 1:
        fixture_path = Path(sys.argv[1])
    if not fixture_path or not fixture_path.exists():
        fixture_dir = Path(__file__).parent / "fixtures"
        candidates = list(fixture_dir.glob("*costco*")) + [fixture_dir / "receipt1.json"]
        for p in candidates:
            if p.exists():
                fixture_path = p
                break
    if not fixture_path or not fixture_path.exists():
        print("No Costco fixture found. Put a fixture with 'blocks' or receipt1.json")
        return

    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    blocks = data.get("blocks") or data.get("ocr_blocks")
    if not blocks:
        blocks = _extract_blocks_from_receipt1(fixture_path)
    if not blocks:
        print("No blocks found in fixture")
        return

    merchant_name = data.get("merchant_name") or data.get("store") or "COSTCO WHOLESALE"
    if isinstance(merchant_name, str) and "\n" in merchant_name:
        merchant_name = merchant_name.replace("\n", " ")

    store_config = get_store_config_for_receipt(merchant_name, blocks=blocks)
    if not store_config:
        store_config = load_store_config("costco_canada_digital")

    print(f"merchant_name: {merchant_name}")
    print(f"chain_id: {store_config.get('chain_id') if store_config else None}")
    print()

    result = process_receipt_pipeline(
        blocks, {}, store_config=store_config, merchant_name=merchant_name
    )

    print("=== RESULT ===")
    print(f"success: {result.get('success')}")
    print(f"chain_id: {result.get('chain_id')}")
    print(f"membership: {result.get('membership')}")
    print(f"Items: {len(result.get('items', []))}")
    for i, it in enumerate(result.get("items", [])[:12]):
        print(f"  {i+1}. {(it['product_name'] or '')[:45]} | {it.get('line_total')}c")
    if len(result.get("items", [])) > 12:
        print(f"  ... +{len(result['items'])-12} more")
    print("Totals:", result.get("totals"))
    print("Validation:", result.get("validation"))

    out_path = Path(__file__).parent / "costco_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "success": result.get("success"),
            "chain_id": result.get("chain_id"),
            "store": result.get("store"),
            "address": result.get("address"),
            "currency": result.get("currency"),
            "items": result.get("items"),
            "totals": result.get("totals"),
            "validation": result.get("validation"),
            "ocr_and_regions": result.get("ocr_and_regions"),
            "ocr_blocks": result.get("ocr_blocks"),
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out_path.name}")
    print(f"Saved {len(result.get('ocr_blocks', []))} OCR blocks and {len(result.get('ocr_and_regions', {}).get('section_rows_detail', []))} sections")


if __name__ == "__main__":
    main()
