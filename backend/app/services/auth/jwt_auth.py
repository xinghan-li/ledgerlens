"""
JWT Authentication for Supabase Auth.

This module provides JWT token verification for Supabase authentication.
Supports both RS256 (Supabase Auth tokens) and HS256 (custom tokens).
"""
from fastapi import Depends, HTTPException, Header, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import jwt  # PyJWT library
from jwt import PyJWKClient
import logging
from ...config import settings

logger = logging.getLogger(__name__)

# HTTPBearer for Swagger UI integration
# Note: HTTPBearer automatically extracts "Bearer <token>" from Authorization header
# scheme_name="Bearer" matches the security scheme name in OpenAPI schema
security = HTTPBearer(auto_error=False, scheme_name="Bearer")

# Supabase JWT secret (get from Supabase Dashboard > Settings > API > JWT Secret)
# This is used to verify HS256 tokens (manually generated)
_supabase_jwt_secret: Optional[str] = None

# JWKS client for RS256 token verification (Supabase Auth tokens)
_jwks_client: Optional[PyJWKClient] = None


def get_supabase_jwt_secret() -> str:
    """
    Get Supabase JWT secret from environment or settings.
    
    The JWT secret is used to verify HS256 tokens. You can find it in:
    Supabase Dashboard > Settings > API > JWT Secret
    """
    global _supabase_jwt_secret
    
    if _supabase_jwt_secret is None:
        # Try to get from settings first
        if settings.supabase_jwt_secret:
            _supabase_jwt_secret = settings.supabase_jwt_secret
        else:
            # Try to get from environment variable
            import os
            secret = os.getenv("SUPABASE_JWT_SECRET")
            
            if not secret:
                raise ValueError(
                    "SUPABASE_JWT_SECRET environment variable is required. "
                    "Get it from Supabase Dashboard > Settings > API > JWT Secret"
                )
            
            _supabase_jwt_secret = secret
        
        logger.info("Supabase JWT secret loaded for HS256")
    
    return _supabase_jwt_secret


