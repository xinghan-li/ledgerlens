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
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Security, Body
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
import asyncio
import re
from .services.ocr.vision_client import ocr_document_bytes
from .services.database.supabase_client import (
    get_test_user_id,
    list_receipts_by_user,
    get_receipt_detail_for_user,
    update_record_item_category,
    update_record_items_categories_batch,
    get_user_analytics_summary,
    get_user_unclassified_items,
    mark_item_idk,
    get_idk_now_classified,
)
from .services.auth.jwt_auth import get_current_user, get_current_user_optional
from .middleware.rate_limiter import check_workflow_rate_limit
from .services.categorization.receipt_categorizer import (
    categorize_receipt,
    categorize_receipts_batch,
    can_categorize_receipt,
    smart_categorize_receipt_items,
)
from .models import ReceiptOCRResponse
from .services.ocr.documentai_client import parse_receipt_documentai
from .services.ocr.textract_client import parse_receipt_textract
from .services.llm.receipt_llm_processor import process_receipt_with_llm_from_ocr
from .core.workflow_processor_vision import process_receipt_workflow_vision
from .core.bulk_processor import process_bulk_receipts
from .core.workflow_processor_vision import PROJECT_ROOT
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _run_vision_workflow_in_thread(
    image_bytes: bytes,
    filename: str,
    mime_type: str,
    user_id: str,
    existing_receipt_id: Optional[str] = None,
):
    """
    Run vision receipt workflow in a dedicated event loop inside a thread.
    Avoids blocking the main FastAPI event loop during processing.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            process_receipt_workflow_vision(
                image_bytes=image_bytes,
                filename=filename,
                mime_type=mime_type,
                user_id=user_id,
                existing_receipt_id=existing_receipt_id,
            )
        )
    finally:
        loop.close()


def _run_vision_pre_check_sync(
    image_bytes: bytes,
    filename: str,
    mime_type: str,
    user_id: str,
) -> Dict[str, Any]:
    """
    Synchronous pre-check: compress image, duplicate check, rate-limit, create DB row, save image.
    Returns early-exit result or receipt IDs for background processing.
    """
    from .core.workflow_processor_vision import (
        _compress_image_if_needed,
        generate_receipt_id,
        _save_image_for_manual_review,
    )
    from .services.database.supabase_client import (
        USER_CLASS_ADMIN,
        check_duplicate_by_hash,
        check_user_locked,
        create_receipt,
        get_user_class,
        update_receipt_file_url,
    )
    import hashlib
    from datetime import datetime

    image_bytes, mime_type = _compress_image_if_needed(image_bytes, mime_type)
    receipt_id = generate_receipt_id(filename)
    file_hash = hashlib.sha256(image_bytes).hexdigest()

    # Lock check
    user_class = get_user_class(user_id)
    if user_class < USER_CLASS_ADMIN:
        locked, locked_until = check_user_locked(user_id)
        if locked:
            return {
                "early_return": True,
                "result": {
                    "success": False, "receipt_id": None, "status": "locked",
                    "error": "user_locked",
                    "message": "Upload is temporarily locked. Please try again later.",
                    "locked_until": locked_until.isoformat() if locked_until else None,
                    "pipeline": "vision_b",
                },
            }

    # Duplicate check
    duplicate_id = check_duplicate_by_hash(file_hash, user_id)
    if duplicate_id:
        allow_dup = user_class >= USER_CLASS_ADMIN or settings.allow_duplicate_for_debug
        if allow_dup:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            file_hash = f"{file_hash}_debug_{timestamp}"
        else:
            return {
                "early_return": True,
                "result": {
                    "success": False, "receipt_id": receipt_id, "status": "duplicate",
                    "error": "duplicate_receipt",
                    "message": "This receipt has already been uploaded.",
                    "existing_receipt_id": duplicate_id, "pipeline": "vision_b",
                },
            }

    # Create DB row (status = "processing")
    try:
        db_receipt_id = create_receipt(
            user_id=user_id,
            raw_file_url=None,
            file_hash=file_hash,
            pipeline_version="vision_b",
        )
        logger.info(f"[vision-async] Created receipt {db_receipt_id}")
    except Exception as exc:
        logger.error(f"[vision-async] Failed to create receipt: {exc}")
        return {
            "early_return": True,
            "result": {
                "success": False, "receipt_id": None, "status": "error",
                "error": "db_error", "message": "Failed to create receipt record.",
                "pipeline": "vision_b",
            },
        }

    # Save image immediately so it persists even if background task fails
    image_path = _save_image_for_manual_review(receipt_id, image_bytes, filename)
    if image_path:
        try:
            update_receipt_file_url(db_receipt_id, image_path)
        except Exception as exc:
            logger.error(f"[vision-async] Failed to update receipt file URL for {db_receipt_id}: {exc}", exc_info=True)

    return {
        "early_return": False,
        "receipt_id": receipt_id,
        "db_receipt_id": db_receipt_id,
        "image_bytes": image_bytes,
        "mime_type": mime_type,
    }


async def _run_vision_background(
    image_bytes: bytes,
    filename: str,
    mime_type: str,
    user_id: str,
    existing_receipt_id: str,
):
    """Fire-and-forget background task: run vision workflow, catch all errors."""
    try:
        result = await asyncio.to_thread(
            _run_vision_workflow_in_thread,
            image_bytes, filename, mime_type, user_id,
            existing_receipt_id=existing_receipt_id,
        )
        logger.info(
            f"[vision-async] Background completed for {existing_receipt_id}: "
            f"status={result.get('status')}"
        )
    except Exception as exc:
        logger.error(f"[vision-async] Background failed for {existing_receipt_id}: {exc}", exc_info=True)
        try:
            from .services.database.supabase_client import update_receipt_status
            update_receipt_status(existing_receipt_id, "failed", "vision_primary", admin_failure_kind="vision_fail")
        except Exception as exc:
            logger.error(f"[vision-async] Failed to update receipt status for {existing_receipt_id}: {exc}", exc_info=True)
from .models import DocumentAIResultRequest
from .processors.validation.coordinate_extractor import extract_text_blocks_with_coordinates
from .processors.validation.receipt_body_detector import filter_blocks_by_receipt_body, get_receipt_body_bounds
from .processors.validation.receipt_partitioner import partition_receipt
from .processors.validation.coordinate_sum_checker import coordinate_based_sum_check
from .processors.validation.pipeline import process_receipt_pipeline
from .config import settings
from pathlib import Path

app = FastAPI(
    title="Receipt OCR MVP",
    description="Minimal FastAPI backend for receipt OCR using Google Cloud Vision",
    version="1.0.0",
    docs_url=None,  # 使用下方自定义 /docs，以支持 ngrok 下用 ngrok-skip-browser-warning 拉取 openapi.json
    redoc_url=None,
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

# CORS configuration - production domains + common dev ports + CORS_ORIGINS (comma-separated) for mobile/ngrok
_default_origins = [
    "https://ledgerlens.net",
    "https://www.ledgerlens.net",
    "https://ledgerlens.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:8000",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8080",
]
_extra = (settings.cors_origins_extra or "").strip()
if _extra:
    _default_origins = _default_origins + [o.strip() for o in _extra.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _cors_headers_for_origin(origin: str) -> dict:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Max-Age": "86400",
        "Access-Control-Allow-Credentials": "true",
    }


class DevCORSOptionsMiddleware(BaseHTTPMiddleware):
    """ENV=local 时：对带 Origin 的请求（OPTIONS 预检及后续请求）一律回显该 Origin，避免未配 CORS_ORIGINS 或 origin 不一致时 400/无 CORS 头。"""

    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        is_local = getattr(settings, "env", "") == "local"
        if not origin or not is_local:
            return await call_next(request)
        if request.method == "OPTIONS":
            return Response(status_code=200, headers=_cors_headers_for_origin(origin))
        response = await call_next(request)
        for k, v in _cors_headers_for_origin(origin).items():
            response.headers[k] = v
        return response


app.add_middleware(DevCORSOptionsMiddleware)


# 自定义 /docs：在页面内用 ngrok-skip-browser-warning 拉取 openapi.json，避免 ngrok 免费版拦截页导致 doc 打不开
SWAGGER_UI_HTML = """
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <title>Receipt OCR MVP - Swagger UI</title>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
    window.onload = function() {
      fetch('/openapi.json', { headers: { 'ngrok-skip-browser-warning': '1' } })
        .then(r => r.json())
        .then(spec => {
          window.ui = SwaggerUIBundle({
            spec: spec,
            dom_id: '#swagger-ui',
            presets: [
              SwaggerUIBundle.presets.apis,
              SwaggerUIStandalonePreset
            ],
            layout: "StandaloneLayout"
          });
        })
        .catch(e => {
          document.getElementById('swagger-ui').innerHTML =
            '<p style="padding:2em;color:#c00;">Failed to load OpenAPI spec. If using ngrok, try opening <a href="/openapi.json">/openapi.json</a> first and click through the warning, then refresh this page.</p><pre>' + e + '</pre>';
        });
    };
  </script>
