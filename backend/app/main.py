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
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import List, Optional
from .services.ocr.vision_client import ocr_document_bytes
from .services.database.supabase_client import get_test_user_id
from .services.auth.jwt_auth import get_current_user, get_current_user_optional
from .services.rag.rag_manager import (
    create_tag, get_tag, list_tags, update_tag,
    create_snippet, list_snippets,
    create_matching_rule, list_matching_rules
)
from .models import ReceiptOCRResponse
from .services.ocr.documentai_client import parse_receipt_documentai
from .services.ocr.textract_client import parse_receipt_textract
from .services.llm.receipt_llm_processor import process_receipt_with_llm_from_docai, process_receipt_with_llm_from_ocr
from .core.workflow_processor import process_receipt_workflow
from .core.bulk_processor import process_bulk_receipts
from .models import DocumentAIResultRequest
from .processors.validation.coordinate_extractor import extract_text_blocks_with_coordinates
from .processors.validation.receipt_partitioner import partition_receipt
from .processors.validation.coordinate_sum_checker import coordinate_based_sum_check
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Receipt OCR MVP",
    description="Minimal FastAPI backend for receipt OCR using Google Cloud Vision",
    version="1.0.0"
)

# Configure Swagger UI to show Authorize button
app.openapi_schema = None  # Will be generated on first access

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    from fastapi.openapi.utils import get_openapi
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security scheme for Bearer token
    # The key must match what HTTPBearer uses (default is "Bearer")
    # But we need to check what HTTPBearer actually uses
    openapi_schema["components"]["securitySchemes"] = {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your JWT token (without 'Bearer' prefix). Get it from /api/auth/authorization endpoint."
        }
    }
    
    # Add security requirement to protected routes
    # Routes that use Depends(get_current_user) need security in OpenAPI schema
    protected_paths = ["/api/receipt/workflow", "/api/receipt/workflow-bulk"]
    
    if "paths" in openapi_schema:
        for path, methods in openapi_schema["paths"].items():
            # Skip auth endpoint itself
            if "/api/auth/" in path:
                continue
            
            # Add security to protected routes
            if path in protected_paths:
                for method, details in methods.items():
                    if isinstance(details, dict):
                        # Force add security requirement
                        details["security"] = [{"Bearer": []}]
                        logger.warning(f"[DEBUG] Added security to {method.upper()} {path}")
                        logger.warning(f"[DEBUG] Route details: {details}")
    
    logger.warning(f"[DEBUG] OpenAPI schema security schemes: {openapi_schema.get('components', {}).get('securitySchemes', {})}")
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

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


# ==================== Auth Endpoints ====================

class AuthorizationRequest(BaseModel):
    """Request model for authorization endpoint."""
    user_id: str  # Supabase user UID


