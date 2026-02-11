"""Check error_log from pipeline."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.store_config_loader import load_store_config
from app.processors.validation.pipeline import process_receipt_pipeline

p = Path(__file__).parent / "fixtures" / "20260209_154003_1.json"
d = json.loads(p.read_text(encoding="utf-8"))
r = process_receipt_pipeline(d["blocks"], {}, store_config=load_store_config("tnt_supermarket_us"))
el = r.get("error_log", [])
with open(Path(__file__).parent / "error_log_out.txt", "w", encoding="utf-8") as f:
    f.write(f"error_log count: {len(el)}\n")
    for i, e in enumerate(el):
        f.write(f"  {i} {e}\n")
    f.write(f"Items: {[i['product_name'] for i in r.get('items', [])]}\n")
print("Wrote error_log_out.txt")
