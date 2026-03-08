"""
JWT Authentication: Firebase Auth (primary) and Supabase Auth (fallback).

When Firebase is configured, Firebase ID tokens are verified first and the user
is resolved via firebase_uid (find or create in public.users). Otherwise Supabase
JWT (RS256/HS256) is verified and sub is used as user_id.
"""
from fastapi import Depends, HTTPException, Header, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, Optional, Tuple
import asyncio
import hashlib
import jwt  # PyJWT library
from jwt import PyJWKClient
import logging
import time
from threading import Lock
from ...config import settings

try:
    from .firebase_auth import verify_firebase_token, get_or_create_user_id
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning("Firebase auth not available: %s", _e)
    verify_firebase_token = None
    get_or_create_user_id = None

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

# Short-TTL token → user_id cache: avoids repeated Firebase verify + Supabase get_or_create per request
_token_cache: Dict[str, Tuple[str, float]] = {}  # sha256(token) → (user_id, expire_at)
_token_cache_lock = Lock()
_TOKEN_CACHE_TTL = 300  # 5 minutes


def _get_cached_user_id(token: str) -> Optional[str]:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    with _token_cache_lock:
        entry = _token_cache.get(token_hash)
        if entry and entry[1] > now:
            return entry[0]
        if token_hash in _token_cache:
            del _token_cache[token_hash]
    return None


def _cache_user_id(token: str, user_id: str) -> None:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expire_at = time.time() + _TOKEN_CACHE_TTL
    with _token_cache_lock:
        _token_cache[token_hash] = (user_id, expire_at)
        # Periodically evict expired entries to prevent unbounded growth
        if len(_token_cache) > 5000:
            now = time.time()
            expired = [k for k, v in _token_cache.items() if v[1] <= now]
            for k in expired:
                del _token_cache[k]


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
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Fast path: token already resolved recently
    cached_user_id = _get_cached_user_id(token)
    if cached_user_id:
        logger.debug("Auth cache hit, user_id=%s", cached_user_id)
        return cached_user_id

    # Decode token header first to detect Firebase vs Supabase tokens
    try:
        header = jwt.get_unverified_header(token)
        token_alg = header.get('alg', 'unknown')
        token_kid = header.get('kid', '')
        logger.debug("Token alg=%s kid=%s", token_alg, token_kid)
    except Exception as e:
        logger.warning("Failed to decode token header: %s", e)
        token_alg = 'unknown'
        token_kid = ''

    # Try Firebase first if available (Firebase ID tokens use RS256 with Google kid)
    if verify_firebase_token is not None and get_or_create_user_id is not None:
        logger.debug("[Auth] Trying Firebase verification")
        fb = await asyncio.to_thread(verify_firebase_token, token)
        if fb is not None:
            firebase_uid, email = fb
            try:
                user_id = await asyncio.to_thread(get_or_create_user_id, firebase_uid, email)
                if user_id:
                    logger.info("Authenticated via Firebase: user_id=%s", user_id)
                    _cache_user_id(token, user_id)
                    return user_id
            except Exception as e:
                logger.warning("Firebase get_or_create_user_id failed: %s", e)
        else:
            # Firebase verification failed but token looks like Firebase (RS256 + typical Google kid length); return explicit error instead of trying Supabase JWKS
            if token_alg == "RS256" and len(token_kid) == 40:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Firebase token verification failed or expired. Please refresh the page or sign in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            logger.info("[Auth] Firebase verify returned None, falling back to Supabase JWT")
    else:
        logger.debug("[Auth] Firebase auth not loaded, using Supabase JWT only")
    
    # Try to verify with both RS256 (Supabase Auth) and HS256 (custom tokens)
    payload = None
    verification_errors = []
    
    # Choose verification order based on token algorithm
    if token_alg == 'HS256':
        # Try HS256 first
        try:
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
            logger.debug("Token verified with HS256")
        except Exception as e:
            verification_errors.append(f"HS256: {str(e)}")
            logger.debug("HS256 verification failed: %s", e)
    else:
        # Try JWKS-based verification (supports RS256, ES256, etc.)
        try:
            jwks_client = get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256", "ES384", "ES512"],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_aud": False
                }
            )
            logger.debug("Token verified with %s", token_alg)
        except Exception as e:
            verification_errors.append(f"{token_alg}: {str(e)}")
            logger.debug("%s verification failed: %s", token_alg, e)

            # Fallback to HS256
            try:
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
                logger.debug("Token verified with HS256 (fallback)")
            except Exception as e2:
                verification_errors.append(f"HS256: {str(e2)}")
                logger.debug("HS256 fallback verification failed: %s", e2)

    # If both methods failed, raise error
    if payload is None:
        error_msg = "Token verification failed. Tried: " + "; ".join(verification_errors)
        logger.warning("Token verification failed for all methods: %s", error_msg)
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

    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user_id (sub)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    logger.debug("Authenticated via Supabase JWT: user_id=%s", user_id)
    _cache_user_id(token, user_id)
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