@app.post("/api/auth/authorization")
async def get_authorization_token(request: AuthorizationRequest):
    """
    Generate JWT token for a user by UID (Development only).
    
    This endpoint uses Supabase Admin API to generate a session token for the user.
    It's designed for development/testing purposes to avoid exposing email/password in Swagger UI.
    
    **Security Note**: This endpoint should be disabled or protected in production.
    
    Args:
        request: AuthorizationRequest containing user_id (Supabase UID)
    
    Returns:
        Dictionary containing:
        - success: Whether the operation was successful
        - token: JWT token that can be used in Authorization header
        - user_id: The user ID
        - usage: Instructions on how to use the token
    
    Example:
        POST /api/auth/authorization
        {
            "user_id": "7981c0a1-6017-4a8c-b551-3fb4118cd798"
        }
    """
    from .config import settings
    
    user_id = request.user_id.strip()
    
    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="user_id is required"
        )
    
    # Validate UUID format (basic check)
    if len(user_id) != 36 or user_id.count('-') != 4:
        raise HTTPException(
            status_code=400,
            detail="Invalid user_id format. Expected UUID format (e.g., 7981c0a1-6017-4a8c-b551-3fb4118cd798)"
        )
    
    try:
        # Check if service role key is configured
        if not settings.supabase_service_role_key:
            raise HTTPException(
                status_code=500,
                detail="SUPABASE_SERVICE_ROLE_KEY is not configured. This endpoint requires admin access."
            )
        
        # Verify user exists and generate session token using Supabase Admin API
        import httpx
        
        logger.info(f"[DEBUG] Starting authorization for user_id: {user_id}")
        logger.info(f"[DEBUG] SUPABASE_URL: {settings.supabase_url}")
        logger.info(f"[DEBUG] SUPABASE_SERVICE_ROLE_KEY configured: {bool(settings.supabase_service_role_key)}")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # First, verify the user exists by calling the Admin API
                # GET /auth/v1/admin/users/{user_id}
                user_url = f"{settings.supabase_url}/auth/v1/admin/users/{user_id}"
                logger.info(f"[DEBUG] GET request to: {user_url}")
                
                get_user_response = await client.get(
                    user_url,
                    headers={
                        "apikey": settings.supabase_service_role_key,
                        "Authorization": f"Bearer {settings.supabase_service_role_key}",
                        "Content-Type": "application/json"
                    }
                )
                
                logger.info(f"[DEBUG] GET user response status: {get_user_response.status_code}")
                logger.info(f"[DEBUG] GET user response headers: {dict(get_user_response.headers)}")
                
                if get_user_response.status_code == 404:
                    logger.error(f"[DEBUG] User not found (404). Response body: {get_user_response.text}")
                    raise HTTPException(
                        status_code=404,
                        detail=f"User with ID {user_id} not found in Supabase Authentication. Please verify:\n"
                               f"1. The user exists in Supabase Dashboard > Authentication > Users\n"
                               f"2. SUPABASE_SERVICE_ROLE_KEY is correctly configured in .env\n"
                               f"3. SUPABASE_URL is correct (should be https://YOUR-PROJECT.supabase.co)"
                    )
                elif get_user_response.status_code != 200:
                    error_detail = get_user_response.text
                    logger.error(f"[DEBUG] Failed to get user info: {get_user_response.status_code} - {error_detail}")
                    raise HTTPException(
                        status_code=get_user_response.status_code,
                        detail=f"Failed to verify user: {error_detail}"
                    )
                
                # User exists, extract email
                user_data = get_user_response.json()
                logger.info(f"[DEBUG] User data received: {user_data}")
                user_email = user_data.get("email") or user_data.get("user", {}).get("email") or "N/A"
                logger.info(f"[DEBUG] User verified: {user_id} ({user_email})")
                
                # Now try to generate a session token
                # Supabase Admin API: POST /auth/v1/admin/users/{user_id}/sessions
                # Note: This endpoint might not exist in all Supabase versions
                # Alternative: Generate a custom JWT token using the JWT secret
                session_url = f"{settings.supabase_url}/auth/v1/admin/users/{user_id}/sessions"
                logger.info(f"[DEBUG] POST request to: {session_url}")
                
                response = await client.post(
                    session_url,
                    headers={
                        "apikey": settings.supabase_service_role_key,
                        "Authorization": f"Bearer {settings.supabase_service_role_key}",
                        "Content-Type": "application/json"
                    },
                    json={}
                )
                
                logger.info(f"[DEBUG] POST session response status: {response.status_code}")
                logger.info(f"[DEBUG] POST session response body: {response.text[:500]}")  # First 500 chars
                
                if response.status_code == 200:
                    data = response.json()
                    # The response might be a session object or just a token
                    token = data.get("access_token") or data.get("session", {}).get("access_token")
                    
                    if not token:
                        # Try to extract from the response structure
                        if "session" in data:
                            token = data["session"].get("access_token")
                        elif isinstance(data, dict) and "access_token" in data:
                            token = data["access_token"]
                        else:
                            logger.error(f"Unexpected response structure: {data}")
                            raise HTTPException(
                                status_code=500,
                                detail="Failed to extract token from Supabase API response"
                            )
                    
                    logger.info(f"[DEBUG] Successfully got token from Admin API session endpoint")
                    return {
                        "success": True,
                        "token": token,
                        "user_id": user_id,
                        "user_email": user_email,
                        "usage": {
                            "swagger_ui": "Click 'Authorize' button in Swagger UI, then enter: Bearer <token>",
                            "curl": f'curl -H "Authorization: Bearer {token[:50]}..." http://localhost:8000/api/auth/test-token',
                            "note": "This token expires in 1 hour (or 7 days for super_admin). Generate a new one when needed."
                        },
                        "method": "admin_api_session"
                    }
                else:
                    # Session endpoint not available or returned error, fallback to manual JWT generation
                    error_detail = response.text
                    logger.warning(f"[DEBUG] Session endpoint returned {response.status_code}: {error_detail}")
                    
                    # If the endpoint doesn't exist or returns error, fallback to generating a custom JWT token
                    # This is actually the preferred method since Supabase Admin API session endpoint may not be available
                    logger.info(f"[DEBUG] Falling back to manual JWT token generation")
                    
                    import jwt
                    from datetime import datetime, timedelta, timezone
                    
                    if not settings.supabase_jwt_secret:
                        logger.error("[DEBUG] SUPABASE_JWT_SECRET is not configured")
                        raise HTTPException(
                            status_code=500,
                            detail="SUPABASE_JWT_SECRET is not configured. Cannot generate custom token."
                        )
                    
                    # Check user class to determine token expiration
                    # super_admin gets 7 days, others get 1 hour
                    from .services.database.supabase_client import _get_client
                    supabase = _get_client()
                    user_class = None
                    try:
                        user_response = supabase.table("users").select("user_class").eq("id", user_id).limit(1).execute()
                        if user_response.data and len(user_response.data) > 0:
                            user_class = user_response.data[0].get("user_class")
                            logger.info(f"[DEBUG] User class: {user_class}")
                    except Exception as e:
                        logger.warning(f"[DEBUG] Failed to get user class: {e}, defaulting to 1 hour")
                    
                    # Set expiration based on user class
                    if user_class == "super_admin":
                        expiration_hours = 24 * 7  # 7 days
                        expiration_note = "7 days"
                    else:
                        expiration_hours = 1  # 1 hour
                        expiration_note = "1 hour"
                    
                    # Create a JWT token manually
                    # This is the standard way to generate tokens for Supabase
                    now = datetime.now(timezone.utc)
                    payload = {
                        "sub": user_id,
                        "email": user_email,
                        "aud": "authenticated",
                        "role": "authenticated",
                        "exp": int((now + timedelta(hours=expiration_hours)).timestamp()),
                        "iat": int(now.timestamp())
                    }
                    
                    logger.info(f"[DEBUG] Generating JWT token with payload: {payload} (expires in {expiration_note})")
                    token = jwt.encode(
                        payload,
                        settings.supabase_jwt_secret,
                        algorithm="HS256"
                    )
                    
                    logger.info(f"[DEBUG] JWT token generated successfully (length: {len(token)}, expires in {expiration_note})")
                    
                    return {
                        "success": True,
                        "token": token,
                        "user_id": user_id,
                        "user_email": user_email,
                        "user_class": user_class,
                        "expires_in": expiration_note,
                        "usage": {
                            "swagger_ui": "Click 'Authorize' button in Swagger UI, then enter: Bearer <token>",
                            "curl": f'curl -H "Authorization: Bearer {token[:50]}..." http://localhost:8000/api/auth/test-token',
                            "note": f"This token expires in {expiration_note}. Generate a new one when needed."
                        },
                        "method": "manual_jwt_generation"
                    }
        
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to generate session token: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate session token: {str(e)}"
            )
        
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="Request to Supabase API timed out"
        )
    except Exception as e:
        logger.error(f"Authorization failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate authorization token: {str(e)}"
        )


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
    
    # Note: This endpoint only performs OCR and returns text
    # For full receipt processing with database storage, use /api/receipt/workflow
    return ReceiptOCRResponse(
        id=None,
        filename=file.filename,
        text=text,
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
async def process_receipt_workflow_endpoint(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user)
):
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
        
        # Call workflow processor with authenticated user_id
        result = await process_receipt_workflow(
            image_bytes=contents,
            filename=file.filename,
            mime_type=mime_type,
            user_id=user_id  # Pass authenticated user_id
        )
        
        logger.info(f"Workflow completed for {file.filename}: status={result.get('status')}")
        
        return result
        
    except Exception as e:
        logger.error(f"Workflow failed for {file.filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Workflow processing failed: {str(e)}"
        )


