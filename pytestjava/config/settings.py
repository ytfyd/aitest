"""项目配置管理模块

使用pydantic-settings管理所有配置项，支持环境变量和.env文件。
配置分类：
- API配置：基础URL、超时、重试策略
- Git配置：仓库路径、认证方式
- JCCI配置：缓存、并行扫描、增量模式等性能优化选项
"""
import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """项目配置类，所有配置项均可通过环境变量覆盖"""
    api_base_url: str = "http://localhost:8160"  # API基础URL
    api_version: str = ""  # API版本号
    test_timeout: int = 30  # 测试超时时间（秒）
    max_retries: int = 3  # 最大重试次数
    retry_delay: int = 1  # 重试间隔（秒）
    default_device_id: str = "web-test-001"  # 默认设备ID
    environment: str = "test"  # 运行环境（test/staging/production）
    
    git_repo_path: str = "."  # Git仓库本地路径
    git_remote_url: Optional[str] = None  # Git远程仓库URL
    git_auth_type: str = "https"  # Git认证方式（https/ssh）
    git_fetch_timeout: int = 60  # Git fetch超时时间（秒）
    
    jcci_enable_optimization: bool = True  # 是否启用JCCI性能优化
    jcci_cache_enabled: bool = True  # 是否启用JCCI缓存
    jcci_cache_dir: str = ".jcci_cache"  # 缓存目录
    jcci_cache_max_size_mb: int = 500  # 缓存最大大小（MB）
    jcci_cache_ttl_hours: int = 24  # 缓存过期时间（小时）
    jcci_max_workers: str = "auto"  # 最大并行工作线程数（auto/数字）
    jcci_incremental_mode: str = "auto"  # 增量模式（auto/true/false）
    jcci_incremental_threshold: int = 50  # 增量模式触发阈值
    jcci_skip_target: bool = True  # 是否跳过target目录
    jcci_skip_build: bool = True  # 是否跳过build目录
    jcci_skip_test_files: bool = True  # 是否跳过测试文件
    jcci_max_file_size_mb: int = 5  # 最大文件大小限制（MB）
    jcci_lazy_loading: bool = False  # 是否启用懒加载
    jcci_performance_warning_threshold: int = 10  # 性能警告阈值（秒）
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )
    
    def load_environment_specific(self, env_name: str = None):
        """加载环境特定的配置文件（如.env.test/.env.production）"""
        env_name = env_name or self.environment or os.getenv("ENVIRONMENT", "test")
        env_path = Path(__file__).parent.parent / f".env.{env_name}"
        if env_path.exists():
            from dotenv import load_dotenv
            load_dotenv(env_path, override=True)


settings = Settings()

if os.getenv("ENVIRONMENT"):
    settings.load_environment_specific(os.getenv("ENVIRONMENT"))
