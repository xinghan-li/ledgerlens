"""
Google Cloud Vision API client wrapper for OCR document text detection.
"""
from google.cloud import vision
from ...config import settings
from .gcp_credentials import get_gcp_credentials
import logging

logger = logging.getLogger(__name__)

# Initialize the Vision client on module import
_client = None


def _get_client():
    """Get or create the Vision API client."""
    global _client
    if _client is None:
        credentials = get_gcp_credentials()
        _client = vision.ImageAnnotatorClient(credentials=credentials)
        logger.info("Google Cloud Vision client initialized")
    
    return _client


def ocr_document_bytes(image_bytes: bytes) -> str:
    """
    Perform OCR document text detection on image bytes.
    
    Args:
        image_bytes: Raw image file bytes
        
    Returns:
        Extracted text string from the document
        
    Raises:
        RuntimeError: If OCR fails or returns an error
    """
    client = _get_client()
    image = vision.Image(content=image_bytes)
    
    response = client.document_text_detection(image=image)
    
    if response.error.message:
        raise RuntimeError(f"Vision API error: {response.error.message}")
    
    if not response.full_text_annotation:
        return ""
    
    return response.full_text_annotation.text or ""
