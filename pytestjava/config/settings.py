import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    api_base_url: str = "http://localhost:8160"
    api_version: str = ""
    test_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 1
    default_device_id: str = "web-test-001"
    environment: str = "test"
    
    git_repo_path: str = "."
    git_remote_url: Optional[str] = None
    git_auth_type: str = "https"
    git_fetch_timeout: int = 60
    
    jcci_enable_optimization: bool = True
    jcci_cache_enabled: bool = True
    jcci_cache_dir: str = ".jcci_cache"
    jcci_cache_max_size_mb: int = 500
    jcci_cache_ttl_hours: int = 24
    jcci_max_workers: str = "auto"
    jcci_incremental_mode: str = "auto"
    jcci_incremental_threshold: int = 50
    jcci_skip_target: bool = True
    jcci_skip_build: bool = True
    jcci_skip_test_files: bool = True
    jcci_max_file_size_mb: int = 5
    jcci_lazy_loading: bool = False
    jcci_performance_warning_threshold: int = 10
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )
    
    def load_environment_specific(self, env_name: str = None):
        env_name = env_name or self.environment or os.getenv("ENVIRONMENT", "test")
        env_path = Path(__file__).parent.parent / f".env.{env_name}"
        if env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(env_path, override=True)


settings = Settings()

if os.getenv("ENVIRONMENT"):
    settings.load_environment_specific(os.getenv("ENVIRONMENT"))
