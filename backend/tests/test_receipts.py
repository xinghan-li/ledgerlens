"""
Receipt Pipeline V2 Test Runner

This script tests the receipt processing pipeline against various input fixtures.

Usage:
    python backend/tests/test_receipts.py                    # Run all tests
    python backend/tests/test_receipts.py tnt_1              # Run specific test
    python backend/tests/test_receipts.py tnt_1 tnt_2       # Run multiple tests
    python backend/tests/test_receipts.py 20260205_143022_1  # Test auto-saved fixture

Test files:
    Input:    backend/tests/fixtures/{name}.json
    Expected: backend/tests/fixtures/{name}_expected.json (optional)
    Output:   backend/tests/output/{name}_actual.json

🚀 AUTO-SAVE FEATURE:
    Every call to /api/receipt/initial-parse automatically saves a fixture to:
    backend/tests/fixtures/YYYYMMDD_HHMMSS_{counter}.json
    
    You can directly test these auto-generated files:
    python backend/tests/test_receipts.py 20260205_143022_1
    
    Or rename them for clarity:
    20260205_143022_1.json → tnt_payment_issue.json

The script will:
1. Load OCR blocks from fixtures/{name}.json
2. Run the receipt_pipeline_v2
3. Save actual output to output/{name}_actual.json
4. Compare with expected output if {name}_expected.json exists
5. Print detailed results

See backend/tests/README.md for fixture format and examples.
"""
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.receipt_pipeline_v2 import process_receipt_pipeline
from app.processors.validation.store_config_loader import load_store_config