</body>
</html>
"""


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return HTMLResponse(content=SWAGGER_UI_HTML)


@app.get("/health", tags=["System"])
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# ==================== Auth Endpoints ====================

class AuthorizationRequest(BaseModel):
    """Request model for authorization endpoint."""
    user_id: str  # Supabase user UID


@app.post("/api/auth/authorization", tags=["Authentication"])
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
                    # super_admin (9) gets 7 days, others get 1 hour
                    from .services.database.supabase_client import get_user_class, USER_CLASS_SUPER_ADMIN
                    user_class = get_user_class(user_id)
                    logger.info(f"[DEBUG] User class: {user_class}")
                    
                    # Set expiration based on user class
                    if user_class == USER_CLASS_SUPER_ADMIN:
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


@app.get("/api/auth/me", tags=["Authentication"])
async def get_current_user_info(user_id: str = Depends(get_current_user)):
    """Return current user id, email, and user_class. Used by frontend to show/hide Developer and role-specific UI."""
    from .services.database.supabase_client import _get_client
    def _query():
        supabase = _get_client()
        return supabase.table("users").select("id, email, user_class, registration_no, user_name").eq("id", user_id).limit(1).execute()
    res = await asyncio.to_thread(_query)
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")
    row = res.data[0]
    reg_no = row.get("registration_no")
    uc = row.get("user_class")
    return {
        "user_id": row.get("id"),
        "email": row.get("email") or "",
        "user_class": int(uc) if uc is not None else 0,
        "registration_no": reg_no,
        "registration_no_display": f"{int(reg_no):09d}" if reg_no is not None else None,
        "username": row.get("user_name"),
    }


@app.patch("/api/auth/me", tags=["Authentication"])
async def update_current_user_profile(
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """Update current user profile. Supported: username (unique, for greeting/feedback)."""
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    username = body.get("username")
    if username is None:
        raise HTTPException(status_code=400, detail="Missing field: username")
    username = (username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if len(username) > 64:
        raise HTTPException(status_code=400, detail="Username too long (max 64)")
    if not all(c.isalnum() or c in "._-" for c in username):
        raise HTTPException(status_code=400, detail="Username may only contain letters, numbers, . _ -")
    existing = supabase.table("users").select("id").eq("user_name", username).execute()
    if existing.data and len(existing.data) > 0 and str(existing.data[0]["id"]) != str(user_id):
        raise HTTPException(status_code=409, detail="Username already taken")
    from datetime import datetime, timezone
    supabase.table("users").update({"user_name": username, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", user_id).execute()
    return {"username": username}


# 暂时：手机测相机时用固定用户拿 token，测完可删
_DEV_USER_ID = "7981c0a1-6017-4a8c-b551-3fb4118cd798"


@app.get("/api/auth/dev-token", tags=["Authentication"])
async def get_dev_token():
    """[暂时] 无鉴权返回指定用户的 JWT，仅当 ALLOW_DEV_TOKEN=1 时可用。用于手机测相机上传。"""
    import os
    import jwt
    from datetime import datetime, timedelta, timezone
    if os.getenv("ALLOW_DEV_TOKEN") != "1":
        raise HTTPException(status_code=404, detail="Not available")
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    res = supabase.table("users").select("id, email").eq("id", _DEV_USER_ID).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Dev user not found")
    row = res.data[0]
    user_id = row.get("id")
    user_email = row.get("email") or ""
    if not settings.supabase_jwt_secret:
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not configured")
    now = datetime.now(timezone.utc)
    expiration_hours = 24 * 7
    payload = {
        "sub": user_id,
        "email": user_email,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int((now + timedelta(hours=expiration_hours)).timestamp()),
        "iat": int(now.timestamp()),
    }
    token = jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256")
    return {"token": token, "user_id": user_id}


@app.get("/api/analytics/summary", tags=["Receipts - Other"])
async def get_analytics_summary(
    user_id: str = Depends(get_current_user),
    period: Optional[str] = None,
    value: Optional[str] = None,
):
    """Aggregated spending by store, payment card, and category (L1/L2/L3). Amounts in cents. Auth required. Optional: period=month|quarter|year, value=e.g. 2026-01|2026-Q1|2026."""
    return get_user_analytics_summary(user_id, period=period, value=value)


@app.get("/api/me/unclassified", tags=["Receipts - Other"])
async def get_my_unclassified(user_id: str = Depends(get_current_user)):
    """List current user's unclassified line items (category_id IS NULL). For the Unclassified page. Auth required."""
    try:
        return get_user_unclassified_items(user_id)
    except Exception as e:
        logger.exception("get_user_unclassified_items failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/me/item/{record_item_id}/idk", tags=["Receipts - Other"])
async def post_item_idk(
    record_item_id: str,
    user_id: str = Depends(get_current_user),
):
    """Mark that the user said 'I don't know' for this line item. Auth required."""
    ok = mark_item_idk(user_id, record_item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or access denied")
    return {"success": True}


class DismissItemBody(BaseModel):
    reason: str  # "incorrect_item" | "other"
    comment: Optional[str] = None


@app.post("/api/me/item/{record_item_id}/dismiss", tags=["Receipts - Other"])
async def post_item_dismiss(
    record_item_id: str,
    body: DismissItemBody,
    user_id: str = Depends(get_current_user),
):
    """
    Dismiss a record_item from the user's unclassified list.
    reason=incorrect_item: marks item as dismissed (LLM extraction error).
    reason=other: dismissed + escalates to classification_review with user comment.
    Auth required.
    """
    from .services.database.supabase_client import dismiss_item
    if body.reason not in ("incorrect_item", "other"):
        raise HTTPException(status_code=422, detail="reason must be 'incorrect_item' or 'other'")
    ok = dismiss_item(user_id, record_item_id, body.reason, body.comment)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or access denied")
    return {"success": True}


@app.get("/api/me/idk-now-classified", tags=["Receipts - Other"])
async def get_idk_now_classified_route(user_id: str = Depends(get_current_user)):
    """Returns record_item_ids that user had marked IDK and that now have a user_category_id (and clears those IDK flags). Auth required."""
    return {"record_item_ids": get_idk_now_classified(user_id)}


# ==================== User Categories Endpoints ====================

@app.get("/api/me/categories", tags=["User Categories"])
async def get_my_categories(user_id: str = Depends(get_current_user)):
    """
    Get the current user's full category tree as a flat list.
    Frontend builds tree from parent_id. L1 nodes are locked (is_locked=True).
    If user has no categories yet, seeds defaults from system categories first.
    Auth required.
    """
    from .services.categories.user_categories_service import (
        get_user_categories,
        seed_user_default_categories_if_needed,
    )
    seed_user_default_categories_if_needed(user_id)
    return {"data": get_user_categories(user_id)}


@app.post("/api/me/categories", tags=["User Categories"])
async def create_my_category(
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """
    Create a new user-defined category. Must provide parent_id (L2+ only; cannot create L1).
    Body: { parent_id: uuid, name: str, sort_order?: int }
    Returns 409 if same name under same parent. Auth required.
    """
    from .services.categories.user_categories_service import create_user_category
    parent_id = body.get("parent_id")
    name = body.get("name", "")
    try:
        sort_order = int(body.get("sort_order", 0))
    except (ValueError, TypeError):
        sort_order = 0
    if not parent_id:
        raise HTTPException(status_code=400, detail="parent_id required (users cannot create L1 categories)")
    try:
        row = create_user_category(user_id=user_id, name=name, parent_id=parent_id, sort_order=sort_order)
        return row
    except ValueError as e:
        msg = str(e)
        if msg == "already_exists":
            raise HTTPException(status_code=409, detail="Category with same name under same parent already exists")
        if msg == "parent_not_found":
            raise HTTPException(status_code=404, detail="Parent category not found")
        if msg == "max_depth_exceeded":
            raise HTTPException(status_code=400, detail="Maximum category depth (10) exceeded")
        raise HTTPException(status_code=400, detail=msg)


@app.patch("/api/me/categories/{cat_id}", tags=["User Categories"])
async def update_my_category(
    cat_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(get_current_user),
):
    """
    Update a user category name and/or sort_order. Cannot rename locked (L1) categories.
    Body: { name?: str, sort_order?: int }
    Auth required.
    """
    from .services.categories.user_categories_service import update_user_category
    name = body.get("name")
    sort_order = body.get("sort_order")
    try:
        row = update_user_category(
            user_id=user_id,
            cat_id=cat_id,
            name=name,
            sort_order=int(sort_order) if sort_order is not None else None,
        )
        return row
    except ValueError as e:
        msg = str(e)
        if msg == "not_found":
            raise HTTPException(status_code=404, detail="Category not found")
        if msg == "locked_category":
            raise HTTPException(status_code=403, detail="Cannot modify locked L1 category")
        if msg == "already_exists":
            raise HTTPException(status_code=409, detail="Category with same name under same parent already exists")
        raise HTTPException(status_code=400, detail=msg)


@app.delete("/api/me/categories/{cat_id}", tags=["User Categories"])
async def delete_my_category(
    cat_id: str,
    child_action: str = "move_to_parent",
    user_id: str = Depends(get_current_user),
):
    """
    Delete a user category (cannot delete locked L1 categories).
    Query param child_action: 'move_to_parent' (default) or 'delete_recursive'.
    Auth required.
    """
    from .services.categories.user_categories_service import delete_user_category
    try:
        result = delete_user_category(user_id=user_id, cat_id=cat_id, child_action=child_action)
        return result
    except ValueError as e:
        msg = str(e)
        if msg == "not_found":
            raise HTTPException(status_code=404, detail="Category not found")
        if msg == "locked_category":
            raise HTTPException(status_code=403, detail="Cannot delete locked L1 category")
        raise HTTPException(status_code=400, detail=msg)


@app.post("/api/receipt/goog-ocr", response_model=ReceiptOCRResponse, tags=["Receipts - OCR Model"])
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


@app.post("/api/receipt/goog-ocr-dai", tags=["Receipts - OCR Model"])
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


@app.post("/api/receipt/amzn-ocr", tags=["Receipts - OCR Model"])
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



@app.post("/api/receipt/gemini-llm", tags=["Receipts - LLM Model"])
async def process_receipt_with_gemini_llm_endpoint(request: DocumentAIResultRequest):
    """
    Process OCR results using Google Gemini LLM (supports multiple OCR providers).
    
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


@app.post("/api/receipt/workflow", tags=["Receipts - Other"])
async def process_receipt_workflow_endpoint(
    file: UploadFile = File(...),
    user_id: str = Depends(check_workflow_rate_limit)  # check_workflow_rate_limit 现在会返回 user_id
):
    """
    Receipt processing workflow (vision pipeline only).

    Same as /api/receipt/workflow-vision. Legacy OCR+LLM pipeline has been deprecated.

    Rate Limit:
    - super_admin and admin: No limit
    - Other user classes: 5 per minute, 20 per hour

    Workflow: Vision (Gemini) → optional store-specific second round → on failure Gemini escalation → needs_review.
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
    
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit."
        )
    
    if not settings.vision_pipeline_enabled:
        raise HTTPException(
            status_code=503,
            detail="Vision pipeline is currently disabled.",
        )

    mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
    return await _handle_async_vision_upload(contents, file.filename, mime_type, user_id)


@app.post("/api/receipt/workflow-vision", tags=["Receipts - Vision"])
async def process_receipt_workflow_vision_endpoint(
    file: UploadFile = File(...),
    user_id: str = Depends(check_workflow_rate_limit),
):
    """
    Vision-only receipt processing pipeline (async).

    Accepts the image, creates a DB record, and returns immediately with receipt_id.
    Processing runs in the background. Poll GET /api/receipt/{receipt_id} for status.
    """
    if file.content_type not in ("image/jpeg", "image/png", "image/jpg"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG/PNG images are supported.",
        )

    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")

    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="File size exceeds 5MB limit.",
        )

    if not settings.vision_pipeline_enabled:
        raise HTTPException(
            status_code=503,
            detail="Vision pipeline is currently disabled.",
        )

    mime_type = "image/jpeg" if file.content_type in ("image/jpeg", "image/jpg") else "image/png"
    return await _handle_async_vision_upload(contents, file.filename, mime_type, user_id)


