#!/usr/bin/env python3
"""
API自动化测试框架主程序
自动检测API变更、生成测试用例、执行测试并发送报告
"""

import os
import sys
import json
import re
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
load_dotenv(Path(__file__).parent / ".env")

from utils.test_generator import TestCaseGenerator
from utils.wechat_notifier import WeChatWorkNotifier
from utils.html_report_generator import HTMLReportGenerator
from config.settings import settings
from utils.enhanced_impact_analyzer import EnhancedImpactAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def prepare_git_repo(repo_path: str, source_branch: str, target_branch: str) -> str:
    """Git仓库准备: fetch + checkout source分支，返回原始分支名"""
    original_branch = None
    
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=repo_path, capture_output=True, text=True, timeout=10
        )
        original_branch = result.stdout.strip()
    except Exception:
        pass
    
    logger.info(f"[Git] 原始分支: {original_branch or 'unknown'}")
    
    logger.info(f"[Git] 执行 git fetch --all ...")
    try:
        subprocess.run(
            ['git', 'fetch', '--all', '--prune'],
            cwd=repo_path, capture_output=True, text=True, timeout=120
        )
        logger.info("[Git] fetch 完成")
    except subprocess.TimeoutExpired:
        logger.warning("[Git] fetch 超时(120秒)")
    except Exception as e:
        logger.warning(f"[Git] fetch 失败: {e}")
    
    logger.info(f"[Git] 执行 git checkout {source_branch} ...")
    try:
        subprocess.run(
            ['git', 'checkout', source_branch],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        logger.info(f"[Git] checkout {source_branch} 完成")
    except Exception as e:
        logger.warning(f"[Git] checkout {source_branch} 失败: {e}")
    
    return original_branch


def restore_git_branch(repo_path: str, original_branch: str):
    """恢复原始分支"""
    if not original_branch or original_branch == 'HEAD':
        return
    try:
        subprocess.run(
            ['git', 'checkout', original_branch],
            cwd=repo_path, capture_output=True, text=True, timeout=30
        )
        logger.info(f"[Git] 已恢复到原始分支: {original_branch}")
    except Exception as e:
        logger.warning(f"[Git] 恢复分支失败: {e}")


class TestRunner:
    """测试运行器主类"""
    
    def __init__(self, git_repo_path: str = None):
        repo_path = git_repo_path or os.getenv("GIT_REPO_PATH", ".")
        self.repo_path = repo_path
        self.test_generator = TestCaseGenerator()
        self.wechat_notifier = WeChatWorkNotifier()
        self.html_report_generator = HTMLReportGenerator()
        self.failed_tests_file = Path(__file__).parent / "test-reports" / "failed_tests.json"
        
        try:
            self.enhanced_analyzer = EnhancedImpactAnalyzer(repo_path, repo_path)
            logger.info("增强版影响分析器初始化成功")
        except Exception as e:
            logger.warning(f"增强版分析器初始化失败: {e}")
            self.enhanced_analyzer = None
    
    def run(self, commit_range: str = "HEAD~1..HEAD") -> bool:
        logger.info("开始API自动化测试工作流程")
        
        try:
            logger.info("步骤1: 检测API变更")
            changes = self.detect_changes(commit_range)
            
            if not changes['affected_endpoints']:
                logger.info("未检测到API接口变更，跳过测试生成")
                self.wechat_notifier.send_simple_message(
                    "API测试报告", "✅ 未检测到API接口变更，跳过冒烟测试"
                )
                return True
            
            logger.info("步骤2: 生成测试用例")
            test_file = self.generate_tests(changes['affected_endpoints'])
            
            logger.info("步骤3: 执行测试")
            test_results = self.execute_tests(test_file)
            
            logger.info("步骤4: 生成报告")
            self.generate_html_report(test_results, changes)
            
            logger.info("步骤5: 发送通知")
            self.send_notifications(test_results, changes)
            
            return test_results.get('failed_tests', 0) == 0
            
        except Exception as e:
            logger.error(f"测试工作流程执行失败: {e}")
            self.wechat_notifier.send_simple_message(
                "API测试报告 - 执行失败", f"❌ 测试执行失败: {str(e)}"
            )
            return False
    
    def detect_changes(self, commit_range: str) -> dict:
        if not self.enhanced_analyzer:
            logger.warning("增强版分析器不可用")
            return {'changed_files': [], 'affected_endpoints': [], 'change_summary': {}}
        
        try:
            logger.info("使用JCCI增强版影响分析器进行变更检测")
            
            affected_endpoints = self.enhanced_analyzer.get_affected_endpoints_for_testing(commit_range)
            change_summary = self.enhanced_analyzer.get_change_summary(commit_range)
            changed_files = self.enhanced_analyzer.code_change_detector.get_changed_files(commit_range)
            
            logger.info(f"JCCI分析检测到 {len(affected_endpoints)} 个受影响的接口")
            for endpoint in affected_endpoints:
                logger.info(f"  - {endpoint['method']} {endpoint['path']} "
                          f"(影响类型: {endpoint['impact_type']}, 置信度: {endpoint['confidence']:.2f})")
            
            try:
                reports_dir = Path(__file__).parent / "test-reports"
                reports_dir.mkdir(parents=True, exist_ok=True)
                self.enhanced_analyzer.save_analysis_report(
                    str(reports_dir / "impact_analysis.json"), commit_range
                )
            except Exception as e:
                logger.warning(f"保存分析报告失败: {e}")
            
            return {
                'changed_files': changed_files,
                'affected_endpoints': affected_endpoints,
                'change_summary': change_summary
            }
        except Exception as e:
            logger.error(f"增强版分析器执行失败: {e}")
            return {'changed_files': [], 'affected_endpoints': [], 'change_summary': {}}
    
    def generate_tests(self, endpoints: list) -> str:
        tests_dir = Path(__file__).parent / "tests" / "generated"
        tests_dir.mkdir(parents=True, exist_ok=True)
        
        self._clean_old_test_files(tests_dir)
        
        failed_endpoints = self._load_failed_tests()
        
        all_endpoints = []
        endpoint_set = set()
        for ep in endpoints + failed_endpoints:
            key = f"{ep['method']}_{ep['path']}"
            if key not in endpoint_set:
                endpoint_set.add(key)
                all_endpoints.append(ep)
        
        logger.info(f"为 {len(endpoints)} 个新接口 + {len(failed_endpoints)} 个失败接口 = 共 {len(all_endpoints)} 个接口生成测试")
        
        test_cases = self.test_generator.generate_test_cases(all_endpoints)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_file = tests_dir / f"test_generated_{timestamp}.py"
        self.test_generator.write_test_file(test_cases, str(test_file))
        
        return str(test_file)
    
    def execute_tests(self, test_file: str) -> dict:
        cmd = ["pytest", test_file, "-v", "--tb=long"]
        logger.info(f"执行命令: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            test_results = self._parse_test_results(result)
            
            logger.info(f"测试执行完成: 总数={test_results['total_tests']}, "
                       f"通过={test_results['passed_tests']}, 失败={test_results['failed_tests']}")
            
            self._save_failed_tests(test_results)
            return test_results
        except Exception as e:
            logger.error(f"测试执行失败: {e}")
            return {
                'total_tests': 0, 'passed_tests': 0, 'failed_tests': 0,
                'skipped_tests': 0, 'failed_details': [], 'test_details': []
            }
    
    def _parse_test_results(self, result: subprocess.CompletedProcess) -> dict:
        output = result.stdout + result.stderr
        lines = output.split('\n')
        
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        for line in lines:
            if 'passed' in line.lower() or 'failed' in line.lower() or 'skipped' in line.lower():
                m = re.search(r'(\d+)\s+passed', line)
                if m: passed_tests = int(m.group(1))
                m = re.search(r'(\d+)\s+failed', line)
                if m: failed_tests = int(m.group(1))
                m = re.search(r'(\d+)\s+skipped', line)
                if m: skipped_tests = int(m.group(1))
                if passed_tests > 0 or failed_tests > 0 or skipped_tests > 0:
                    break
        
        total_tests = passed_tests + failed_tests + skipped_tests
        if total_tests == 0:
            total_tests = 1
            if result.returncode == 0:
                passed_tests = 1
            else:
                failed_tests = 1
        
        test_details = []
        failed_details = []
        error_messages = {}
        current_test = None
        error_buffer = []
        
        for line in lines:
            stripped = line.strip()
            
            if ' PASSED' in line and '::' in line and 'test_' in line:
                parts = line.split('::')
                test_name = parts[-1].split()[0].strip()
                test_details.append({'name': test_name, 'status': 'PASSED'})
            
            elif ' FAILED' in line and '::' in line and 'test_' in line:
                parts = line.split('::')
                test_name = parts[-1].split()[0].strip()
                test_details.append({'name': test_name, 'status': 'FAILED'})
                failed_details.append({'name': test_name, 'error': ''})
                current_test = test_name
                error_buffer = []
            
            elif current_test and stripped.startswith('E '):
                error_buffer.append(stripped[2:].strip())
            
            elif current_test and (stripped.startswith('===') or stripped.startswith('---')):
                if error_buffer:
                    error_messages[current_test] = '\n'.join(error_buffer[-5:])
                current_test = None
                error_buffer = []
        
        if current_test and error_buffer:
            error_messages[current_test] = '\n'.join(error_buffer[-5:])
        
        for fail in failed_details:
            fail['error'] = error_messages.get(fail['name'], '连接超时或服务器未响应')
        
        responses_file = Path(__file__).parent / "test-reports" / "responses.json"
        if responses_file.exists():
            try:
                with open(responses_file, 'r', encoding='utf-8') as f:
                    stored_responses = json.load(f)
                for detail in test_details:
                    if detail['name'] in stored_responses:
                        resp = stored_responses[detail['name']]
                        detail['response'] = json.dumps(resp.get('response', {}), ensure_ascii=False)
            except Exception:
                pass
        
        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failed_tests': failed_tests,
            'skipped_tests': skipped_tests,
            'failed_details': failed_details,
            'test_details': test_details,
            'return_code': result.returncode
        }
    
    def generate_html_report(self, test_results: dict, changes: dict) -> str:
        return self.html_report_generator.generate(test_results, changes)
    
    def send_notifications(self, test_results: dict, changes: dict):
        test_results.update({
            'changed_files': changes.get('changed_files', []),
            'affected_endpoints': changes.get('affected_endpoints', []),
            'timestamp': datetime.now().isoformat()
        })
        
        success = self.wechat_notifier.send_test_report(test_results)
        if success:
            logger.info("测试报告发送成功")
        else:
            logger.warning("发送测试报告失败")
    
    def _clean_old_test_files(self, tests_dir: Path):
        try:
            for test_file in tests_dir.glob("test_generated_*.py"):
                test_file.unlink()
        except Exception as e:
            logger.warning(f"清理旧测试文件失败: {e}")
    
    def _load_failed_tests(self) -> list:
        if not self.failed_tests_file.exists():
            return []
        try:
            with open(self.failed_tests_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []
    
    def _save_failed_tests(self, test_results: dict):
        failed_endpoints = []
        endpoint_set = set()
        for fail in test_results.get('failed_details', []):
            method = fail.get('method', 'GET')
            path = fail.get('path', '/')
            if method != 'N/A' and path != 'N/A':
                key = f"{method}_{path}"
                if key not in endpoint_set:
                    endpoint_set.add(key)
                    failed_endpoints.append({
                        'method': method, 'path': path,
                        'full_endpoint': f"{method} {path}",
                        'test_name': fail.get('name', '')
                    })
        try:
            self.failed_tests_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.failed_tests_file, 'w', encoding='utf-8') as f:
                json.dump(failed_endpoints, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存失败测试用例失败: {e}")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='API测试运行器')
    parser.add_argument('--commit-range', default='HEAD~1..HEAD',
                       help='Git提交范围（默认: HEAD~1..HEAD）')
    parser.add_argument('--branch', nargs=2, metavar=('SOURCE', 'TARGET'),
                       help='比较两个分支（如: --branch origin/test-feature origin/main）')
    parser.add_argument('--git-repo-path', default=None,
                       help='Git仓库本地路径')
    
    args = parser.parse_args()
    
    if args.git_repo_path:
        os.environ['GIT_REPO_PATH'] = args.git_repo_path
    
    commit_range = args.commit_range
    original_branch = None
    
    if args.branch:
        source_branch, target_branch = args.branch
        commit_range = f"{target_branch}..{source_branch}"
        logger.info(f"分支对比模式: {source_branch} vs {target_branch}")
        logger.info(f"提交范围: {commit_range}")
        
        repo_path = args.git_repo_path or os.getenv("GIT_REPO_PATH", ".")
        original_branch = prepare_git_repo(repo_path, source_branch, target_branch)
    
    try:
        runner = TestRunner(git_repo_path=args.git_repo_path)
        success = runner.run(commit_range)
    finally:
        if original_branch:
            repo_path = args.git_repo_path or os.getenv("GIT_REPO_PATH", ".")
            restore_git_branch(repo_path, original_branch)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
