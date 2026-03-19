import os
from typing import Optional
# 直接使用 pydantic v2.0+ 的语法，因为 requirements.txt 中指定了 pydantic==2.5.0
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API Configuration
    api_base_url: str = Field(default="http://localhost:8080", env="API_BASE_URL")
    api_version: str = Field(default="v1", env="API_VERSION")
    
    # Test Configuration
    test_timeout: int = Field(default=30, env="TEST_TIMEOUT")
    max_retries: int = Field(default=3, env="MAX_RETRIES")
    retry_delay: int = Field(default=1, env="RETRY_DELAY")
    
    # Authentication
    test_phone_number: str = Field(default="13800138000", env="TEST_PHONE_NUMBER")
    test_verification_code: str = Field(default="123456", env="TEST_VERIFICATION_CODE")
    default_device_id: str = Field(default="web-test-001", env="DEFAULT_DEVICE_ID")
    
    # WeChat Work Configuration
    wechat_work_webhook_url: str = Field(
        default="https://qyapi.weixin.qq.com/cgi-bin/webhook/send", 
        env="WECHAT_WORK_WEBHOOK_URL"
    )
    wechat_work_key: Optional[str] = Field(default=None, env="WECHAT_WORK_KEY")
    
    # Allure Configuration
    allure_results_dir: str = Field(default="./allure-results", env="ALLURE_RESULTS_DIR")
    allure_report_dir: str = Field(default="./allure-report", env="ALLURE_REPORT_DIR")
    
    # CI/CD Configuration
    ci_commit_sha: Optional[str] = Field(default=None, env="CI_COMMIT_SHA")
    ci_build_number: Optional[str] = Field(default=None, env="CI_BUILD_NUMBER")
    ci_job_url: Optional[str] = Field(default=None, env="CI_JOB_URL")
    
    # Git Configuration
    git_repo_path: str = Field(default=".", env="GIT_REPO_PATH")
    git_branch: str = Field(default="main", env="GIT_BRANCH")
    
    # 配置类，用于设置环境变量文件等配置
    # 直接使用 pydantic v2.0+ 的 model_config，因为 requirements.txt 中指定了 pydantic==2.5.0
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# 全局设置实例，用于在整个应用程序中访问配置
settings = Settings()