async def _handle_async_vision_upload(
    contents: bytes, filename: str, mime_type: str, user_id: str,
) -> Dict[str, Any]:
    """Shared async upload handler: pre-check → return immediately → background processing."""
    try:
        pre = await asyncio.to_thread(
            _run_vision_pre_check_sync, contents, filename, mime_type, user_id,
        )
    except Exception as exc:
        logger.error(f"[vision-async] Pre-check failed for {filename}: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload pre-check failed: {str(exc)}")

    if pre.get("early_return"):
        return pre["result"]

    db_receipt_id = pre["db_receipt_id"]

    # Kick off background processing (fire-and-forget)
    asyncio.create_task(
        _run_vision_background(
            pre["image_bytes"], filename, pre["mime_type"], user_id, db_receipt_id,
        )
    )

    return {
        "success": True,
        "receipt_id": db_receipt_id,
        "status": "processing",
        "message": "Receipt uploaded. Processing has started.",
        "pipeline": "vision_b",
    }


@app.get("/api/receipt/list", tags=["Receipts - Other"])
async def list_my_receipts(
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(get_current_user),
):
    """List current user's receipts, most recent first. Auth required."""
    rows = await asyncio.to_thread(list_receipts_by_user, user_id=user_id, limit=limit, offset=offset)
    return {"data": rows, "limit": limit, "offset": offset}


