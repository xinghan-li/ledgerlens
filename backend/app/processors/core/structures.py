"""
Receipt Processing Data Structures.

This module defines unified data structures for receipt processing pipeline.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class RowType(Enum):
    """Row type classification."""
    UNKNOWN = "UNKNOWN"
    HEADER = "HEADER"
    ITEM = "ITEM"
    TOTALS = "TOTALS"
    PAYMENT = "PAYMENT"


@dataclass
class TextBlock:
    """Represents a single text block from OCR."""
    text: str
    x: float
    y: float
    center_x: float
    center_y: float
    is_amount: bool
    amount: Optional[float]
    block_id: int
    width: Optional[float] = None
    height: Optional[float] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)  # Store original OCR data

    @classmethod
    def from_dict(cls, block_dict: Dict[str, Any], block_id: int) -> "TextBlock":
        """Create TextBlock from OCR block dictionary."""
        return cls(
            text=block_dict.get("text", "").strip(),
            x=block_dict.get("x", 0.0),
            y=block_dict.get("y", 0.0),
            center_x=block_dict.get("center_x") or block_dict.get("x", 0.0),
            center_y=block_dict.get("center_y") or block_dict.get("y", 0.0),
            is_amount=block_dict.get("is_amount", False),
            amount=block_dict.get("amount"),
            block_id=block_id,
            width=block_dict.get("width"),
            height=block_dict.get("height"),
            raw_data=block_dict
        )


@dataclass
class PhysicalRow:
    """Represents a physical row on the receipt."""
    row_id: int
    blocks: List[TextBlock]
    y_top: float
    y_bottom: float
    y_center: float
    text: str
    row_type: RowType = RowType.UNKNOWN

    def get_amount_blocks(self) -> List[TextBlock]:
        """Get all amount blocks in this row."""
        return [b for b in self.blocks if b.is_amount and b.amount is not None]

    def get_text_blocks(self) -> List[TextBlock]:
        """Get all non-amount text blocks in this row."""
        return [b for b in self.blocks if not b.is_amount]


@dataclass
class ReceiptRegions:
    """Represents partitioned receipt regions."""
    header_rows: List[PhysicalRow] = field(default_factory=list)
    item_rows: List[PhysicalRow] = field(default_factory=list)
    totals_rows: List[PhysicalRow] = field(default_factory=list)
    payment_rows: List[PhysicalRow] = field(default_factory=list)

    def get_all_rows(self) -> List[PhysicalRow]:
        """Get all rows in order."""
        return (self.header_rows + self.item_rows +
                self.totals_rows + self.payment_rows)


@dataclass
class AmountColumn:
    """Represents a detected amount column."""
    center_x: float
    tolerance: float
    confidence: float = 1.0
    block_count: int = 0


@dataclass
class AmountColumns:
    """Represents all detected amount columns."""
    main_column: AmountColumn
    all_columns: List[AmountColumn] = field(default_factory=list)

    def is_in_column(self, block: TextBlock, column: Optional[AmountColumn] = None) -> bool:
        """Check if a block is in the specified column (or main column)."""
        target = column or self.main_column
        return abs(block.center_x - target.center_x) <= target.tolerance


class AmountUsageTracker:
    """Tracks which amount blocks have been used and their roles."""

    def __init__(self):
        self.used_block_ids: Dict[int, str] = {}  # block_id -> role
        self.used_y_coordinates: Dict[float, str] = {}  # rounded_y -> role
        self.usage_log: List[Dict[str, Any]] = []  # For debugging

    def mark_used(self, block: TextBlock, role: str, row_id: Optional[int] = None):
        """Mark a block as used with a specific role."""
        self.used_block_ids[block.block_id] = role
        y_rounded = round(block.center_y, 3)
        self.used_y_coordinates[y_rounded] = role

        log_entry = {
            "block_id": block.block_id,
            "amount": block.amount,
            "role": role,
            "y": int(block.center_y * 10000),
            "x": int(block.center_x * 10000),
            "row_id": row_id
        }
        self.usage_log.append(log_entry)

    def is_used(self, block: TextBlock) -> bool:
        """Check if a block has been used."""
        return block.block_id in self.used_block_ids

    def get_role(self, block: TextBlock) -> Optional[str]:
        """Get the role of a used block."""
        return self.used_block_ids.get(block.block_id)

    def get_usage_summary(self) -> Dict[str, Any]:
        """Get summary of usage for debugging."""
        role_counts = {}
        for role in self.used_block_ids.values():
            role_counts[role] = role_counts.get(role, 0) + 1

        return {
            "total_used": len(self.used_block_ids),
            "role_distribution": role_counts,
            "usage_log": self.usage_log
        }


@dataclass
class ExtractedItem:
    """Represents an extracted receipt item."""
    product_name: str
    line_total: float
    amount_block_id: int
    row_id: int
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    unit: Optional[str] = None  # e.g. "1/100 lb" for weight-based items
    raw_text: str = ""
    confidence: float = 1.0  # Based on math validation
    on_sale: bool = False  # True if (SALE) prefix was found and removed


@dataclass
class TotalsSequence:
    """Represents the totals sequence (subtotal + fees + tax = total)."""
    subtotal: Optional[TextBlock] = None
    subtotal_row: Optional[PhysicalRow] = None
    total: Optional[TextBlock] = None
    total_row: Optional[PhysicalRow] = None
    middle_amounts: List[TextBlock] = field(default_factory=list)
    middle_rows: List[PhysicalRow] = field(default_factory=list)

    def get_calculated_total(self) -> float:
        """Calculate total from subtotal + middle amounts."""
        if not self.subtotal or not self.subtotal.amount:
            return 0.0
        subtotal_val = self.subtotal.amount
        middle_sum = sum(b.amount for b in self.middle_amounts if b.amount)
        return subtotal_val + middle_sum
