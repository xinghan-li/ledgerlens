"""
Firebase Authentication: verify ID tokens and map Firebase UID to our internal user id.

Credential loading priority:
  1. FIREBASE_SERVICE_ACCOUNT_JSON  — JSON string (for Cloud Run / Secret Manager)
  2. FIREBASE_SERVICE_ACCOUNT_PATH  — file path (for local dev)
  3. GOOGLE_APPLICATION_CREDENTIALS — file path fallback
"""
from typing import Optional, Tuple
import json
import logging
import os
import uuid

from ...config import settings

logger = logging.getLogger(__name__)

_firebase_app = None


def _get_firebase_app():
    global _firebase_app
    if _firebase_app is not None:
        return _firebase_app
    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        raise ValueError(
            "firebase-admin is not installed. pip install firebase-admin"
        )

    # Priority 1: JSON string from environment (Cloud Run / Secret Manager)
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_json:
        try:
            sa_dict = json.loads(sa_json)
            cred = credentials.Certificate(sa_dict)
            _firebase_app = firebase_admin.initialize_app(cred)
            logger.info("Firebase Admin SDK initialized from FIREBASE_SERVICE_ACCOUNT_JSON")
            return _firebase_app
        except Exception as e:
            raise ValueError(f"Failed to parse FIREBASE_SERVICE_ACCOUNT_JSON: {e}")

    # Priority 2: file path (local dev)
    cred_path = (
        getattr(settings, "firebase_service_account_path", None) or ""
    ).strip() or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if cred_path and os.path.isfile(cred_path):
        cred = credentials.Certificate(cred_path)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized from file: %s", cred_path)
        return _firebase_app

    raise ValueError(
        "Firebase credentials not found. "
        "Set FIREBASE_SERVICE_ACCOUNT_JSON (JSON string) "
        "or FIREBASE_SERVICE_ACCOUNT_PATH / GOOGLE_APPLICATION_CREDENTIALS (file path)."
    )


def verify_firebase_token(id_token: str) -> Optional[Tuple[str, str]]:
    """
    Verify Firebase ID token. Returns (firebase_uid, email) or None if invalid/not Firebase.
    """
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth
    except ImportError as ie:
        logger.error("[Firebase] ImportError in verify_firebase_token: %s", ie)
        return None
    try:
        _get_firebase_app()
        # 允许 60 秒时钟偏差，减少客户端与服务器时间不同步导致的误判
        decoded = firebase_auth.verify_id_token(id_token, clock_skew_seconds=60)
        # Python SDK may return dict or object (DecodedToken); support both
        _keys = list(decoded.keys()) if isinstance(decoded, dict) else [k for k in dir(decoded) if not k.startswith("_")]
        logger.info("[Firebase] verify_id_token OK, decoded type=%s keys=%s", type(decoded).__name__, _keys[:20])
        def _get(key: str):
            if hasattr(decoded, key):
                return getattr(decoded, key, None)
            if isinstance(decoded, dict):
                return decoded.get(key)
            return None
        uid = _get("uid") or _get("user_id") or _get("sub")
        email = (_get("email") or "").strip() if _get("email") else ""
        if not uid:
            logger.warning("[Firebase] Token decoded but no uid/user_id/sub: decoded_type=%s", type(decoded).__name__)
            return None
        return (str(uid).strip(), email or "")
    except Exception as e:
        logger.error("Firebase token verification failed: %s", e, exc_info=True)
        return None


def get_or_create_user_id(firebase_uid: str, email: str) -> Optional[str]:
    """
    Find user by firebase_uid, or create one. Returns our internal user id (UUID) or None on error.
    """
    from ..database.supabase_client import _get_client
    firebase_uid = (firebase_uid or "").strip()
    if not firebase_uid:
        return None
    supabase = _get_client()
    # Find by firebase_uid (log so you can compare with DB if match fails)
    logger.info("[Firebase] Looking up user by firebase_uid=%r (compare with DB value)", firebase_uid)
    res = supabase.table("users").select("id, firebase_uid").eq("firebase_uid", firebase_uid).limit(1).execute()
    if res.data and len(res.data) > 0:
        return str(res.data[0]["id"])
    # Fallback: DB might have leading/trailing spaces; match by trimmed value
    res = supabase.table("users").select("id, firebase_uid").not_.is_("firebase_uid", "null").execute()
    for row in (res.data or []):
        if (row.get("firebase_uid") or "").strip() == firebase_uid:
            return str(row["id"])
    # Optional: find by email and attach firebase_uid (migration: existing Supabase user first Firebase login)
    # Try exact match first, then case-insensitive so "xinghan.sde@gmail.com" matches "Xinghan.sde@gmail.com"
    if email:
        res = supabase.table("users").select("id").eq("email", email).limit(1).execute()
        if res.data and len(res.data) > 0:
            row = res.data[0]
            user_id = str(row["id"])
            supabase.table("users").update({"firebase_uid": firebase_uid}).eq("id", user_id).execute()
            return user_id
        # Case-insensitive fallback: match existing user so same email = same account
        email_lower = (email or "").strip().lower()
        if email_lower:
            res = supabase.table("users").select("id, email").not_.is_("email", "null").execute()
            for row in (res.data or []):
                if (row.get("email") or "").strip().lower() == email_lower:
                    user_id = str(row["id"])
                    supabase.table("users").update({"firebase_uid": firebase_uid}).eq("id", user_id).execute()
                    logger.info("Linked existing user by email (case-insensitive): id=%s email=%s", user_id, email)
                    return user_id
    # Create new user
    new_id = str(uuid.uuid4())
    supabase.table("users").insert({
        "id": new_id,
        "firebase_uid": firebase_uid,
        "email": email or None,
        "user_class": 0,
        "status": "active",
    }).execute()
    logger.info("Created new user from Firebase: id=%s firebase_uid=%s email=%s", new_id, firebase_uid, email)
    return new_id