def get_jwks_client() -> PyJWKClient:
    """
    Get JWKS client for RS256 token verification.
    
    Supabase Auth tokens use RS256 algorithm and can be verified using
    the public keys from the JWKS endpoint.
    """
    global _jwks_client
    
    if _jwks_client is None:
        # Construct JWKS URL from Supabase URL
        supabase_url = settings.supabase_url
        if not supabase_url:
            raise ValueError("SUPABASE_URL is not configured")
        
        # Remove trailing slash if present
        supabase_url = supabase_url.rstrip('/')
        
        # JWKS endpoint - Supabase uses /auth/v1/ prefix
        jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json"
        
        _jwks_client = PyJWKClient(jwks_url)
        logger.info(f"JWKS client initialized for RS256: {jwks_url}")
    
    return _jwks_client


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> str:
    """
    Verify Supabase JWT token and return user_id.
    
    This is a FastAPI dependency that can be used with Depends().
    Uses HTTPBearer for Swagger UI integration.
    
    Usage:
        @app.post("/api/receipt/workflow")
        async def workflow(
            file: UploadFile,
            user_id: str = Depends(get_current_user)
        ):
            ...
    
    Args:
        credentials: HTTPAuthorizationCredentials from HTTPBearer (contains the token)
        authorization: Raw Authorization header for debugging
        
    Returns:
        user_id (str): UUID of the authenticated user
        
    Raises:
        HTTPException: 401 if token is missing or invalid
    """
    # Debug: Print all relevant information
    logger.warning(f"[DEBUG] ========== Authorization Debug ==========")
    logger.warning(f"[DEBUG] credentials object: {credentials}")
    logger.warning(f"[DEBUG] credentials type: {type(credentials)}")
    logger.warning(f"[DEBUG] authorization header (raw): {authorization}")
    logger.warning(f"[DEBUG] authorization header type: {type(authorization)}")
    
    if credentials:
        logger.warning(f"[DEBUG] credentials.credentials: {credentials.credentials}")
        logger.warning(f"[DEBUG] credentials.credentials length: {len(credentials.credentials) if credentials.credentials else 0}")
    else:
        logger.warning(f"[DEBUG] credentials is None or empty")
    
    if not credentials:
        logger.warning("[DEBUG] No credentials provided from HTTPBearer")
        logger.warning(f"[DEBUG] But raw Authorization header is: {authorization}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authorization header is required. HTTPBearer got: {credentials}, Raw header: {authorization}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    if not token:
        logger.warning("[DEBUG] Token is empty")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.debug(f"[DEBUG] Token received (length: {len(token)})")
    
    # First, decode token header to check algorithm (without verification)
    try:
        header = jwt.get_unverified_header(token)
        token_alg = header.get('alg', 'unknown')
        logger.info(f"[DEBUG] Token algorithm from header: {token_alg}")
    except Exception as e:
        logger.warning(f"[DEBUG] Failed to decode token header: {e}")
        token_alg = 'unknown'
    
    # Try to verify with both RS256 (Supabase Auth) and HS256 (custom tokens)
    payload = None
    verification_errors = []
    
    # Choose verification order based on token algorithm
    if token_alg == 'HS256':
        # Try HS256 first
        try:
            logger.debug("[DEBUG] Trying HS256 verification with JWT Secret...")
            jwt_secret = get_supabase_jwt_secret()
            
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": False
                }
            )
            logger.info("[DEBUG] Token verified successfully with HS256")
            
        except Exception as e:
            verification_errors.append(f"HS256: {str(e)}")
            logger.warning(f"[DEBUG] HS256 verification failed: {e}")
    else:
        # Try JWKS-based verification (supports RS256, ES256, etc.)
        try:
            logger.debug(f"[DEBUG] Trying {token_alg} verification with JWKS...")
            jwks_client = get_jwks_client()
            
            # Get signing key from JWKS
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            
            # Verify and decode token - let PyJWT auto-detect algorithm
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256", "ES384", "ES512"],  # Support multiple algorithms
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": False  # Disable audience verification
                }
            )
            logger.info(f"[DEBUG] Token verified successfully with {token_alg}")
            
        except Exception as e:
            verification_errors.append(f"{token_alg}: {str(e)}")
            logger.warning(f"[DEBUG] {token_alg} verification failed: {e}")
            
            # Fallback to HS256
            try:
                logger.debug("[DEBUG] Trying HS256 verification with JWT Secret (fallback)...")
                jwt_secret = get_supabase_jwt_secret()
                
                payload = jwt.decode(
                    token,
                    jwt_secret,
                    algorithms=["HS256"],
                    options={
                        "verify_signature": True,
                        "verify_exp": True,
                        "verify_iat": True,
                        "verify_aud": False
                    }
                )
                logger.info("[DEBUG] Token verified successfully with HS256 (fallback)")
                
            except Exception as e2:
                verification_errors.append(f"HS256: {str(e2)}")
                logger.warning(f"[DEBUG] HS256 verification failed: {e2}")
    
    # If both methods failed, raise error
    if payload is None:
        error_msg = "Token verification failed. Tried: " + "; ".join(verification_errors)
        logger.warning(f"[DEBUG] {error_msg}")
        
        # Check for specific error types
        if any("expired" in err.lower() for err in verification_errors):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error_msg,
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    # Extract user_id from payload
    # Supabase JWT payload structure:
    # {
    #   "sub": "user-uuid",  # This is the user_id
    #   "email": "user@example.com",
    #   "aud": "authenticated",
    #   "role": "authenticated",
    #   "exp": 1234567890,
    #   "iat": 1234567890
    # }
    user_id = payload.get("sub")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user_id (sub)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    logger.debug(f"Authenticated user: {user_id}")
    return user_id


async def get_current_user_optional(
    authorization: Optional[str] = Header(None, alias="Authorization")
) -> Optional[str]:
    """
    Optional authentication - returns user_id if token is valid, None otherwise.
    
    Use this for endpoints that work with or without authentication.
    
    Usage:
        @app.get("/api/public-data")
        async def public_data(
            user_id: Optional[str] = Depends(get_current_user_optional)
        ):
            if user_id:
                # Return personalized data
            else:
                # Return public data
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None
