import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API Configuration
    api_base_url: str = "http://localhost:8160"
    api_version: str = ""
    
    # Test Configuration
    test_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 1
    default_device_id: str = "web-test-001"
    
    # CI/CD Configuration
    ci_commit_sha: Optional[str] = None
    ci_build_number: Optional[str] = None
    ci_job_url: Optional[str] = None
    
    
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )


settings = Settings()