@app.post("/api/receipt/coordinate-sum-check")
async def coordinate_sum_check_endpoint(
    file: UploadFile = File(...)
):
    """
    Coordinate-based sum check for receipt debugging.
    
    This endpoint:
    1. Calls Google Document AI OCR to get coordinate data
    2. Partitions receipt into 4 regions (header, items, totals, payment)
    3. Performs coordinate-based sum check
    4. Returns formatted vertical addition output for debugging
    
    Returns:
        Dictionary containing:
        - coordinate_check: Sum check results using coordinates
        - formatted_output: Vertical addition format for debugging
        - regions: Partitioned receipt regions
        - raw_coordinate_data: Raw coordinate data from Document AI
    """
    try:
        # Read file
        contents = await file.read()
        mime_type = file.content_type or "image/jpeg"
        
        # Call Document AI
        logger.info(f"Processing receipt for coordinate sum check: {file.filename}")
        docai_result = parse_receipt_documentai(contents, mime_type=mime_type)
        
        # Extract coordinate data
        coordinate_data = docai_result.get("coordinate_data", {})
        if not coordinate_data:
            raise HTTPException(
                status_code=500,
                detail="Failed to extract coordinate data from Document AI response"
            )
        
        # Extract text blocks with coordinates
        blocks = extract_text_blocks_with_coordinates(coordinate_data)
        
        # Partition receipt
        regions = partition_receipt(blocks, coordinate_data)
        
        # Perform coordinate-based sum check
        # We need LLM result for comparison, but for this debug endpoint,
        # we'll use Document AI entities as a proxy
        llm_result_proxy = {
            "receipt": {
                "subtotal": docai_result.get("subtotal"),
                "tax": docai_result.get("tax") or 0.0,
                "total": docai_result.get("total")
            },
            "items": docai_result.get("line_items", [])
        }
        
        is_valid, check_details = coordinate_based_sum_check(
            blocks,
            regions,
            llm_result_proxy
        )
        
        # Generate response
        response = {
            "success": True,
            "coordinate_check": check_details,
            "formatted_output": check_details.get("formatted_output", ""),
            "regions": {
                "header": {
                    "block_count": len(regions.get("header", [])),
                    "text": "\n".join(b.get("text", "") for b in regions.get("header", [])[:5])
                },
                "items": {
                    "block_count": len(regions.get("items", [])),
                    "amount_count": sum(1 for b in regions.get("items", []) if b.get("is_amount"))
                },
                "totals": {
                    "block_count": len(regions.get("totals", [])),
                    "text": "\n".join(b.get("text", "") for b in regions.get("totals", []))
                },
                "payment": {
                    "block_count": len(regions.get("payment", [])),
                    "text": "\n".join(b.get("text", "") for b in regions.get("payment", [])[:5])
                }
            },
            "markers": {
                "first_item": regions.get("markers", {}).get("first_item", {}).get("text") if regions.get("markers", {}).get("first_item") else None,
                "subtotal": regions.get("markers", {}).get("subtotal", {}).get("text") if regions.get("markers", {}).get("subtotal") else None,
                "total": regions.get("markers", {}).get("total", {}).get("text") if regions.get("markers", {}).get("total") else None
            },
            "raw_coordinate_data": {
                "text_blocks_count": len(coordinate_data.get("text_blocks", [])),
                "pages_count": len(coordinate_data.get("pages", []))
            }
        }
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Coordinate sum check failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Coordinate sum check failed: {str(e)}"
        )


