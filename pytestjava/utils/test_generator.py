import json
import re
from typing import Dict, List, Any, Optional
from pathlib import Path
from utils.swagger_client import swagger_client


class TestCaseGenerator:
    """测试用例生成器类"""
    
    def __init__(self, api_specs: Optional[Dict[str, Any]] = None):
        self.api_specs = api_specs or {}
        self.test_templates = self._load_test_templates()
    
    def _load_test_templates(self) -> Dict[str, str]:
        return {
            "positive": """
@pytest.mark.positive
@pytest.mark.smoke
def test_{endpoint_name}_positive():
    \"\"\"测试 {method} {path} - 正向测试用例\"\"\"
    
    # 准备测试数据
    test_data = {test_data}
    
    # 发起API请求
    response = api_client.{method}('{path}'{params})
    
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
    
    response = api_client.{method}('{path}'{params})
    
    end_time = time.time()
    response_time = end_time - start_time
    
    # 验证响应
    data = api_client.validate_response(response, {expected_status})
    
    # 断言性能要求
    assert response_time < {max_response_time}, "响应时间超过限制"
"""
        }
    
    def generate_test_cases(self, endpoints: List[Dict[str, str]]) -> Dict[str, List[str]]:
        test_cases = {"positive": [], "negative": [], "performance": []}
        
        for endpoint in endpoints:
            method = endpoint['method']
            path = endpoint['path']
            
            endpoint_info = swagger_client.get_endpoint_info(path, method)
            real_path = path
            if endpoint_info:
                real_path = endpoint_info["full_path"]
            
            test_data, path_params, query_params = self._get_test_data_from_swagger(
                real_path, method
            )
            
            final_path = self._replace_path_params(real_path, path_params)
            
            endpoint_name = self._sanitize_endpoint_name(final_path)
            
            positive_test = self._generate_positive_test(
                endpoint_name, method, final_path, test_data, query_params
            )
            if positive_test:
                test_cases["positive"].append(positive_test)
            
            negative_tests = self._generate_negative_tests(
                endpoint_name, method, final_path, test_data
            )
            test_cases["negative"].extend(negative_tests)
            
            performance_test = self._generate_performance_test(
                endpoint_name, method, final_path, test_data, query_params
            )
            if performance_test:
                test_cases["performance"].append(performance_test)
        
        return test_cases
    
    def _get_test_data_from_swagger(self, path: str, method: str) -> tuple:
        """从 Swagger 文档获取测试数据"""
        endpoint_info = swagger_client.get_endpoint_info(path, method)
        
        test_data = {}
        path_params = {}
        query_params = {}
        
        if not endpoint_info:
            return test_data, path_params, query_params
        
        parameters = endpoint_info.get("parameters", [])
        
        for param in parameters:
            param_name = param.get("name")
            param_in = param.get("in")
            schema = param.get("schema", {})
            param_type = schema.get("type", "string")
            param_format = schema.get("format", "")
            description = param.get("description", "")
            
            value = self._generate_value_by_type(
                param_name, param_type, param_format, schema, description
            )
            
            if param_in == "query":
                query_params[param_name] = value
                test_data[param_name] = value
            elif param_in == "path":
                path_params[param_name] = value
        
        request_body = endpoint_info.get("requestBody")
        if request_body:
            content = request_body.get("content", {})
            if "application/json" in content:
                schema_ref = content["application/json"].get("schema", {}).get("$ref", "")
                if "LoginBody" in schema_ref:
                    test_data["username"] = "admin"
                    test_data["password"] = "admin123"
        
        return test_data, path_params, query_params
    
    def _generate_value_by_type(self, name: str, type_name: str, format_name: str, 
                                 schema: Dict, description: str) -> Any:
        """根据类型生成测试值"""
        name_lower = name.lower()
        
        if type_name == "integer":
            if "id" in name_lower:
                return 1
            if "page" in name_lower:
                return 1
            if "size" in name_lower or "limit" in name_lower:
                return 10
            return 1
        
        if type_name == "string":
            if format_name == "date-time" or "time" in name_lower or "date" in name_lower:
                return "2024-01-01T00:00:00"
            if "key" in name_lower:
                return "test_key"
            if "name" in name_lower:
                return "test_name"
            if "code" in name_lower:
                return "test_code"
            if "value" in name_lower:
                return "test_value"
            if "type" in name_lower:
                return "test_type"
            if "status" in name_lower:
                return "0"
            if "phone" in name_lower or "mobile" in name_lower:
                return "13800138000"
            if "email" in name_lower:
                return "test@example.com"
            if "url" in name_lower or "link" in name_lower:
                return "http://example.com"
            if "ids" in name_lower:
                return "1"
            return "test"
        
        if type_name == "boolean":
            return True
        
        if type_name == "array":
            return []
        
        if type_name == "object":
            return {}
        
        return None
    
    def _replace_path_params(self, path: str, path_params: Dict) -> str:
        """替换路径参数"""
        result = path
        for param_name, value in path_params.items():
            result = result.replace(f"{{{param_name}}}", str(value))
        return result
    
    def _sanitize_endpoint_name(self, path: str) -> str:
        name = path.strip('/').replace('/', '_').replace('-', '_').replace('{', '').replace('}', '')
        name = ''.join(c if c.isalnum() or c == '_' else '' for c in name)
        return name.lower()
    
    def _generate_positive_test(self, endpoint_name: str, method: str, path: str, 
                                 test_data: Dict, query_params: Dict) -> Optional[str]:
        method_lower = method.lower() if isinstance(method, str) else str(method).lower()
        
        params_str = ""
        if query_params:
            params_str = f", params={json.dumps(query_params)}"
        
        test_data_str = json.dumps(test_data) if test_data else "{}"
        
        template = self.test_templates["positive"]
        
        return template.format(
            endpoint_name=endpoint_name,
            method=method_lower,
            path=path,
            test_data=test_data_str,
            params=params_str,
            expected_status=200,
            additional_assertions=self._get_additional_assertions(method, path)
        )
    
    def _generate_negative_tests(self, endpoint_name: str, method: str, path: str, 
                                  test_data: Dict) -> List[str]:
        negative_scenarios = self._get_negative_scenarios(method, path)
        tests = []
        
        method_lower = method.lower() if isinstance(method, str) else str(method).lower()
        
        for scenario, scenario_data in negative_scenarios.items():
            template = self.test_templates["negative"]
            test = template.format(
                endpoint_name=endpoint_name,
                method=method_lower,
                path=path,
                scenario=scenario,
                test_data=scenario_data["data"],
                expected_status=scenario_data["status"]
            )
            tests.append(test)
        
        return tests
    
    def _generate_performance_test(self, endpoint_name: str, method: str, path: str,
                                   test_data: Dict, query_params: Dict) -> Optional[str]:
        method_lower = method.lower() if isinstance(method, str) else str(method).lower()
        
        params_str = ""
        if query_params:
            params_str = f", params={json.dumps(query_params)}"
        
        test_data_str = json.dumps(test_data) if test_data else "{}"
        
        template = self.test_templates["performance"]
        
        return template.format(
            endpoint_name=endpoint_name,
            method=method_lower,
            path=path,
            test_data=test_data_str,
            params=params_str,
            expected_status=200,
            max_response_time=1.0
        )
    
    def _get_negative_scenarios(self, method: str, path: str) -> Dict[str, Dict[str, Any]]:
        scenarios = {}
        
        if "/auth/" in path:
            scenarios = {
                "unauthorized": {
                    "data": "{}",
                    "status": 401
                }
            }
        
        return scenarios
    
    def _get_additional_assertions(self, method: str, path: str) -> str:
        if "/auth/login" in path:
            return "assert 'accessToken' in data"
        return ""
    
    def write_test_file(self, test_cases: Dict[str, List[str]], file_path: str):
        content = """import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.api_client import api_client

"""

        content += """
# Auto-generated test cases for API endpoints
# Generated by API Test Framework

"""

        for category, tests in test_cases.items():
            if tests:
                content += f"\n# {category.upper()} TEST CASES\n"
                for test in tests:
                    content += test + "\n"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"Generated test file: {file_path}")
        print(f"Total test cases: {sum(len(tests) for tests in test_cases.values())}")
