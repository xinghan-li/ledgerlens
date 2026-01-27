"""
Configuration settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from dotenv import load_dotenv
from pathlib import Path

# Determine .env file path (backend/.env)
_env_path = Path(__file__).parent.parent / ".env"

# Load environment variables from .env file
# Use override=True to ensure environment variables take precedence over defaults
load_dotenv(dotenv_path=_env_path, override=True)

# Debug: Print loaded environment variables (for debugging only)
import os
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
    
    # Application settings
    env: str = Field(
        default="local",
        alias="ENV",
        description="Environment (local, staging, production)"
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
    
    # OpenAI settings
    openai_api_key: Optional[str] = Field(
        default=None,
        alias="OPENAI_API_KEY",
        description="OpenAI API key for LLM processing"
    )
    openai_model: str = Field(
        default="gpt-4o-mini",
        alias="OPENAI_MODEL",
        description="OpenAI model to use (e.g., gpt-4o-mini, gpt-4o, gpt-4-turbo)"
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
        default="gemini-1.5-flash",
        alias="GEMINI_MODEL",
        description=(
            "Google Gemini model to use. "
            "Free tier: gemini-1.5-flash (recommended), gemini-1.5-pro. "
            "Paid tier: gemini-2.0-flash-exp (experimental, requires paid plan)"
        )
    )
    
    model_config = {
        "env_file": str(_env_path),  # Use explicit .env file path
        "case_sensitive": False,
        "env_file_encoding": "utf-8",
    }


# Create a singleton settings instance
settings = Settings()

# Debug: Print final loaded configuration (for debugging only)
print(f"[DEBUG] Final Gemini model from settings: {settings.gemini_model}")
print(f"[DEBUG] Gemini API key set: {bool(settings.gemini_api_key)}")
