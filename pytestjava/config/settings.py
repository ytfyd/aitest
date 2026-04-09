"""
应用配置管理模块

配置文件说明：
- .env: 仅存放敏感信息（账号、密码、Token等）
- config/settings.py: 存放非敏感默认配置（路径、开关、参数等）
- .env.{environment}: 环境特定敏感配置（可选，覆盖.env中的值）

多环境加载顺序（优先级从高到低）：
1. 命令行参数 (--environment, --git-repo-path 等)
2. 环境变量 (ENVIRONMENT, GIT_REPO_PATH 等)
3. .env.{environment} 文件 (环境特定敏感配置)
4. .env 文件 (基础敏感配置)
5. settings.py 中的默认值 (非敏感配置)

使用示例：
    from config.settings import settings
    
    print(settings.environment)        # 当前环境
    print(settings.api_base_url)       # API地址
    print(settings.git_repo_path)      # Git仓库路径
"""

import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    应用设置类
    
    设计原则：
    - 敏感信息（账号、密码、Token）从 .env 文件读取
    - 非敏感配置（路径、开关、参数）在此定义默认值
    - 支持通过环境变量覆盖任何配置项
    """
    
    # ==================== API基础配置 ====================
    api_base_url: str = "http://localhost:8160"
    api_version: str = ""
    
    # ==================== 测试执行配置 ====================
    test_timeout: int = 30              # API请求超时时间（秒）
    max_retries: int = 3                # 最大重试次数
    retry_delay: int = 1                # 重试间隔（秒）
    default_device_id: str = "web-test-001"
    
    # ==================== CI/CD集成配置 ====================
    ci_commit_sha: Optional[str] = None  # CI提交哈希
    ci_build_number: Optional[str] = None  # CI构建号
    ci_job_url: Optional[str] = None     # CI任务URL
    
    # ==================== 环境配置（问题3：默认改为test）====================
    environment: str = "test"            # 默认环境: development / test / production
    
    # ==================== Git仓库配置（非敏感）====================
    git_repo_path: str = "."             # Git仓库本地路径
    
    # Git远程仓库配置（非敏感）
    git_remote_url: Optional[str] = None  # 远程仓库URL（可在环境文件中覆盖）
    git_auth_type: str = "https"          # 认证方式: https / ssh / token
    
    # Git自动拉取配置（非敏感）
    git_auto_pull: bool = False           # 是否自动执行 git pull
    git_auto_pull_branch: Optional[str] = None  # 自动切换并pull的分支
    git_fetch_timeout: int = 60           # git fetch/pull 超时时间（秒）
    git_force_sync: bool = False          # 是否强制同步到远程（git reset --hard）
    
    # ==================== 性能优化配置（6大策略）====================
    
    # 主开关
    jcci_enable_optimization: bool = True   # 启用超级优化引擎
    
    # 策略1: 智能缓存配置
    jcci_cache_enabled: bool = True         # 启用缓存
    jcci_cache_dir: str = ".jcci_cache"     # 缓存目录
    jcci_cache_max_size_mb: int = 500       # 缓存最大大小(MB)
    jcci_cache_ttl_hours: int = 24          # 缓存有效期(小时)
    
    # 策略2: 并行扫描配置
    jcci_max_workers: str = "auto"          # 线程数: auto=自动检测(CPU核心×2)
    
    # 策略3: 增量模式配置
    jcci_incremental_mode: str = "auto"     # auto=自动判断(变更<50文件时启用)
    jcci_incremental_threshold: int = 50    # 增量模式阈值(文件数)
    
    # 策略4: 文件过滤配置
    jcci_skip_target: bool = True           # 跳过target目录
    jcci_skip_build: bool = True            # 跳过build目录
    jcci_skip_test_files: bool = True       # 跳过测试文件
    jcci_max_file_size_mb: int = 5          # 最大文件大小(MB)
    
    # 策略5: 懒加载配置
    jcci_lazy_loading: bool = False         # 懒加载模式（超大型项目才需要）
    
    # 性能监控
    jcci_performance_warning_threshold: int = 10  # 性能警告阈值(秒)
    
    model_config = SettingsConfigDict(
        env_file=".env",                    # 敏感配置文件
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"                       # 允许额外字段（兼容旧配置）
    )
    
    def load_environment_specific(self, env_name: str = None):
        """
        加载特定环境的敏感配置文件
        
        参数:
            env_name: 环境名称 (development/test/production)
                     如果不传，使用 self.environment 或 ENVIRONMENT 环境变量
        
        加载逻辑：
            1. 尝试加载 .env.{env_name} 文件
            2. 如果存在，覆盖 .env 中的同名配置
            3. 用于存放不同环境的敏感信息（如不同环境的账号密码）
        
        示例：
            .env.test 中可以定义测试环境的专用账号：
                USERNAME=test_user
                PASSWORD=test_password_123
        """
        env_name = env_name or self.environment or os.getenv("ENVIRONMENT", "test")
        
        env_files = [
            f".env.{env_name}",           # 特定环境敏感配置
            ".env"                         # 基础敏感配置（已加载）
        ]
        
        for env_file in env_files:
            env_path = Path(__file__).parent.parent / env_file
            if env_path.exists() and str(env_file) != ".env":
                from dotenv import load_dotenv
                load_dotenv(env_path, override=True)
                logger = __import__('logging').getLogger(__name__)
                logger.info(f"[Settings] 已加载环境配置: {env_file}")
                break
    
    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.environment.lower() == "development"
    
    @property
    def is_test(self) -> bool:
        """是否为测试环境"""
        return self.environment.lower() == "test"
    
    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.environment.lower() == "production"


# 创建全局单例实例
settings = Settings()

# 自动加载特定环境配置（如果设置了ENVIRONMENT环境变量）
if os.getenv("ENVIRONMENT"):
    settings.load_environment_specific(os.getenv("ENVIRONMENT"))
