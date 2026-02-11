"""
Tax and Fee Classifier: Classify middle amounts as tax or fees with fuzzy matching.

This module implements Step 6 of the receipt processing pipeline.
"""
from typing import List, Tuple, Optional
import logging
from enum import Enum
from .receipt_structures import PhysicalRow, TextBlock, AmountUsageTracker
from .fuzzy_label_matcher import fuzzy_match_label

logger = logging.getLogger(__name__)


class FeeType(Enum):
    """Classification of fee/tax types."""
    TAX_EXPLICIT = "TAX_EXPLICIT"
    FEE_EXPLICIT = "FEE_EXPLICIT"
    FEE_GENERIC = "FEE_GENERIC"
    UNKNOWN = "UNKNOWN"


def classify_fee_or_tax(row_text: str, context: Optional[dict] = None) -> Tuple[FeeType, Optional[str]]:
    """
    Classify a row as tax, fee, or unknown based on text content using fuzzy matching.
    
    Args:
        row_text: Text content of the row
        context: Optional context for fuzzy matching (region, has_amount_on_right, column_role)
        
    Returns:
        Tuple of (FeeType enum value, normalized_label) where normalized_label is the matched
        standard label if found, or None
    """
    # Use fuzzy matching to find best match
    # First try tax candidates
    tax_match = fuzzy_match_label(
        row_text,
        candidates=None,  # Will use context to select
        context={**(context or {}), "column_role": "TAX"}
    )
    
    if tax_match:
        matched_label, score = tax_match
        logger.debug(f"Fuzzy matched '{row_text}' → '{matched_label}' (tax, score={score:.3f})")
        return FeeType.TAX_EXPLICIT, matched_label
    
    # Try fee candidates
    fee_match = fuzzy_match_label(
        row_text,
        candidates=None,
        context={**(context or {}), "column_role": "FEE_OR_TAX"}
    )
    
    if fee_match:
        matched_label, score = fee_match
        logger.debug(f"Fuzzy matched '{row_text}' → '{matched_label}' (fee, score={score:.3f})")
        return FeeType.FEE_EXPLICIT, matched_label
    
    # Fallback to keyword-based classification
    normalized = _fuzzy_normalize(row_text)
    
    # Explicit tax indicators
    tax_keywords = ['TAX', 'VAT', 'GST', 'SALES TAX']
    if any(kw in normalized for kw in tax_keywords) or '%' in row_text:
        return FeeType.TAX_EXPLICIT, None
    
    # Explicit fee indicators
    fee_keywords = ['FEE', 'ENVIRONMENTAL', 'BOTTLE', 'DEPOSIT', 'CRF', 'ENV FEE']
    if any(kw in normalized for kw in fee_keywords):
        return FeeType.FEE_EXPLICIT, None
    
    # Generic fee/tax indicators
    generic_keywords = ['FEE/TAX', 'FEE TAX', 'FEE AND TAX']
    if any(kw in normalized for kw in generic_keywords):
        return FeeType.FEE_GENERIC, None
    
    return FeeType.UNKNOWN, None


def extract_tax_and_fees(
    totals_sequence: "TotalsSequence",
    tracker: AmountUsageTracker
) -> Tuple[List[dict], List[dict]]:
    """
    Extract tax and fees from middle amounts with priority handling.
    
    Args:
        totals_sequence: TotalsSequence with middle_amounts and middle_rows populated
        tracker: AmountUsageTracker to mark used blocks
        
    Returns:
        Tuple of (tax_list, fees_list) where both are lists of dicts with 'label' and 'amount'
    """
    tax_list = []  # List of dicts with 'label' and 'amount' for each tax line
    fees = []
    
    # Pair middle amounts with their rows
    amount_row_pairs = list(zip(totals_sequence.middle_amounts, totals_sequence.middle_rows))
    
    for block, row in amount_row_pairs:
        if tracker.is_used(block):
            continue
        
        # Build context for fuzzy matching
        context = {
            "region": "TOTALS",
            "has_amount_on_right": True,
            "column_role": "FEE_OR_TAX"
        }
        
        fee_type, normalized_label = classify_fee_or_tax(row.text, context=context)
        
        # Use normalized label if available, otherwise use original text
        display_label = normalized_label or row.text
        
        if fee_type == FeeType.TAX_EXPLICIT:
            # Add to tax_list
            tax_list.append({"label": display_label, "amount": block.amount})
            tracker.mark_used(block, role="TAX", row_id=row.row_id)
            logger.info(f"✓ Identified TAX: ${block.amount:.2f} from '{row.text}' → '{display_label}'")
        
        elif fee_type == FeeType.FEE_EXPLICIT:
            fees.append({"label": display_label, "amount": block.amount})
            tracker.mark_used(block, role="FEE", row_id=row.row_id)
            logger.info(f"✓ Identified FEE (explicit): ${block.amount:.2f} from '{row.text}' → '{display_label}'")
        
        elif fee_type == FeeType.FEE_GENERIC:
            # Generic fee/tax - add to fees
            fees.append({"label": display_label, "amount": block.amount})
            tracker.mark_used(block, role="FEE_GENERIC", row_id=row.row_id)
            logger.info(f"✓ Identified FEE (generic): ${block.amount:.2f} from '{row.text}' → '{display_label}'")
        
        else:
            # Unknown - add to fees as fallback
            fees.append({"label": display_label or "Unknown Fee", "amount": block.amount})
            tracker.mark_used(block, role="FEE_UNKNOWN", row_id=row.row_id)
            logger.warning(f"⚠ Unclassified amount added to fees: ${block.amount:.2f} from '{row.text}' → '{display_label}'")
    
    # Calculate total tax for validation
    total_tax = sum(tax["amount"] for tax in tax_list)
    
    # Validate tax amount (should be < 20% of subtotal)
    if total_tax > 0 and totals_sequence.subtotal and totals_sequence.subtotal.amount:
        subtotal_val = totals_sequence.subtotal.amount
        tax_percentage = (total_tax / subtotal_val) * 100
        if tax_percentage > 20.0:
            logger.warning(
                f"⚠ Tax validation failed: Tax ${total_tax:.2f} is {tax_percentage:.1f}% of subtotal "
                f"${subtotal_val:.2f} (expected < 20%)"
            )
            # Move all taxes to fees
            for tax_item in tax_list:
                fees.append({"label": f"{tax_item['label']} (invalid - >20%)", "amount": tax_item["amount"]})
            tax_list = []
            logger.warning("  → Moved all taxes to fees, tax list cleared")
        else:
            logger.info(
                f"✓ Tax validation passed: Total tax ${total_tax:.2f} ({len(tax_list)} taxes) is {tax_percentage:.1f}% of subtotal "
                f"${subtotal_val:.2f}"
            )
            # Log individual tax components
            for tax_item in tax_list:
                logger.info(f"  - {tax_item['label']}: ${tax_item['amount']:.2f}")
    
    return tax_list, fees


def _fuzzy_normalize(text: str) -> str:
    """Normalize text for fuzzy matching."""
    import re
    return re.sub(r'[.\s\-_]', '', text.upper())
