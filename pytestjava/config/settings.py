import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API Configuration
    api_base_url: str = "http://localhost:8080"
    api_version: str = "v1"
    
    # Test Configuration
    test_timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 1
    
    # Authentication
    test_phone_number: str = "13800138000"
    test_verification_code: str = "123456"
    default_device_id: str = "web-test-001"
    
    # WeChat Work Configuration
    wechat_work_webhook_url: str = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    wechat_work_key: Optional[str] = None
    
    # Allure Configuration
    allure_results_dir: str = "./allure-results"
    allure_report_dir: str = "./allure-report"
    
    # CI/CD Configuration
    ci_commit_sha: Optional[str] = None
    ci_build_number: Optional[str] = None
    ci_job_url: Optional[str] = None
    
    # Git Configuration
    git_repo_path: str = "."
    git_branch: str = "main"
    
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=False
    )


settings = Settings()