def load_test_fixture(fixture_name: str) -> Dict[str, Any]:
    """Load test fixture JSON."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixture_path = fixtures_dir / f"{fixture_name}.json"
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_expected_output(fixture_name: str) -> Optional[Dict[str, Any]]:
    """Load expected output JSON if it exists."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    expected_path = fixtures_dir / f"{fixture_name}_expected.json"
    if not expected_path.exists():
        return None
    with open(expected_path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_results(actual: Dict[str, Any], expected: Dict[str, Any]) -> List[str]:
    """Compare actual and expected results, return list of differences."""
    diffs = []
    
    # Compare success
    if actual.get("success") != expected.get("success"):
        diffs.append(f"❌ success: actual={actual.get('success')}, expected={expected.get('success')}")
    
    # Compare item count
    actual_items = actual.get("items", [])
    expected_items = expected.get("items", [])
    if len(actual_items) != len(expected_items):
        diffs.append(f"❌ item_count: actual={len(actual_items)}, expected={len(expected_items)}")
    
    # Compare each item
    for i, (actual_item, expected_item) in enumerate(zip(actual_items, expected_items)):
        if actual_item.get("product_name") != expected_item.get("product_name"):
            diffs.append(f"❌ item[{i}].product_name: actual='{actual_item.get('product_name')}', expected='{expected_item.get('product_name')}'")
        if actual_item.get("line_total") != expected_item.get("line_total"):
            diffs.append(f"❌ item[{i}].line_total: actual={actual_item.get('line_total')} (${actual_item.get('line_total')/100:.2f}), expected={expected_item.get('line_total')} (${expected_item.get('line_total')/100:.2f})")
        if actual_item.get("quantity") != expected_item.get("quantity"):
            diffs.append(f"❌ item[{i}].quantity: actual={actual_item.get('quantity')}, expected={expected_item.get('quantity')}")
        if actual_item.get("unit") != expected_item.get("unit"):
            diffs.append(f"❌ item[{i}].unit: actual={actual_item.get('unit')}, expected={expected_item.get('unit')}")
        if actual_item.get("unit_price") != expected_item.get("unit_price"):
            diffs.append(f"❌ item[{i}].unit_price: actual={actual_item.get('unit_price')}, expected={expected_item.get('unit_price')}")
        if actual_item.get("on_sale") != expected_item.get("on_sale"):
            diffs.append(f"❌ item[{i}].on_sale: actual={actual_item.get('on_sale')}, expected={expected_item.get('on_sale')}")
    
    # Compare totals
    actual_totals = actual.get("totals", {})
    expected_totals = expected.get("totals", {})
    for key in ["subtotal", "tax", "total"]:
        if actual_totals.get(key) != expected_totals.get(key):
            diffs.append(f"❌ totals.{key}: actual={actual_totals.get(key)}, expected={expected_totals.get(key)}")
    
    # Compare validation
    if actual.get("item_sum_check") != expected.get("item_sum_check"):
        diffs.append(f"❌ item_sum_check: actual={actual.get('item_sum_check')}, expected={expected.get('item_sum_check')}")
    if actual.get("total_sum_check") != expected.get("total_sum_check"):
        diffs.append(f"❌ total_sum_check: actual={actual.get('total_sum_check')}, expected={expected.get('total_sum_check')}")
    
    return diffs


def run_test(fixture_name: str, verbose: bool = False) -> bool:
    """Run test for a single fixture. Returns True if passed."""
    print(f"\n{'='*80}")
    print(f"Testing: {fixture_name}")
    print(f"{'='*80}")
    
    try:
        # Load fixture
        fixture = load_test_fixture(fixture_name)
        blocks = fixture.get("blocks", [])
        chain_id = fixture.get("chain_id")
        
        # Load store config if chain_id provided
        store_config = None
        if chain_id:
            store_config = load_store_config(chain_id)
            if store_config:
                print(f"✓ Loaded store config for: {chain_id}")
        
        # Run pipeline
        print(f"Processing {len(blocks)} blocks...")
        result = process_receipt_pipeline(blocks, llm_result={}, store_config=store_config)
        
        # Print summary
        print(f"\n📊 Result Summary:")
        print(f"  Success: {result.get('success')}")
        print(f"  Method: {result.get('method')}")
        print(f"  Store: {result.get('store', 'N/A')}")
        print(f"  Items: {len(result.get('items', []))}")
        print(f"  Item sum check: {result.get('item_sum_check')}")
        print(f"  Total sum check: {result.get('total_sum_check')}")
        
        # Print items
        print(f"\n📝 Items:")
        for i, item in enumerate(result.get("items", []), 1):
            sale_flag = " [SALE]" if item.get("on_sale") else ""
            qty_str = f" (qty={item.get('quantity', 1)}" + (f" {item.get('unit')}" if item.get('unit') else "") + ")" if item.get('quantity') != 1 or item.get('unit') else ""
            unit_price_str = f" @ ${item.get('unit_price')/100:.2f}" if item.get('unit_price') else ""
            print(f"  {i}. {item['product_name']}{sale_flag}{qty_str}{unit_price_str} = ${item['line_total']/100:.2f}")
        
        # Print totals
        totals = result.get("totals", {})
        print(f"\n💰 Totals:")
        if totals.get("subtotal"):
            print(f"  Subtotal: ${totals['subtotal']:.2f}")
        if totals.get("tax"):
            print(f"  Tax: ${totals['tax']:.2f}")
        if totals.get("total"):
            print(f"  Total: ${totals['total']:.2f}")
        
        # Save actual output
        output_dir = Path(__file__).parent / "output"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / f"{fixture_name}_actual.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Saved actual output to: {output_path}")
        
        # Compare with expected if exists
        expected = load_expected_output(fixture_name)
        if expected:
            print(f"\n🔍 Comparing with expected output...")
            diffs = compare_results(result, expected)
            if diffs:
                print(f"\n❌ Found {len(diffs)} differences:")
                for diff in diffs:
                    print(f"  {diff}")
                return False
            else:
                print(f"\n✅ All checks passed!")
                return True
        else:
            print(f"\n⚠️  No expected output found (create {fixture_name}_expected.json to enable comparison)")
            return True
    
    except Exception as e:
        print(f"\n💥 Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test runner."""
    # Get test name from command line or run all
    if len(sys.argv) > 1:
        test_name = sys.argv[1]
        fixtures = [test_name]
    else:
        # Find all fixtures
        fixtures_dir = Path(__file__).parent / "fixtures"
        if not fixtures_dir.exists():
            print(f"❌ Fixtures directory not found: {fixtures_dir}")
            print(f"Create test fixtures in: {fixtures_dir}")
            return
        
        fixtures = []
        for path in fixtures_dir.glob("*.json"):
            if not path.name.endswith("_expected.json"):
                fixtures.append(path.stem)
        
        if not fixtures:
            print(f"❌ No test fixtures found in: {fixtures_dir}")
            print(f"Create test fixtures (e.g. tnt_1.json) with OCR blocks")
            return
    
    # Run tests
    results = {}
    for fixture_name in fixtures:
        passed = run_test(fixture_name, verbose=True)
        results[fixture_name] = passed
    
    # Print summary
    print(f"\n{'='*80}")
    print(f"Test Summary")
    print(f"{'='*80}")
    total = len(results)
    passed = sum(1 for p in results.values() if p)
    failed = total - passed
    
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {total}, Passed: {passed}, Failed: {failed}")
    
    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
