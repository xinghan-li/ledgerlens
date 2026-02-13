"""
一次性脚本：调查 receipt_processing_runs.output_payload 结构
"""
import os
import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import json
from pathlib import Path
from dotenv import load_dotenv

backend_dir = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(backend_dir))
load_dotenv(dotenv_path=backend_dir / ".env")

from app.services.database.supabase_client import _get_client


def get_structure(obj, depth=0):
    """递归获取 JSON 结构概要"""
    if depth > 3:
        return "..."
    if obj is None:
        return "null"
    if isinstance(obj, dict):
        return {k: get_structure(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return "[]"
        return [get_structure(obj[0], depth + 1), f"...({len(obj)} items)"]
    if isinstance(obj, (str, int, float, bool)):
        t = type(obj).__name__
        s = str(obj)
        return f"{t}:{s[:40]}..." if len(s) > 40 else f"{t}:{s}"
    return str(type(obj))


def main():
    supabase = _get_client()
    runs = supabase.table("receipt_processing_runs")\
        .select("id, receipt_id, stage, status, output_payload")\
        .not_.is_("output_payload", "null")\
        .limit(20)\
        .execute()

    # 取 5 个不同 stage/receipt 的样本
    seen = set()
    samples = []
    for r in runs.data:
        key = (r.get("stage"), r.get("receipt_id"))
        if key in seen:
            continue
        seen.add(key)
        samples.append(r)
        if len(samples) >= 5:
            break

    print("=" * 80)
    print("receipt_processing_runs.output_payload 结构调查 (5 samples)")
    print("=" * 80)

    for i, run in enumerate(samples, 1):
        payload = run.get("output_payload") or {}
        print(f"\n--- Sample {i}: run_id={run.get('id')}, stage={run.get('stage')}, status={run.get('status')} ---")
        print("顶层 keys:", list(payload.keys()) if isinstance(payload, dict) else type(payload))
        print("结构概要:")
        print(json.dumps(get_structure(payload), indent=2, ensure_ascii=False))

    # 汇总
    all_keys = set()
    for r in samples:
        p = r.get("output_payload") or {}
        if isinstance(p, dict):
            all_keys.update(p.keys())
    print("\n" + "=" * 80)
    print("汇总: 5 个样本中出现的所有顶层 key:", sorted(all_keys))


if __name__ == "__main__":
    main()
