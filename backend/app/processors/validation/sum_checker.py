"""
Re-export from processors.core.sum_checker for backward compatibility.
"""
from ..core.sum_checker import (
    check_receipt_sums,
    apply_field_conflicts_resolution,
    detect_package_price_discounts,
)
__all__ = ["check_receipt_sums", "apply_field_conflicts_resolution", "detect_package_price_discounts"]
