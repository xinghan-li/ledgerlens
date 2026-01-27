"""
FastAPI application for Receipt OCR MVP.

Run instructions:
1. Create virtual environment:
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\\Scripts\\activate

2. Install dependencies:
   pip install -r requirements.txt

3. Copy and configure environment:
   cp .env.example .env
   # Edit .env with your actual values

4. Run server:
   uvicorn app.main:app --reload --port 8000

Example curl request:
curl -X POST "http://127.0.0.1:8000/api/receipts/ocr" \
  -F "file=@/path/to/receipt.jpg"
"""
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from .services.ocr.vision_client import ocr_document_bytes
from .services.database.supabase_client import save_receipt_ocr, save_parsed_receipt, get_or_create_merchant, get_test_user_id
from .models import ReceiptOCRResponse, ReceiptIngestRequest, ReceiptIngestResponse, ReceiptItemResponse
from .core.receipt_parser import parse_receipt
from .services.ocr.documentai_client import parse_receipt_documentai
from .services.ocr.textract_client import parse_receipt_textract
from .services.llm.receipt_llm_processor import process_receipt_with_llm_from_docai, process_receipt_with_llm_from_ocr
from .core.workflow_processor import process_receipt_workflow
from .core.bulk_processor import process_bulk_receipts
from .models import DocumentAIResultRequest
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Receipt OCR MVP",
    description="Minimal FastAPI backend for receipt OCR using Google Cloud Vision",
    version="1.0.0"
)

# CORS configuration - allow common development ports
# In production, should restrict to specific domains
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/receipt/goog-ocr", response_model=ReceiptOCRResponse)
async def ocr_receipt_google_vision(file: UploadFile = File(...)):
    """
    Perform OCR using Google Cloud Vision API.
    
    - Accepts JPEG or PNG images
    - Maximum file size: approximately 5MB
    - Returns extracted text and saves to Supabase
    """
    # Basic validation: only allow jpg/png
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # Check file size (approximately 5MB limit)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # Perform OCR
        text = ocr_document_bytes(contents)
        logger.info(f"OCR completed for file: {file.filename}")
    except Exception as e:
        logger.error(f"OCR failed for {file.filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"OCR failed: {str(e)}"
        )
    
    # Save to Supabase
    try:
        # TODO: wire user_id from auth later; use None for now
        saved = save_receipt_ocr(user_id=None, filename=file.filename, text=text)
        logger.info(f"Receipt saved to Supabase: {saved.get('id')}")
    except Exception as e:
        logger.error(f"Failed to save receipt to Supabase: {e}")
        # Still return the OCR result even if save fails
        return ReceiptOCRResponse(
            id=None,
            filename=file.filename,
            text=text,
        )
    
    return ReceiptOCRResponse(
        id=str(saved.get("id")) if saved.get("id") else None,
        filename=file.filename,
        text=text,
    )


