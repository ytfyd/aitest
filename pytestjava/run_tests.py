#!/usr/bin/env python3
"""
API自动化测试框架主程序
自动检测API变更、生成测试用例、执行测试并发送报告
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
from utils.git_manager import GitManager, get_git_manager


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TestRunner:
    """测试运行器主类"""
    
    def __init__(self, git_repo_path: str = None, auto_pull: bool = None, environment: str = None):
        repo_path = git_repo_path or os.getenv("GIT_REPO_PATH", ".")
        self.test_generator = TestCaseGenerator()
        self.wechat_notifier = WeChatWorkNotifier()
        self.html_report_generator = HTMLReportGenerator()
        self.test_results = {}
        self.failed_tests_file = Path(__file__).parent / "test-reports" / "failed_tests.json"
        
        # 初始化Git管理器（新增）
        try:
            self.git_manager = GitManager(
                repo_path=repo_path,
                environment=environment or os.getenv("ENVIRONMENT", "test")
            )
            logger.info(f"Git管理器初始化成功 (环境: {self.git_manager.environment.value})")
            
            # 如果启用自动拉取或通过参数指定，则执行自动拉取
            should_auto_pull = auto_pull if auto_pull is not None else (
                os.getenv("GIT_AUTO_PULL", "false").lower() == "true"
            )
            
            if should_auto_pull:
                logger.info("🤖 检测到自动拉取模式，开始执行...")
                success, message = self.git_manager.auto_pull_if_configured()
                if not success:
                    logger.warning(f"⚠️ 自动拉取部分失败:\n{message}")
                    # 不阻塞测试流程，仅记录警告
                else:
                    logger.info(f"✅ 自动拉取成功完成")
                    
        except Exception as e:
            logger.warning(f"Git管理器初始化失败: {e}，将使用基础Git功能")
            self.git_manager = None
        
        # 初始化增强版影响分析器（基于JCCI框架）
        try:
            self.enhanced_analyzer = EnhancedImpactAnalyzer(repo_path, repo_path)
            self.code_change_detector = CodeChangeDetector(repo_path, repo_path)
            logger.info("增强版影响分析器初始化成功（基于JCCI框架）")
        except Exception as e:
            logger.warning(f"增强版分析器初始化失败: {e}")
            self.enhanced_analyzer = None
            self.code_change_detector = None
    
    def run(self, commit_range: str = "HEAD~1..HEAD") -> bool:
        """执行完整的测试工作流程"""
        logger.info("开始API自动化测试工作流程")
        
        try:
            logger.info("步骤1: 检测API变更")
            changes = self.detect_changes(commit_range)
            
            if not changes['affected_endpoints']:
                logger.info("未检测到API接口变更，跳过测试生成")
                self.wechat_notifier.send_simple_message(
                    "API测试报告",
                    "✅ 本次提交未检测到API接口变更，跳过冒烟测试"
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
                "API测试报告 - 执行失败",
                f"❌ 测试执行失败: {str(e)}"
            )
            return False
    
    def detect_changes(self, commit_range: str) -> dict:
        """使用JCCI增强版分析器检测指定提交范围内的API变更"""
        if self.enhanced_analyzer:
            try:
                logger.info("使用JCCI增强版影响分析器进行变更检测")
                
                # 从增强版分析器获取受影响的接口
                affected_endpoints = self.enhanced_analyzer.get_affected_endpoints_for_testing(commit_range)
                
                # 获取变更摘要
                change_summary = self.enhanced_analyzer.get_change_summary(commit_range)
                
                # 从代码变更检测器获取变更文件列表
                changed_files = []
                if self.code_change_detector:
                    changed_files = self.code_change_detector.get_changed_files(commit_range)
                
                logger.info(f"JCCI分析检测到 {len(affected_endpoints)} 个受影响的接口")
                for endpoint in affected_endpoints:
                    logger.info(f"  - {endpoint['method']} {endpoint['path']} (影响类型: {endpoint['impact_type']}, 置信度: {endpoint['confidence']:.2f})")
                
                # 保存详细分析报告
                try:
                    reports_dir = Path(__file__).parent / "test-reports"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    analysis_file = reports_dir / "impact_analysis.json"
                    self.enhanced_analyzer.save_analysis_report(str(analysis_file), commit_range)
                    logger.info(f"详细分析报告已保存至 {analysis_file}")
                except Exception as e:
                    logger.warning(f"保存分析报告失败: {e}")
                
                return {
                    'changed_files': changed_files,
                    'affected_endpoints': affected_endpoints,
                    'change_summary': change_summary
                }
            except Exception as e:
                logger.error(f"增强版分析器执行失败: {e}")
                return {
                    'changed_files': [],
                    'affected_endpoints': [],
                    'change_summary': {}
                }
        
        logger.warning("增强版分析器不可用")
        return {
            'changed_files': [],
            'affected_endpoints': [],
            'change_summary': {}
        }
    
    def generate_tests(self, endpoints: list) -> str:
        """为受影响的接口生成测试用例"""
        tests_dir = Path(__file__).parent / "tests" / "generated"
        tests_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理旧的测试文件
        self._clean_old_test_files(tests_dir)
        
        # 加载上次运行失败的测试用例
        failed_endpoints = self._load_failed_tests()
        
        # 合并当前接口与失败接口（去重）
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
        
        logger.info(f"正在为 {len(endpoints)} 个新接口 + {len(failed_endpoints)} 个失败接口 = 共 {len(all_endpoints)} 个接口生成测试")
        
        test_cases = self.test_generator.generate_test_cases(all_endpoints)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        test_file = tests_dir / f"test_generated_{timestamp}.py"
        
        self.test_generator.write_test_file(test_cases, str(test_file))
        
        return str(test_file)
    
    def execute_tests(self, test_file: str) -> dict:
        """使用pytest执行生成的测试"""
        cmd = [
            "pytest",
            test_file,
            "-v",
            "--tb=long"
        ]
        
        logger.info(f"执行命令: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            test_results = self._parse_test_results(result)
            
            logger.info(f"测试执行完成:")
            logger.info(f"  - 总数: {test_results['total_tests']}")
            logger.info(f"  - 通过: {test_results['passed_tests']}")
            logger.info(f"  - 失败: {test_results['failed_tests']}")
            logger.info(f"  - 跳过: {test_results['skipped_tests']}")
            
            # 保存失败的测试用例供下次运行使用
            self._save_failed_tests(test_results)
            
            return test_results
            
        except Exception as e:
            logger.error(f"测试执行失败: {e}")
            return {
                'total_tests': 0,
                'passed_tests': 0,
                'failed_tests': 0,
                'skipped_tests': 0,
                'failed_details': [{'name': '执行错误', 'error': str(e)}],
                'test_details': []
            }
    
    def _parse_test_results(self, result: subprocess.CompletedProcess) -> dict:
        """解析pytest输出，提取详细的测试结果"""
        output = result.stdout + result.stderr
        
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        # 使用字典避免重复
        test_details_dict = {}
        failed_details_dict = {}
        passed_details_dict = {}
        
        # 从测试文件中提取请求数据用于获取请求参数
        test_data_map = self._extract_test_data_from_file()
        
        # 从输出中解析汇总信息
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
            
            # 从测试会话输出中检测通过/失败的测试（如 tests/file.py::test_name PASSED）
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
        
        # 为失败的测试分配错误信息
        for test_name, fail in failed_details_dict.items():
            if test_name in error_messages:
                fail['error'] = error_messages[test_name]
            elif not fail['error']:
                fail['error'] = '连接超时或服务器未响应'
        
        # 从文件加载存储的响应数据
        responses_file = Path(__file__).parent / "test-reports" / "responses.json"
        stored_responses = {}
        if responses_file.exists():
            try:
                with open(responses_file, 'r', encoding='utf-8') as f:
                    stored_responses = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load responses: {e}")
        
        # 用实际响应数据更新测试详情
        for test_name, detail in test_details_dict.items():
            if test_name in stored_responses:
                resp_data = stored_responses[test_name]
                detail['response'] = json.dumps(resp_data.get('response', {}), ensure_ascii=False)
                if 'request_params' in resp_data:
                    detail['request_params'] = json.dumps(resp_data['request_params'], ensure_ascii=False)
        
        # 用实际响应数据更新通过的测试详情
        for test_name, detail in passed_details_dict.items():
            if test_name in stored_responses:
                resp_data = stored_responses[test_name]
                detail['response'] = json.dumps(resp_data.get('response', {}), ensure_ascii=False)
                if 'request_params' in resp_data:
                    detail['request_params'] = json.dumps(resp_data['request_params'], ensure_ascii=False)
        
        # 用实际响应数据更新失败的测试详情
        for test_name, detail in failed_details_dict.items():
            if test_name in stored_responses:
                resp_data = stored_responses[test_name]
                detail['response'] = json.dumps(resp_data.get('response', {}), ensure_ascii=False)
                if 'request_params' in resp_data:
                    detail['request_params'] = json.dumps(resp_data['request_params'], ensure_ascii=False)
        
        # 将字典转换为列表
        test_details = list(test_details_dict.values())
        failed_details = list(failed_details_dict.values())
        passed_details = list(passed_details_dict.values())
        
        # 使用从解析详情中获取的实际数量，而不是汇总行
        actual_total = len(test_details)
        actual_passed = len(passed_details)
        actual_failed = len(failed_details)
        actual_skipped = total_tests - actual_passed - actual_failed if total_tests > 0 else 0
        
        # 如果没有解析到详情但有汇总数量，则使用汇总数量
        if actual_total == 0 and total_tests > 0:
            logger.warning("No test details parsed, using summary counts")
            actual_total = total_tests
            actual_passed = passed_tests
            actual_failed = failed_tests
            actual_skipped = skipped_tests
        else:
            # 使用实际解析的数量
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
        """从生成的测试文件中提取测试数据"""
        test_data_map = {}
        
        try:
            # 查找最新生成的测试文件
            tests_dir = Path(__file__).parent / "tests" / "generated"
            test_files = list(tests_dir.glob("test_generated_*.py"))
            
            if not test_files:
                return test_data_map
            
            latest_file = max(test_files, key=lambda p: p.stat().st_mtime)
            
            with open(latest_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 解析测试函数以提取请求数据
            import re
            
            # 查找所有测试函数 - 改进的正则表达式模式
            test_pattern = r'def\s+(test_\w+)\s*\(\s*\)\s*:\s*"""(.*?)"""(.*?)\n\n\n|def\s+(test_\w+)\s*\(\s*\)\s*:\s*"""(.*?)"""(.*?)\Z'
            matches = re.findall(test_pattern, content, re.DOTALL)
            
            for match in matches:
                # 处理两种模式匹配组
                if match[0]:  # First pattern matched
                    test_name = match[0]
                    docstring = match[1]
                    func_body = match[2]
                else:  # Second pattern matched (last test)
                    test_name = match[3]
                    docstring = match[4]
                    func_body = match[5]
                
                # 从文档字符串中提取方法和路径
                method_match = re.search(r'(get|post|put|delete|patch).*?(/\S+)', docstring.lower())
                method = method_match.group(1).upper() if method_match else 'GET'
                path = method_match.group(2) if method_match else '/'
                
                # 从api_client调用中提取data参数
                # 在函数体中查找 data={...}
                data_match = re.search(r'api_client\.\w+\s*\(\s*[\'"][^\'"]+[\'"]\s*,\s*data\s*=\s*(\{[^}]+\})', func_body)
                if data_match:
                    request_params = data_match.group(1)
                else:
                    # 回退到test_data变量
                    test_data_match = re.search(r'test_data\s*=\s*(\{[^}]*\})', func_body)
                    request_params = test_data_match.group(1) if test_data_match else '{}'
                
                test_data_map[test_name] = {
                    'method': method,
                    'path': path,
                    'request_params': request_params,
                    'response': '待获取'  # 将在实际测试执行时填充
                }
        
        except Exception as e:
            logger.warning(f"Failed to extract test data: {e}")
        
        return test_data_map
    
    def generate_html_report(self, test_results: dict, changes: dict) -> str:
        """生成美观的HTML测试报告"""
        return self.html_report_generator.generate(test_results, changes)
    
    def _generate_report_image(self, report_path: str = None) -> str:
        """将HTML报告转换为图片用于企业微信通知
        
        参数:
            report_path: HTML报告文件路径（可选，未提供时使用默认值）
            
        返回:
            str: 生成的图片文件路径，如果转换失败则返回None
        """
        from utils.html_to_image import HTMLToImageConverter, FallbackImageGenerator
        
        try:
            if report_path is None:
                report_path = self.reports_dir / "test-report.html"
            
            report_path = Path(report_path)
            
            if not report_path.exists():
                logger.warning(f"HTML report not found: {report_path}")
                return None
            
            # 生成截图
            image_path = report_path.with_suffix('.png')
            
            converter = HTMLToImageConverter()
            converter.convert_to_image(report_path, image_path)
            
            if image_path.exists():
                logger.info(f"Report screenshot generated: {image_path}")
                return str(image_path)
            else:
                logger.warning("截图生成失败")
                
                # 尝试回退方案
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate report image: {e}")
            
            # 尝试基于PIL的回退方案
            try:
                fallback_image = self.reports_dir / "test-report-fallback.png"
                result = FallbackImageGenerator.generate_text_report_image(
                    getattr(self, '_last_test_results', {}), 
                    fallback_image
                )
                if result:
                    logger.info("生成了基于文本的回退报告图片")
                    return result
            except Exception as fallback_err:
                logger.error(f"Fallback image generation also failed: {fallback_err}")
            
            return None
    
    def send_notifications(self, test_results: dict, changes: dict):
        """发送测试结果到企业微信（包含报告截图）"""
        # 存储测试结果供潜在的回退使用
        self._last_test_results = test_results.copy()
        
        test_results.update({
            'changed_files': changes.get('changed_files', []),
            'affected_endpoints': changes.get('affected_endpoints', []),
            'commit_sha': settings.ci_commit_sha,
            'build_number': settings.ci_build_number,
            'timestamp': datetime.now().isoformat()
        })
        
        # 尝试生成并发送带图片的通知
        report_image_path = None
        report_html_path = None
        
        # 获取报告路径（从html_report_generator或默认值）
        reports_dir = Path(__file__).parent / "test-reports"
        html_report_path = reports_dir / "test-report.html"
        
        if html_report_path.exists():
            logger.info("正在生成报告截图用于通知...")
            report_image_path = self._generate_report_image(html_report_path)
            report_html_path = str(html_report_path) if html_report_path.exists() else None
        
        # 发送带图片和HTML文件的通知
        success = self.wechat_notifier.send_test_report(
            test_results, 
            report_image_path=report_image_path,
            report_html_path=report_html_path
        )
        
        if success:
            logger.info("测试报告发送成功")
        else:
            logger.warning("发送测试报告失败")
    
    def _clean_old_test_files(self, tests_dir: Path):
        """清理之前运行的旧测试文件"""
        try:
            test_files = list(tests_dir.glob("test_generated_*.py"))
            for test_file in test_files:
                test_file.unlink()
                logger.info(f"Removed old test file: {test_file}")
        except Exception as e:
            logger.warning(f"Failed to clean old test files: {e}")
    
    def _load_failed_tests(self) -> list:
        """加载上次运行的失败测试用例"""
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
        """保存失败测试用例供下次运行使用"""
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
    """主入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='API测试运行器', 
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="""
使用示例:
  python run_tests.py                              # 分析最近一次提交
  python run_tests.py --commit-range HEAD~5..HEAD  # 分析最近5次提交
  python run_tests.py --branch test-feature main   # 对比test-feature与main分支
  python run_tests.py --branch feature-xxx origin/main  # 对比本地分支与远程分支
  
Git管理功能（新增）:
  python run_tests.py --auto-pull                  # 自动拉取最新代码
  python run_tests.py --environment production      # 使用生产环境配置
  python run_tests.py --branch origin/test-feature origin/main \\
                   --auto-pull --git-repo-path ./campus-master
""")
    
    parser.add_argument('--commit-range', default='HEAD~1..HEAD', 
                       help='要分析的Git提交范围（默认: HEAD~1..HEAD）')
    parser.add_argument('--branch', nargs=2, metavar=('SOURCE', 'TARGET'),
                       help='比较两个分支（例如: --branch test-feature main）')
    parser.add_argument('--config', default='.env', 
                       help='配置文件路径（默认: .env）')
    parser.add_argument('--git-repo-path', default=None,
                       help='要分析的Git仓库路径（覆盖.env设置）')
    
    # 新增Git管理相关参数
    parser.add_argument('--auto-pull', action='store_true', default=None,
                       help='自动拉取最新代码（覆盖.env中的GIT_AUTO_PULL设置）')
    parser.add_argument('--no-auto-pull', action='store_true',
                       help='禁用自动拉取（即使.env中GIT_AUTO_PULL=true）')
    parser.add_argument('--environment', choices=['development', 'test', 'production'],
                       help='指定运行环境（加载对应的.env.{environment}配置文件）')
    parser.add_argument('--git-status', action='store_true',
                       help='显示Git仓库状态信息并退出')
    parser.add_argument('--force-sync', action='store_true',
                       help='强制同步到远程状态（git reset --hard，会丢失本地修改！）')
    
    args = parser.parse_args()
    
    if args.config and Path(args.config).exists():
        os.environ['ENV_FILE'] = args.config
    
    if args.git_repo_path:
        os.environ['GIT_REPO_PATH'] = args.git_repo_path
    
    # 设置环境模式（新增）
    if args.environment:
        os.environ['ENVIRONMENT'] = args.environment
        logger.info(f"🌍 环境模式: {args.environment}")
        
        # 加载特定环境的配置文件
        settings.load_environment_specific(args.environment)
    
    # 处理自动拉取参数（新增）
    auto_pull = None
    if args.auto_pull:
        auto_pull = True
        logger.info("✅ 已启用自动拉取（命令行参数）")
    elif args.no_auto_pull:
        auto_pull = False
        logger.info("❌ 已禁用自动拉取（命令行参数）")
    
    # 如果只是查看Git状态，则显示后退出
    if args.git_status:
        repo_path = args.git_repo_path or os.getenv("GIT_REPO_PATH", ".")
        try:
            git_mgr = GitManager(repo_path=repo_path)
            git_mgr.print_summary()
            sys.exit(0)
        except Exception as e:
            print(f"❌ 获取Git状态失败: {e}")
            sys.exit(1)
    
    # 处理强制同步参数（新增）
    if args.force_sync:
        os.environ['GIT_FORCE_SYNC'] = 'true'
        logger.warning("⚠️  已启用强制同步模式（将使用git reset --hard）")
    
    commit_range = args.commit_range
    if args.branch:
        source_branch, target_branch = args.branch
        commit_range = f"{target_branch}..{source_branch}"
        logger.info(f"分支对比模式: {source_branch} vs {target_branch}")
        logger.info(f"转换为提交范围: {commit_range}")
        
        is_remote_branch = '/' in source_branch or '/' in target_branch
        if is_remote_branch:
            import subprocess
            repo_path = args.git_repo_path or os.getenv("GIT_REPO_PATH", ".")
            logger.info(f"检测到远程分支，正在执行 'git fetch' 以更新远程引用...")
            try:
                fetch_result = subprocess.run(
                    ['git', 'fetch', '--all'],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if fetch_result.returncode == 0:
                    logger.info(f"Git fetch 执行成功")
                else:
                    logger.warning(f"Git fetch 警告: {fetch_result.stderr}")
            except subprocess.TimeoutExpired:
                logger.warning("Git fetch 超时（60秒），使用缓存的远程引用")
            except Exception as e:
                logger.warning(f"Git fetch 失败: {e}，使用缓存的远程引用")
    
    runner = TestRunner(
        git_repo_path=args.git_repo_path,
        auto_pull=auto_pull,
        environment=args.environment
    )
    success = runner.run(commit_range)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
