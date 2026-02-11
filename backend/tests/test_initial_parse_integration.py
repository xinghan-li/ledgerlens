"""Test initial parse integration with workflow."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.processors.validation.coordinate_extractor import extract_text_blocks_with_coordinates
from app.processors.validation.pipeline import process_receipt_pipeline
from app.processors.validation.store_config_loader import get_store_config_for_receipt
from app.prompts.prompt_manager import format_prompt

def test_initial_parse_in_prompt():
    """Test that initial parse result is included in prompt."""
    # Load test fixture
    fixture_path = Path(__file__).parent / "fixtures" / "20260210_170524_1.json"
    data = json.load(open(fixture_path, encoding='utf-8'))
    blocks = data.get("blocks", [])
    merchant_name = data.get("merchant_name", "TRADER JOE'S")
    
    # Simulate initial parse
    store_config = get_store_config_for_receipt(merchant_name, blocks=blocks)
    initial_parse_result = process_receipt_pipeline(
        blocks=blocks,
        llm_result={},
        store_config=store_config,
        merchant_name=merchant_name
    )
    
    print("=== Initial Parse Result ===")
    print(f"Success: {initial_parse_result.get('success')}")
    print(f"Method: {initial_parse_result.get('method')}")
    print(f"Items: {len(initial_parse_result.get('items', []))}")
    print(f"Total: {initial_parse_result.get('totals', {}).get('total')}")
    
    # Test float precision
    ocr_blocks = initial_parse_result.get("ocr_blocks", [])
    if ocr_blocks:
        sample = ocr_blocks[0]
        print(f"\n=== Float Precision Check ===")
        for key, value in sample.items():
            if isinstance(value, float):
                str_val = str(value)
                decimals = len(str_val.split('.')[1]) if '.' in str_val else 0
                status = "OK" if decimals <= 5 else "ERROR"
                print(f"{key}: {value} ({decimals} decimals) [{status}]")
    
    # Format prompt with initial parse
    raw_text = "Test receipt text"
    trusted_hints = {}
    
    system_message, user_message, rag_metadata = format_prompt(
        raw_text=raw_text,
        trusted_hints=trusted_hints,
        prompt_config=None,
        merchant_name=merchant_name,
        initial_parse_result=initial_parse_result
    )
    
    print(f"\n=== Prompt Integration Check ===")
    print(f"Initial parse in RAG metadata: {rag_metadata.get('initial_parse_provided', False)}")
    print(f"Initial parse method: {rag_metadata.get('initial_parse_method')}")
    print(f"Initial parse items: {rag_metadata.get('initial_parse_items_count')}")
    
    # Check if initial parse is in user_message
    has_initial_parse = "Initial Parse Result" in user_message
    print(f"Initial parse in user_message: {has_initial_parse}")
    
    if has_initial_parse:
        # Find and display the initial parse section
        start_idx = user_message.find("## Initial Parse Result")
        end_idx = user_message.find("## Raw Text:", start_idx)
        if start_idx > 0:
            snippet = user_message[start_idx:start_idx+500]
            print(f"\nUser message snippet (first 500 chars of initial parse section):")
            print(snippet)
            print("...")
    
    print("\n=== TEST PASSED ===")

if __name__ == "__main__":
    test_initial_parse_in_prompt()