@app.get("/api/receipt/{receipt_id}", tags=["Receipts - Other"])
async def get_my_receipt(
    receipt_id: str,
    user_id: str = Depends(get_current_user),
):
    """Get one receipt's full JSON (workflow-style). Must be owner. Auth required."""
    # Run sync DB work in thread so the event loop is not blocked (avoids stalling vision pipeline when opening a receipt while another is processing).
    detail = await asyncio.to_thread(get_receipt_detail_for_user, receipt_id, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    return detail


def _fetch_receipt_processing_runs_sync(receipt_id: str):
    """Sync helper: receipt_status + receipt_processing_runs + workflow_steps. Run in thread to avoid blocking."""
    from .services.database.supabase_client import _get_client, get_receipt_workflow_steps
    supabase = _get_client()
    rec = supabase.table("receipt_status").select("id, user_id, pipeline_version").eq("id", receipt_id).limit(1).execute()
    runs_res = supabase.table("receipt_processing_runs").select(
        "id, stage, model_provider, model_name, model_version, status, error_message, validation_status, created_at, input_payload, output_payload"
    ).eq("receipt_id", receipt_id).order("created_at", desc=False).execute()
    steps = get_receipt_workflow_steps(receipt_id)
    return rec, runs_res, steps


@app.get("/api/receipt/{receipt_id}/processing-runs", tags=["Receipts - Other"])
async def get_receipt_processing_runs(
    receipt_id: str,
    user_id: str = Depends(get_current_user),
):
    """Get processing runs (workflow log) for a receipt. Admin/super_admin only; receipt must belong to current user."""
    from .services.database.supabase_client import get_user_class, USER_CLASS_ADMIN
    if get_user_class(user_id) < USER_CLASS_ADMIN:
        raise HTTPException(status_code=403, detail="Admin or super_admin required")
    rec, runs_res, steps = await asyncio.to_thread(_fetch_receipt_processing_runs_sync, receipt_id)
    if not rec.data or rec.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    pipeline_version = (rec.data[0].get("pipeline_version") or "legacy_a")
    # receipt_processing_runs has RLS: rows visible only when auth.uid() = receipt_status.user_id.
    # Backend must use SUPABASE_SERVICE_ROLE_KEY so RLS is bypassed; with anon key auth.uid() is null and runs come back empty.
    runs = runs_res.data or []
    if not runs and rec.data:
        logger.warning(
            "get_receipt_processing_runs: receipt %s has no runs in API response. "
            "If runs exist in DB, backend likely using anon key; set SUPABASE_SERVICE_ROLE_KEY to bypass RLS.",
            receipt_id,
        )
    track = "unknown"
    track_method = None
    for r in runs:
        if r.get("stage") == "rule_based_cleaning":
            out = r.get("output_payload") or {}
            if isinstance(out, dict) and out.get("success"):
                method = out.get("method")
                if method and str(method).strip():
                    track = "specific_rule"
                    track_method = str(method).strip()
                else:
                    track = "general"
            else:
                track = "general"
            break
    if track == "unknown" and pipeline_version == "vision_b":
        # Use the latest pass stage (runs ordered by created_at asc): store_specific > escalation > primary
        for r in runs:
            if r.get("status") != "pass":
                continue
            s = r.get("stage")
            if s in ("vision_primary", "vision_escalation", "vision_store_specific"):
                track = s
    return {
        "track": track,
        "track_method": track_method,
        "runs": runs,
        "workflow_steps": steps,
        "pipeline_version": pipeline_version,
    }


@app.post("/api/receipt/{receipt_id}/confirm-receipt", tags=["Receipts - Other"])
async def confirm_receipt_after_reject(
    receipt_id: str,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """User confirmed 'this is a clear receipt' after Valid fail or OCR fail. Runs Gemini Vision pipeline. Requires receipt in pending_receipt_confirm."""
    from pathlib import Path
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    rec = supabase.table("receipt_status").select("id, user_id, current_stage, raw_file_url").eq("id", receipt_id).limit(1).execute()
    if not rec.data or rec.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    row = rec.data[0]
    if row.get("current_stage") != "pending_receipt_confirm":
        raise HTTPException(status_code=400, detail="Receipt is not awaiting user confirmation")
    if not body.get("confirmed"):
        return {"success": False, "message": "User did not confirm"}
    raw_url = (row.get("raw_file_url") or "").strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="No image stored for this receipt")
    image_bytes: bytes
    if "://" not in raw_url or raw_url.startswith("/") or raw_url.startswith("output"):
        path = Path(raw_url)
        if not path.is_absolute():
            path = PROJECT_ROOT / raw_url
        if not path.exists():
            raise HTTPException(status_code=404, detail="Receipt image file not found")
        image_bytes = path.read_bytes()
    else:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(raw_url)
            r.raise_for_status()
            image_bytes = r.content
    mime_type = "image/jpeg"
    if raw_url.lower().endswith(".png"):
        mime_type = "image/png"
    # Run vision pipeline with existing receipt (no new create_receipt / duplicate check)
    result = await asyncio.to_thread(
        _run_vision_workflow_in_thread,
        image_bytes,
        Path(raw_url).name or "receipt.jpg",
        mime_type,
        user_id,
        existing_receipt_id=receipt_id,
    )
    return result


@app.post("/api/receipt/{receipt_id}/correct", tags=["Receipts - Other"])
async def correct_my_receipt(
    receipt_id: str,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """Submit manual correction for own receipt. Same body as admin failed-receipts submit: { summary, items }."""
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    rec = supabase.table("receipt_status").select("id, user_id").eq("id", receipt_id).limit(1).execute()
    if not rec.data or rec.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    from .services.admin.failed_receipts_service import submit_manual_correction
    summary = body.get("summary") or {}
    items = body.get("items") or []
    try:
        result = submit_manual_correction(receipt_id=receipt_id, summary=summary, items=items)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/receipt/{receipt_id}/review-complete", tags=["Receipts - Other"])
async def review_complete_my_receipt(
    receipt_id: str,
    user_id: str = Depends(get_current_user),
):
    """Mark a needs_review receipt as reviewed and set status to success. Must be receipt owner and current_status must be needs_review."""
    from .services.database.supabase_client import _get_client, update_receipt_status
    supabase = _get_client()
    rec = supabase.table("receipt_status").select("id, user_id, current_status, current_stage").eq("id", receipt_id).limit(1).execute()
    if not rec.data or rec.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    row = rec.data[0]
    if row.get("current_status") != "needs_review":
        raise HTTPException(status_code=400, detail="Receipt is not in needs_review status")
    stage = row.get("current_stage") or "vision_primary"
    update_receipt_status(receipt_id=receipt_id, current_status="success", current_stage=stage)
    return {"success": True, "receipt_id": receipt_id, "status": "success"}


@app.post("/api/receipt/{receipt_id}/escalate", tags=["Receipts - Other"])
async def escalate_receipt(
    receipt_id: str,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """User escalates a receipt with notes; receipt appears in admin Failed Receipts with kind 'User escalation' so admin can see what went wrong."""
    from .services.database.supabase_client import (
        _get_client,
        update_receipt_status,
        create_receipt_escalation,
    )
    supabase = _get_client()
    rec = supabase.table("receipt_status").select("id, user_id, current_stage").eq("id", receipt_id).limit(1).execute()
    if not rec.data or rec.data[0]["user_id"] != user_id:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    notes = (body.get("notes") or "").strip()
    create_receipt_escalation(receipt_id=receipt_id, user_id=user_id, notes=notes)
    stage = rec.data[0].get("current_stage") or "vision_primary"
    update_receipt_status(
        receipt_id=receipt_id,
        current_status="needs_review",
        current_stage=stage,
        admin_failure_kind="user_escalated",
    )
    return {"success": True, "receipt_id": receipt_id, "message": "Escalated; admin will review."}


@app.delete("/api/receipt/{receipt_id}", tags=["Receipts - Other"])
async def delete_my_receipt(
    receipt_id: str,
    user_id: str = Depends(get_current_user),
):
    """Permanently delete own receipt. Removes receipt and its record_items/summaries; does not affect products/price data. Auth required."""
    from .services.admin.failed_receipts_service import delete_receipt_for_user
    if not delete_receipt_for_user(receipt_id=receipt_id, user_id=user_id):
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    return {"success": True, "receipt_id": receipt_id}


@app.get("/api/categories", tags=["Receipts - Other"])
async def get_categories_for_user(user_id: str = Depends(get_current_user)):
    """
    Get current user's category tree for dropdowns. Returns per-user categories (seeds defaults on first call).
    Flat list: id, parent_id, name, path, level, is_locked, sort_order.
    Auth required.
    """
    from .services.categories.user_categories_service import (
        get_user_categories,
        seed_user_default_categories_if_needed,
    )
    seed_user_default_categories_if_needed(user_id)
    return {"data": get_user_categories(user_id)}


def _is_valid_uuid(s: str) -> bool:
    """Basic UUID format check (36 chars, 4 hyphens). Rejects 'null' and empty."""
    if not s or not isinstance(s, str) or s.strip().lower() == "null":
        return False
    s = s.strip()
    return len(s) == 36 and s.count("-") == 4


@app.patch("/api/receipt/{receipt_id}/item/{item_id}/category", tags=["Receipts - Other"])
async def update_item_category(
    receipt_id: str,
    item_id: str,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """
    Update one record_item's user_category_id (user-facing category).
    Body: { \"user_category_id\": \"uuid\" or null }. Must be receipt owner. Auth required.
    """
    if not _is_valid_uuid(receipt_id):
        raise HTTPException(status_code=400, detail="Invalid receipt_id")
    if not _is_valid_uuid(item_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid item_id. The item may not be saved yet (e.g. from run preview); complete review first.",
        )
    user_category_id = body.get("user_category_id")
    if user_category_id is not None and not isinstance(user_category_id, str):
        user_category_id = str(user_category_id) if user_category_id else None
    ok = update_record_item_category(
        receipt_id=receipt_id, item_id=item_id, user_id=user_id, user_category_id=user_category_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Item, receipt, or user_category not found or access denied")
    return {"success": True}


@app.patch("/api/receipt/{receipt_id}/items/categories", tags=["Receipts - Other"])
async def update_items_categories_batch(
    receipt_id: str,
    body: dict = Body(...),
    user_id: str = Depends(get_current_user),
):
    """
    Batch-update user_category_id for multiple record_items in one request.
    Body: { "updates": [{ "item_id": "uuid", "user_category_id": "uuid" | null }] }
    Auth required; verifies receipt and category ownership.
    """
    if not _is_valid_uuid(receipt_id):
        raise HTTPException(status_code=400, detail="Invalid receipt_id")
    updates = body.get("updates")
    if not isinstance(updates, list) or not updates:
        raise HTTPException(status_code=400, detail="updates must be a non-empty list")
    for u in updates:
        if not isinstance(u, dict) or not u.get("item_id"):
            raise HTTPException(status_code=400, detail="Each update must have item_id")
        if not _is_valid_uuid(u["item_id"]):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid item_id {u['item_id']}. The item may not be saved yet; complete review first.",
            )
        cat_id = u.get("user_category_id")
        if cat_id is not None and not _is_valid_uuid(str(cat_id)):
            raise HTTPException(status_code=400, detail=f"Invalid user_category_id {cat_id}")
    result = update_record_items_categories_batch(
        receipt_id=receipt_id,
        user_id=user_id,
        updates=updates,
    )
    if result.get("error") == "receipt_not_found":
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    return result


@app.post("/api/receipt/coordinate-sum-check", tags=["Receipts - Other"])
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
        # Note: Items are now extracted directly from coordinates, not from LLM result
        llm_result_proxy = {
            "receipt": {
                "subtotal": docai_result.get("subtotal"),
                "tax": docai_result.get("tax") or 0.0,
                "total": docai_result.get("total")
            },
            "items": []  # Items will be extracted from coordinates, not from here
        }
        
        is_valid, check_details = coordinate_based_sum_check(
            blocks,
            regions,
            llm_result_proxy
        )
        
        # Print formatted output to console for debugging (only if debug logs enabled)
        from .config import settings
        formatted_output = check_details.get("formatted_output", "")
        if formatted_output and settings.enable_debug_logs:
            logger.info("=" * 60)
            logger.info("Coordinate Sum Check - Formatted Output:")
            logger.info("=" * 60)
            # Print each line separately so it displays correctly in console
            for line in formatted_output.split('\n'):
                logger.info(line)
            logger.info("=" * 60)
        
        # Generate response (formatted_output is already in check_details, no need to duplicate)
        response = {
            "success": True,
            "coordinate_check": check_details,
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
                "pages_count": len(coordinate_data.get("pages", [])),
                "all_text_blocks": [
                    {
                        "text": b.get("text", ""),
                        "x": round(b.get("x", 0), 4),
                        "y": round(b.get("y", 0), 4),
                        "center_x": round(b.get("center_x", 0), 4) if b.get("center_x") else None,
                        "center_y": round(b.get("center_y", 0), 4) if b.get("center_y") else None,
                        "is_amount": b.get("is_amount", False),
                        "amount": round(b.get("amount", 0), 2) if b.get("amount") else None
                    }
                    for b in blocks[:200]  # Limit to first 200 blocks to avoid huge response
                ]
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


def _block_to_json(b: dict) -> dict:
    """Serialize a text block for JSON response (text, center_x, center_y, is_amount, amount)."""
    return {
        "text": b.get("text", ""),
        "center_x": round(b.get("center_x", 0), 4),
        "center_y": round(b.get("center_y", 0), 4),
        "is_amount": b.get("is_amount", False),
        "amount": round(b.get("amount", 0), 2) if b.get("amount") is not None else None,
    }


@app.post("/api/receipt/body-detector", tags=["Receipts - Other"])
async def receipt_body_detector_endpoint(file: UploadFile = File(..., description="Receipt image (JPEG or PNG)")):
    """
    Receipt body detector: upload a JPEG/PNG, get JSON with the estimated receipt body box and which blocks are inside vs dropped.
    Use this to verify that all valid receipt content is inside the new bounds (and nothing important was dropped).
    """
    if file.content_type not in ("image/jpeg", "image/jpg", "image/png"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG or PNG images are supported.",
        )
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Empty file.")
    mime_type = file.content_type or "image/jpeg"
    try:
        docai_result = parse_receipt_documentai(contents, mime_type=mime_type)
        coordinate_data = docai_result.get("coordinate_data", {})
        if not coordinate_data:
            raise HTTPException(
                status_code=500,
                detail="Failed to extract coordinate data from Document AI response",
            )
        all_blocks = extract_text_blocks_with_coordinates(coordinate_data, apply_receipt_body_filter=False)
        bounds = get_receipt_body_bounds(all_blocks)
        blocks_inside = filter_blocks_by_receipt_body(all_blocks)
        left_bound = bounds.get("left_bound", 0)
        right_bound = bounds.get("right_bound", 1)
        y_keep_min = bounds.get("y_keep_min", 0)
        blocks_dropped = [
            b for b in all_blocks
            if not (b.get("center_y", 0) >= y_keep_min and left_bound <= b.get("center_x", 0) <= right_bound)
        ]
        return {
            "success": True,
            "bounds": bounds,
            "count_inside": len(blocks_inside),
            "count_dropped": len(blocks_dropped),
            "blocks_inside": [_block_to_json(b) for b in blocks_inside],
            "blocks_dropped": [_block_to_json(b) for b in blocks_dropped],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Receipt body detector failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Receipt body detector failed: {str(e)}",
        )


@app.post("/api/receipt/workflow-bulk", dependencies=[Depends(get_current_user)], tags=["Receipts - Other"])
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


# ==================== Admin (require_admin dependency) ====================

# Explicit tier values so admin check does not depend on constant identity (avoids prod/dev mismatch).
_REQUIRE_ADMIN_MIN_TIER = 7  # 7=admin, 9=super_admin

async def require_admin(user_id: str = Depends(get_current_user)) -> str:
    """
    Dependency to require admin (7) or super_admin (9) user class.
    Uses literal 7 so production cannot deny tier-7 due to wrong USER_CLASS_ADMIN.
    """
    from .services.database.supabase_client import get_user_class
    try:
        raw = await asyncio.to_thread(get_user_class, user_id)
        user_class = int(raw) if raw is not None else 0
        if user_class >= _REQUIRE_ADMIN_MIN_TIER:
            logger.debug("require_admin: user_id=%s user_class=%s OK", user_id, user_class)
            return user_id
        # Log at WARNING so it appears in production; search logs for "REQUIRE_ADMIN_403" or "require_admin"
        logger.warning(
            "REQUIRE_ADMIN_403 require_admin: user_id=%s user_class=%s (need>=%s) — run in DB: UPDATE users SET user_class=7 WHERE id='%s'",
            user_id, user_class, _REQUIRE_ADMIN_MIN_TIER, user_id,
        )
        # Use structured detail so frontend shows "code: REQUIRE_ADMIN_DENIED" (not "7" as error code).
        # Include user_id so operator can verify in DB: SELECT id, user_class FROM users WHERE id = '<user_id>'
        raise HTTPException(
            status_code=403,
            detail={
                "code": "REQUIRE_ADMIN_DENIED",
                "message": "Access denied. Required: admin or super_admin.",
                "required_tier_min": _REQUIRE_ADMIN_MIN_TIER,
                "current_tier": user_class,
                "user_id": user_id,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check user class for {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to verify user permissions")


# ==================== Admin User Management (list / update user_class) ====================

@app.get("/api/admin/users", tags=["Admin - User Management"])
async def admin_list_users(
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(require_admin),
):
    """List users (id, email, user_class, user_name, registration_no, status). Admin/super_admin only. Returns current_user_class so frontend can restrict editable tiers."""
    from .services.database.supabase_client import _get_client, get_user_class
    supabase = _get_client()
    res = supabase.table("users").select("id, email, user_class, user_name, registration_no, status, created_at", count="exact").order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    current_user_class = get_user_class(user_id)
    return {"data": res.data or [], "total": res.count or 0, "limit": limit, "offset": offset, "current_user_class": current_user_class}


@app.patch("/api/admin/users/{target_user_id}", tags=["Admin - User Management"])
async def admin_patch_user(
    target_user_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(require_admin),
):
    """Update a user (e.g. user_class). Admin/super_admin only. You may only set user_class to a value strictly lower than your own (e.g. 9 can set up to 7, 7 can set up to 2). Body: { \"user_class\": 0|2|7|9 }."""
    from .services.database.supabase_client import _get_client, get_user_class, USER_CLASS_FREE, USER_CLASS_PREMIUM, USER_CLASS_ADMIN, USER_CLASS_SUPER_ADMIN
    uc = body.get("user_class")
    if uc is None:
        raise HTTPException(status_code=400, detail="Missing user_class")
    try:
        uc = int(uc)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="user_class must be an integer")
    allowed = {USER_CLASS_FREE, USER_CLASS_PREMIUM, USER_CLASS_ADMIN, USER_CLASS_SUPER_ADMIN}
    if uc not in allowed:
        raise HTTPException(status_code=400, detail=f"user_class must be one of {sorted(allowed)}")
    current_class = get_user_class(user_id)
    if uc >= current_class:
        raise HTTPException(
            status_code=403,
            detail=f"You may only set users to a tier lower than your own (yours={current_class}). Cannot set to {uc}."
        )
    target_current_class = get_user_class(target_user_id)
    if target_current_class >= current_class:
        raise HTTPException(
            status_code=403,
            detail="You cannot change the tier of a user whose tier is same or higher than yours."
        )
    supabase = _get_client()
    res = supabase.table("users").update({"user_class": uc}).eq("id", target_user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")
    from .middleware.rate_limiter import clear_user_class_cache
    clear_user_class_cache(target_user_id)
    return {"ok": True, "user_id": target_user_id, "user_class": uc}


# ==================== Admin Classification Review Endpoints ====================

@app.get("/api/admin/classification-review/suggest-normalized", tags=["Admin - Classification Review"])
async def admin_suggest_normalized_names(
    q: Optional[str] = None,
    limit: int = 20,
    user_id: str = Depends(require_admin),
):
    """Suggest normalized_name from products and product_categorization_rules for autocomplete. Admin only."""
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    seen = set()
    out = []
    if q and len(q.strip()) >= 1:
        qn = q.strip().lower()
        for table in ("products", "product_categorization_rules"):
            res = supabase.table(table).select("normalized_name").ilike("normalized_name", f"%{qn}%").limit(limit).execute()
            for r in (res.data or []):
                n = (r.get("normalized_name") or "").strip()
                if n and n not in seen:
                    seen.add(n)
                    out.append(n)
                    if len(out) >= limit:
                        break
            if len(out) >= limit:
                break
    return {"suggestions": out[:limit]}


@app.get("/api/admin/classification-review", tags=["Admin - Classification Review"])
async def admin_list_classification_review(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(require_admin),
):
    """List classification_review rows; filter by status (pending, confirmed, etc.). Admin only."""
    from .services.admin.classification_review_service import list_classification_review
    rows, total = list_classification_review(status=status, limit=limit, offset=offset)
    return {"data": rows, "total": total, "limit": limit, "offset": offset}


@app.patch("/api/admin/classification-review/{cr_id}", tags=["Admin - Classification Review"])
async def admin_patch_classification_review(
    cr_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(require_admin),
):
    """Update a classification_review row (normalized_name, category_id, status, etc.). Admin only."""
    from .services.admin.classification_review_service import update_classification_review
    try:
        row = update_classification_review(
            cr_id,
            normalized_name=body.get("normalized_name"),
            category_id=body.get("category_id"),
            store_chain_id=body.get("store_chain_id"),
            size_quantity=body.get("size_quantity"),
            size_unit=body.get("size_unit"),
            package_type=body.get("package_type"),
            match_type=body.get("match_type"),
            status=body.get("status"),
        )
        return row
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/classification-review/{cr_id}/confirm", tags=["Admin - Classification Review"])
async def admin_confirm_classification_review(
    cr_id: str,
    body: Optional[dict] = Body(None),
    user_id: str = Depends(require_admin),
):
    """
    Confirm a row: write to product_categorization_rules and products, set status=confirmed.
    If body has "force_different_name": true, skip similarity check.
    Returns 409 if similar normalized_name exists and force_different_name not set.
    """
    from .services.admin.classification_review_service import confirm_classification_review
    body = body or {}
    force = body.get("force_different_name", False)
    try:
        result = confirm_classification_review(cr_id, confirmed_by=user_id, force_different_name=force)
        if result.get("similar_to"):
            raise HTTPException(
                status_code=409,
                detail={"similar_to": result["similar_to"], "message": result.get("message", "")},
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/admin/classification-review/{cr_id}", tags=["Admin - Classification Review"])
async def admin_delete_classification_review(
    cr_id: str,
    user_id: str = Depends(require_admin),
):
    """Hard-delete a classification_review row. Use to remove duplicate or unwanted entries. Admin only."""
    from .services.admin.classification_review_service import delete_classification_review
    try:
        delete_classification_review(cr_id)
        return {"success": True, "id": cr_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/classification-review/backfill-record-items", tags=["Admin - Classification Review"])
async def admin_backfill_record_items(
    user_id: str = Depends(require_admin),
    limit: int = 0,
    batch: int = 200,
):
    """
    Backfill record_items: product_name_clean (where NULL), on_sale→false (quantity×unit pricing),
    product_id (link to products by normalized_name + store_chain). Admin only.
    Same logic as scripts/maintenance/backfill_product_name_clean.py; use this to run on demand (e.g. after confirming items in Classification Review).
    """
    from .services.admin.record_items_backfill_service import run_record_items_backfill
    result = run_record_items_backfill(limit=limit or 0, batch_size=batch, dry_run=False)
    return {"success": True, **result}


@app.post("/api/admin/classification-review/dedupe", tags=["Admin - Classification Review"])
async def admin_dedupe_classification_review(user_id: str = Depends(require_admin)):
    """
    Remove duplicate classification_review rows: same store_chain + same normalized product.
    Keeps the latest (by created_at); deletes older duplicates. Admin only.
    """
    from .services.admin.classification_review_service import dedupe_classification_review
    result = dedupe_classification_review()
    return {"success": True, **result}


# ==================== Admin Store Review (store_candidates) ====================

@app.get("/api/admin/store-review", tags=["Admin - Store Review"])
async def admin_list_store_review(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(require_admin),
):
    """List store_candidates; filter by status (pending, approved, rejected). Admin only."""
    from .services.admin.store_review_service import list_store_candidates
    rows, total = list_store_candidates(status=status, limit=limit, offset=offset)
    return {"data": rows, "total": total, "limit": limit, "offset": offset}


@app.get("/api/admin/store-review/chains", tags=["Admin - Store Review"])
async def admin_list_store_chains(
    active_only: bool = True,
    user_id: str = Depends(require_admin),
):
    """List store_chains for dropdown (add as location of). Admin only."""
    from .services.admin.store_review_service import list_store_chains
    return {"data": list_store_chains(active_only=active_only)}


@app.patch("/api/admin/store-review/{candidate_id}", tags=["Admin - Store Review"])
async def admin_patch_store_review(
    candidate_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(require_admin),
):
    """Update a store_candidates row (raw_name, normalized_name, status, rejection_reason). Admin only."""
    from .services.admin.store_review_service import update_store_candidate
    try:
        row = update_store_candidate(
            candidate_id,
            raw_name=body.get("raw_name"),
            normalized_name=body.get("normalized_name"),
            status=body.get("status"),
            rejection_reason=body.get("rejection_reason"),
        )
        return row
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/store-review/{candidate_id}/approve", tags=["Admin - Store Review"])
async def admin_approve_store_review(
    candidate_id: str,
    body: Optional[dict] = Body(None),
    user_id: str = Depends(require_admin),
):
    """
    Approve a store candidate: create store_chain and/or store_location, set status=approved.
    Body: chain_name (for new chain), add_as_location_of_chain_id (to add only location to existing chain),
    location_name, address_line1, city, state, zip_code, country_code, phone.
    """
    from .services.admin.store_review_service import approve_store_candidate
    body = body or {}
    try:
        result = approve_store_candidate(
            candidate_id,
            approved_by=user_id,
            chain_name=body.get("chain_name"),
            add_as_location_of_chain_id=body.get("add_as_location_of_chain_id"),
            location_name=body.get("location_name"),
            address_line1=body.get("address_line1"),
            address_line2=body.get("address_line2"),
            city=body.get("city"),
            state=body.get("state"),
            zip_code=body.get("zip_code"),
            country_code=body.get("country_code"),
            phone=body.get("phone"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/admin/store-review/{candidate_id}/reject", tags=["Admin - Store Review"])
async def admin_reject_store_review(
    candidate_id: str,
    body: Optional[dict] = Body(None),
    user_id: str = Depends(require_admin),
):
    """Reject a store candidate. Body: rejection_reason (optional)."""
    from .services.admin.store_review_service import reject_store_candidate
    body = body or {}
    try:
        result = reject_store_candidate(
            candidate_id,
            reviewed_by=user_id,
            rejection_reason=body.get("rejection_reason"),
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/store-review/backfill-store-locations", tags=["Admin - Store Review"])
async def admin_backfill_store_locations(
    body: Optional[dict] = Body(None),
    user_id: str = Depends(require_admin),
):
    """
    Backfill record_summaries.store_location_id for receipts that match existing store_locations
    by address (with Suite/Unit/Ste normalized). Optional body: { "location_id": "uuid" } to run for one location only.
    """
    from .services.database.supabase_client import run_backfill_store_locations
    location_id = (body or {}).get("location_id") if isinstance(body, dict) else None
    result = run_backfill_store_locations(location_id=location_id)
    return result


# ==================== Admin Failed Receipts (manual correct) ====================

@app.get("/api/admin/failed-receipts", tags=["Admin - Failed Receipts"])
async def admin_list_failed_receipts(
    limit: int = 50,
    offset: int = 0,
    user_id: str = Depends(require_admin),
):
    """List failed/needs_review receipts with failure reason. Admin only."""
    from .services.admin.failed_receipts_service import list_failed_receipts
    rows, total = list_failed_receipts(limit=limit, offset=offset)
    return {"data": rows, "total": total, "limit": limit, "offset": offset}


@app.get("/api/admin/failed-receipts/{receipt_id}", tags=["Admin - Failed Receipts"])
async def admin_get_failed_receipt(
    receipt_id: str,
    user_id: str = Depends(require_admin),
):
    """Get one failed receipt for manual correct (prefill from DB or last run). Admin only."""
    from .services.admin.failed_receipts_service import get_failed_receipt_for_edit
    row = get_failed_receipt_for_edit(receipt_id)
    if not row:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return row


@app.post("/api/admin/failed-receipts/{receipt_id}/submit", tags=["Admin - Failed Receipts"])
async def admin_submit_failed_receipt_correction(
    receipt_id: str,
    body: dict = Body(...),
    user_id: str = Depends(require_admin),
):
    """Submit manually corrected receipt data. Creates/updates record_summaries and record_items, sets status=success. Admin only."""
    from .services.admin.failed_receipts_service import submit_manual_correction
    summary = body.get("summary") or {}
    items = body.get("items") or []
    try:
        result = submit_manual_correction(receipt_id=receipt_id, summary=summary, items=items)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/admin/failed-receipts/{receipt_id}", tags=["Admin - Failed Receipts"])
async def admin_delete_failed_receipt(
    receipt_id: str,
    user_id: str = Depends(require_admin),
):
    """Hard-delete a failed/needs_review receipt and all related records. Admin only."""
    from .services.admin.failed_receipts_service import (
        delete_receipt_hard,
        get_failed_receipt_for_edit,
        FAILED_STATUSES,
    )
    row = get_failed_receipt_for_edit(receipt_id)
    if not row or row.get("current_status") not in FAILED_STATUSES:
        raise HTTPException(status_code=404, detail="Receipt not found or not in failed/needs_review")
    try:
        delete_receipt_hard(receipt_id)
        return {"success": True, "receipt_id": receipt_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/receipt-image/{receipt_id}", tags=["Admin - Failed Receipts"])
async def admin_get_receipt_image(
    receipt_id: str,
    user_id: str = Depends(require_admin),
):
    """Serve receipt image for failed/needs_review receipts. raw_file_url may be local path or HTTP URL. Admin only."""
    from pathlib import Path
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    res = supabase.table("receipt_status").select("raw_file_url").eq("id", receipt_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Receipt not found")
    raw_url = (res.data[0].get("raw_file_url") or "").strip()
    if not raw_url:
        raise HTTPException(status_code=404, detail="No image for this receipt")
    # If HTTP/HTTPS, redirect (frontend should use raw_url directly; this endpoint for local paths)
    if raw_url.lower().startswith(("http://", "https://")):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=raw_url)
    # Local path: resolve relative to project root; guard against path traversal
    file_path = (PROJECT_ROOT / raw_url).resolve()
    try:
        file_path.relative_to(PROJECT_ROOT)
    except ValueError:
        raise HTTPException(status_code=404, detail="Image file not found")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
    # Infer media type from extension
    suffix = file_path.suffix.lower()
    media = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png" if suffix == ".png" else "application/octet-stream"
    return FileResponse(str(file_path), media_type=media)


# ==================== Admin Categories Endpoints ====================

@app.get("/api/admin/categories", tags=["Admin - Categories"])
async def admin_get_categories_tree(
    active_only: bool = True,
    user_id: str = Depends(require_admin),
):
    """Get categories tree (flat list with id, parent_id, name, path, level). Admin only."""
    from .services.admin.categories_admin_service import get_categories_tree
    return {"data": get_categories_tree(active_only=active_only)}


@app.post("/api/admin/categories", tags=["Admin - Categories"])
async def admin_create_category(
    body: dict = Body(...),
    user_id: str = Depends(require_admin),
):
    """Create category. Body: parent_id (null for L1), name, level. Returns 409 if same name under same parent. Admin only."""
    from .services.admin.categories_admin_service import create_category
    try:
        row = create_category(
            parent_id=body.get("parent_id"),
            name=body.get("name", ""),
            level=int(body.get("level", 1)),
        )
        return row
    except ValueError as e:
        if str(e) == "already_exists":
            raise HTTPException(status_code=409, detail="Category with same name under same parent already exists")
        raise HTTPException(status_code=400, detail=str(e))


@app.patch("/api/admin/categories/{cat_id}", tags=["Admin - Categories"])
async def admin_update_category(
    cat_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(require_admin),
):
    """Update category name. Admin only."""
    from .services.admin.categories_admin_service import update_category
    try:
        return update_category(cat_id, name=body.get("name"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/admin/categories/{cat_id}", tags=["Admin - Categories"])
async def admin_delete_category(
    cat_id: str,
    user_id: str = Depends(require_admin),
):
    """Soft delete category (set is_active=false). Admin only."""
    from .services.admin.categories_admin_service import delete_category_soft
    try:
        delete_category_soft(cat_id)
        return {"message": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/categories/{cat_id}/hard-delete", tags=["Admin - Categories"])
async def admin_hard_delete_category(
    cat_id: str,
    body: dict = Body(...),
    user_id: str = Depends(require_admin),
):
    """
    Hard delete category (and descendants). Body: action = "release" | "reassign";
    if "reassign", target_category_id (L3 uuid) required.
    Related record_items/classification_review (and rules/overrides when reassign) are updated then category removed.
    """
    from .services.admin.categories_admin_service import hard_delete_category
    action = (body.get("action") or "").strip().lower()
    if action not in ("release", "reassign"):
        raise HTTPException(status_code=400, detail="action must be 'release' or 'reassign'")
    target_category_id = body.get("target_category_id") or None
    if action == "reassign" and not target_category_id:
        raise HTTPException(status_code=400, detail="target_category_id required when action is reassign")
    try:
        result = hard_delete_category(cat_id, action=action, target_category_id=target_category_id)
        return result
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)


@app.get("/api/admin/users/{target_user_id}/categories", tags=["Admin - Categories"])
async def admin_get_user_categories(
    target_user_id: str,
    user_id: str = Depends(require_admin),
):
    """
    Admin: get the full category tree for any user.
    Useful for debugging and analytics. Admin only.
    """
    from .services.categories.user_categories_service import admin_get_user_categories
    return {"data": admin_get_user_categories(target_user_id)}


# ==================== RAG Management Endpoints ====================

@app.post("/api/receipt/initial-parse", tags=["Receipts - Other"])
async def initial_parse(file: UploadFile = File(...)):
    """
    Initial parse: row-based receipt pipeline (structured parse with optional store config).
    
    This endpoint uses the pipeline architecture:
    1. Physical row reconstruction
    2. Statistical column detection
    3. Region splitting
    4. Item extraction with multi-line support
    5. Totals sequence extraction
    6. Tax/fee classification
    7. Math validation
    8. Amount usage tracking (消消乐)
    
    Returns:
        Dictionary containing:
        - success: Whether validation passed
        - items: Extracted items
        - totals: Subtotal, tax, fees, total
        - validation: Validation results
        - usage_tracker: Amount usage summary
        - formatted_output: Vertical addition format for debugging
    """
    try:
        # Read file
        contents = await file.read()
        mime_type = file.content_type or "image/jpeg"
        
        # Call Document AI to get coordinate data
        from .services.ocr.documentai_client import parse_receipt_documentai
        docai_result = parse_receipt_documentai(contents, mime_type)
        
        # Extract coordinate_data (same as old endpoint: text_blocks live under coordinate_data)
        coordinate_data = docai_result.get("coordinate_data", {})
        if not coordinate_data:
            raise HTTPException(
                status_code=500,
                detail="Failed to extract coordinate data from Document AI response"
            )
        
        # Extract text blocks with coordinates (all then filter for receipt body so we can log included/dropped)
        from .processors.validation.coordinate_extractor import extract_text_blocks_with_coordinates
        from .processors.validation.receipt_body_detector import filter_blocks_by_receipt_body, get_receipt_body_bounds
        all_blocks = extract_text_blocks_with_coordinates(coordinate_data, apply_receipt_body_filter=False)
        blocks = filter_blocks_by_receipt_body(all_blocks)
        receipt_body_bounds = get_receipt_body_bounds(all_blocks)
        left_b = receipt_body_bounds.get("left_bound", 0)
        right_b = receipt_body_bounds.get("right_bound", 1)
        y_keep_min = receipt_body_bounds.get("y_keep_min", 0)
        dropped_blocks = [
            b for b in all_blocks
            if not (b.get("center_y", 0) >= y_keep_min and left_b <= b.get("center_x", 0) <= right_b)
        ]
        dropped_blocks.sort(key=lambda b: (b.get("center_y", 0), b.get("center_x", 0)))
        receipt_body_dropped_count = len(dropped_blocks)

        # Load store config by merchant name (config-driven pipeline)
        from .processors.validation.store_config_loader import get_store_config_for_receipt
        merchant_name = docai_result.get("merchant_name") or ""
        store_config = get_store_config_for_receipt(merchant_name, blocks=blocks)
        if store_config:
            logger.info(f"Using store config: chain_id={store_config.get('chain_id', '')}")

        # Create LLM result proxy (for expected values)
        llm_result_proxy = {
            "receipt": {
                "subtotal": docai_result.get("subtotal"),
                "tax": docai_result.get("tax") or 0.0,
                "total": docai_result.get("total")
            },
            "items": []
        }

        # Auto-save test fixture for debugging (blocks + chain_id)
        try:
            from datetime import datetime
            from pathlib import Path
            import json
            import glob
            
            test_fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
            test_fixtures_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate filename: YYYYMMDD_HHMMSS_{counter}.json
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            existing = list(test_fixtures_dir.glob(f"{timestamp}_*.json"))
            counter = len(existing) + 1
            fixture_filename = f"{timestamp}_{counter}.json"
            fixture_path = test_fixtures_dir / fixture_filename
            
            fixture_data = {
                "chain_id": store_config.get("chain_id") if store_config else None,
                "merchant_name": merchant_name,
                "timestamp": datetime.now().isoformat(),
                "blocks": blocks
            }
            
            with open(fixture_path, "w", encoding="utf-8") as f:
                json.dump(fixture_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"✓ Auto-saved test fixture: {fixture_path.name}")
        except Exception as e:
            # Don't fail the request if fixture save fails
            logger.warning(f"Failed to save test fixture: {e}")
        
        # Process using new pipeline (with optional store config and merchant_name)
        result = process_receipt_pipeline(blocks, llm_result_proxy, store_config=store_config, merchant_name=merchant_name)
        
        # Print formatted output to console for debugging (only if debug logs enabled)
        from .config import settings
        formatted_output = result.get("formatted_output", "")
        if formatted_output and settings.enable_debug_logs:
            logger.info("=" * 60)
            logger.info("Pipeline V2 - Formatted Output:")
            logger.info("=" * 60)
            for line in formatted_output.split('\n'):
                logger.info(line)
            logger.info("=" * 60)
        
        # Print usage tracker summary (only if debug logs enabled)
        usage_summary = result.get("usage_tracker", {})
        if usage_summary and settings.enable_debug_logs:
            logger.info("=" * 60)
            logger.info("Amount Usage Tracker Summary:")
            logger.info(f"Total used: {usage_summary.get('total_used', 0)}")
            logger.info(f"Role distribution: {usage_summary.get('role_distribution', {})}")
            logger.info("=" * 60)

        # Print OCR and region info (only if debug logs enabled) — unified format: line_no, x, y, amt, included, text; section separators
        ocr_regions = result.get("ocr_and_regions", {})
        if ocr_regions and settings.enable_debug_logs:
            logger.info("=" * 60)
            logger.info("OCR & Regions (line_no, x, y, amt, receipt body included, text):")
            logger.info("Receipt body: %d inside, %d dropped", len(blocks), receipt_body_dropped_count)
            ac = ocr_regions.get("amount_column", {})
            logger.info("Amount column: main_x=%s, tolerance=%s — %s", ac.get("main_x"), ac.get("tolerance"), ac.get("note", ""))
            section_rows_detail = ocr_regions.get("section_rows_detail", [])
            line_no = 0
            for sec_idx, sec in enumerate(section_rows_detail):
                logger.info("---------- %s ----------", sec.get("label", sec.get("section", "")))
                for row in sec.get("rows", []):
                    for blk in row.get("blocks", []):
                        line_no += 1
                        x = blk.get("x", 0) / 10000.0  # Convert back from integer
                        y = blk.get("y", 0) / 10000.0  # Convert back from integer
                        amt = blk.get("is_amount", False)
                        text = (blk.get("text") or "")[:80]
                        logger.info("  [%d] x=%.4f y=%.4f amt=%s included=T | %s", line_no, x, y, "T" if amt else "F", repr(text))
                # Separator after each section (e.g. after last header row, before Items)
                if sec_idx + 1 < len(section_rows_detail):
                    logger.info("----------")
            if dropped_blocks:
                logger.info("---------- Dropped (outside receipt body) ----------")
                for b in dropped_blocks:
                    line_no += 1
                    x = b.get("center_x", 0)  # Original blocks still have center_x/center_y
                    y = b.get("center_y", 0)
                    amt = b.get("is_amount", False)
                    text = ((b.get("text") or "")[:80])
                    logger.info("  [%d] x=%.4f y=%.4f amt=%s included=F | %s", line_no, x, y, "T" if amt else "F", repr(text))
            logger.info("=" * 60)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in initial-parse: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


# ============================================
# Categorization Endpoints
# ============================================

class CategorizeReceiptRequest(BaseModel):
    receipt_id: str
    force: Optional[bool] = False

class CategorizeReceiptsBatchRequest(BaseModel):
    receipt_ids: List[str]
    force: Optional[bool] = False


@app.post("/api/receipt/categorize/{receipt_id}", tags=["Receipts - Categorization"])
async def categorize_single_receipt(
    receipt_id: str,
    force: bool = False,
    user_id: str = Depends(get_current_user),
):
    """
    将 receipt_processing_runs.output_payload 标准化并保存到 record_items/record_summaries

    前置条件：
    1. Receipt 必须存在且属于当前用户
    2. current_status 必须是 'success' (通过了 sum check)
    3. 必须有成功的 LLM processing run

    参数：
    - receipt_id: Receipt UUID
    - force: 如果为 True，重新处理已经 categorize 过的小票

    返回：
    {
        "success": bool,
        "receipt_id": str,
        "summary_id": str,
        "items_count": int,
        "message": str
    }
    """
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    owns = supabase.table("receipt_status").select("id").eq("id", receipt_id).eq("user_id", user_id).limit(1).execute()
    if not owns.data:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    try:
        # categorize_receipt is sync and may call asyncio.run() internally; run in thread to avoid "asyncio.run() cannot be called from a running event loop"
        result = await asyncio.to_thread(categorize_receipt, receipt_id, force=force)

        if not result.get("success"):
            raise HTTPException(
                status_code=400,
                detail=result.get("message", "Categorization failed")
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error categorizing receipt {receipt_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/receipt/categorize-batch", tags=["Receipts - Categorization"])
async def categorize_batch_receipts(
    request: CategorizeReceiptsBatchRequest,
    user_id: str = Depends(get_current_user),
):
    """
    批量 categorize 多张小票

    参数：
    - receipt_ids: List of receipt UUIDs
    - force: 如果为 True，重新处理已经 categorize 过的小票

    返回：
    {
        "total": int,
        "success": int,
        "failed": int,
        "results": [...]
    }
    """
    if not request.receipt_ids:
        return {"total": 0, "success": 0, "failed": 0, "results": []}

    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    owned_rows = supabase.table("receipt_status").select("id").in_("id", request.receipt_ids).eq("user_id", user_id).execute()
    owned_ids = {row["id"] for row in (owned_rows.data or [])}
    unauthorized = [rid for rid in request.receipt_ids if rid not in owned_ids]
    if unauthorized:
        raise HTTPException(status_code=403, detail=f"Access denied for {len(unauthorized)} receipt(s)")

    try:
        # Run in thread so internal asyncio.run() (e.g. in categorize_receipt) does not conflict with the event loop
        result = await asyncio.to_thread(
            categorize_receipts_batch,
            receipt_ids=list(owned_ids),
            force=request.force,
        )
        return result
    except Exception as e:
        logger.error(f"Error in batch categorization: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/receipt/{receipt_id}/smart-categorize", tags=["Receipts - Categorization"])
async def smart_categorize_my_receipt(
    receipt_id: str,
    user_id: str = Depends(get_current_user),
    body: Optional[dict] = Body(None),
):
    """Run rules + LLM on items. If body.item_ids is provided, run only on those record_item ids (re-run selected); else only uncategorized."""
    item_ids = None
    if body and isinstance(body.get("item_ids"), list) and len(body["item_ids"]) > 0:
        item_ids = [str(x) for x in body["item_ids"]]
    result = await smart_categorize_receipt_items(receipt_id=receipt_id, user_id=user_id, item_ids=item_ids)
    if not result.get("success"):
        raise HTTPException(status_code=404 if "not found" in (result.get("message") or "").lower() else 400, detail=result.get("message"))
    return result


@app.get("/api/receipt/categorize/check/{receipt_id}", tags=["Receipts - Categorization"])
async def check_can_categorize(
    receipt_id: str,
    user_id: str = Depends(get_current_user),
):
    """
    检查小票是否可以被 categorize

    返回：
    {
        "can_categorize": bool,
        "reason": str
    }
    """
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    owns = supabase.table("receipt_status").select("id").eq("id", receipt_id).eq("user_id", user_id).limit(1).execute()
    if not owns.data:
        raise HTTPException(status_code=404, detail="Receipt not found or access denied")
    try:
        can_categorize, reason = can_categorize_receipt(receipt_id)
        return {
            "receipt_id": receipt_id,
            "can_categorize": can_categorize,
            "reason": reason,
        }
    except Exception as e:
        logger.error(f"Error checking receipt {receipt_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Communications: articles + updates (content/articles, content/updates) ====================

_CONTENT_ROOT = Path(__file__).resolve().parent.parent.parent / "content"
_CONTENT_ARTICLES_DIR = _CONTENT_ROOT / "articles"
_CONTENT_UPDATES_DIR = _CONTENT_ROOT / "updates"


def _normalize_ledger_lens(s: str) -> str:
    """Remove any space (including Unicode spaces) between 'Ledger' and 'Lens' so it renders as LedgerLens."""
    if not s or "Ledger" not in s or "Lens" not in s:
        return s
    return re.sub(r"Ledger\s+Lens", "LedgerLens", s, flags=re.IGNORECASE)


def _parse_blog_frontmatter(content: str) -> tuple[dict, str]:
    """Parse --- delimited frontmatter; return (attrs, body)."""
    if not content.strip().startswith("---"):
        return {}, content
    parts = content.strip().split("\n", 1)
    rest = parts[1] if len(parts) > 1 else ""
    if "---" not in rest:
        return {}, content
    fm, body = rest.split("---", 1)
    attrs = {}
    for line in fm.strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            val = v.strip().strip('"').strip("'")
            if k.strip().lower() in ("title", "subtitle"):
                val = _normalize_ledger_lens(val)
            attrs[k.strip().lower()] = val
    return attrs, body.strip()


def _list_blog_posts() -> List[dict]:
    """List .md from content/articles (type=article) and content/updates (type=update); return sorted by date desc."""
    out = []
    for content_dir, post_type in [(_CONTENT_ARTICLES_DIR, "article"), (_CONTENT_UPDATES_DIR, "update")]:
        if not content_dir.exists():
            continue
        for p in content_dir.glob("*.md"):
            try:
                raw = p.read_text(encoding="utf-8")
                attrs, body = _parse_blog_frontmatter(raw)
                slug = attrs.get("slug") or p.stem
                title = attrs.get("title") or slug
                subtitle = attrs.get("subtitle") or ""
                date = attrs.get("date") or ""
                excerpt = (attrs.get("excerpt") or body.split("\n\n")[0] if body else "")[:200]
                out.append({"slug": slug, "title": title, "subtitle": subtitle, "date": date, "excerpt": excerpt, "type": post_type})
            except Exception as e:
                logger.warning(f"Skip content file {p}: {e}")
                continue
    out.sort(key=lambda x: x.get("date") or "", reverse=True)
    return out


def _get_blog_post(slug: str) -> Optional[dict]:
    """Get one post by slug from content/articles or content/updates. Return { slug, title, subtitle, date, body } or None."""
    for content_dir in (_CONTENT_ARTICLES_DIR, _CONTENT_UPDATES_DIR):
        if not content_dir.exists():
            continue
        for p in content_dir.glob("*.md"):
            try:
                raw = p.read_text(encoding="utf-8")
                attrs, body = _parse_blog_frontmatter(raw)
                post_slug = attrs.get("slug") or p.stem
                if post_slug != slug:
                    continue
                return {
                    "slug": post_slug,
                    "title": attrs.get("title") or post_slug,
                    "subtitle": attrs.get("subtitle") or "",
                    "date": attrs.get("date") or "",
                    "body": body,
                }
            except Exception as e:
                logger.warning(f"Skip content file {p}: {e}")
                continue
    return None


@app.get("/api/public/home-stats", tags=["Public"])
async def public_home_stats():
    """
    Single source for homepage: stores (by chain) and locations (by state/province).
    Use this so store cards and map always show consistent data from one response.
    """
    from .services.database.supabase_client import (
        get_store_chains_with_receipt_counts,
        get_location_stats,
    )
    stores = get_store_chains_with_receipt_counts(active_only=True)
    locations = get_location_stats()
    return {"stores": stores, "locations": locations}


@app.get("/api/public/store-stats", tags=["Public"])
async def public_store_stats():
    """
    Public endpoint: list store chains with receipt counts for homepage.
    Prefer /api/public/home-stats for homepage so store + map use same source.
    """
    from .services.database.supabase_client import get_store_chains_with_receipt_counts
    stores = get_store_chains_with_receipt_counts(active_only=True)
    return {"stores": stores}


@app.get("/api/public/location-stats", tags=["Public"])
async def public_location_stats():
    """
    Public endpoint: receipt counts per US state and Canadian province for the homepage map.
    Prefer /api/public/home-stats for homepage so store + map use same source.
    """
    from .services.database.supabase_client import get_location_stats
    locations = get_location_stats()
    return {"locations": locations}


@app.get("/api/blog", tags=["Blog"])
async def list_blog_posts(type: Optional[str] = None):
    """List blog posts (slug, title, date, excerpt, type) for the blog listing page.
    Optional query: type=article|update to filter."""
    posts = _list_blog_posts()
    if type and type.strip().lower() in ("article", "update"):
        posts = [p for p in posts if p.get("type") == type.strip().lower()]
    return posts


@app.get("/api/blog/{slug}", tags=["Blog"])
async def get_blog_post(slug: str):
    """Get a single blog post by slug. Returns title, date, body (markdown)."""
    post = _get_blog_post(slug)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


# ==================== Admin - Prompts ====================
# Level 7 admin: store-related only (create with chain binding; edit only non-system prompts).
# Level 9 super_admin: can create default-scope prompts and edit system first-round prompts.
PROTECTED_PROMPT_KEYS = frozenset({"vision_primary", "vision_escalation", "classification"})


class PromptLibraryItem(BaseModel):
    id: str
    key: str
    category: str
    content_role: str
    content: str
    version: int
    is_active: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    bindings: List[dict] = []
    binding_count: int = 0


class PromptBindingItem(BaseModel):
    id: str
    prompt_key: str
    library_id: str
    scope: str
    chain_id: Optional[str] = None
    location_id: Optional[str] = None
    priority: int
    is_active: bool
    chain_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@app.get("/api/admin/prompts", tags=["Admin - Prompts"])
async def admin_list_prompts(
    category: Optional[str] = None,
    user_id: str = Depends(require_admin),
):
    """
    List all prompt_library entries with binding count and chain names.
    Optional query: category=receipt|classification|system|analysis to filter.
    Returns current_user_class (7 or 9) so frontend can restrict edit/create by role.
    """
    from .services.database.supabase_client import _get_client, get_user_class
    supabase = _get_client()
    current_user_class = int(get_user_class(user_id) or 0)
    q = supabase.table("prompt_library").select("*").order("key")
    if category and category.strip():
        q = q.eq("category", category.strip())
    lib_res = q.execute()
    library_rows = list(lib_res.data or [])
    if not library_rows:
        return {"data": []}
    lib_ids = [r["id"] for r in library_rows]
    bind_res = (
        supabase.table("prompt_binding")
        .select("id, prompt_key, library_id, scope, chain_id, location_id, priority, is_active, created_at, updated_at")
        .in_("library_id", lib_ids)
        .execute()
    )
    bindings = list(bind_res.data or [])
    chain_ids = list({b["chain_id"] for b in bindings if b.get("chain_id")})
    chain_names = {}
    if chain_ids:
        chain_res = supabase.table("store_chains").select("id, name").in_("id", chain_ids).execute()
        for c in chain_res.data or []:
            chain_names[c["id"]] = c.get("name")
    for b in bindings:
        b["chain_name"] = chain_names.get(b["chain_id"]) if b.get("chain_id") else None
    bindings_by_lib: dict = {}
    for b in bindings:
        lid = b["library_id"]
        if lid not in bindings_by_lib:
            bindings_by_lib[lid] = []
        bindings_by_lib[lid].append(b)
    out = []
    for r in library_rows:
        bid = r["id"]
        blist = bindings_by_lib.get(bid, [])
        out.append({
            "id": bid,
            "key": r.get("key", ""),
            "category": r.get("category", ""),
            "content_role": r.get("content_role", ""),
            "content": r.get("content", ""),
            "version": r.get("version") or 1,
            "is_active": r.get("is_active", True),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "bindings": blist,
            "binding_count": len(blist),
        })
    return {"data": out, "current_user_class": current_user_class}


@app.post("/api/admin/prompts", tags=["Admin - Prompts"])
async def admin_create_prompt(
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(require_admin),
):
    """
    Create a new prompt_library entry. Body: key, category, content_role, content,
    is_active (optional, default true), and optionally bind_to_chain_id, bind_scope, bind_priority
    to create an initial binding.
    Level 7: must bind to a chain (store-specific). Level 9: may create default-scope prompts.
    """
    from .services.database.supabase_client import _get_client, get_user_class, USER_CLASS_SUPER_ADMIN
    supabase = _get_client()
    current_user_class = int(get_user_class(user_id) or 0)
    bind_to_chain_id = body.get("bind_to_chain_id")
    bind_scope = (body.get("bind_scope") or "default").strip()
    if current_user_class < USER_CLASS_SUPER_ADMIN:
        if not bind_to_chain_id or bind_scope != "chain":
            raise HTTPException(
                status_code=403,
                detail="Only Super Admin can create default-scope prompts. Admin must bind to a chain (store-specific).",
            )
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    category = (body.get("category") or "receipt").strip()
    content_role = (body.get("content_role") or "system").strip()
    if content_role not in ("system", "user_template", "schema"):
        raise HTTPException(status_code=400, detail="content_role must be system, user_template, or schema")
    content = body.get("content") or ""
    is_active = body.get("is_active", True)
    existing = supabase.table("prompt_library").select("id").eq("key", key).execute()
    if existing.data and len(existing.data) > 0:
        raise HTTPException(status_code=400, detail=f"Prompt library key already exists: {key}")
    ins = supabase.table("prompt_library").insert({
        "key": key,
        "category": category,
        "content_role": content_role,
        "content": content,
        "is_active": is_active,
    }).execute()
    if not ins.data or len(ins.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create prompt_library row")
    row = ins.data[0]
    lib_id = row["id"]
    bind_to_chain_id = body.get("bind_to_chain_id")
    bind_scope = (body.get("bind_scope") or "default").strip()
    bind_priority = body.get("bind_priority", 50 if bind_scope == "chain" else 10)
    if bind_to_chain_id and bind_scope == "chain":
        supabase.table("prompt_binding").insert({
            "prompt_key": key,
            "library_id": lib_id,
            "scope": "chain",
            "chain_id": bind_to_chain_id,
            "priority": bind_priority,
            "is_active": True,
        }).execute()
    elif bind_scope == "default":
        supabase.table("prompt_binding").insert({
            "prompt_key": key,
            "library_id": lib_id,
            "scope": "default",
            "priority": bind_priority,
            "is_active": True,
        }).execute()
    return {"id": lib_id, "key": key, "message": "Created"}


@app.patch("/api/admin/prompts/{prompt_id}", tags=["Admin - Prompts"])
async def admin_update_prompt(
    prompt_id: str,
    body: dict = Body(default_factory=dict),
    user_id: str = Depends(require_admin),
):
    """Update a prompt_library entry. Body: content (optional), is_active (optional). Only Super Admin can edit protected keys (vision_primary, vision_escalation, classification)."""
    from .services.database.supabase_client import _get_client, get_user_class, USER_CLASS_SUPER_ADMIN
    supabase = _get_client()
    current_user_class = int(get_user_class(user_id) or 0)
    lib = supabase.table("prompt_library").select("id, key").eq("id", prompt_id).limit(1).execute()
    if not lib.data or len(lib.data) == 0:
        raise HTTPException(status_code=404, detail="Prompt not found")
    prompt_key = lib.data[0].get("key") or ""
    if prompt_key in PROTECTED_PROMPT_KEYS and current_user_class < USER_CLASS_SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only Super Admin can edit system first-round prompts (vision_primary, vision_escalation, classification).",
        )
    updates = {}
    if "content" in body:
        updates["content"] = body["content"]
    if "is_active" in body:
        updates["is_active"] = bool(body["is_active"])
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one of content, is_active")
    res = supabase.table("prompt_library").update(updates).eq("id", prompt_id).execute()
    if not res.data or len(res.data) == 0:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"id": prompt_id, "message": "Updated"}


class AddBindingBody(BaseModel):
    prompt_key: str
    scope: str  # default | chain | location
    chain_id: Optional[str] = None
    location_id: Optional[str] = None
    priority: int = 50


@app.post("/api/admin/prompts/{prompt_id}/bindings", tags=["Admin - Prompts"])
async def admin_add_prompt_binding(
    prompt_id: str,
    body: AddBindingBody,
    user_id: str = Depends(require_admin),
):
    """Add a binding for a prompt_library entry (e.g. bind to a chain). Level 7 can only add chain/location; Level 9 can add default."""
    from .services.database.supabase_client import _get_client, get_user_class, USER_CLASS_SUPER_ADMIN
    supabase = _get_client()
    current_user_class = int(get_user_class(user_id) or 0)
    lib = supabase.table("prompt_library").select("id, key").eq("id", prompt_id).limit(1).execute()
    if not lib.data or len(lib.data) == 0:
        raise HTTPException(status_code=404, detail="Prompt not found")
    key = lib.data[0]["key"]
    scope = (body.scope or "default").strip()
    if scope not in ("default", "chain", "location"):
        raise HTTPException(status_code=400, detail="scope must be default, chain, or location")
    if scope == "default" and current_user_class < USER_CLASS_SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Only Super Admin can add default-scope bindings. Admin may add chain or location bindings only.",
        )
    if scope == "default":
        ins = supabase.table("prompt_binding").insert({
            "prompt_key": key,
            "library_id": prompt_id,
            "scope": "default",
            "priority": body.priority,
            "is_active": True,
        }).execute()
    elif scope == "chain":
        if not body.chain_id:
            raise HTTPException(status_code=400, detail="chain_id required for scope=chain")
        ins = supabase.table("prompt_binding").insert({
            "prompt_key": key,
            "library_id": prompt_id,
            "scope": "chain",
            "chain_id": body.chain_id,
            "priority": body.priority,
            "is_active": True,
        }).execute()
    else:
        if not body.location_id:
            raise HTTPException(status_code=400, detail="location_id required for scope=location")
        ins = supabase.table("prompt_binding").insert({
            "prompt_key": key,
            "library_id": prompt_id,
            "scope": "location",
            "location_id": body.location_id,
            "priority": body.priority,
            "is_active": True,
        }).execute()
    if not ins.data or len(ins.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create binding")
    return {"id": ins.data[0]["id"], "message": "Binding added"}


@app.delete("/api/admin/prompts/bindings/{binding_id}", tags=["Admin - Prompts"])
async def admin_remove_prompt_binding(
    binding_id: str,
    user_id: str = Depends(require_admin),
):
    """Soft-deactivate a prompt_binding (set is_active=false)."""
    from .services.database.supabase_client import _get_client
    supabase = _get_client()
    res = supabase.table("prompt_binding").update({"is_active": False}).eq("id", binding_id).execute()
    if not res.data or len(res.data) == 0:
        raise HTTPException(status_code=404, detail="Binding not found")
    return {"id": binding_id, "message": "Binding deactivated"}


@app.post("/api/admin/prompts/cache/clear", tags=["Admin - Prompts"])
async def admin_clear_prompt_cache(
    user_id: str = Depends(require_admin),
):
    """Clear in-memory prompt cache so next request uses fresh DB content."""
    from .prompts.prompt_manager import clear_cache
    clear_cache()
    return {"message": "Cache cleared"}
