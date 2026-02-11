"""
Column Detection: Detect amount columns using statistical methods.

This module implements Step 2 of the receipt processing pipeline.
"""
from typing import List, Dict, Any
import logging
from collections import Counter
from .receipt_structures import TextBlock, AmountColumn, AmountColumns

logger = logging.getLogger(__name__)

# Default bin size for histogram (1% of page width)
DEFAULT_BIN_SIZE = 0.01
# Minimum number of amounts in a column to be considered valid
MIN_COLUMN_COUNT = 3


def detect_amount_columns(
    blocks: List[TextBlock],
    bin_size: float = DEFAULT_BIN_SIZE,
    max_clusters: int = 3
) -> AmountColumns:
    """
    Detect amount columns by building a histogram of amount X coordinates.
    
    Args:
        blocks: List of TextBlock objects (should include amount blocks)
        bin_size: Size of histogram bins (default 0.01 = 1% of page width)
        max_clusters: Maximum number of columns to detect
        
    Returns:
        AmountColumns object with main column and all detected columns
    """
    # Extract amount blocks
    amount_blocks = [b for b in blocks if b.is_amount and b.amount is not None]
    
    if not amount_blocks:
        logger.warning("No amount blocks found for column detection")
        # Return a default right-aligned column
        return AmountColumns(
            main_column=AmountColumn(center_x=0.5, tolerance=0.1, confidence=0.0)
        )
    
    # Build histogram of X coordinates
    xs = [b.center_x for b in amount_blocks]
    histogram = _build_histogram(xs, bin_size)
    
    # Find peaks in histogram
    peaks = _find_histogram_peaks(histogram, min_count=MIN_COLUMN_COUNT)
    
    if not peaks:
        logger.warning("No clear column peaks found, using rightmost amounts")
        # Fallback: use rightmost amounts
        rightmost_x = max(xs)
        return AmountColumns(
            main_column=AmountColumn(
                center_x=rightmost_x,
                tolerance=bin_size * 2,
                confidence=0.5,
                block_count=len(amount_blocks)
            )
        )
    
    # Sort peaks by X coordinate (left to right)
    peaks_sorted = sorted(peaks, key=lambda p: p["center_x"])
    
    # Select rightmost peak as main column (amounts are typically right-aligned)
    main_peak = peaks_sorted[-1]
    main_column = AmountColumn(
        center_x=main_peak["center_x"],
        tolerance=bin_size * 2,  # 2x bin size as tolerance
        confidence=main_peak["confidence"],
        block_count=main_peak["count"]
    )
    
    # Create AmountColumn objects for all peaks
    all_columns = [
        AmountColumn(
            center_x=p["center_x"],
            tolerance=bin_size * 2,
            confidence=p["confidence"],
            block_count=p["count"]
        )
        for p in peaks_sorted
    ]
    
    logger.info(
        f"Detected {len(peaks)} amount columns: "
        f"main column at X={main_column.center_x:.4f} "
        f"(confidence={main_column.confidence:.2f}, {main_column.block_count} blocks)"
    )
    
    return AmountColumns(
        main_column=main_column,
        all_columns=all_columns
    )


def _build_histogram(xs: List[float], bin_size: float) -> Dict[float, int]:
    """
    Build a histogram of X coordinates.
    
    Args:
        xs: List of X coordinates
        bin_size: Size of each bin
        
    Returns:
        Dictionary mapping bin_center -> count
    """
    histogram = Counter()
    
    for x in xs:
        # Round to nearest bin center
        bin_center = round(x / bin_size) * bin_size
        histogram[bin_center] += 1
    
    return dict(histogram)


def _find_histogram_peaks(
    histogram: Dict[float, int],
    min_count: int = MIN_COLUMN_COUNT
) -> List[Dict[str, Any]]:
    """
    Find peaks in histogram (local maxima with sufficient count).
    
    Args:
        histogram: Dictionary mapping bin_center -> count
        min_count: Minimum count to be considered a peak
        
    Returns:
        List of peak dictionaries with center_x, count, and confidence
    """
    if not histogram:
        return []
    
    # Sort by bin center
    sorted_bins = sorted(histogram.items())
    peaks = []
    
    for i, (bin_center, count) in enumerate(sorted_bins):
        if count < min_count:
            continue
        
        # Check if this is a local maximum
        is_peak = True
        if i > 0:
            prev_count = sorted_bins[i - 1][1]
            if count <= prev_count:
                is_peak = False
        
        if i < len(sorted_bins) - 1:
            next_count = sorted_bins[i + 1][1]
            if count <= next_count:
                is_peak = False
        
        if is_peak:
            # Calculate confidence based on count relative to max count
            max_count = max(c for _, c in sorted_bins)
            confidence = count / max_count if max_count > 0 else 0.0
            
            peaks.append({
                "center_x": bin_center,
                "count": count,
                "confidence": confidence
            })
    
    return peaks