@app.post("/api/ingest/receipt", response_model=ReceiptIngestResponse)
async def ingest_receipt(request: ReceiptIngestRequest):
    """
    Receive OCR text, parse receipt information and save to database.
    
    - Parse merchant name, date/time, total amount, items, etc.
    - Save to receipts and receipt_items tables
    - Return parsed structured data
    
    Note: A valid user_id is required (must exist in auth.users table).
    Can be provided in the following ways:
    1. Get from authentication information in request headers (recommended, to be implemented)
    2. Set TEST_USER_ID environment variable for development testing
    """
    # Get user ID
    user_id = get_test_user_id()
    
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "user_id is required. Please either:\n"
                "1. Implement authentication to get user_id from request\n"
                "2. Set TEST_USER_ID environment variable (must exist in auth.users table)\n"
                "To create a test user, use Supabase Auth API or create one in Supabase dashboard."
            )
        )
    
    try:
        # Parse receipt
        parsed = parse_receipt(request.text)
        
        # If merchant identified, get or create merchant record
        if parsed.merchant_name:
            merchant_id = get_or_create_merchant(parsed.merchant_name)
            parsed.merchant_id = merchant_id
            logger.info(f"Merchant: {parsed.merchant_name} (ID: {merchant_id})")
        
        # Save to database
        saved = save_parsed_receipt(
            user_id=user_id,
            parsed_receipt=parsed,
            ocr_text=request.text,
            image_url=None
        )
        
        receipt_id = saved["receipt_id"]
        logger.info(f"Receipt ingested successfully: ID={receipt_id}, Items={len(saved['items'])}")
        
        # Build response - get is_on_sale information from original parsing
        items_response = []
        for idx, db_item in enumerate(saved["items"]):
            # Find corresponding item from original parsed item list
            original_item = None
            if idx < len(parsed.items):
                original_item = parsed.items[idx]
            
            normalized_text = db_item.get("normalized_text") or db_item.get("raw_text", "")
            # Check if contains [SALE] marker
            is_on_sale = "[SALE]" in normalized_text or (original_item and original_item.is_on_sale)
            # Remove [SALE] marker to get pure product name
            product_name = normalized_text.replace("[SALE] ", "").strip() if normalized_text else ""
            
            items_response.append(
                ReceiptItemResponse(
                    id=db_item.get("id"),
                    line_index=db_item["line_index"],
                    product_name=product_name,
                    quantity=db_item.get("quantity"),
                    unit=None,  # Database doesn't store unit separately for now
                    unit_price=db_item.get("unit_price"),
                    line_total=db_item.get("line_total"),
                    is_on_sale=is_on_sale,
                    category=original_item.category if original_item else None,
                )
            )
        
        return ReceiptIngestResponse(
            receipt_id=receipt_id,
            merchant_name=parsed.merchant_name,
            merchant_id=parsed.merchant_id,
            purchase_time=parsed.purchase_time,
            total=float(parsed.total) if parsed.total else None,
            subtotal=float(parsed.subtotal) if parsed.subtotal else None,
            tax=float(parsed.tax) if parsed.tax else None,
            item_count=parsed.item_count,
            payment_method=parsed.payment_method,
            items=items_response,
        )
        
    except Exception as e:
        logger.error(f"Failed to ingest receipt: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Receipt ingestion failed: {str(e)}"
        )


@app.post("/api/receipt/goog-ocr-dai")
async def parse_receipt_with_documentai(file: UploadFile = File(...)):
    """
    Parse receipt image using Google Document AI Expense Parser.
    
    - Accepts JPEG or PNG images
    - Uses Google Document AI's Expense Parser processor
    - Returns structured data extracted by Document AI
    
    Note: This endpoint only returns parsing results, does not save to database.
    """
    # Basic validation: only allow jpg/png
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # Check file size (approximately 5MB limit)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # Determine MIME type
        mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
        
        # Parse using Document AI
        parsed_data = parse_receipt_documentai(contents, mime_type=mime_type)
        logger.info(f"Document AI parsing completed for file: {file.filename}")
        
        return {
            "filename": file.filename,
            "success": True,
            "data": parsed_data
        }
        
    except Exception as e:
        logger.error(f"Document AI parsing failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Document AI parsing failed: {str(e)}"
        )


@app.post("/api/receipt/amzn-ocr")
async def parse_receipt_with_textract(file: UploadFile = File(...)):
    """
    Parse receipt image using AWS Textract.
    
    - Accepts JPEG or PNG images
    - Uses AWS Textract's detect_document_text and analyze_expense APIs
    - Returns structured data extracted by Textract (normalized format, compatible with Document AI)
    
    Note: This endpoint only returns parsing results, does not save to database.
    The returned format is already normalized and can be directly used with /api/receipt/llm-process endpoint.
    
    Configuration requirements:
    - Need to configure AWS credentials (via ~/.aws/credentials or environment variables)
    - Need IAM permissions: AmazonTextractFullAccess or at least detect_document_text and analyze_expense permissions
    """
    # Basic validation: only allow jpg/png
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # Check file size (approximately 5MB limit)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # Parse using Textract
        parsed_data = parse_receipt_textract(contents)
        logger.info(f"Textract parsing completed for file: {file.filename}")
        
        return {
            "filename": file.filename,
            "success": True,
            "data": parsed_data
        }
        
    except Exception as e:
        logger.error(f"Textract parsing failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Textract parsing failed: {str(e)}"
        )


