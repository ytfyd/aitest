#!/usr/bin/env python3
"""
Main test execution script for API testing framework
Automatically detects API changes, generates tests, executes them, and sends reports
"""

import os
import sys
import json
import time
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

load_dotenv(Path(__file__).parent / ".env")

from utils.test_generator import TestCaseGenerator
from utils.wechat_notifier import WeChatWorkNotifier
from utils.swagger_client import swagger_client
from utils.html_report_generator import HTMLReportGenerator
from config.settings import settings
from utils.enhanced_impact_analyzer import EnhancedImpactAnalyzer
from utils.code_change_detector import CodeChangeDetector


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestRunner:
    """Main test runner class"""
    
    def __init__(self, git_repo_path: str = None):
        repo_path = git_repo_path or os.getenv("GIT_REPO_PATH", ".")
        self.test_generator = TestCaseGenerator()
        self.wechat_notifier = WeChatWorkNotifier()
        self.html_report_generator = HTMLReportGenerator()
        self.test_results = {}
        self.failed_tests_file = Path(__file__).parent / "test-reports" / "failed_tests.json"
        
        # Initialize enhanced impact analyzer with JCCI
        try:
            self.enhanced_analyzer = EnhancedImpactAnalyzer(repo_path, repo_path)
            self.code_change_detector = CodeChangeDetector(repo_path, repo_path)
            logger.info("Enhanced impact analyzer initialized successfully with JCCI framework")
        except Exception as e:
            logger.warning(f"Failed to initialize enhanced analyzer: {e}")
            self.enhanced_analyzer = None
            self.code_change_detector = None
    
    def run(self, commit_range: str = "HEAD~1..HEAD") -> bool:
        """Run the complete testing workflow"""
        logger.info("Starting API testing workflow")
        
        try:
            logger.info("Step 1: Detecting API changes")
            changes = self.detect_changes(commit_range)
            
            if not changes['affected_endpoints']:
                logger.info("No API changes detected, skipping test generation")
                self.wechat_notifier.send_simple_message(
                    "API测试报告",
                    "✅ 本次提交未检测到API接口变更，跳过冒烟测试"
                )
                return True
            
            logger.info("Step 2: Generating test cases")
            test_file = self.generate_tests(changes['affected_endpoints'])
            
            logger.info("Step 3: Executing tests")
            test_results = self.execute_tests(test_file)
            
            logger.info("Step 4: Generating reports")
            self.generate_html_report(test_results, changes)
            
            logger.info("Step 5: Sending notifications")
            self.send_notifications(test_results, changes)
            
            return test_results.get('failed_tests', 0) == 0
            
        except Exception as e:
            logger.error(f"Test workflow failed: {e}")
            self.wechat_notifier.send_simple_message(
                "API测试报告 - 执行失败",
                f"❌ 测试执行失败: {str(e)}"
            )
            return False
    
    def detect_changes(self, commit_range: str) -> dict:
        """Detect API changes in the specified commit range using JCCI enhanced analyzer"""
        if self.enhanced_analyzer:
            try:
                logger.info("Using enhanced impact analyzer with JCCI framework")
                
                # Get affected endpoints from enhanced analyzer
                affected_endpoints = self.enhanced_analyzer.get_affected_endpoints_for_testing(commit_range)
                
                # Get change summary
                change_summary = self.enhanced_analyzer.get_change_summary(commit_range)
                
                # Get changed files from code change detector
                changed_files = []
                if self.code_change_detector:
                    changed_files = self.code_change_detector.get_changed_files(commit_range)
                
                logger.info(f"JCCI analysis detected {len(affected_endpoints)} affected endpoints")
                for endpoint in affected_endpoints:
                    logger.info(f"  - {endpoint['method']} {endpoint['path']} (impact: {endpoint['impact_type']}, confidence: {endpoint['confidence']:.2f})")
                
                # Save detailed analysis report
                try:
                    reports_dir = Path(__file__).parent / "test-reports"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    analysis_file = reports_dir / "impact_analysis.json"
                    self.enhanced_analyzer.save_analysis_report(str(analysis_file), commit_range)
                    logger.info(f"Detailed analysis saved to {analysis_file}")
                except Exception as e:
                    logger.warning(f"Failed to save analysis report: {e}")
                
                return {
                    'changed_files': changed_files,
                    'affected_endpoints': affected_endpoints,
                    'change_summary': change_summary
                }
            except Exception as e:
                logger.error(f"Enhanced analyzer failed: {e}")
                return {
                    'changed_files': [],
                    'affected_endpoints': [],
                    'change_summary': {}
                }
        
        logger.warning("Enhanced analyzer not available")
        return {
            'changed_files': [],
            'affected_endpoints': [],
            'change_summary': {}
        }
    
    def generate_tests(self, endpoints: list) -> str:
        """Generate test cases for affected endpoints"""
        tests_dir = Path(__file__).parent / "tests" / "generated"
        tests_dir.mkdir(parents=True, exist_ok=True)
        
        # Clean old test files
        self._clean_old_test_files(tests_dir)
        
        # Load failed test cases from last run
        failed_endpoints = self._load_failed_tests()
        
        # Merge current endpoints with failed endpoints (avoid duplicates)
        all_endpoints = []
        endpoint_set = set()
        
        for endpoint in endpoints:
            endpoint_key = f"{endpoint['method']}_{endpoint['path']}"
            if endpoint_key not in endpoint_set:
                endpoint_set.add(endpoint_key)
                all_endpoints.append(endpoint)
        
        for endpoint in failed_endpoints:
            endpoint_key = f"{endpoint['method']}_{endpoint['path']}"
            if endpoint_key not in endpoint_set:
                endpoint_set.add(endpoint_key)
                all_endpoints.append(endpoint)
        
        logger.info(f"Generating tests for {len(endpoints)} new endpoints + {len(failed_endpoints)} failed endpoints = {len(all_endpoints)} total")
        
        test_cases = self.test_generator.generate_test_cases(all_endpoints)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_file = tests_dir / f"test_generated_{timestamp}.py"
        
        self.test_generator.write_test_file(test_cases, str(test_file))
        
        return str(test_file)
    
    def execute_tests(self, test_file: str) -> dict:
        """Execute the generated tests using pytest"""
        cmd = [
            "pytest",
            test_file,
            "-v",
            "--tb=long"
        ]
        
        logger.info(f"Executing: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            test_results = self._parse_test_results(result)
            
            logger.info(f"Test execution completed:")
            logger.info(f"  - Total: {test_results['total_tests']}")
            logger.info(f"  - Passed: {test_results['passed_tests']}")
            logger.info(f"  - Failed: {test_results['failed_tests']}")
            logger.info(f"  - Skipped: {test_results['skipped_tests']}")
            
            # Save failed test cases for next run
            self._save_failed_tests(test_results)
            
            return test_results
            
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return {
                'total_tests': 0,
                'passed_tests': 0,
                'failed_tests': 0,
                'skipped_tests': 0,
                'failed_details': [{'name': 'Execution Error', 'error': str(e)}],
                'test_details': []
            }
    
    def _parse_test_results(self, result: subprocess.CompletedProcess) -> dict:
        """Parse pytest output to extract test results with detailed info"""
        output = result.stdout + result.stderr
        
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        # Use dict to avoid duplicates
        test_details_dict = {}
        failed_details_dict = {}
        passed_details_dict = {}
        
        # Extract test data from test file for request parameters
        test_data_map = self._extract_test_data_from_file()
        
        # Parse summary from output
        lines = output.split('\n')
        for line in lines:
            if 'passed' in line.lower() or 'failed' in line.lower() or 'skipped' in line.lower():
                import re
                
                passed_match = re.search(r'(\d+)\s+passed', line)
                failed_match = re.search(r'(\d+)\s+failed', line)
                skipped_match = re.search(r'(\d+)\s+skipped', line)
                
                if passed_match:
                    passed_tests = int(passed_match.group(1))
                if failed_match:
                    failed_tests = int(failed_match.group(1))
                if skipped_match:
                    skipped_tests = int(skipped_match.group(1))
                
                if passed_tests > 0 or failed_tests > 0 or skipped_tests > 0:
                    total_tests = passed_tests + failed_tests + skipped_tests
                    break
        
        if total_tests == 0:
            if result.returncode == 0:
                passed_tests = 1
                total_tests = 1
            else:
                failed_tests = 1
                total_tests = 1
        
        # Parse test results - only process lines with test outcomes
        error_messages = {}
        current_test = None
        error_buffer = []
        in_error = False
        processed_tests = set()
        
        for i, line in enumerate(lines):
            # Detect failed test from long format - look for lines with " test_name " between underscores
            stripped = line.strip()
            if stripped.startswith('_') and ' test_' in stripped:
                # Extract test name - find the part between spaces
                parts = stripped.split(' test_')
                if len(parts) >= 2:
                    test_part = 'test_' + parts[1].split(' ')[0]
                    if test_part.startswith('test_') and not test_part.endswith('_'):
                        test_name = test_part.rstrip('_')
                        # Save previous test's error if exists
                        if current_test and error_buffer:
                            error_messages[current_test] = '\n'.join(error_buffer[-5:])
                        # Start new test
                        if test_name not in processed_tests:
                            processed_tests.add(test_name)
                            current_test = test_name
                            test_info = test_data_map.get(test_name, {})
                            failed_details_dict[test_name] = {
                                'name': test_name,
                                'error': '',
                                'request_params': test_info.get('request_params', 'N/A'),
                                'response': test_info.get('response', 'N/A'),
                                'method': test_info.get('method', 'N/A'),
                                'path': test_info.get('path', 'N/A')
                            }
                            # Also add to test_details_dict
                            test_details_dict[test_name] = {
                                'name': test_name,
                                'status': 'FAILED',
                                'request_params': test_info.get('request_params', 'N/A'),
                                'response': test_info.get('response', 'N/A'),
                                'method': test_info.get('method', 'N/A'),
                                'path': test_info.get('path', 'N/A')
                            }
                            in_error = True
                            error_buffer = []
            # Capture error details from assertion errors (lines starting with 'E ')
            elif current_test and in_error:
                if line.strip().startswith('E '):
                    error_buffer.append(line.strip()[2:].strip())  # Remove 'E ' prefix
                # End of error section
                elif line.strip().startswith('===') or line.strip().startswith('---'):
                    if error_buffer:
                        error_messages[current_test] = '\n'.join(error_buffer[-5:])
                    current_test = None
                    in_error = False
                    error_buffer = []
                elif line.strip().startswith('PASSED') or line.strip().startswith('FAILED'):
                    if error_buffer:
                        error_messages[current_test] = '\n'.join(error_buffer[-5:])
                    current_test = None
                    in_error = False
                    error_buffer = []
            
            # Also handle short format (FAILED tests/...::test_name) for summary
            elif line.startswith('FAILED ') and '::' in line and 'test_' in line:
                parts = line.split('::')
                if len(parts) >= 2:
                    test_name = parts[-1].split()[0].strip()
                    if test_name not in processed_tests:
                        processed_tests.add(test_name)
                        test_info = test_data_map.get(test_name, {})
                        failed_details_dict[test_name] = {
                            'name': test_name,
                            'error': '',
                            'request_params': test_info.get('request_params', 'N/A'),
                            'response': test_info.get('response', 'N/A'),
                            'method': test_info.get('method', 'N/A'),
                            'path': test_info.get('path', 'N/A')
                        }
                        # Also add to test_details_dict
                        test_details_dict[test_name] = {
                            'name': test_name,
                            'status': 'FAILED',
                            'request_params': test_info.get('request_params', 'N/A'),
                            'response': test_info.get('response', 'N/A'),
                            'method': test_info.get('method', 'N/A'),
                            'path': test_info.get('path', 'N/A')
                        }
            
            # Detect passed/failed tests from test session output (like tests/file.py::test_name PASSED)
            if (' PASSED' in line or ' FAILED' in line) and '::' in line and 'test_' in line:
                parts = line.split('::')
                if len(parts) >= 2:
                    test_name = parts[-1].split()[0].strip()
                    status = 'PASSED' if ' PASSED' in line else 'FAILED'
                    test_info = test_data_map.get(test_name, {})
                    test_detail = {
                        'name': test_name,
                        'status': status,
                        'request_params': test_info.get('request_params', 'N/A'),
                        'response': test_info.get('response', 'N/A'),
                        'method': test_info.get('method', 'N/A'),
                        'path': test_info.get('path', 'N/A')
                    }
                    test_details_dict[test_name] = test_detail
                    
                    if status == 'PASSED':
                        passed_details_dict[test_name] = test_detail
        
        # Assign error messages to failed tests
        for test_name, fail in failed_details_dict.items():
            if test_name in error_messages:
                fail['error'] = error_messages[test_name]
            elif not fail['error']:
                fail['error'] = '连接超时或服务器未响应'
        
        # Load stored responses from file
        responses_file = Path(__file__).parent / "test-reports" / "responses.json"
        stored_responses = {}
        if responses_file.exists():
            try:
                with open(responses_file, 'r', encoding='utf-8') as f:
                    stored_responses = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load responses: {e}")
        
        # Update test details with actual responses
        for test_name, detail in test_details_dict.items():
            if test_name in stored_responses:
                resp_data = stored_responses[test_name]
                detail['response'] = json.dumps(resp_data.get('response', {}), ensure_ascii=False)
                if 'request_params' in resp_data:
                    detail['request_params'] = json.dumps(resp_data['request_params'], ensure_ascii=False)
        
        # Update passed details with actual responses
        for test_name, detail in passed_details_dict.items():
            if test_name in stored_responses:
                resp_data = stored_responses[test_name]
                detail['response'] = json.dumps(resp_data.get('response', {}), ensure_ascii=False)
                if 'request_params' in resp_data:
                    detail['request_params'] = json.dumps(resp_data['request_params'], ensure_ascii=False)
        
        # Update failed details with actual responses
        for test_name, detail in failed_details_dict.items():
            if test_name in stored_responses:
                resp_data = stored_responses[test_name]
                detail['response'] = json.dumps(resp_data.get('response', {}), ensure_ascii=False)
                if 'request_params' in resp_data:
                    detail['request_params'] = json.dumps(resp_data['request_params'], ensure_ascii=False)
        
        # Convert dicts to lists
        test_details = list(test_details_dict.values())
        failed_details = list(failed_details_dict.values())
        passed_details = list(passed_details_dict.values())
        
        # Use actual counts from parsed details instead of summary line
        actual_total = len(test_details)
        actual_passed = len(passed_details)
        actual_failed = len(failed_details)
        actual_skipped = total_tests - actual_passed - actual_failed if total_tests > 0 else 0
        
        # If no details were parsed but we have counts from summary, use summary counts
        if actual_total == 0 and total_tests > 0:
            logger.warning("No test details parsed, using summary counts")
            actual_total = total_tests
            actual_passed = passed_tests
            actual_failed = failed_tests
            actual_skipped = skipped_tests
        else:
            # Use actual parsed counts
            total_tests = actual_total
            passed_tests = actual_passed
            failed_tests = actual_failed
            skipped_tests = actual_skipped
        
        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failed_tests': failed_tests,
            'skipped_tests': skipped_tests,
            'failed_details': failed_details,
            'passed_details': passed_details,
            'test_details': test_details,
            'return_code': result.returncode
        }
    
    def _extract_test_data_from_file(self) -> dict:
        """Extract test data from the generated test file"""
        test_data_map = {}
        
        try:
            # Find the latest generated test file
            tests_dir = Path(__file__).parent / "tests" / "generated"
            test_files = list(tests_dir.glob("test_generated_*.py"))
            
            if not test_files:
                return test_data_map
            
            latest_file = max(test_files, key=lambda p: p.stat().st_mtime)
            
            with open(latest_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse test functions to extract request data
            import re
            
            # Find all test functions - improved pattern
            test_pattern = r'def\s+(test_\w+)\s*\(\s*\)\s*:\s*"""(.*?)"""(.*?)\n\n\n|def\s+(test_\w+)\s*\(\s*\)\s*:\s*"""(.*?)"""(.*?)\Z'
            matches = re.findall(test_pattern, content, re.DOTALL)
            
            for match in matches:
                # Handle both pattern groups
                if match[0]:  # First pattern matched
                    test_name = match[0]
                    docstring = match[1]
                    func_body = match[2]
                else:  # Second pattern matched (last test)
                    test_name = match[3]
                    docstring = match[4]
                    func_body = match[5]
                
                # Extract method and path from docstring
                method_match = re.search(r'(get|post|put|delete|patch).*?(/\S+)', docstring.lower())
                method = method_match.group(1).upper() if method_match else 'GET'
                path = method_match.group(2) if method_match else '/'
                
                # Extract data parameter from api_client call
                # Look for data={...} in the function body
                data_match = re.search(r'api_client\.\w+\s*\(\s*[\'"][^\'"]+[\'"]\s*,\s*data\s*=\s*(\{[^}]+\})', func_body)
                if data_match:
                    request_params = data_match.group(1)
                else:
                    # Fallback to test_data variable
                    test_data_match = re.search(r'test_data\s*=\s*(\{[^}]*\})', func_body)
                    request_params = test_data_match.group(1) if test_data_match else '{}'
                
                test_data_map[test_name] = {
                    'method': method,
                    'path': path,
                    'request_params': request_params,
                    'response': '待获取'  # Will be populated during actual test execution
                }
        
        except Exception as e:
            logger.warning(f"Failed to extract test data: {e}")
        
        return test_data_map
    
    def generate_html_report(self, test_results: dict, changes: dict):
        """Generate a beautiful HTML test report"""
        return self.html_report_generator.generate(test_results, changes)
    
    def send_notifications(self, test_results: dict, changes: dict):
        """Send test results to WeChat Work"""
        test_results.update({
            'changed_files': changes.get('changed_files', []),
            'affected_endpoints': changes.get('affected_endpoints', []),
            'commit_sha': settings.ci_commit_sha,
            'build_number': settings.ci_build_number,
            'timestamp': datetime.now().isoformat()
        })
        
        success = self.wechat_notifier.send_test_report(test_results)
        
        if success:
            logger.info("Test report sent successfully")
        else:
            logger.warning("Failed to send test report")
    
    def _clean_old_test_files(self, tests_dir: Path):
        """Clean old test files from previous runs"""
        try:
            test_files = list(tests_dir.glob("test_generated_*.py"))
            for test_file in test_files:
                test_file.unlink()
                logger.info(f"Removed old test file: {test_file}")
        except Exception as e:
            logger.warning(f"Failed to clean old test files: {e}")
    
    def _load_failed_tests(self) -> list:
        """Load failed test cases from last run"""
        if not self.failed_tests_file.exists():
            return []
        
        try:
            with open(self.failed_tests_file, 'r', encoding='utf-8') as f:
                failed_tests = json.load(f)
            logger.info(f"Loaded {len(failed_tests)} failed test cases from last run")
            return failed_tests
        except Exception as e:
            logger.warning(f"Failed to load failed tests: {e}")
            return []
    
    def _save_failed_tests(self, test_results: dict):
        """Save failed test cases for next run"""
        failed_endpoints = []
        endpoint_set = set()
        
        for fail in test_results.get('failed_details', []):
            test_name = fail.get('name', '')
            method = fail.get('method', 'GET')
            path = fail.get('path', '/')
            
            if method != 'N/A' and path != 'N/A':
                endpoint_key = f"{method}_{path}"
                if endpoint_key not in endpoint_set:
                    endpoint_set.add(endpoint_key)
                    failed_endpoints.append({
                        'method': method,
                        'path': path,
                        'full_endpoint': f"{method} {path}",
                        'test_name': test_name
                    })
        
        try:
            self.failed_tests_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.failed_tests_file, 'w', encoding='utf-8') as f:
                json.dump(failed_endpoints, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(failed_endpoints)} failed test cases for next run")
        except Exception as e:
            logger.warning(f"Failed to save failed tests: {e}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='API Test Runner', 
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="""
使用示例:
  python run_tests.py                              # 分析最近一次提交
  python run_tests.py --commit-range HEAD~5..HEAD  # 分析最近5次提交
  python run_tests.py --branch test-feature main   # 对比test-feature与main分支
  python run_tests.py --branch feature-xxx origin/main  # 对比本地分支与远程分支
""")
    
    parser.add_argument('--commit-range', default='HEAD~1..HEAD', 
                       help='Git commit range to analyze (default: HEAD~1..HEAD)')
    parser.add_argument('--branch', nargs=2, metavar=('SOURCE', 'TARGET'),
                       help='Compare two branches (e.g., --branch test-feature main)')
    parser.add_argument('--config', default='.env', 
                       help='Configuration file path (default: .env)')
    parser.add_argument('--git-repo-path', default=None,
                       help='Git repository path to analyze (overrides .env setting)')
    
    args = parser.parse_args()
    
    if args.config and Path(args.config).exists():
        os.environ['ENV_FILE'] = args.config
    
    if args.git_repo_path:
        os.environ['GIT_REPO_PATH'] = args.git_repo_path
    
    commit_range = args.commit_range
    if args.branch:
        source_branch, target_branch = args.branch
        commit_range = f"{target_branch}..{source_branch}"
        logger.info(f"Branch comparison mode: {source_branch} vs {target_branch}")
        logger.info(f"Converted to commit range: {commit_range}")
        
        is_remote_branch = '/' in source_branch or '/' in target_branch
        if is_remote_branch:
            import subprocess
            repo_path = args.git_repo_path or os.getenv("GIT_REPO_PATH", ".")
            logger.info(f"Detected remote branch(es), running 'git fetch' to update remote references...")
            try:
                fetch_result = subprocess.run(
                    ['git', 'fetch', '--all'],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if fetch_result.returncode == 0:
                    logger.info(f"Git fetch completed successfully")
                else:
                    logger.warning(f"Git fetch warning: {fetch_result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning("Git fetch timed out (60s), using cached remote references")
            except Exception as e:
                logger.warning(f"Git fetch failed: {e}, using cached remote references")
    
    runner = TestRunner(git_repo_path=args.git_repo_path)
    success = runner.run(commit_range)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
