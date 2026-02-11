"""
Standard receipt processing pipeline.

This is the default pipeline used for most receipts.
"""
from typing import List
from .base import ReceiptPipeline, PipelineStage

# Import processors (organized by function, not by stage!)
from ..processors.text.data_cleaner import clean_llm_result
from ..processors.enrichment.address_matcher import correct_address
from ..processors.stores.tnt_supermarket import clean_tnt_receipt_items
from ..processors.core.sum_checker import check_receipt_sums


def validate_wrapper(llm_result):
    """Wrapper for sum_checker to return llm_result for pipeline continuity."""
    is_valid, details = check_receipt_sums(llm_result)
    # Validation details are already added to llm_result by check_receipt_sums
    return llm_result


class StandardPipeline(ReceiptPipeline):
    """
    Standard pipeline for receipt processing.
    
    Stages:
    1. Initial data cleaning (dates, times)
    2. Merchant-specific processing (T&T currently)
    3. Address enrichment
    4. Sum validation
    """
    
    def build_stages(self) -> List[PipelineStage]:
        return [
            PipelineStage(
                name="data_cleaning",
                processor=clean_llm_result,
                required=True
            ),
            PipelineStage(
                name="merchant_processing",
                processor=clean_tnt_receipt_items,
                required=False,
                skip_on_error=True
            ),
            PipelineStage(
                name="address_correction",
                processor=lambda x: correct_address(x, auto_correct=True),
                required=False,
                skip_on_error=True
            ),
            PipelineStage(
                name="sum_validation",
                processor=validate_wrapper,
                required=True
            ),
        ]