@app.post("/api/receipt/openai-llm")
async def process_receipt_with_openai_llm_endpoint(request: DocumentAIResultRequest):
    """
    Process OCR results using OpenAI LLM (supports multiple OCR providers).
    
    Input: JSON returned by any OCR service (from /api/receipt/goog-ocr-dai or /api/receipt/amzn-ocr)
    
    Core advantages (unified processing):
    - Automatically normalize different OCR output formats
    - Unified extraction based on raw_text (not dependent on OCR-specific format)
    - Unified validation logic (regardless of OCR source)
    - Merchant-specific rules only need one set (targeting raw_text, not OCR)
    
    Workflow:
    1. Automatically detect and normalize OCR results (Google Document AI / AWS Textract)
    2. Extract high-confidence fields (confidence >= 0.95) as trusted_hints
    3. Get corresponding RAG prompt based on merchant name
    4. Call OpenAI LLM for structured reconstruction
    5. Backend mathematical validation based on raw_text (not dependent on OCR)
    6. Return structured JSON that can be directly stored to database
    
    Note: This endpoint returns complete structured data, including tbd (to be determined) fields.
    
    Usage example:
    1. First call POST /api/receipt/goog-ocr-dai or POST /api/receipt/amzn-ocr to upload image and get OCR result
    2. Send the data field from returned JSON as body's data to this endpoint
    """
    try:
        # Detect OCR provider (via metadata or auto-detection)
        ocr_data = request.data
        ocr_provider = "unknown"
        
        if isinstance(ocr_data, dict):
            # Check if has metadata field
            if "metadata" in ocr_data and "ocr_provider" in ocr_data["metadata"]:
                ocr_provider = ocr_data["metadata"]["ocr_provider"]
            else:
                # Auto-detection: check for characteristic fields
                # Use key check instead of string conversion, more efficient and accurate
                if "ExpenseDocuments" in ocr_data and isinstance(ocr_data.get("ExpenseDocuments"), list):
                    ocr_provider = "aws_textract"
                elif "entities" in ocr_data and "line_items" in ocr_data:
                    ocr_provider = "google_documentai"
                elif "Blocks" in ocr_data and isinstance(ocr_data.get("Blocks"), list):
                    # AWS Textract's detect_document_text returns Blocks
                    ocr_provider = "aws_textract"
        
        # Call unified LLM processing workflow (auto-normalize, use OpenAI)
        result = await process_receipt_with_llm_from_ocr(
            ocr_result=ocr_data,
            merchant_name=None,  # Auto-identify from OCR result
            ocr_provider=ocr_provider,
            llm_provider="openai"
        )
        
        logger.info(f"OpenAI LLM processing completed for file: {request.filename} (OCR: {ocr_provider})")
        
        return {
            "filename": request.filename,
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"OpenAI LLM processing failed for {request.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI LLM processing failed: {str(e)}"
        )


@app.post("/api/receipt/gemini-llm")
async def process_receipt_with_gemini_llm_endpoint(request: DocumentAIResultRequest):
    """
    Process OCR results using Google Gemini LLM (supports multiple OCR providers).
    
    Input: JSON returned by any OCR service (from /api/receipt/goog-ocr-dai or /api/receipt/amzn-ocr)
    
    Core advantages (unified processing):
    - Automatically normalize different OCR output formats
    - Unified extraction based on raw_text (not dependent on OCR-specific format)
    - Unified validation logic (regardless of OCR source)
    - Merchant-specific rules only need one set (targeting raw_text, not OCR)
    - Uses Google Gemini LLM (temporarily reuses OpenAI's RAG prompt)
    
    Workflow:
    1. Automatically detect and normalize OCR results (Google Document AI / AWS Textract)
    2. Extract high-confidence fields (confidence >= 0.95) as trusted_hints
    3. Get corresponding RAG prompt based on merchant name (reuses OpenAI's prompt)
    4. Call Google Gemini LLM for structured reconstruction
    5. Backend mathematical validation based on raw_text (not dependent on OCR)
    6. Return structured JSON that can be directly stored to database
    
    Note: This endpoint returns complete structured data, including tbd (to be determined) fields.
    
    Usage example:
    1. First call POST /api/receipt/goog-ocr-dai or POST /api/receipt/amzn-ocr to upload image and get OCR result
    2. Send the data field from returned JSON as body's data to this endpoint
    """
    try:
        # Detect OCR provider (via metadata or auto-detection)
        ocr_data = request.data
        ocr_provider = "unknown"
        
        if isinstance(ocr_data, dict):
            # Check if has metadata field
            if "metadata" in ocr_data and "ocr_provider" in ocr_data["metadata"]:
                ocr_provider = ocr_data["metadata"]["ocr_provider"]
            else:
                # Auto-detection: check for characteristic fields
                # Use key check instead of string conversion, more efficient and accurate
                if "ExpenseDocuments" in ocr_data and isinstance(ocr_data.get("ExpenseDocuments"), list):
                    ocr_provider = "aws_textract"
                elif "entities" in ocr_data and "line_items" in ocr_data:
                    ocr_provider = "google_documentai"
                elif "Blocks" in ocr_data and isinstance(ocr_data.get("Blocks"), list):
                    # AWS Textract's detect_document_text returns Blocks
                    ocr_provider = "aws_textract"
        
        # Call unified LLM processing workflow (auto-normalize, use Gemini)
        result = await process_receipt_with_llm_from_ocr(
            ocr_result=ocr_data,
            merchant_name=None,  # Auto-identify from OCR result
            ocr_provider=ocr_provider,
            llm_provider="gemini"
        )
        
        logger.info(f"Gemini LLM processing completed for file: {request.filename} (OCR: {ocr_provider})")
        
        return {
            "filename": request.filename,
            "success": True,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"Gemini LLM processing failed for {request.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Gemini LLM processing failed: {str(e)}"
        )


