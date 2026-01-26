"""
Merchant processor registry.

Automatically loads and applies merchant-specific processors.
"""
from typing import Dict, Any, List, Type
import logging

from .base import MerchantProcessor

logger = logging.getLogger(__name__)

# Registry of all available processors
# Import merchant processors as they are created
MERCHANT_PROCESSORS: List[Type[MerchantProcessor]] = [
    # Add processor classes here as they are created
    # Example: WalmartProcessor, TargetProcessor, etc.
]


def register_processor(processor_class: Type[MerchantProcessor]):
    """
    Register a merchant processor.
    
    Args:
        processor_class: Processor class to register
    """
    if processor_class not in MERCHANT_PROCESSORS:
        MERCHANT_PROCESSORS.append(processor_class)
        logger.info(f"Registered processor: {processor_class.__name__}")


def apply_merchant_processors(llm_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply all applicable merchant-specific processors.
    
    Automatically detects which processor(s) to apply based on merchant name.
    
    Args:
        llm_result: LLM processing result
    
    Returns:
        Processed result
    """
    receipt = llm_result.get("receipt", {})
    merchant_name = receipt.get("merchant_name", "")
    
    if not merchant_name:
        logger.warning("No merchant name found, skipping merchant processors")
        return llm_result
    
    # Try each processor
    applied_processors = []
    for ProcessorClass in MERCHANT_PROCESSORS:
        processor = ProcessorClass()
        
        if processor.applies_to(merchant_name):
            logger.info(f"Applying {ProcessorClass.__name__} to {merchant_name}")
            llm_result = processor.process(llm_result)
            applied_processors.append(ProcessorClass.__name__)
    
    if not applied_processors:
        logger.debug(f"No merchant-specific processor found for: {merchant_name}")
    else:
        # Add metadata
        if "_metadata" not in llm_result:
            llm_result["_metadata"] = {}
        llm_result["_metadata"]["merchant_processors_applied"] = applied_processors
    
    return llm_result
