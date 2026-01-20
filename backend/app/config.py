"""
Configuration settings loaded from environment variables.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
    }


# Create a singleton settings instance
settings = Settings()