@app.post("/api/receipt/workflow-bulk", dependencies=[Depends(get_current_user)])
async def process_receipt_workflow_bulk_endpoint(
    files: List[UploadFile] = File(...),
    user_id: str = Depends(get_current_user)
):
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
        # Process bulk receipts with authenticated user_id
        result = await process_bulk_receipts(files, user_id=user_id, max_concurrent=3)
        
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


# ==================== RAG Management Endpoints ====================

def require_admin(user_id: str = Depends(get_current_user)) -> str:
    """
    Dependency to require admin or super_admin user class.
    
    Args:
        user_id: User ID from JWT token
        
    Returns:
        user_id if user is admin/super_admin
        
    Raises:
        HTTPException: 403 if user is not admin/super_admin
    """
    from .services.database.supabase_client import _get_client
    
    try:
        supabase = _get_client()
        res = supabase.table("users").select("user_class").eq("id", user_id).limit(1).execute()
        if res.data:
            user_class = res.data[0].get("user_class", "free")
            if user_class in ("super_admin", "admin"):
                return user_id
            else:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied. Required: admin or super_admin, got: {user_class}"
                )
        else:
            raise HTTPException(
                status_code=404,
                detail="User not found in database"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check user class: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to verify user permissions"
        )


# Tag Management
@app.get("/api/rag/tags")
async def list_rag_tags(
    is_active: Optional[bool] = None,
    user_id: str = Depends(require_admin)
):
    """
    List all RAG tags.
    
    Requires: admin or super_admin
    """
    tags = list_tags(is_active=is_active)
    return {"success": True, "tags": tags}


