"""
Base class for merchant-specific processors.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)


class MerchantProcessor(ABC):
    """
    Base class for merchant-specific receipt processing.
    
    Each merchant processor can override methods to handle:
    - Item name expansion (e.g., Walmart abbreviations)
    - Merchant-specific cleaning rules
    - Custom validation logic
    - Category mapping
    """
    
    # Merchant identification
    MERCHANT_NAMES = []  # e.g., ["Walmart", "Walmart Supercenter"]
    MERCHANT_ALIASES = []  # Common OCR errors or variations
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    def applies_to(self, merchant_name: str) -> bool:
        """
        Check if this processor applies to the given merchant.
        
        Args:
            merchant_name: Merchant name from receipt
        
        Returns:
            True if this processor should be applied
        """
        if not merchant_name:
            return False
        
        merchant_lower = merchant_name.lower()
        
        # Check exact matches and aliases
        all_names = self.MERCHANT_NAMES + self.MERCHANT_ALIASES
        return any(name.lower() in merchant_lower for name in all_names)
    
    def process(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point for processing.
        
        Calls various processing steps in order:
        1. Clean items
        2. Expand abbreviations
        3. Extract merchant-specific fields
        4. Validate
        
        Args:
            llm_result: LLM processing result
        
        Returns:
            Processed result
        """
        receipt = llm_result.get("receipt", {})
        merchant_name = receipt.get("merchant_name", "")
        
        if not self.applies_to(merchant_name):
            self.logger.debug(f"Processor {self.__class__.__name__} does not apply to {merchant_name}")
            return llm_result
        
        self.logger.info(f"Applying {self.__class__.__name__} to {merchant_name}")
        
        # Step 1: Clean items (remove non-product lines)
        llm_result = self.clean_items(llm_result)
        
        # Step 2: Expand abbreviations
        llm_result = self.expand_item_names(llm_result)
        
        # Step 3: Extract merchant-specific fields
        llm_result = self.extract_custom_fields(llm_result)
        
        # Step 4: Custom validation
        llm_result = self.validate(llm_result)
        
        return llm_result
    
    def clean_items(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove non-product items (e.g., loyalty points, membership cards).
        
        Override in subclass for merchant-specific cleaning.
        """
        return llm_result
    
    def expand_item_names(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Expand abbreviated item names.
        
        Override in subclass for merchant-specific abbreviations.
        Example: "GV MILK 2%" → "Great Value Milk 2%"
        """
        return llm_result
    
    def extract_custom_fields(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract merchant-specific fields.
        
        Override in subclass for custom fields.
        Example: membership number, reward points, etc.
        """
        return llm_result
    
    def validate(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform merchant-specific validation.
        
        Override in subclass for custom validation.
        """
        return llm_result
