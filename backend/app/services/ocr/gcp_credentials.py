"""
GCP Credentials helper.

Loading priority:
  1. GOOGLE_APPLICATION_CREDENTIALS_JSON  — JSON string (Cloud Run / Secret Manager)
  2. GOOGLE_APPLICATION_CREDENTIALS       — file path (local dev)
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_credentials = None


def get_gcp_credentials():
    """
    Return google.oauth2.service_account.Credentials.
    Tries JSON string first, then file path.
    """
    global _credentials
    if _credentials is not None:
        return _credentials

    from google.oauth2 import service_account

    # Priority 1: JSON string (Cloud Run / Secret Manager)
    sa_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()
    if sa_json:
        try:
            sa_dict = json.loads(sa_json)
            _credentials = service_account.Credentials.from_service_account_info(sa_dict)
            logger.info("GCP credentials loaded from GOOGLE_APPLICATION_CREDENTIALS_JSON")
            return _credentials
        except Exception as e:
            raise ValueError(f"Failed to parse GOOGLE_APPLICATION_CREDENTIALS_JSON: {e}")

    # Priority 2: file path (local dev)
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if cred_path and os.path.isfile(cred_path):
        _credentials = service_account.Credentials.from_service_account_file(cred_path)
        logger.info("GCP credentials loaded from file: %s", cred_path)
        return _credentials

    raise ValueError(
        "GCP credentials not found. "
        "Set GOOGLE_APPLICATION_CREDENTIALS_JSON (JSON string) "
        "or GOOGLE_APPLICATION_CREDENTIALS (file path)."
    )
