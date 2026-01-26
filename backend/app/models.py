"""
Pydantic models for API request/response schemas.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from decimal import Decimal
from datetime import datetime


class ReceiptOCRResponse(BaseModel):
    """Response model for receipt OCR endpoint."""
    id: Optional[str] = None
    filename: str
    text: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "filename": "receipt.jpg",
                "text": "Extracted OCR text here..."
            }
        }


class ReceiptItemResponse(BaseModel):
    """Response model for receipt item."""
    id: Optional[int] = None
    line_index: int
    product_name: str
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    line_total: Optional[float] = None
    is_on_sale: bool = False
    category: Optional[str] = None


class ReceiptIngestRequest(BaseModel):
    """Request model for receipt ingestion endpoint."""
    id: Optional[str] = None
    filename: str
    text: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "filename": "receipt.jpg",
                "text": "OCR extracted text..."
            }
        }


class DocumentAIResultRequest(BaseModel):
    """Request model for LLM processing endpoint - accepts Document AI JSON output."""
    filename: str
    data: dict = Field(
        ...,
        description="Complete JSON data returned by Document AI (contains raw_text, entities, line_items, etc.)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "filename": "receipt.jpg",
                "data": {
                    "raw_text": "Receipt text...",
                    "entities": {
                        "supplier_name": {"value": "T&T Supermarket", "confidence": 1.0}
                    },
                    "line_items": [
                        {"raw_text": "EGG TRAY BUN", "line_total": 6.50}
                    ]
                }
            }
        }


class ReceiptIngestResponse(BaseModel):
    """Response model for receipt ingestion endpoint."""
    receipt_id: int
    merchant_name: Optional[str] = None
    merchant_id: Optional[int] = None
    purchase_time: Optional[datetime] = None
    total: Optional[float] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    item_count: int
    payment_method: Optional[str] = None
    items: List[ReceiptItemResponse] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "receipt_id": 1,
                "merchant_name": "T&T Supermarket US",
                "purchase_time": "2026-01-10T14:47:15",
                "total": 22.77,
                "subtotal": 22.77,
                "tax": 0.0,
                "item_count": 7,
                "payment_method": "Visa",
                "items": []
            }
        }
