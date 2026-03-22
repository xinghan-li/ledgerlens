"""
Receipt parsing evaluators.

Each evaluator takes (predicted, ground_truth) dicts and returns a score dict.
All monetary values are in CENTS (integers).
"""
from typing import Any, Dict, List, Optional


def evaluate_total(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """Check if receipt.total matches."""
    p_total = (predicted.get("receipt") or {}).get("total")
    t_total = (truth.get("receipt") or {}).get("total")
    if t_total is None:
        return {"metric": "total_match", "score": None, "reason": "no ground truth total"}
    match = p_total == t_total
    diff = abs((p_total or 0) - t_total)
    return {
        "metric": "total_match",
        "score": 1.0 if match else 0.0,
        "predicted": p_total,
        "expected": t_total,
        "diff_cents": diff,
        "close": diff <= 3,  # within 3 cents tolerance
    }


def evaluate_subtotal(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """Check if receipt.subtotal matches."""
    p = (predicted.get("receipt") or {}).get("subtotal")
    t = (truth.get("receipt") or {}).get("subtotal")
    if t is None:
        return {"metric": "subtotal_match", "score": None, "reason": "no ground truth"}
    match = p == t
    diff = abs((p or 0) - t)
    return {
        "metric": "subtotal_match",
        "score": 1.0 if match else 0.0,
        "predicted": p,
        "expected": t,
        "diff_cents": diff,
    }


def evaluate_tax(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """Check if receipt.tax matches."""
    p = (predicted.get("receipt") or {}).get("tax")
    t = (truth.get("receipt") or {}).get("tax")
    if t is None:
        return {"metric": "tax_match", "score": None, "reason": "no ground truth"}
    match = p == t
    return {
        "metric": "tax_match",
        "score": 1.0 if match else 0.0,
        "predicted": p,
        "expected": t,
    }


def evaluate_item_count(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """Check if number of items matches."""
    p_items = predicted.get("items") or []
    t_items = truth.get("items") or []
    p_count = len(p_items)
    t_count = len(t_items)
    return {
        "metric": "item_count",
        "score": 1.0 if p_count == t_count else 0.0,
        "predicted": p_count,
        "expected": t_count,
        "diff": p_count - t_count,
    }


def evaluate_item_totals(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """
    For each item in ground truth, check if a matching item exists in predicted
    with the same line_total. Uses product_name fuzzy matching.
    Returns fraction of correctly matched items.
    """
    p_items = predicted.get("items") or []
    t_items = truth.get("items") or []
    if not t_items:
        return {"metric": "item_totals", "score": None, "reason": "no ground truth items"}

    # Build lookup: product_name -> line_total for predicted
    p_lookup: Dict[str, int] = {}
    for item in p_items:
        name = (item.get("product_name") or "").strip().lower()
        if name:
            p_lookup[name] = item.get("line_total")

    matched = 0
    mismatched = []
    for t_item in t_items:
        t_name = (t_item.get("product_name") or "").strip().lower()
        t_total = t_item.get("line_total")
        if t_name in p_lookup:
            if p_lookup[t_name] == t_total:
                matched += 1
            else:
                mismatched.append({
                    "product": t_name,
                    "expected": t_total,
                    "predicted": p_lookup[t_name],
                })
        else:
            mismatched.append({"product": t_name, "expected": t_total, "predicted": None})

    score = matched / len(t_items) if t_items else 0.0
    return {
        "metric": "item_totals",
        "score": round(score, 3),
        "matched": matched,
        "total": len(t_items),
        "mismatched": mismatched[:10],  # cap for readability
    }


def evaluate_date(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """Check purchase_date matches."""
    p = (predicted.get("receipt") or {}).get("purchase_date")
    t = (truth.get("receipt") or {}).get("purchase_date")
    if not t:
        return {"metric": "date_match", "score": None, "reason": "no ground truth"}
    return {
        "metric": "date_match",
        "score": 1.0 if p == t else 0.0,
        "predicted": p,
        "expected": t,
    }


def evaluate_merchant(predicted: Dict, truth: Dict) -> Dict[str, Any]:
    """Check merchant_name matches (case-insensitive contains)."""
    p = (predicted.get("receipt") or {}).get("merchant_name") or ""
    t = (truth.get("receipt") or {}).get("merchant_name") or ""
    if not t:
        return {"metric": "merchant_match", "score": None, "reason": "no ground truth"}
    match = t.lower() in p.lower() or p.lower() in t.lower()
    return {
        "metric": "merchant_match",
        "score": 1.0 if match else 0.0,
        "predicted": p,
        "expected": t,
    }


def evaluate_address_completeness(predicted: Dict, truth: Dict = None) -> Dict[str, Any]:
    """Check how many structured address fields are filled (no ground truth needed)."""
    receipt = predicted.get("receipt") or {}
    fields = ["address_line1", "city", "state", "zip_code", "country"]
    filled = sum(1 for f in fields if receipt.get(f))
    return {
        "metric": "address_completeness",
        "score": round(filled / len(fields), 3),
        "filled": filled,
        "total": len(fields),
        "missing": [f for f in fields if not receipt.get(f)],
    }


def evaluate_sum_check(predicted: Dict, truth: Dict = None) -> Dict[str, Any]:
    """Run internal sum check: items sum ≈ subtotal, subtotal + tax ≈ total."""
    receipt = predicted.get("receipt") or {}
    items = predicted.get("items") or []

    total = receipt.get("total")
    subtotal = receipt.get("subtotal")
    tax = receipt.get("tax") or 0

    items_sum = sum(item.get("line_total") or 0 for item in items)

    results = {}

    # Items sum vs subtotal
    if subtotal is not None:
        diff = abs(items_sum - subtotal)
        results["items_vs_subtotal"] = {
            "items_sum": items_sum,
            "subtotal": subtotal,
            "diff": diff,
            "passed": diff <= 3,
        }

    # Subtotal + tax vs total
    if subtotal is not None and total is not None:
        calc_total = subtotal + tax
        diff = abs(calc_total - total)
        results["subtotal_tax_vs_total"] = {
            "calculated": calc_total,
            "total": total,
            "diff": diff,
            "passed": diff <= 3,
        }

    all_passed = all(r.get("passed", True) for r in results.values())
    return {
        "metric": "sum_check",
        "score": 1.0 if all_passed else 0.0,
        "details": results,
    }


# All evaluators in evaluation order
ALL_EVALUATORS = [
    evaluate_total,
    evaluate_subtotal,
    evaluate_tax,
    evaluate_item_count,
    evaluate_item_totals,
    evaluate_date,
    evaluate_merchant,
    evaluate_address_completeness,
    evaluate_sum_check,
]
