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
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {{"raw_text": response.text}}
    save_response('test_{endpoint_name}_positive', {{
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': {test_data}
    }})
    
    # 验证响应
    data = api_client.validate_response(response, {expected_status})
    
    # 断言响应结构 - 检查业务响应码
    assert data.get('code') == 200, f"业务响应码错误: {{data.get('msg', 'Unknown error')}}"
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
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {{"raw_text": response.text}}
    save_response('test_{endpoint_name}_negative_{scenario}', {{
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': {test_data}
    }})
    
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
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {{"raw_text": response.text}}
    save_response('test_{endpoint_name}_performance', {{
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': {test_data},
        'response_time': response_time
    }})
    
    # 验证响应
    data = api_client.validate_response(response, {expected_status})
    
    # 断言业务响应码
    assert data.get('code') == 200, f"业务响应码错误: {{data.get('msg', 'Unknown error')}}"
    
    # 断言性能要求
    assert response_time < {max_response_time}, "响应时间超过限制"
"""
        }
    
    def generate_test_cases(self, endpoints: List[Dict[str, str]]) -> Dict[str, List[str]]:
        test_cases = {"positive": [], "negative": [], "performance": []}
        
        # Track generated test names to avoid duplicates
        generated_tests = set()
        
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
            
            # Generate positive test
            positive_test_name = f"test_{endpoint_name}_positive"
            if positive_test_name not in generated_tests:
                positive_test = self._generate_positive_test(
                    endpoint_name, method, final_path, test_data, query_params
                )
                if positive_test:
                    test_cases["positive"].append(positive_test)
                    generated_tests.add(positive_test_name)
            
            # Generate negative tests
            negative_tests = self._generate_negative_tests(
                endpoint_name, method, final_path, test_data
            )
            for test in negative_tests:
                # Extract test name from test code
                import re
                test_name_match = re.search(r'def\s+(test_\w+)\s*\(', test)
                if test_name_match:
                    test_name = test_name_match.group(1)
                    if test_name not in generated_tests:
                        test_cases["negative"].append(test)
                        generated_tests.add(test_name)
            
            # Generate performance test
            performance_test_name = f"test_{endpoint_name}_performance"
            if performance_test_name not in generated_tests:
                performance_test = self._generate_performance_test(
                    endpoint_name, method, final_path, test_data, query_params
                )
                if performance_test:
                    test_cases["performance"].append(performance_test)
                    generated_tests.add(performance_test_name)
        
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
                schema_info = content["application/json"].get("schema", {})
                schema_ref = schema_info.get("$ref", "")
                
                if "LoginBody" in schema_ref:
                    test_data["username"] = "admin"
                    test_data["password"] = "admin123"
                elif schema_ref:
                    schema_name = schema_ref.split("/")[-1]
                    body_data = swagger_client._generate_data_from_schema_ref(schema_name)
                    test_data.update(body_data)
        
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
        
        # Build params string for query parameters or body data
        params_str = ""
        if query_params:
            params_str = f", params={json.dumps(query_params)}"
        
        # For POST/PUT methods with body data, add data parameter
        data_str = ""
        if test_data and method_lower in ['post', 'put', 'patch']:
            data_str = f", data={json.dumps(test_data)}"
        
        test_data_str = json.dumps(test_data) if test_data else "{}"
        
        # Check if this is a login endpoint - needs special handling
        # Only match exact /login endpoint, not any endpoint containing 'login'
        is_login_endpoint = path.lower() == '/login' or path.lower().endswith('/login')
        
        if is_login_endpoint:
            # Use a separate session for login endpoint to avoid auth header conflicts
            login_template = """
@pytest.mark.positive
@pytest.mark.smoke
def test_{endpoint_name}_positive():
    \"\"\"测试 {method} {path} - 正向测试用例\"\"\"
    
    # 准备测试数据
    test_data = {test_data}
    
    # 登录接口使用独立请求，避免认证header冲突
    import requests
    response = requests.{method}('{base_url}{path}', json={test_data_str})
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {{"raw_text": response.text}}
    save_response('test_{endpoint_name}_positive', {{
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': {test_data}
    }})
    
    # 验证响应
    assert response.status_code == 200, f"HTTP状态码错误: {{response.status_code}}"
    data = response.json()
    
    # 断言业务响应码
    assert data.get('code') == 200, f"业务响应码错误: {{data.get('msg', 'Unknown error')}}"
    assert 'token' in data, "登录响应缺少token字段"
