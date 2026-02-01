"""
JWT Authentication for Supabase Auth.

This module provides JWT token verification for Supabase authentication.
"""
from fastapi import Depends, HTTPException, Header, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import jwt  # PyJWT library
import logging
from ...config import settings

logger = logging.getLogger(__name__)

# HTTPBearer for Swagger UI integration
# Note: HTTPBearer automatically extracts "Bearer <token>" from Authorization header
# scheme_name="Bearer" matches the security scheme name in OpenAPI schema
security = HTTPBearer(auto_error=False, scheme_name="Bearer")

# Supabase JWT secret (get from Supabase Dashboard > Settings > API > JWT Secret)
# This is used to verify JWT tokens
_supabase_jwt_secret: Optional[str] = None


def get_supabase_jwt_secret() -> str:
    """
    Get Supabase JWT secret from environment or settings.
    
    The JWT secret is used to verify tokens. You can find it in:
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
        
        logger.info("Supabase JWT secret loaded")
    
    return _supabase_jwt_secret


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
    
    try:
        # Get JWT secret
        jwt_secret = get_supabase_jwt_secret()
        
        # Verify and decode token
        # Supabase uses HS256 algorithm
        # Note: We disable audience verification because manually generated tokens
        # might have different audience values than Supabase's default
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": False  # Disable audience verification for manually generated tokens
            }
        )
        
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
        
        # Verify user exists in our users table
        # (Optional: you can add this check if needed)
        # from ..database.supabase_client import get_user
        # user = get_user(user_id)
        # if not user:
        #     raise HTTPException(401, "User not found")
        
        logger.debug(f"Authenticated user: {user_id}")
        return user_id
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        logger.error(f"Token verification failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