@app.post("/api/receipt/workflow")
async def process_receipt_workflow_endpoint(file: UploadFile = File(...)):
    """
    Complete receipt processing workflow.
    
    Workflow:
    1. Google Document AI OCR
    2. Decide whether to use Gemini or GPT-4o-mini based on Gemini rate limiting
    3. LLM processing to get structured JSON
    4. Sum check (tolerance ±0.03)
    5. If failed, introduce AWS OCR + GPT-4o-mini secondary processing
    6. File storage and timeline recording
    7. Statistics update
    
    Returns:
    - success: Whether successful
    - receipt_id: Receipt ID (format: 001_mmyydd_hhmm)
    - status: Status (passed, passed_with_resolution, passed_after_backup, needs_manual_review, error)
    - data: Structured receipt data
    - sum_check: Sum check details
    - timeline: Timeline (optional)
    """
    # Basic validation
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported."
        )
    
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    
    # Check file size (approximately 5MB limit)
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    try:
        # Determine MIME type
        mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
        
        # Call workflow processor
        result = await process_receipt_workflow(
            image_bytes=contents,
            filename=file.filename,
            mime_type=mime_type
        )
        
        logger.info(f"Workflow completed for {file.filename}: status={result.get('status')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Workflow failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Workflow processing failed: {str(e)}"
        )


@app.post("/api/receipt/workflow-bulk")
async def process_receipt_workflow_bulk_endpoint(files: List[UploadFile] = File(...)):
    """
    Bulk receipt processing workflow endpoint.
    
    Accepts multiple receipt images and processes them with rate limiting.
    
    Features:
    - Processes multiple JPEG/PNG images in one request
    - Respects Gemini API rate limit (15 requests/minute)
    - Automatically queues files when rate limit is reached
    - Waits for next minute when Gemini limit is exceeded
    
    Args:
        files: List of image files (JPEG/PNG)
    
    Returns:
        Dictionary containing:
        - success: Overall success status
        - total: Total number of files received
        - processed: Number of files processed
        - successful: Number of successful processing
        - failed: Number of failed processing
        - results: List of individual processing results
    
    Example:
        curl -X POST "http://127.0.0.1:8000/api/receipt/workflow-bulk" \
          -F "files=@receipt1.jpg" \
          -F "files=@receipt2.jpg" \
          -F "files=@receipt3.jpg"
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail="No files provided"
        )
    
    if len(files) > 100:  # Reasonable limit for bulk upload
        raise HTTPException(
            status_code=400,
            detail="Too many files. Maximum 100 files per request."
        )
    
    try:
        # Process bulk receipts
        result = await process_bulk_receipts(files, max_concurrent=3)
        
        logger.info(
            f"Bulk processing completed: {result.get('successful', 0)} successful, "
            f"{result.get('failed', 0)} failed out of {result.get('processed', 0)} files"
        )
        
        return result
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        logger.error(
            f"Bulk workflow failed: {error_type}: {error_msg}",
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Bulk processing failed: {error_type}: {error_msg}"
        )
