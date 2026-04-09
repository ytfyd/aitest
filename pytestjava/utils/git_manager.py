"""
Git仓库管理器模块
统一管理Git远程地址、认证、自动拉取和多环境切换

功能：
- 支持HTTPS/SSH/Token三种认证方式
- 自动配置Git凭据（临时或持久化）
- 支持自动fetch/pull/reset操作
- 多环境配置切换（development/test/production）
- 完整的错误处理和日志记录

使用示例：
    from utils.git_manager import GitManager
    
    # 方式1：使用.env配置自动初始化
    git_mgr = GitManager(repo_path="/path/to/repo")
    
    # 方式2：手动指定参数
    git_mgr = GitManager(
        repo_path="/path/to/repo",
        remote_url="https://github.com/org/project.git",
        auth_type="https",
        username="user",
        password="token"
    )
    
    # 执行操作
    git_mgr.fetch_all()           # 更新所有远程引用
    git_mgr.pull(branch="main")   # 拉取指定分支
    git_mgr.sync_to_remote()      # 强制同步到远程状态
"""

import os
import re
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

try:
    from git import Repo, InvalidGitRepositoryError, GitCommandError
    GITPYTHON_AVAILABLE = True
except ImportError:
    GITPYTHON_AVAILABLE = False
    logging.warning("GitPython未安装，将使用subprocess作为备选方案")

logger = logging.getLogger(__name__)


class AuthType(Enum):
    """Git认证方式枚举"""
    HTTPS = "https"
    SSH = "ssh"
    TOKEN = "token"


class EnvironmentMode(Enum):
    """环境模式枚举"""
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


@dataclass
class GitConfig:
    """Git配置数据类"""
    remote_url: str = ""
    auth_type: str = "https"
    username: str = ""
    password: str = ""
    ssh_key_path: str = ""
    ssh_passphrase: str = ""
    auto_pull: bool = False
    auto_pull_branch: str = ""
    fetch_timeout: int = 60
    force_sync: bool = False


