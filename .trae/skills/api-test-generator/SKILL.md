---
name: "api-test-generator"
description: "Generates pytest API test cases from Swagger/OpenAPI documentation. Invoke when user needs to create automated API tests or when Java code changes are detected in Spring Boot projects."
---

# API Test Generator

This skill generates comprehensive pytest-based API test cases by analyzing Swagger/OpenAPI documentation and Java controller code.

## When to Invoke

- When user requests API test case generation
- When Java controller files are modified
- When Swagger documentation is updated
- When setting up automated API testing for a project

## Test Generation Rules

### 1. Test Case Types

Generate three types of test cases for each endpoint:

#### Positive Tests (`@pytest.mark.positive`, `@pytest.mark.smoke`)
- Test successful API calls with valid data
- Verify response status code is 200
- Validate response structure contains expected fields

#### Negative Tests (`@pytest.mark.negative`, `@pytest.mark.regression`)
- Test API calls with invalid/missing data
- Test unauthorized access scenarios
- Verify appropriate error responses (400, 401, 403, 404)

#### Performance Tests (`@pytest.mark.performance`)
- Measure API response time
- Assert response time is under threshold (default: 1 second)

### 2. Test Data Generation

#### From Swagger Schema
- Extract `example` values from Swagger schema properties
- For `LoginBody`, use: `{"username": "admin", "password": "admin123", "code": "1234", "uuid": "uuid-123456"}`

#### Type-Based Generation
| Type | Format | Example Value |
|------|--------|---------------|
| integer | - | 1 |
| integer | page | 1 |
| integer | size/limit | 10 |
| string | date-time | "2024-01-01T00:00:00" |
| string | name | "test_name" |
| string | key | "test_key" |
| string | code | "test_code" |
| string | value | "test_value" |
| string | type | "test_type" |
| string | status | "0" |
| string | phone/mobile | "13800138000" |
| string | email | "test@example.com" |
| string | url/link | "http://example.com" |
| string | ids | "1" |
| boolean | - | true |
| array | - | [] |
| object | - | {} |

#### Path Parameter Replacement
- Replace `{id}` with `1`
- Replace `{userName}` with `"test_user"`
- Replace `{infoIds}` with `"1"`

### 3. Request Building

#### GET Requests
```python
# With query parameters
response = api_client.get('/api/users', params={"page": 1, "size": 10})

# With path parameters (already replaced)
response = api_client.get('/api/users/1')
```

#### POST/PUT Requests
```python
# With JSON body
response = api_client.post('/api/login', data={"username": "admin", "password": "admin123"})
```

#### DELETE Requests
```python
response = api_client.delete('/api/users/1')
```

### 4. Response Validation

#### Success Response (200)
```python
data = api_client.validate_response(response, 200)

# Store response for reporting
try:
    resp_json = response.json()
except:
    resp_json = {"raw_text": response.text}
save_response('test_endpoint_name_positive', {
    'status_code': response.status_code,
    'response': resp_json,
    'request_params': test_data
})

# Assert business response code - CRITICAL
assert data.get('code') == 200, f"业务响应码错误: {data.get('msg', 'Unknown error')}"
```

#### Error Response (4xx)
```python
assert response.status_code == 400  # or 401, 403, 404
error_data = response.json()
assert 'errorCode' in error_data
assert 'message' in error_data
```

### 5. Special Endpoint Handling

#### Login Endpoint (`/login`) - CRITICAL

**IMPORTANT**: Login endpoints MUST use independent requests to avoid Authorization header conflicts.

```python
@pytest.mark.positive
@pytest.mark.smoke
def test_login_positive():
    """测试 POST /login - 正向测试用例"""
    
    # Prepare test data
    test_data = {"username": "admin", "password": "admin123"}
    
    # Use independent request for login endpoint to avoid auth header conflicts
    import requests
    response = requests.post('http://localhost:8160/login', json=test_data)
    
    # Store response for reporting
    try:
        resp_json = response.json()
    except:
        resp_json = {"raw_text": response.text}
    save_response('test_login_positive', {
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': test_data
    })
    
    # Validate response
    assert response.status_code == 200, f"HTTP状态码错误: {response.status_code}"
    data = response.json()
    
    # Assert business response code
    assert data.get('code') == 200, f"业务响应码错误: {data.get('msg', 'Unknown error')}"
    assert 'token' in data, "登录响应缺少token字段"
```

**Why**: Login endpoints return 403 error when called with existing Authorization header.

#### File Upload Endpoints
- Use `files` parameter with test file
- Set `content_type` to `multipart/form-data`

#### Paginated Endpoints
- Include `page` and `size` in query params
- Assert response contains `list`, `total`, `pageNum`, `pageSize`

### 6. Test File Structure