"""
            from config.settings import settings
            return login_template.format(
                endpoint_name=endpoint_name,
                method=method_lower,
                path=path,
                test_data=test_data_str,
                test_data_str=test_data_str,
                base_url=settings.api_base_url
            )
        
        template = self.test_templates["positive"]
        
        return template.format(
            endpoint_name=endpoint_name,
            method=method_lower,
            path=path,
            test_data=test_data_str,
            params=params_str + data_str,
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
        
        # Build params string for query parameters or body data
        params_str = ""
        if query_params:
            params_str = f", params={json.dumps(query_params)}"
        
        # For POST/PUT methods with body data, add data parameter
        data_str = ""
        if test_data and method_lower in ['post', 'put', 'patch']:
            data_str = f", data={json.dumps(test_data)}"
        
        test_data_str = json.dumps(test_data) if test_data else "{}"
        
        # Check if this is a login endpoint - needs special handling
        is_login_endpoint = '/login' in path.lower()
        
        if is_login_endpoint:
            # Use a separate session for login endpoint to avoid auth header conflicts
            from config.settings import settings
            login_perf_template = """
@pytest.mark.performance
def test_{endpoint_name}_performance():
    \"\"\"测试 {method} {path} - 性能测试\"\"\"
    
    # 准备测试数据
    test_data = {test_data}
    
    # 登录接口使用独立请求，避免认证header冲突
    import time
    import requests
    start_time = time.time()
    response = requests.{method}('{base_url}{path}', json={test_data_str})
    end_time = time.time()
    response_time = end_time - start_time
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {{"raw_text": response.text}}
    save_response('test_{endpoint_name}_performance', {{
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': {test_data},
        'response_time': response_time
    }})
    
    # 验证响应
    assert response.status_code == 200, f"HTTP状态码错误: {{response.status_code}}"
    data = response.json()
    
    # 断言业务响应码
    assert data.get('code') == 200, f"业务响应码错误: {{data.get('msg', 'Unknown error')}}"
    
    # 断言性能要求
    assert response_time < 1.0, "响应时间超过限制"
"""
            return login_perf_template.format(
                endpoint_name=endpoint_name,
                method=method_lower,
                path=path,
                test_data=test_data_str,
                test_data_str=test_data_str,
                base_url=settings.api_base_url
            )
        
        template = self.test_templates["performance"]
        
        return template.format(
            endpoint_name=endpoint_name,
            method=method_lower,
            path=path,
            test_data=test_data_str,
            params=params_str + data_str,
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
        else:
            # For POST/PUT/PATCH endpoints - test missing required fields
            if method.upper() in ['POST', 'PUT', 'PATCH']:
                scenarios["missing_required_fields"] = {
                    "data": "{}",
                    "status": 400
                }
            
            # For GET endpoints - test invalid parameters
            if method.upper() == 'GET':
                scenarios["invalid_params"] = {
                    "data": '{"invalid_param": "invalid_value"}',
                    "status": 400
                }
            
            # For DELETE endpoints - test invalid ID or unauthorized access
            if method.upper() == 'DELETE':
                scenarios["unauthorized"] = {
                    "data": "{}",
                    "status": 403
                }
            
            # For endpoints with path parameters - test invalid ID
            if '{' in path and '}' in path:
                scenarios["invalid_id"] = {
                    "data": "{}",
                    "status": 404
                }
        
        return scenarios
    
    def _get_additional_assertions(self, method: str, path: str) -> str:
        if "/auth/login" in path:
            return "assert 'accessToken' in data"
        return ""
    
    def write_test_file(self, test_cases: Dict[str, List[str]], file_path: str):
        content = """import pytest
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.api_client import api_client


# Response storage file
RESPONSE_FILE = Path(__file__).parent.parent.parent / "test-reports" / "responses.json"


def save_response(test_name: str, response_data: dict):
    \"\"\"Save response data to file for reporting\"\"\"
    try:
        RESPONSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        responses = {}
        if RESPONSE_FILE.exists():
            with open(RESPONSE_FILE, 'r', encoding='utf-8') as f:
                responses = json.load(f)
        
        responses[test_name] = response_data
        
        with open(RESPONSE_FILE, 'w', encoding='utf-8') as f:
            json.dump(responses, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Warning: Failed to save response: {e}")


# Authentication fixture - login before running tests
@pytest.fixture(scope="session", autouse=True)
def setup_authentication():
    \"\"\"Auto-login before running tests\"\"\"
    # Clear previous responses
    if RESPONSE_FILE.exists():
        os.remove(RESPONSE_FILE)
    
    api_client.login(username="admin", password="admin123")
    yield
    api_client.clear_auth()


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