@dataclass
class GitOperationResult:
    """Git操作结果数据类"""
    success: bool
    operation: str
    message: str
    output: str = ""
    error: str = ""
    duration_seconds: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class GitManager:
    """
    Git仓库管理器 - 核心管理类
    
    功能特性：
    1. 统一配置管理（从.env读取或手动传入）
    2. 多种认证方式（HTTPS用户名密码/SSH密钥/Personal Token）
    3. 自动拉取和同步功能
    4. 多环境配置支持
    5. 安全的凭据处理（避免明文日志输出）
    """
    
    def __init__(self, 
                 repo_path: str,
                 config: GitConfig = None,
                 environment: str = None):
        """
        初始化Git管理器
        
        参数:
            repo_path: 本地Git仓库路径
            config: GitConfig对象（可选，不传则从环境变量读取）
            environment: 环境模式 development/test/production（可选）
        """
        self.repo_path = Path(repo_path).resolve()
        
        # 加载配置
        self.config = config or self._load_config_from_env()
        
        # 环境模式
        self.environment = EnvironmentMode(
            environment or os.getenv("ENVIRONMENT", "test")
        )
        
        # 初始化Git仓库对象
        self.repo = None
        self._init_repo()
        
        logger.info(f"[GitManager] 初始化完成")
        logger.info(f"  📂 仓库路径: {self.repo_path}")
        logger.info(f"  🔗 远程URL: {self._mask_url(self.config.remote_url)}")
        logger.info(f"  🔐 认证方式: {self.config.auth_type}")
        logger.info(f"  🌍 环境模式: {self.environment.value}")
    
    def _init_repo(self):
        """初始化GitPython Repo对象"""
        if not GITPYTHON_AVAILABLE:
            logger.warning("[GitManager] GitPython不可用，将使用subprocess")
            return
        
        try:
            self.repo = Repo(str(self.repo_path))
            logger.info(f"[GitManager] Git仓库已加载 (当前分支: {self.active_branch})")
        except InvalidGitRepositoryError:
            raise ValueError(
                f"'{self.repo_path}' 不是有效的Git仓库。"
                f"\n请先执行: cd {self.repo_path} && git init && git remote add origin <url>"
            )
        except Exception as e:
            logger.error(f"[GitManager] 初始化Git仓库失败: {e}")
            raise
    
    @property
    def active_branch(self) -> str:
        """获取当前活动分支名"""
        try:
            if self.repo and not self.repo.head.is_detached:
                return self.repo.active_branch.name
            return "HEAD detached"
        except Exception:
            return "unknown"
    
    @property
    def remotes(self) -> Dict[str, str]:
        """获取所有远程仓库及其URL"""
        result = {}
        try:
            if self.repo:
                for remote in self.repo.remotes:
                    result[remote.name] = next(remote.urls, "")
        except Exception as e:
            logger.warning(f"[GitManager] 获取远程仓库失败: {e}")
        return result
    
    def _load_config_from_env(self) -> GitConfig:
        """从环境变量加载Git配置"""
        config = GitConfig(
            remote_url=os.getenv("GIT_REMOTE_URL", ""),
            auth_type=os.getenv("GIT_AUTH_TYPE", "https"),
            username=os.getenv("GIT_USERNAME", ""),
            password=os.getenv("GIT_PASSWORD", ""),
            ssh_key_path=os.getenv("GIT_SSH_KEY_PATH", "~/.ssh/id_ed25519"),
            ssh_passphrase=os.getenv("GIT_SSH_PASSPHRASE", ""),
            auto_pull=os.getenv("GIT_AUTO_PULL", "false").lower() == "true",
            auto_pull_branch=os.getenv("GIT_AUTO_PULL_BRANCH", ""),
            fetch_timeout=int(os.getenv("GIT_FETCH_TIMEOUT", "60")),
            force_sync=os.getenv("GIT_FORCE_SYNC", "false").lower() == "true",
        )
        
        return config
    
    def _mask_url(self, url: str) -> str:
        """遮蔽URL中的敏感信息（密码/token）"""
        if not url:
            return "(未配置)"
        
        # 遮蔽 https://user:password@github.com/... 格式
        masked = re.sub(
            r'(https?://)[^:@]+:[^@]+(@)',
            r'\1***:***\2',
            url
        )
        
        # 遮蔽 token 格式
        masked = re.sub(
            r'(access_token|token)=([^&\s]+)',
            r'\1=***',
            masked
        )
        
        return masked
    
    def _run_git_command(self, 
                         args: List[str], 
                         timeout: int = None,
                         use_credentials: bool = True) -> GitOperationResult:
        """
        执行Git命令（使用subprocess）
        
        参数:
            args: Git命令参数列表（如 ['fetch', '--all']）
            timeout: 超时时间（秒）
            use_credentials: 是否注入认证信息
            
        返回:
            GitOperationResult对象
        """
        start_time = datetime.now()
        operation = ' '.join(['git'] + args)
        
        try:
            # 构建完整命令
            cmd = ['git'] + args
            
            # 注入认证信息（如果需要）
            env = os.environ.copy()
            if use_credentials and self.config.auth_type in [AuthType.HTTPS.value, AuthType.TOKEN.value]:
                if self.config.username and self.config.password:
                    # 设置环境变量供Git Credential Manager使用
                    env['GIT_ASKPASS'] = 'echo'
                    env['GIT_USERNAME'] = self.config.username
                    env['GIT_PASSWORD'] = self.config.password
                    env['GIT_TERMINAL_PROMPT'] = '0'
            
            logger.debug(f"[GitManager] 执行命令: {' '.join(cmd)} (工作目录: {self.repo_path})")
            
            result = subprocess.run(
                cmd,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=timeout or self.config.fetch_timeout,
                env=env,
                encoding='utf-8',
                errors='ignore'  # 忽略无法解码的字符
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            if result.returncode == 0:
                logger.info(f"[GitManager] ✅ 命令成功: {operation} ({duration:.2f}s)")
                return GitOperationResult(
                    success=True,
                    operation=operation,
                    message="执行成功",
                    output=result.stdout.strip(),
                    duration_seconds=duration
                )
            else:
                error_msg = result.stderr.strip() or "未知错误"
                logger.warning(f"[GitManager] ❌ 命令失败: {operation}")
                logger.warning(f"[GitManager] 错误: {error_msg[:200]}")
                
                return GitOperationResult(
                    success=False,
                    operation=operation,
                    message=f"执行失败: {error_msg}",
                    error=error_msg,
                    duration_seconds=duration
                )
                
        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[GitManager] ⏰ 命令超时: {operation} (> {timeout or self.config.fetch_timeout}s)")
            return GitOperationResult(
                success=False,
                operation=operation,
                message=f"命令超时 ({timeout or self.config.fetch_timeout}秒)",
                duration_seconds=duration
            )
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"[GitManager] 💥 命令异常: {operation} - {e}")
            return GitOperationResult(
                success=False,
                operation=operation,
                message=f"执行异常: {str(e)}",
                error=str(e),
                duration_seconds=duration
            )
    
    def configure_remote(self, 
                         name: str = "origin", 
                         url: str = None,
                         force: bool = True) -> GitOperationResult:
        """
        配置远程仓库地址
        
        参数:
            name: 远程仓库名称（默认origin）
            url: 远程URL（不传则使用配置文件中的URL）
            force: 是否强制覆盖已有配置
            
        返回:
            GitOperationResult
        """
        url = url or self.config.remote_url
        if not url:
            return GitOperationResult(
                success=False,
                operation="configure_remote",
                message="未指定远程URL（请设置GIT_REMOTE_URL或传入url参数）"
            )
        
        logger.info(f"[GitManager] 配置远程仓库: {name} -> {self._mask_url(url)}")
        
        # 检查远程是否已存在
        check_result = self._run_git_command(['remote', '-v'])
        if name in check_result.output and not force:
            logger.info(f"[GitManager] 远程 '{name}' 已存在，跳过配置")
            return GitOperationResult(
                success=True,
                operation=f"remote set-url {name}",
                message=f"远程 '{name}' 已存在，未修改"
            )
        
        # 设置或更新远程URL
        if name in check_result.output:
            return self._run_git_command(['remote', 'set-url', name, url])
        else:
            return self._run_git_command(['remote', 'add', name, url])
    
    def configure_credentials(self) -> GitOperationResult:
        """
        配置Git凭据（根据认证类型）
        
        支持三种方式：
        1. HTTPS + 用户名/密码（存储到credential helper）
        2. SSH + 密钥（检查密钥文件是否存在）
        3. Token认证（嵌入URL中）
        
        返回:
            GitOperationResult
        """
        auth_type = self.config.auth_type.lower()
        
        logger.info(f"[GitManager] 🔐 配置认证: 类型={auth_type}")
        
        if auth_type == AuthType.SSH.value:
            return self._configure_ssh_auth()
        elif auth_type == AuthType.TOKEN.value:
            return self._configure_token_auth()
        else:  # HTTPS (default)
            return self._configure_https_auth()
    
    def _configure_https_auth(self) -> GitOperationResult:
        """配置HTTPS认证（用户名+密码/PAT）"""
        username = self.config.username
        password = self.config.password
        
        if not username or not password:
            return GitOperationResult(
                success=False,
                operation="configure_https_auth",
                message="HTTPS认证需要配置GIT_USERNAME和GIT_PASSWORD"
            )
        
        try:
            # 使用git credential store临时存储凭据
            credential_input = (
                f"protocol=https\n"
                f"host={self._extract_host(self.config.remote_url)}\n"
                f"username={username}\n"
                f"password={password}\n\n"
            )
            
            result = subprocess.run(
                ['git', 'credential', 'approve'],
                input=credential_input,
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                logger.info(f"[GitManager] ✅ HTTPS凭据已配置 (用户: {username})")
                return GitOperationResult(
                    success=True,
                    operation="configure_https_auth",
                    message=f"HTTPS凭据已配置 (用户: {username})"
                )
            else:
                logger.warning(f"[GitManager] ⚠️ 凭据存储失败: {result.stderr}")
                # 即使存储失败，仍可继续（使用环境变量方式）
                return GitOperationResult(
                    success=True,
                    operation="configure_https_auth",
                    message="使用环境变量方式认证（fallback）"
                )
                
        except Exception as e:
            logger.warning(f"[GitManager] HTTPS认证配置异常: {e}")
            return GitOperationResult(
                success=True,  # 不阻塞流程
                operation="configure_https_auth",
                message=f"使用环境变量方式认证: {str(e)}"
            )
    
    def _configure_ssh_auth(self) -> GitOperationResult:
        """配置SSH认证"""
        ssh_key = Path(self.config.ssh_key_path).expanduser()
        
        if not ssh_key.exists():
            return GitOperationResult(
                success=False,
                operation="configure_ssh_auth",
                message=f"SSH密钥文件不存在: {ssh_key}"
            )
        
        # 检查权限（Linux/Mac需要600权限）
        import stat
        file_mode = ssh_key.stat().st_mode & 0o777
        if file_mode != 0o600:
            logger.warning(f"[GitManager] ⚠️ SSH密钥权限过于开放: {oct(file_mode)}, 建议 chmod 600")
        
        logger.info(f"[GitManager] ✅ SSH密钥已找到: {ssh_key}")
        return GitOperationResult(
            success=True,
            operation="configure_ssh_auth",
            message=f"SSH密钥已就绪: {ssh_key.name}"
        )
    
    def _configure_token_auth(self) -> GitOperationResult:
        """配置Token认证（嵌入URL）"""
        if not self.config.password:
            return GitOperationResult(
                success=False,
                operation="configure_token_auth",
                message="Token认证需要配置GIT_PASSWORD（作为Personal Access Token）"
            )
        
        # 将token嵌入到URL中: https://TOKEN@github.com/...
        url = self.config.remote_url
        if '@' not in url:
            # 插入token到URL
            token_url = re.sub(
                r'(https?://)',
                rf'\g<1>{self.config.password}@',
                url
            )
            self.config.remote_url = token_url
            logger.info(f"[GitManager] ✅ Token已嵌入URL")
        
        return GitOperationResult(
            success=True,
            operation="configure_token_auth",
            message="Token认证已配置"
        )
    
    def _extract_host(self, url: str) -> str:
        """从URL提取主机名"""
        match = re.search(r'https?://([^/@]+)', url)
        return match.group(1) if match else url
    
    def fetch_all(self, 
                  prune: bool = True,
                  timeout: int = None) -> GitOperationResult:
        """
        更新所有远程分支引用（git fetch --all）
        
        参数:
            prune: 是否删除已不存在于远程的本地引用
            timeout: 超时时间
            
        返回:
            GitOperationResult
        """
        logger.info(f"[GitManager] 📥 开始更新远程引用...")
        
        args = ['fetch', '--all']
        if prune:
            args.append('--prune')
        
        result = self._run_git_command(args, timeout=timeout)
        
        if result.success:
            # 输出更新的分支信息
            lines = result.output.split('\n')
            updated_count = len([l for l in lines if '->' in l])
            if updated_count > 0:
                logger.info(f"[GitManager] ✅ 已更新 {updated_count} 个远程分支")
        
        return result
    
    def pull(self, 
             branch: str = None,
             remote: str = "origin",
             force: bool = None,
             timeout: int = None) -> GitOperationResult:
        """
        拉取指定分支的最新代码（git pull）
        
        参数:
            branch: 分支名称（不传则使用当前分支或配置中的auto_pull_branch）
            remote: 远程仓库名称
            force: 是否允许非快进合并
            timeout: 超时时间
            
        返回:
            GitOperationResult
        """
        branch = branch or self.config.auto_pull_branch
        force = force if force is not None else self.config.force_sync
        
        # 如果没有指定分支，使用当前分支
        if not branch:
            branch = self.active_branch
            if branch == "HEAD detached":
                return GitOperationResult(
                    success=False,
                    operation="pull",
                    message="当前处于detached HEAD状态，无法pull。请指定分支名称。"
                )
        
        logger.info(f"[GitManager] ⬇️  拉取分支: {remote}/{branch}" + 
                   (" (强制模式)" if force else ""))
        
        # 先切换到目标分支（如果不是当前分支）
        if branch != self.active_branch:
            checkout_result = self.checkout(branch)
            if not checkout_result.success:
                return checkout_result
        
        # 执行pull
        args = ['pull', remote, branch]
        if force:
            args.insert(1, '--no-rebase')  # 允许非快进合并
        
        result = self._run_git_command(args, timeout=timeout)
        
        if result.success:
            logger.info(f"[GitManager] ✅ 分支 '{branch}' 拉取成功")
        
        return result
    
    def checkout(self, 
                 branch_or_ref: str,
                 create_new: bool = False,
                 force: bool = False) -> GitOperationResult:
        """
        切换分支（git checkout）
        
        参数:
            branch_or_ref: 分支名或commit hash
            create_new: 是否创建新分支
            force: 强制切换（丢弃本地修改）
            
        返回:
            GitOperationResult
        """
        args = ['checkout']
        if force:
            args.append('-f')
        if create_new:
            args.append('-b')
        args.append(branch_or_ref)
        
        logger.info(f"[GitManager] 🔄 切换分支: {branch_or_ref}" + 
                   (" (新建)" if create_new else "") +
                   (" (强制)" if force else ""))
        
        result = self._run_git_command(args, timeout=30)
        
        if result.success:
            logger.info(f"[GitManager] ✅ 已切换到: {branch_or_ref}")
        
        return result
    
    def sync_to_remote(self, 
                       branch: str = None,
                       remote: str = "origin") -> GitOperationResult:
        """
        强制同步本地分支到远程状态（用于CI/CD确保代码一致）
        
        流程：
        1. git fetch --all
        2. git reset --hard origin/<branch>
        3. git clean -fd（清理未跟踪的文件）
        
        参数:
            branch: 目标分支
            remote: 远程仓库名称
            
        返回:
            GitOperationResult
        """
        branch = branch or self.config.auto_pull_branch or self.active_branch
        
        logger.warning(f"[GitManager] ⚠️  强制同步模式: 将重置到 {remote}/{branch}")
        logger.warning("[GitManager] ⚠️  本地未提交的修改将会丢失！")
        
        results = []
        
        # 步骤1: Fetch
        fetch_result = self.fetch_all()
        results.append(fetch_result)
        if not fetch_result.success:
            return GitOperationResult(
                success=False,
                operation="sync_to_remote",
                message=f"Fetch失败: {fetch_result.message}"
            )
        
        # 步骤2: Reset to remote
        reset_result = self._run_git_command(
            ['reset', '--hard', f'{remote}/{branch}'],
            timeout=30
        )
        results.append(reset_result)
        
        # 步骤3: Clean untracked files
        clean_result = self._run_git_command(
            ['clean', '-fd'],
            timeout=30
        )
        results.append(clean_result)
        
        overall_success = all(r.success for r in results)
        
        if overall_success:
            logger.info(f"[GitManager] ✅ 强制同步完成: {remote}/{branch}")
        
        return GitOperationResult(
            success=overall_success,
            operation="sync_to_remote",
            message=f"{'成功' if overall_success else '部分失败'} 同步到 {remote}/{branch}",
            output='\n'.join([r.output for r in results if r.output]),
            error='\n'.join([r.error for r in results if r.error])
        )
    
    def auto_pull_if_configured(self) -> Tuple[bool, str]:
        """
        如果配置了自动拉取，则执行自动拉取流程
        
        返回:
            (是否执行了拉取, 结果消息)
        """
        if not self.config.auto_pull:
            logger.info("[GitManager] ℹ️  未启用自动拉取（GIT_AUTO_PULL=false）")
            return False, "自动拉取未启用"
        
        logger.info("[GitManager] 🤖 开始自动拉取流程...")
        
        steps = []
        
        # 步骤1: 配置远程地址
        if self.config.remote_url:
            remote_result = self.configure_remote()
            steps.append(("配置远程", remote_result))
        
        # 步骤2: 配置认证
        cred_result = self.configure_credentials()
        steps.append(("配置认证", cred_result))
        
        # 步骤3: Fetch
        fetch_result = self.fetch_all()
        steps.append(("更新远程引用", fetch_result))
        
        # 步骤4: Pull 或 Sync
        if self.config.force_sync:
            pull_result = self.sync_to_remote()
        else:
            pull_result = self.pull()
        steps.append(("拉取代码", pull_result))
        
        # 汇总结果
        all_success = all(r.success for _, r in steps)
        summary_lines = [
            f"{step_name}: {'✅' if result.success else '❌'} {result.message}"
            for step_name, result in steps
        ]
        
        summary = "\n".join(summary_lines)
        
        if all_success:
            logger.info(f"[GitManager] 🎉 自动拉取全部成功:\n{summary}")
        else:
            logger.warning(f"[GitManager] ⚠️  自动拉取部分失败:\n{summary}")
        
        return all_success, summary
    
    def get_current_commit_info(self) -> Dict[str, str]:
        """获取当前提交信息"""
        info = {}
        
        try:
            # 获取短hash
            result = self._run_git_command(['rev-parse', '--short', 'HEAD'], use_credentials=False)
            if result.success:
                info['short_hash'] = result.output
            
            # 获取完整hash
            result = self._run_git_command(['rev-parse', 'HEAD'], use_credentials=False)
            if result.success:
                info['full_hash'] = result.output
            
            # 获取提交信息
            result = self._run_git_command(['log', '-1', '--pretty=%s'], use_credentials=False)
            if result.success:
                info['message'] = result.output
            
            # 获取作者
            result = self._run_git_command(['log', '-1', '--pretty=%an'], use_credentials=False)
            if result.success:
                info['author'] = result.output
            
            # 获取时间
            result = self._run_git_command(['log', '-1', '--pretty=%ai'], use_credentials=False)
            if result.success:
                info['date'] = result.output
                
        except Exception as e:
            logger.error(f"[GitManager] 获取提交信息失败: {e}")
        
        return info
    
    def get_status(self) -> Dict[str, Any]:
        """获取仓库状态摘要"""
        status = {
            'repo_path': str(self.repo_path),
            'active_branch': self.active_branch,
            'remotes': self.remotes,
            'is_clean': True,
            'uncommitted_files': [],
            'current_commit': {}
        }
        
        try:
            # 检查是否有未提交的更改
            result = self._run_git_command(['status', '--porcelain'], use_credentials=False)
            if result.success and result.output.strip():
                status['is_clean'] = False
                status['uncommitted_files'] = result.output.split('\n')
            
            # 获取当前提交信息
            status['current_commit'] = self.get_current_commit_info()
            
        except Exception as e:
            logger.error(f"[GitManager] 获取状态失败: {e}")
        
        return status
    
    def print_summary(self):
        """打印Git管理器状态摘要"""
        print("\n" + "="*70)
        print("📦 Git仓库管理器 - 状态摘要")
        print("="*70)
        
        status = self.get_status()
        
        print(f"\n📂 仓库路径: {status['repo_path']}")
        print(f"🌿 当前分支: {status['active_branch']}")
        print(f"🔗 远程仓库:")
        for name, url in status['remotes'].items():
            print(f"   • {name}: {self._mask_url(url)}")
        
        commit = status.get('current_commit', {})
        if commit:
            print(f"\n📌 当前提交:")
            print(f"   Hash: {commit.get('short_hash', 'N/A')}")
            print(f"   信息: {commit.get('message', 'N/A')[:60]}...")
            print(f"   作者: {commit.get('author', 'N/A')}")
            print(f"   时间: {commit.get('date', 'N/A')}")
        
        print(f"\n🧹 工作区状态: {'✅ 干净' if status['is_clean'] else '⚠️ 有未提交更改'}")
        if not status['is_clean']:
            print(f"   未提交文件数: {len(status['uncommitted_files'])}")
        
        print(f"\n🔐 认证配置:")
        print(f"   方式: {self.config.auth_type}")
        print(f"   用户: {self.config.username or '(未配置)'}")
        print(f"   自动拉取: {'✅ 启用' if self.config.auto_pull else '❌ 禁用'}")
        print(f"   强制同步: {'⚠️ 启用' if self.config.force_sync else '❌ 禁用'}")
        
        print(f"\n🌍 环境: {self.environment.value}")
        print("="*70 + "\n")


# ==================== 全局单例 ====================
_global_git_manager: Optional[GitManager] = None


def get_git_manager(repo_path: str = None, **kwargs) -> GitManager:
    """
    获取全局Git管理器实例
    
    参数:
        repo_path: 仓库路径（首次调用时必须提供）
        **kwargs: 传递给GitManager的其他参数
        
    返回:
        GitManager实例
    """
    global _global_git_manager
    
    if _global_git_manager is None:
        if not repo_path:
            repo_path = os.getenv("GIT_REPO_PATH", ".")
        _global_git_manager = GitManager(repo_path=repo_path, **kwargs)
    
    return _global_git_manager


def reset_git_manager():
    """重置全局Git管理器（用于测试）"""
    global _global_git_manager
    _global_git_manager = None
