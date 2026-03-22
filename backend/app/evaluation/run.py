"""
Evaluation runner for receipt parsing accuracy.

Usage:
    python -m app.evaluation.run --ground-truth evaluation/ground_truth/
    python -m app.evaluation.run --ground-truth evaluation/ground_truth/ --predictions output/20260219/

Ground truth files are JSON with the same schema as LLM output (receipt + items).
File names should match between ground truth and predictions directories.

If --predictions is omitted, runs the vision pipeline on corresponding images
from input/ (TODO: implement live evaluation).
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from .evaluators import ALL_EVALUATORS


def load_json_files(directory: Path) -> Dict[str, Dict]:
    """Load all JSON files from a directory. Returns {filename_stem: data}."""
    results = {}
    for f in sorted(directory.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # Handle output files that wrap data in {"data": ...}
            if "data" in data and "receipt" in data["data"]:
                data = data["data"]
            results[f.stem] = data
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  WARNING: Skipping {f.name}: {e}", file=sys.stderr)
    return results


def evaluate_single(predicted: Dict, truth: Dict) -> List[Dict[str, Any]]:
    """Run all evaluators on a single (predicted, truth) pair."""
    results = []
    for evaluator in ALL_EVALUATORS:
        try:
            result = evaluator(predicted, truth)
            results.append(result)
        except Exception as e:
            results.append({
                "metric": evaluator.__name__,
                "score": None,
                "error": str(e),
            })
    return results


def aggregate_scores(all_results: Dict[str, List[Dict]]) -> Dict[str, Any]:
    """Aggregate per-receipt scores into summary metrics."""
    metric_scores: Dict[str, List[float]] = {}

    for receipt_id, evaluations in all_results.items():
        for ev in evaluations:
            metric = ev["metric"]
            score = ev.get("score")
            if score is not None:
                metric_scores.setdefault(metric, []).append(score)

    summary = {}
    for metric, scores in metric_scores.items():
        n = len(scores)
        avg = sum(scores) / n if n else 0
        perfect = sum(1 for s in scores if s == 1.0)
        summary[metric] = {
            "average": round(avg, 3),
            "perfect_count": perfect,
            "total_count": n,
            "perfect_rate": round(perfect / n, 3) if n else 0,
        }

    return summary


def print_report(
    all_results: Dict[str, List[Dict]],
    summary: Dict[str, Any],
):
    """Print a human-readable evaluation report."""
    print("=" * 70)
    print("RECEIPT PARSING EVALUATION REPORT")
    print("=" * 70)
    print(f"\nReceipts evaluated: {len(all_results)}\n")

    # Summary table
    print(f"{'Metric':<25} {'Avg Score':>10} {'Perfect':>10} {'Total':>8} {'Rate':>8}")
    print("-" * 65)
    for metric, stats in summary.items():
        print(
            f"{metric:<25} {stats['average']:>10.3f} "
            f"{stats['perfect_count']:>10} {stats['total_count']:>8} "
            f"{stats['perfect_rate']:>7.1%}"
        )

    # Per-receipt details (failures only)
    print("\n" + "=" * 70)
    print("FAILURES BY RECEIPT")
    print("=" * 70)
    for receipt_id, evaluations in all_results.items():
        failures = [ev for ev in evaluations if ev.get("score") is not None and ev["score"] < 1.0]
        if failures:
            print(f"\n  {receipt_id}:")
            for f in failures:
                detail = ""
                if "predicted" in f and "expected" in f:
                    detail = f" (predicted={f['predicted']}, expected={f['expected']})"
                elif "diff_cents" in f:
                    detail = f" (diff={f['diff_cents']} cents)"
                print(f"    FAIL {f['metric']}: score={f['score']}{detail}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate receipt parsing accuracy")
    parser.add_argument(
        "--ground-truth", "-g",
        required=True,
        help="Directory containing ground truth JSON files",
    )
    parser.add_argument(
        "--predictions", "-p",
        required=False,
        help="Directory containing prediction JSON files (output from pipeline)",
    )
    parser.add_argument(
        "--output", "-o",
        required=False,
        help="Path to save JSON report",
    )
    args = parser.parse_args()

    gt_dir = Path(args.ground_truth)
    if not gt_dir.is_dir():
        print(f"ERROR: Ground truth directory not found: {gt_dir}", file=sys.stderr)
        sys.exit(1)

    ground_truths = load_json_files(gt_dir)
    if not ground_truths:
        print(f"ERROR: No JSON files found in {gt_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(ground_truths)} ground truth files from {gt_dir}")

    if args.predictions:
        pred_dir = Path(args.predictions)
        predictions = load_json_files(pred_dir)
        print(f"Loaded {len(predictions)} prediction files from {pred_dir}")
    else:
        print("ERROR: --predictions is required (live evaluation not yet implemented)")
        sys.exit(1)

    # Match ground truth to predictions by filename stem
    all_results = {}
    matched = 0
    for gt_name, gt_data in ground_truths.items():
        if gt_name in predictions:
            matched += 1
            all_results[gt_name] = evaluate_single(predictions[gt_name], gt_data)
        else:
            print(f"  WARNING: No prediction found for ground truth: {gt_name}", file=sys.stderr)

    if not all_results:
        print("ERROR: No matching ground truth / prediction pairs found", file=sys.stderr)
        sys.exit(1)

    print(f"Matched {matched} pairs\n")

    summary = aggregate_scores(all_results)
    print_report(all_results, summary)

    # Save JSON report
    if args.output:
        report = {
            "summary": summary,
            "receipts": {
                rid: evals for rid, evals in all_results.items()
            },
        }
        out_path = Path(args.output)
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nJSON report saved to {out_path}")


if __name__ == "__main__":
    main()
