"""
Configuration settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import Optional, Any
from dotenv import load_dotenv
from pathlib import Path
import os

_backend_dir = Path(__file__).parent.parent
# When LEDGERLENS_ENV=production (e.g. sync script with --production), load .env.production
_env_name = os.getenv("LEDGERLENS_ENV", "")
_env_path = _backend_dir / ".env.production" if _env_name == "production" else _backend_dir / ".env"

# Load environment variables from .env file
# Use override=True to ensure environment variables take precedence over defaults
load_dotenv(dotenv_path=_env_path, override=True)

# Debug: Print loaded environment variables (for debugging only)
_gemini_model_env = os.getenv("GEMINI_MODEL")
if _gemini_model_env:
    print(f"[DEBUG] GEMINI_MODEL from environment: {_gemini_model_env}")


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Google Cloud Platform settings
    gcp_credentials_path: str = Field(
        default="",
        alias="GOOGLE_APPLICATION_CREDENTIALS",
        description="Absolute path to Google Cloud service account JSON key file"
    )
    gcp_project_id: str = Field(
        default="",
        alias="GCP_PROJECT_ID",
        description="Google Cloud Platform project ID"
    )
    
    # Google Document AI settings
    documentai_processor_name: str = Field(
        default="",
        alias="DOCUMENTAI_PROCESSOR_NAME",
        description="Document AI processor name (e.g., projects/PROJECT_ID/locations/LOCATION/processors/PROCESSOR_ID)"
    )
    documentai_endpoint: Optional[str] = Field(
        default=None,
        alias="DOCUMENTAI_ENDPOINT",
        description="Document AI prediction endpoint URL (optional, will be constructed if not provided)"
    )
    
    # Supabase settings
    supabase_url: str = Field(
        default="",
        alias="SUPABASE_URL",
        description="Supabase project URL"
    )
    supabase_anon_key: str = Field(
        default="",
        alias="SUPABASE_ANON_KEY",
        description="Supabase anonymous key"
    )
    supabase_service_role_key: Optional[str] = Field(
        default=None,
        alias="SUPABASE_SERVICE_ROLE_KEY",
        description="Supabase service role key (optional, for server-side writes)"
    )
    supabase_jwt_secret: Optional[str] = Field(
        default=None,
        alias="SUPABASE_JWT_SECRET",
        description=(
            "Supabase JWT secret for token verification. "
            "Get it from Supabase Dashboard > Settings > API > JWT Keys > Legacy JWT Secret"
        )
    )

    # Firebase (optional; when set, backend accepts Firebase ID tokens and find-or-creates users by firebase_uid)
    firebase_service_account_path: Optional[str] = Field(
        default=None,
        alias="FIREBASE_SERVICE_ACCOUNT_PATH",
        description="Path to Firebase service account JSON (local dev). In production use FIREBASE_SERVICE_ACCOUNT_JSON instead."
    )
    firebase_service_account_json: Optional[str] = Field(
        default=None,
        alias="FIREBASE_SERVICE_ACCOUNT_JSON",
        description="Firebase service account JSON as a string (for Cloud Run / Secret Manager). Takes priority over FIREBASE_SERVICE_ACCOUNT_PATH."
    )

    # Application settings
    env: str = Field(
        default="local",
        alias="ENV",
        description="Environment (local, staging, production)"
    )
    # CORS: 逗号分隔的额外允许的 origin，用于手机/ngrok 测前端（例如 https://xxx.ngrok-free.app,http://192.168.1.100:3000）
    cors_origins_extra: Optional[str] = Field(
        default=None,
        alias="CORS_ORIGINS",
        description="Comma-separated extra origins for CORS (e.g. ngrok frontend URL for mobile testing)"
    )
    log_level: str = Field(
        default="info",
        alias="LOG_LEVEL",
        description="Logging level"
    )
    test_user_id: Optional[str] = Field(
        default=None,
        alias="TEST_USER_ID",
        description="Test user ID for development (must exist in auth.users table)"
    )
    
    # OpenAI settings (DEPRECATED — pipeline is Gemini-only as of 2025-03-21)
    # Kept for backward compatibility with .env files; not used in any active code path.
    openai_api_key: Optional[str] = Field(
        default=None,
        alias="OPENAI_API_KEY",
        description="[DEPRECATED] OpenAI API key — no longer used"
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        alias="OPENAI_MODEL",
        description="[DEPRECATED] OpenAI model — no longer used"
    )
    openai_escalation_model: Optional[str] = Field(
        default=None,
        alias="OPENAI_ESCALATION_MODEL",
        description="[DEPRECATED] OpenAI escalation model — no longer used"
    )
    
    # AWS settings
    aws_region: str = Field(
        default="us-west-2",
        alias="AWS_REGION",
        description="AWS region for Textract service (e.g., us-west-2, us-east-1)"
    )
    
    # Google Gemini settings
    gemini_api_key: Optional[str] = Field(
        default=None,
        alias="GEMINI_API_KEY",
        description="Google Gemini API key for LLM processing"
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        alias="GEMINI_MODEL",
        description="Google Gemini model to use"
    )
    gemini_escalation_model: Optional[str] = Field(
        default=None,
        alias="GEMINI_ESCALATION_MODEL",
        description="When set (e.g. gemini-3.1-pro), cascade failures escalate to this model with image input for consensus with OpenAI escalation"
    )
    confidence_threshold: float = Field(
        default=0.80,
        alias="CONFIDENCE_THRESHOLD",
        description="LLM confidence threshold (0-1). Sum check PASS + confidence below this triggers escalation."
    )
    
    # Vision-First pipeline (Route B) settings
    vision_pipeline_enabled: bool = Field(
        default=True,
        alias="VISION_PIPELINE_ENABLED",
        description=(
            "Enable Vision-First pipeline (Route B). "
            "When True, /api/receipt/workflow-vision is active and the frontend uses "
            "the vision-first flow. Set to 'false' to disable and fall back to legacy."
        )
    )

    # Debug settings
    allow_duplicate_for_debug: bool = Field(
        default=False,
        alias="ALLOW_DUPLICATE_FOR_DEBUG",
        description=(
            "Allow duplicate file uploads for debugging. "
            "When enabled, duplicate files will be processed with a modified file_hash "
            "to allow comparison of results. Set to 'true', '1', 'yes', or 'on' to enable."
        )
    )
    enable_debug_logs: bool = Field(
        default=True,
        alias="ENABLE_DEBUG_LOGS",
        description=(
            "Enable detailed debug logging for coordinate sum check and pipeline processing. "
            "Set to 'false', '0', 'no', or 'off' to disable in production. "
            "When disabled, detailed debug logs (like formatted output, usage tracker) will not be printed."
        )
    )
    
    @field_validator('allow_duplicate_for_debug', 'enable_debug_logs', 'vision_pipeline_enabled', mode='before')
    @classmethod
    def parse_bool_from_string(cls, v: Any) -> bool:
        """Parse boolean from string environment variable."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes', 'on', 'y', 't')
        return bool(v)
    
    model_config = {
        "env_file": str(_env_path),  # Use explicit .env file path
        "case_sensitive": False,
        "env_file_encoding": "utf-8",
        "extra": "ignore",  # Ignore env vars not declared as fields (e.g. GOOGLE_APPLICATION_CREDENTIALS_JSON)
    }


# Create a singleton settings instance
settings = Settings()

# Debug: Print final loaded configuration (for debugging only)
print(f"[DEBUG] Final Gemini model from settings: {settings.gemini_model}")
print(f"[DEBUG] Gemini API key set: {bool(settings.gemini_api_key)}")
print(f"[DEBUG] ALLOW_DUPLICATE_FOR_DEBUG from env: {os.getenv('ALLOW_DUPLICATE_FOR_DEBUG', 'not set')}")
print(f"[DEBUG] allow_duplicate_for_debug from settings: {settings.allow_duplicate_for_debug}")