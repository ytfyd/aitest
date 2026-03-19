import json
import yaml
from typing import Dict, List, Any, Optional
from pathlib import Path


class TestCaseGenerator:
    """
    测试用例生成器类
    
    功能：基于API规范和检测到的代码变更自动生成测试用例
    支持生成正向测试、负向测试和性能测试用例
    
    特性：
    - 自动解析API端点信息
    - 生成多种类型的测试用例模板
    - 支持自定义测试数据生成
    - 可扩展的测试模板系统
    """
    
    def __init__(self, api_specs: Optional[Dict[str, Any]] = None):
        """
        初始化测试用例生成器
        
        参数：
            api_specs: API规范字典，包含端点、方法、参数等信息
        """
        self.api_specs = api_specs or {}
        self.test_templates = self._load_test_templates()
    
    def _load_test_templates(self) -> Dict[str, str]:
        """
        加载测试用例模板
        
        返回：
            包含正向、负向、性能测试模板的字典
        """
        return {
            "positive": """
@pytest.mark.positive
@pytest.mark.smoke
def test_{endpoint_name}_positive():
    \"\"\"测试 {method} {path} - 正向测试用例\"\"\"
    
    # 准备测试数据
    test_data = {test_data}
    
    # 发起API请求
    response = api_client.{method}('{path}', data=test_data)
    
    # 验证响应
    data = api_client.validate_response(response, {expected_status})
    
    # 断言响应结构
    assert 'requestId' in data
    {additional_assertions}
""",
            
            "negative": """
@pytest.mark.negative
@pytest.mark.regression
def test_{endpoint_name}_negative_{scenario}():
    \"\"\"测试 {method} {path} - 负向测试用例: {scenario}\"\"\"
    
    # 准备无效的测试数据
    test_data = {test_data}
    
    # 发起API请求
    response = api_client.{method}('{path}', data=test_data)
    
    # 验证错误响应
    assert response.status_code == {expected_status}
    
    # 断言错误结构
    error_data = response.json()
    assert 'errorCode' in error_data
    assert 'message' in error_data
""",
            
            "performance": """
@pytest.mark.performance
def test_{endpoint_name}_performance():
    \"\"\"测试 {method} {path} - 性能测试\"\"\"
    
    # 准备测试数据
    test_data = {test_data}
    
    # 测量响应时间
    import time
    start_time = time.time()
    
    response = api_client.{method}('{path}', data=test_data)
    
    end_time = time.time()
    response_time = end_time - start_time
    
    # 验证响应
    data = api_client.validate_response(response, {expected_status})
    
    # 断言性能要求
    assert response_time < {max_response_time}, "响应时间超过限制"
"""
        }
    
    def generate_test_cases(self, endpoints: List[Dict[str, str]]) -> Dict[str, List[str]]:
        """
        为给定的API端点生成测试用例
        
        参数：
            endpoints: API端点列表，每个端点包含method和path信息
            
        返回：
            包含正向、负向、性能测试用例的字典
        """
        test_cases = {"positive": [], "negative": [], "performance": []}
        
        for endpoint in endpoints:
            method = endpoint['method']
            path = endpoint['path']
            endpoint_name = self._sanitize_endpoint_name(path)
            
            # 生成正向测试用例
            positive_test = self._generate_positive_test(endpoint_name, method, path)
            if positive_test:
                test_cases["positive"].append(positive_test)
            
            # 生成负向测试用例
            negative_tests = self._generate_negative_tests(endpoint_name, method, path)
            test_cases["negative"].extend(negative_tests)
            
            # 生成性能测试用例
            performance_test = self._generate_performance_test(endpoint_name, method, path)
            if performance_test:
                test_cases["performance"].append(performance_test)
        
        return test_cases
    
    def _sanitize_endpoint_name(self, path: str) -> str:
        """
        将API端点路径转换为有效的Python函数名
        
        参数：
            path: API路径，如 "/auth/sms-code"
            
        返回：
            有效的Python函数名，如 "auth_sms_code"
        """
        # 移除首尾斜杠并替换特殊字符
        name = path.strip('/').replace('/', '_').replace('-', '_').replace('{', '').replace('}', '')
        # 移除剩余的非字母数字字符
        name = ''.join(c if c.isalnum() or c == '_' else '' for c in name)
        return name.lower()
    
    def _generate_positive_test(self, endpoint_name: str, method: str, path: str) -> Optional[str]:
        """
        生成正向测试用例
        
        参数：
            endpoint_name: 端点名称
            method: HTTP方法
            path: API路径
            
        返回：
            正向测试用例代码，如果无法生成则返回None
        """
        # 根据端点规范获取测试数据
        test_data = self._get_test_data(method, path, "positive")
        
        if not test_data:
            return None
        
        template = self.test_templates["positive"]
        # 确保方法名为小写字符串
        method_lower = method.lower() if isinstance(method, str) else str(method).lower()
        
        return template.format(
            endpoint_name=endpoint_name,
            method=method_lower,  # 使用小写方法名
            path=path,
            test_data=test_data,
            expected_status=200,
            additional_assertions=self._get_additional_assertions(method, path)
        )
    
    def _generate_negative_tests(self, endpoint_name: str, method: str, path: str) -> List[str]:
        """生成负向测试用例"""
        negative_scenarios = self._get_negative_scenarios(method, path)
        tests = []
        
        # 确保方法名为小写
        method_lower = method
        if isinstance(method, str):
            method_lower = method.lower()
        
        for scenario, scenario_data in negative_scenarios.items():
            template = self.test_templates["negative"]
            test = template.format(
                endpoint_name=endpoint_name,
                method=method_lower,  # 使用小写方法名
                path=path,
                scenario=scenario,
                test_data=scenario_data["data"],
                expected_status=scenario_data["status"]
            )
            tests.append(test)
        
        return tests
    
    def _generate_performance_test(self, endpoint_name: str, method: str, path: str) -> Optional[str]:
        """生成性能测试用例"""
        test_data = self._get_test_data(method, path, "positive")
        
        if not test_data:
            return None
        
        template = self.test_templates["performance"]
        # 确保方法名为小写字符串
        method_lower = method.lower() if isinstance(method, str) else str(method).lower()
        
        return template.format(
            endpoint_name=endpoint_name,
            method=method_lower,  # 使用小写方法名
            path=path,
            test_data=test_data,
            expected_status=200,
            max_response_time=1.0  # 1 second max response time
        )
    
    def _get_test_data(self, method: str, path: str, test_type: str) -> str:
        """
        根据端点获取适当的测试数据
        
        参数：
            method: HTTP方法
            path: API路径
            test_type: 测试类型（positive/negative/performance）
            
        返回：
            测试数据的字符串表示
        """
        # 基于PRD规范生成测试数据
        if path == "/auth/sms-code" and method == "POST":
            return json.dumps({"phone": "13800138000", "deviceId": "web-test-001"})
        
        elif path == "/auth/login-sms" and method == "POST":
            return json.dumps({
                "phone": "13800138000", 
                "smsCode": "123456", 
                "agreePolicy": True, 
                "deviceId": "web-test-001"
            })
        
        elif path == "/home/overview" and method == "GET":
            return "None"  # GET请求通常不需要请求体
        
        # 默认返回空字典
        return "{}"
    
    def _get_negative_scenarios(self, method: str, path: str) -> Dict[str, Dict[str, Any]]:
        """Get negative test scenarios based on endpoint"""
        scenarios = {}
        
        if path == "/auth/sms-code" and method == "POST":
            scenarios = {
                "invalid_phone": {
                    "data": "{\"phone\": \"123\", \"deviceId\": \"web-test-001\"}",
                    "status": 400
                },
                "missing_phone": {
                    "data": "{\"deviceId\": \"web-test-001\"}",
                    "status": 400
                }
            }
        
        elif path == "/auth/login-sms" and method == "POST":
            scenarios = {
                "wrong_code": {
                    "data": "{\"phone\": \"13800138000\", \"smsCode\": \"000000\", \"agreePolicy\": true, \"deviceId\": \"web-test-001\"}",
                    "status": 400
                },
                "no_policy": {
                    "data": "{\"phone\": \"13800138000\", \"smsCode\": \"123456\", \"agreePolicy\": false, \"deviceId\": \"web-test-001\"}",
                    "status": 400
                }
            }
        
        elif path == "/home/overview" and method == "GET":
            scenarios = {
                "unauthorized": {
                    "data": "None",
                    "status": 401
                }
            }
        
        return scenarios
    
    def _get_additional_assertions(self, method: str, path: str) -> str:
        """Get additional assertions based on endpoint"""
        if path == "/auth/sms-code" and method == "POST":
            return "assert 'requestId' in data\n    assert 'cooldownSeconds' in data"
        
        elif path == "/auth/login-sms" and method == "POST":
            return "assert 'accessToken' in data\n    assert 'tokenExpireAt' in data\n    assert 'user' in data\n    assert 'userId' in data['user']"
        
        elif path == "/home/overview" and method == "GET":
            return "assert 'shortcuts' in data\n    assert 'schedules' in data\n    assert 'courses' in data\n    assert 'tabs' in data"
        
        return ""
    
    def write_test_file(self, test_cases: Dict[str, List[str]], file_path: str):
        """Write generated test cases to a file"""
        content = """import pytest
from utils.api_client import api_client

"""
        
        # Add imports
        content += """
# Auto-generated test cases for API endpoints
# Generated by API Test Framework

"""
        
        # Add test cases
        for category, tests in test_cases.items():
            if tests:
                content += f"\n# {category.upper()} TEST CASES\n"
                for test in tests:
                    content += test + "\n"
        
        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Generated test file: {file_path}")
        print(f"Total test cases: {sum(len(tests) for tests in test_cases.values())}")