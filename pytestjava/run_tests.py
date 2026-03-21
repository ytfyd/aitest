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

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from utils.git_detector import GitChangeDetector
from utils.test_generator import TestCaseGenerator
from utils.wechat_notifier import WeChatWorkNotifier
from config.settings import settings


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestRunner:
    """Main test runner class"""
    
    def __init__(self, git_repo_path: str = None):
        repo_path = git_repo_path or settings.git_repo_path
        self.git_detector = GitChangeDetector(repo_path)
        self.test_generator = TestCaseGenerator()
        self.wechat_notifier = WeChatWorkNotifier()
        self.test_results = {}
    
    def run(self, commit_range: str = "HEAD~1..HEAD") -> bool:
        """Run the complete testing workflow"""
        logger.info("Starting API testing workflow")
        
        try:
            # Step 1: Detect API changes
            logger.info("Step 1: Detecting API changes")
            changes = self.detect_changes(commit_range)
            
            if not changes['affected_endpoints']:
                logger.info("No API changes detected, skipping test generation")
                self.wechat_notifier.send_simple_message(
                    "API测试报告",
                    "✅ 本次提交未检测到API接口变更，跳过冒烟测试"
                )
                return True
            
            # Step 2: Generate test cases
            logger.info("Step 2: Generating test cases")
            test_file = self.generate_tests(changes['affected_endpoints'])
            
            # Step 3: Execute tests
            logger.info("Step 3: Executing tests")
            test_results = self.execute_tests(test_file)
            
            # Step 4: Generate reports
            logger.info("Step 4: Generating reports")
            self.generate_reports()
            
            # Step 5: Send notifications
            logger.info("Step 5: Sending notifications")
            self.send_notifications(test_results, changes)
            
            # Return success based on test results
            return test_results.get('failed_tests', 0) == 0
            
        except Exception as e:
            logger.error(f"Test workflow failed: {e}")
            self.wechat_notifier.send_simple_message(
                "API测试报告 - 执行失败",
                f"❌ 测试执行失败: {str(e)}"
            )
            return False
    
    def detect_changes(self, commit_range: str) -> dict:
        """Detect API changes in the specified commit range"""
        changes = self.git_detector.detect_api_changes(commit_range)
        
        logger.info(f"Detected {len(changes['changed_files'])} changed Java files")
        logger.info(f"Affected endpoints: {len(changes['affected_endpoints'])}")
        
        for endpoint in changes['affected_endpoints']:
            logger.info(f"  - {endpoint['full_endpoint']}")
        
        return changes
    
    def generate_tests(self, endpoints: list) -> str:
        """Generate test cases for affected endpoints"""
        test_cases = self.test_generator.generate_test_cases(endpoints)
        
        # Create tests directory if it doesn't exist
        tests_dir = Path("tests/generated")
        tests_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate test file name with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_file = tests_dir / f"test_generated_{timestamp}.py"
        
        self.test_generator.write_test_file(test_cases, str(test_file))
        
        return str(test_file)
    
    def execute_tests(self, test_file: str) -> dict:
        """Execute the generated tests using pytest"""
        # Ensure Allure results directory exists
        Path(settings.allure_results_dir).mkdir(parents=True, exist_ok=True)
        
        # Build pytest command
        cmd = [
            "pytest",
            test_file,
            "-v",
            "--tb=short",
            f"--alluredir={settings.allure_results_dir}",
            "--junit-xml=test-results.xml",
            "--html=test-report.html",
            "--self-contained-html"
        ]
        
        logger.info(f"Executing: {' '.join(cmd)}")
        
        try:
            # Run pytest
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            # Parse test results
            test_results = self._parse_test_results(result)
            
            # Log results
            logger.info(f"Test execution completed:")
            logger.info(f"  - Total: {test_results['total_tests']}")
            logger.info(f"  - Passed: {test_results['passed_tests']}")
            logger.info(f"  - Failed: {test_results['failed_tests']}")
            logger.info(f"  - Skipped: {test_results['skipped_tests']}")
            
            return test_results
            
        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return {
                'total_tests': 0,
                'passed_tests': 0,
                'failed_tests': 0,
                'skipped_tests': 0,
                'failed_details': [{'name': 'Execution Error', 'error': str(e)}]
            }
    
    def _parse_test_results(self, result: subprocess.CompletedProcess) -> dict:
        """Parse pytest output to extract test results"""
        output = result.stdout + result.stderr
        
        # Extract basic counts
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        lines = output.split('\n')
        
        # Try to parse pytest summary line
        for line in lines:
            if 'passed' in line.lower() or 'failed' in line.lower() or 'skipped' in line.lower():
                # Parse various pytest summary formats
                import re
                
                # Format: "3 passed, 1 failed, 2 skipped in 0.12s"
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
        
        # If parsing failed, check return code
        if total_tests == 0:
            if result.returncode == 0:
                passed_tests = 1
                total_tests = 1
            else:
                failed_tests = 1
                total_tests = 1
        
        # Extract failed test details
        failed_details = []
        if failed_tests > 0:
            for line in lines:
                if 'FAILED' in line:
                    parts = line.split('::')
                    if len(parts) >= 2:
                        test_name = parts[-1].strip()
                        failed_details.append({
                            'name': test_name,
                            'error': 'See test output for details'
                        })
        
        return {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failed_tests': failed_tests,
            'skipped_tests': skipped_tests,
            'failed_details': failed_details,
            'return_code': result.returncode
        }
    
    def generate_reports(self):
        """Generate Allure and other test reports"""
        # Generate Allure report
        if Path(settings.allure_results_dir).exists():
            cmd = [
                "allure", "generate",
                settings.allure_results_dir,
                "-o", settings.allure_report_dir,
                "--clean"
            ]
            
            try:
                subprocess.run(cmd, check=True)
                logger.info(f"Allure report generated: {settings.allure_report_dir}")
            except Exception as e:
                logger.warning(f"Failed to generate Allure report: {e}")
    
    def send_notifications(self, test_results: dict, changes: dict):
        """Send test results to WeChat Work"""
        # Add additional metadata to test results
        test_results.update({
            'changed_files': changes.get('changed_files', []),
            'affected_endpoints': changes.get('affected_endpoints', []),
            'commit_sha': settings.ci_commit_sha,
            'build_number': settings.ci_build_number,
            'timestamp': datetime.now().isoformat()
        })
        
        # Send notification
        success = self.wechat_notifier.send_test_report(test_results)
        
        if success:
            logger.info("Test report sent successfully")
        else:
            logger.warning("Failed to send test report")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='API Test Runner')
    parser.add_argument('--commit-range', default='HEAD~1..HEAD', 
                       help='Git commit range to analyze (default: HEAD~1..HEAD)')
    parser.add_argument('--config', default='.env', 
                       help='Configuration file path (default: .env)')
    parser.add_argument('--git-repo-path', default=None,
                       help='Git repository path to analyze (overrides .env setting)')
    
    args = parser.parse_args()
    
    # Set environment file if specified
    if args.config and Path(args.config).exists():
        os.environ['ENV_FILE'] = args.config
    
    # Override git repo path if specified via command line
    if args.git_repo_path:
        os.environ['GIT_REPO_PATH'] = args.git_repo_path
    
    # Create and run test runner
    runner = TestRunner(git_repo_path=args.git_repo_path)
    success = runner.run(args.commit_range)
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()