@app.post("/api/rag/tags")
async def create_rag_tag(
    tag_name: str,
    tag_type: str,
    description: str,
    priority: int = 50,
    is_active: bool = True,
    user_id: str = Depends(require_admin)
):
    """
    Create a new RAG tag.
    
    Requires: admin or super_admin
    """
    try:
        tag = create_tag(
            tag_name=tag_name,
            tag_type=tag_type,
            description=description,
            priority=priority,
            is_active=is_active
        )
        return {"success": True, "tag": tag}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create tag: {str(e)}")


@app.get("/api/rag/tags/{tag_name}")
async def get_rag_tag(
    tag_name: str,
    user_id: str = Depends(require_admin)
):
    """
    Get a RAG tag by name.
    
    Requires: admin or super_admin
    """
    tag = get_tag(tag_name)
    if not tag:
        raise HTTPException(status_code=404, detail=f"Tag '{tag_name}' not found")
    return {"success": True, "tag": tag}


@app.put("/api/rag/tags/{tag_name}")
async def update_rag_tag(
    tag_name: str,
    description: Optional[str] = None,
    priority: Optional[int] = None,
    is_active: Optional[bool] = None,
    user_id: str = Depends(require_admin)
):
    """
    Update a RAG tag.
    
    Requires: admin or super_admin
    """
    try:
        tag = update_tag(
            tag_name=tag_name,
            description=description,
            priority=priority,
            is_active=is_active
        )
        return {"success": True, "tag": tag}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update tag: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update tag: {str(e)}")


# Snippet Management
@app.get("/api/rag/tags/{tag_name}/snippets")
async def list_rag_snippets(
    tag_name: str,
    user_id: str = Depends(require_admin)
):
    """
    List all snippets for a tag.
    
    Requires: admin or super_admin
    """
    snippets = list_snippets(tag_name)
    return {"success": True, "snippets": snippets}


@app.post("/api/rag/tags/{tag_name}/snippets")
async def create_rag_snippet(
    tag_name: str,
    snippet_type: str,
    content: str,
    priority: int = 10,
    is_active: bool = True,
    user_id: str = Depends(require_admin)
):
    """
    Create a snippet for a tag.
    
    Requires: admin or super_admin
    
    snippet_type: "system_message", "prompt_addition", "extraction_rule", "validation_rule", "example"
    """
    try:
        snippet = create_snippet(
            tag_name=tag_name,
            snippet_type=snippet_type,
            content=content,
            priority=priority,
            is_active=is_active
        )
        return {"success": True, "snippet": snippet}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create snippet: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create snippet: {str(e)}")


# Matching Rule Management
@app.get("/api/rag/tags/{tag_name}/matching-rules")
async def list_rag_matching_rules(
    tag_name: str,
    user_id: str = Depends(require_admin)
):
    """
    List all matching rules for a tag.
    
    Requires: admin or super_admin
    """
    rules = list_matching_rules(tag_name)
    return {"success": True, "matching_rules": rules}


@app.post("/api/rag/tags/{tag_name}/matching-rules")
async def create_rag_matching_rule(
    tag_name: str,
    match_type: str,
    match_pattern: str,
    priority: int = 100,
    is_active: bool = True,
    user_id: str = Depends(require_admin)
):
    """
    Create a matching rule for a tag.
    
    Requires: admin or super_admin
    
    match_type: "store_name", "fuzzy_store_name", "keyword", "regex", "ocr_pattern", "location_state", "location_country"
    """
    try:
        rule = create_matching_rule(
            tag_name=tag_name,
            match_type=match_type,
            match_pattern=match_pattern,
            priority=priority,
            is_active=is_active
        )
        return {"success": True, "matching_rule": rule}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create matching rule: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create matching rule: {str(e)}")
