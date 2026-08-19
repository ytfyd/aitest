---
name: "webapp-testing"
description: "Web application testing skill for comprehensive test coverage. Invoke when user needs to test web applications, APIs, or create automated test suites."
---

# Web Application Testing

This skill provides comprehensive web application testing capabilities, including:

## Capabilities

### 1. API Testing
- REST API endpoint testing
- Request/response validation
- Authentication and authorization testing
- Performance and load testing

### 2. UI Testing
- Browser automation testing
- Element interaction testing
- Visual regression testing
- Cross-browser compatibility

### 3. Integration Testing
- End-to-end workflow testing
- Database integration testing
- Third-party service integration
- Microservices communication testing

### 4. Security Testing
- Authentication bypass testing
- Input validation testing
- SQL injection testing
- XSS vulnerability testing

## Testing Frameworks

This skill supports multiple testing frameworks:

- **pytest**: Python testing framework
- **Jest**: JavaScript testing framework
- **Playwright**: Browser automation
- **Selenium**: Web UI testing
- **Postman/Newman**: API testing
- **k6**: Load testing

## Usage Guidelines

### When to Invoke
- User asks to test a web application
- User needs to create automated tests
- User wants to validate API endpoints
- User needs performance testing
- User asks about test coverage

### Test Structure
1. **Unit Tests**: Test individual components
2. **Integration Tests**: Test component interactions
3. **E2E Tests**: Test complete user workflows
4. **Performance Tests**: Test under load conditions

## Best Practices

1. **Test Coverage**: Aim for high code coverage
2. **Test Independence**: Tests should not depend on each other
3. **Clear Assertions**: Use descriptive assertion messages
4. **Test Data**: Use fixtures and factories for test data
5. **Continuous Integration**: Run tests on every commit

## Example Test Patterns

### API Test Example
```python
def test_api_endpoint(client):
    response = client.get('/api/endpoint')
    assert response.status_code == 200
    assert 'expected_field' in response.json()
```

### UI Test Example
```python
def test_login_page(page):
    page.goto('/login')
    page.fill('#username', 'testuser')
    page.fill('#password', 'password')
    page.click('#submit')
    assert page.url == '/dashboard'
```

## Test Report Generation

Generate comprehensive test reports including:
- Test execution summary
- Pass/fail statistics
- Coverage metrics
- Performance metrics
- Error details and stack traces