```python
import pytest
import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.api_client import api_client


# Response storage file
RESPONSE_FILE = Path(__file__).parent.parent.parent / "test-reports" / "responses.json"


def save_response(test_name: str, response_data: dict):
    """Save response data to file for reporting"""
    try:
        RESPONSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        responses = {}  # IMPORTANT: Use {}, not {{}}
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
    """Auto-login before running tests"""
    # Clear previous responses
    if RESPONSE_FILE.exists():
        os.remove(RESPONSE_FILE)
    
    api_client.login(username="admin", password="admin123")
    yield
    api_client.clear_auth()


# Auto-generated test cases for API endpoints
# Generated by API Test Framework

# POSITIVE TEST CASES

@pytest.mark.positive
@pytest.mark.smoke
def test_api_users_get_positive():
    """测试 GET /api/users - 正向测试用例"""
    
    # 准备测试数据
    test_data = {"page": 1, "size": 10}
    
    # 发起API请求
    response = api_client.get('/api/users', params=test_data)
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {"raw_text": response.text}
    save_response('test_api_users_get_positive', {
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': test_data
    })
    
    # 验证响应
    data = api_client.validate_response(response, 200)
    
    # 断言业务响应码
    assert data.get('code') == 200, f"业务响应码错误: {data.get('msg', 'Unknown error')}"

# NEGATIVE TEST CASES

@pytest.mark.negative
@pytest.mark.regression
def test_api_users_get_negative_invalid_params():
    """测试 GET /api/users - 负向测试用例: invalid_params"""
    
    # 准备无效的测试数据
    test_data = {}
    
    # 发起API请求
    response = api_client.get('/api/users', data=test_data)
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {"raw_text": response.text}
    save_response('test_api_users_get_negative_invalid_params', {
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': test_data
    })
    
    # 验证错误响应
    assert response.status_code == 400
    
    # 断言错误结构
    error_data = response.json()
    assert 'errorCode' in error_data
    assert 'message' in error_data

# PERFORMANCE TEST CASES

@pytest.mark.performance
def test_api_users_get_performance():
    """测试 GET /api/users - 性能测试"""
    
    # 准备测试数据
    test_data = {"page": 1, "size": 10}
    
    # 测量响应时间
    import time
    start_time = time.time()
    
    response = api_client.get('/api/users', params=test_data)
    
    end_time = time.time()
    response_time = end_time - start_time
    
    # 存储响应结果用于报告
    try:
        resp_json = response.json()
    except:
        resp_json = {"raw_text": response.text}
    save_response('test_api_users_get_performance', {
        'status_code': response.status_code,
        'response': resp_json,
        'request_params': test_data,
        'response_time': response_time
    })
    
    # 验证响应
    data = api_client.validate_response(response, 200)
    
    # 断言业务响应码
    assert data.get('code') == 200, f"业务响应码错误: {data.get('msg', 'Unknown error')}"
    
    # 断言性能要求
    assert response_time < 1.0, "响应时间超过限制"
```

### 7. Critical Implementation Rules

#### Rule 1: Response Storage
- **MUST** save every test response to `responses.json`
- Use `save_response()` function after every API call
- Include `status_code`, `response`, and `request_params`

#### Rule 2: Business Response Code Assertion
- **MUST** check `data.get('code') == 200`
- **DO NOT** check for `requestId` field
- Include error message in assertion: `f"业务响应码错误: {data.get('msg', 'Unknown error')}"`

#### Rule 3: Login Endpoint Isolation
- **MUST** use `import requests` for login endpoints
- **DO NOT** use `api_client` for login (causes 403 error)
- Assert `token` field exists in response

#### Rule 4: Authentication Fixture
- **MUST** include `setup_authentication` fixture in every test file
- Fixture clears previous responses before tests
- Auto-login with credentials: `username="admin"`, `password="admin123"`

#### Rule 5: Response Dictionary Initialization
- **MUST** use `responses = {}` (single braces)
- **DO NOT** use `responses = {{}}` (double braces)
- Double braces are only for format strings, not direct file writes
    
    # 验证响应
    data = api_client.validate_response(response, 200)
    
    # 断言性能要求
    assert response_time < 1.0, "响应时间超过限制"
```

### 7. Naming Conventions

- **Function name**: `test_{endpoint_path}_{method}_{type}`
- **Endpoint path**: Replace `/` with `_`, remove `{` and `}`
- **Example**: `/api/users/{id}` → `test_api_users_id_get_positive`

### 8. Swagger Integration

1. Fetch API docs from `http://localhost:8160/v3/api-docs`
2. Parse endpoints from `paths` section
3. Extract schemas from `components/schemas`
4. Use `example` values from schema properties
5. Follow `$ref` references for request/response bodies

### 9. Output Location

- Generated files: `pytestjava/tests/generated/test_generated_{timestamp}.py`
- Report files: `pytestjava/test-reports/test-report.html`

## Example Usage

```python
# Generate tests for all detected endpoints
python pytestjava/run_tests.py --git-repo-path ./campus-master

# Generate tests for specific endpoints
endpoints = [
    {"method": "POST", "path": "/login"},
    {"method": "GET", "path": "/api/users"}
]
generator = TestCaseGenerator()
test_cases = generator.generate_test_cases(endpoints)
```
