---
name: "swagger-test-generator"
description: "Generates pytest test cases based on Swagger/OpenAPI documentation. Invoke when user needs to create API tests from Swagger docs or when Java code changes are detected."
---

# Swagger Test Generator

This skill generates professional pytest test cases based on Swagger/OpenAPI documentation for Spring Boot applications.

## When to Invoke

Invoke this skill when:
- User wants to generate API test cases from Swagger documentation
- User needs to test Spring Boot REST APIs
- Java code changes are detected and need test coverage
- User asks about API testing automation

## Features

### 1. Swagger Integration
- Fetches API documentation from `/v3/api-docs` endpoint
- Parses OpenAPI 3.0 specifications
- Extracts endpoint parameters, request bodies, and response schemas

### 2. Test Case Generation
- **Positive Tests**: Validates successful API responses
- **Negative Tests**: Tests error handling scenarios
- **Performance Tests**: Measures API response times

### 3. Smart Data Generation
- Generates appropriate test data based on parameter types
- Handles path parameters (`{id}`, `{userName}`, etc.)
- Generates query parameters from Swagger specs
- Creates request bodies for POST/PUT operations

## Usage

### Basic Usage

```bash
python pytestjava/run_tests.py --git-repo-path "path/to/java/project"
```

### Configuration

1. Set the API base URL in `pytestjava/config/settings.py`:
```python
API_BASE_URL: str = "http://localhost:8160"
```

2. Ensure Swagger documentation is available at:
```
{API_BASE_URL}/v3/api-docs
```

## Generated Test Structure

```
pytestjava/
├── tests/
│   └── generated/
│       └── test_generated_YYYYMMDD_HHMMSS.py
├── test-reports/
│   └── test-report.html
└── utils/
    ├── swagger_client.py      # Swagger API client
    ├── test_generator.py      # Test case generator
    ├── git_detector.py        # Git change detector
    └── api_client.py          # HTTP client
```

## Test Case Format

Generated test cases follow this structure:

```python
@pytest.mark.positive
@pytest.mark.smoke
def test_endpoint_name_positive():
    """Test GET /api/endpoint - Positive test case"""
    
    # Prepare test data from Swagger
    test_data = {"param1": "value1"}
    
    # Make API request
    response = api_client.get('/api/endpoint', params=test_data)
    
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
    
    # Validate response
    data = api_client.validate_response(response, 200)
    
    # Assert business response code
    assert data.get('code') == 200, f"业务响应码错误: {data.get('msg', 'Unknown error')}"
```

## Critical Rules

### 1. Login Endpoint Special Handling

**IMPORTANT**: Login endpoints (`/login`) must use independent requests to avoid Authorization header conflicts.

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

### 2. Response Assertion Rules

**CRITICAL**: Always check business response code `code == 200`, NOT `requestId` field.

```python
# ✅ CORRECT - Check business response code
assert data.get('code') == 200, f"业务响应码错误: {data.get('msg', 'Unknown error')}"

# ❌ WRONG - Don't check requestId
# assert 'requestId' in data
```

**Reason**: Actual API responses use `code` field for business status, not `requestId`.

### 3. Response Storage Mechanism

**REQUIRED**: Every test must save response data to `responses.json` for report generation.

```python
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
```

**File Location**: `pytestjava/test-reports/responses.json`

### 4. Authentication Mechanism

**AUTO-LOGIN**: Use pytest fixture to automatically login before tests.

```python
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
```

**Token Usage**: The `api_client` automatically adds `Authorization: Bearer {token}` header to all requests.

### 5. Report Data Update

**CRITICAL**: Update all test detail dictionaries with response data.

```python
# Load stored responses from file
responses_file = Path(__file__).parent / "test-reports" / "responses.json"
stored_responses = {}
if responses_file.exists():
    with open(responses_file, 'r', encoding='utf-8') as f:
        stored_responses = json.load(f)

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
```

## Path Parameter Replacement

The skill automatically replaces path parameters with test values:

| Original Path | Replaced Path |
|--------------|---------------|
| `/users/{id}` | `/users/1` |
| `/unlock/{userName}` | `/unlock/test_name` |
| `/delete/{infoIds}` | `/delete/1` |

## Data Type Mapping

| Swagger Type | Test Value |
|-------------|------------|
| `integer` | `1` |
| `string` | `"test"` |
| `string` (date-time) | `"2024-01-01T00:00:00"` |
| `boolean` | `true` |
| `array` | `[]` |
| `object` | `{}` |

## Integration with Git

The skill integrates with Git to detect code changes:

1. Detects modified Java files
2. Extracts `@RequestMapping`, `@GetMapping`, `@PostMapping`, etc.
3. Maps endpoints to Swagger documentation
4. Generates tests only for affected endpoints

## Report Generation

Generates HTML reports with:
- Test execution summary
- Pass/fail statistics
- Failed test details
- Response time metrics

Report location: `pytestjava/test-reports/test-report.html`

## Best Practices

1. **Start the target application** before running tests
2. **Ensure Swagger is enabled** in your Spring Boot application
3. **Configure authentication** if APIs require authorization
4. **Review generated tests** before committing to version control

## Troubleshooting

### Swagger Documentation Not Found
```
Error: Failed to fetch API docs
```
Solution: Ensure the application is running and Swagger is enabled.

### Path Parameters Not Replaced
Check that the endpoint pattern matches between Java annotations and Swagger documentation.

### Test Failures Due to Authentication
Add authentication headers in `api_client.py`:
```python
headers = {
    "Authorization": "Bearer your-token",
    "Content-Type": "application/json"
}
```

## Example Workflow

1. Make changes to Java controller
2. Commit changes to Git
3. Run test generator
4. Review generated tests
5. Execute tests
6. Review HTML report
