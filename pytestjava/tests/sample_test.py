"""
Sample test file demonstrating the API testing framework capabilities
This file shows how to write manual tests alongside auto-generated tests
"""

import pytest
import allure
from utils.api_client import api_client
from config.settings import settings


@allure.feature("Authentication API")
class TestAuthenticationAPI:
    """Manual test cases for authentication endpoints"""
    
    @allure.story("Send SMS Verification Code")
    @allure.title("Send verification code with valid phone number")
    @pytest.mark.smoke
    @pytest.mark.positive
    def test_send_sms_code_positive(self):
        """Test sending SMS verification code with valid phone number"""
        
        test_data = {
            "phone": settings.test_phone_number,
            "deviceId": settings.default_device_id
        }
        
        with allure.step("Send SMS verification code request"):
            response = api_client.post("/auth/sms-code", data=test_data)
        
        with allure.step("Validate response"):
            data = api_client.validate_response(response, 200)
            
            # Assert response structure
            assert "requestId" in data
            assert "cooldownSeconds" in data
            assert isinstance(data["cooldownSeconds"], int)
    
    @allure.story("Send SMS Verification Code")
    @allure.title("Send verification code with invalid phone number")
    @pytest.mark.negative
    def test_send_sms_code_invalid_phone(self):
        """Test sending SMS verification code with invalid phone number"""
        
        test_data = {
            "phone": "123",  # Invalid phone number
            "deviceId": settings.default_device_id
        }
        
        with allure.step("Send SMS verification code with invalid phone"):
            response = api_client.post("/auth/sms-code", data=test_data)
        
        with allure.step("Validate error response"):
            assert response.status_code == 400
            
            error_data = response.json()
            assert "errorCode" in error_data
            assert "message" in error_data


@allure.feature("Login API")
class TestLoginAPI:
    """Manual test cases for login endpoints"""
    
    @allure.story("SMS Login")
    @allure.title("Login with valid SMS code")
    @pytest.mark.smoke
    @pytest.mark.positive
    def test_sms_login_positive(self):
        """Test SMS login with valid credentials"""
        
        test_data = {
            "phone": settings.test_phone_number,
            "smsCode": settings.test_verification_code,
            "agreePolicy": True,
            "deviceId": settings.default_device_id
        }
        
        with allure.step("Send login request"):
            response = api_client.post("/auth/login-sms", data=test_data)
        
        with allure.step("Validate login response"):
            data = api_client.validate_response(response, 200)
            
            # Assert response structure
            assert "accessToken" in data
            assert "tokenExpireAt" in data
            assert "user" in data
            assert "userId" in data["user"]
            assert "nickname" in data["user"]
    
    @allure.story("SMS Login")
    @allure.title("Login with wrong SMS code")
    @pytest.mark.negative
    def test_sms_login_wrong_code(self):
        """Test SMS login with wrong verification code"""
        
        test_data = {
            "phone": settings.test_phone_number,
            "smsCode": "000000",  # Wrong code
            "agreePolicy": True,
            "deviceId": settings.default_device_id
        }
        
        with allure.step("Send login request with wrong code"):
            response = api_client.post("/auth/login-sms", data=test_data)
        
        with allure.step("Validate error response"):
            assert response.status_code == 400
            
            error_data = response.json()
            assert "errorCode" in error_data
            assert "message" in error_data


@allure.feature("Home API")
class TestHomeAPI:
    """Manual test cases for home page endpoints"""
    
    @allure.story("Home Overview")
    @allure.title("Get home overview data")
    @pytest.mark.smoke
    @pytest.mark.positive
    def test_home_overview_positive(self):
        """Test getting home overview data"""
        
        # First, login to get access token
        login_data = {
            "phone": settings.test_phone_number,
            "smsCode": settings.test_verification_code,
            "agreePolicy": True,
            "deviceId": settings.default_device_id
        }
        
        with allure.step("Login to get access token"):
            login_response = api_client.post("/auth/login-sms", data=login_data)
            login_data = login_response.json()
            access_token = login_data["accessToken"]
        
        with allure.step("Get home overview with access token"):
            headers = {"Authorization": f"Bearer {access_token}"}
            response = api_client.get("/home/overview", headers=headers)
        
        with allure.step("Validate home overview response"):
            data = api_client.validate_response(response, 200)
            
            # Assert response structure
            assert "shortcuts" in data
            assert "schedules" in data
            assert "courses" in data
            assert "tabs" in data
            
            # Assert data types
            assert isinstance(data["shortcuts"], list)
            assert isinstance(data["schedules"], list)
            assert isinstance(data["courses"], list)
            assert isinstance(data["tabs"], list)
    
    @allure.story("Home Overview")
    @allure.title("Get home overview without authentication")
    @pytest.mark.negative
    def test_home_overview_unauthorized(self):
        """Test getting home overview without authentication"""
        
        with allure.step("Get home overview without access token"):
            response = api_client.get("/home/overview")
        
        with allure.step("Validate unauthorized response"):
            assert response.status_code == 401
            
            error_data = response.json()
            assert "errorCode" in error_data
            assert "message" in error_data


@allure.feature("Performance Testing")
class TestPerformance:
    """Performance test cases"""
    
    @allure.story("Response Time")
    @allure.title("Test home overview response time")
    @pytest.mark.performance
    def test_home_overview_performance(self):
        """Test home overview API response time"""
        
        import time
        
        # Login first
        login_data = {
            "phone": settings.test_phone_number,
            "smsCode": settings.test_verification_code,
            "agreePolicy": True,
            "deviceId": settings.default_device_id
        }
        
        with allure.step("Login to get access token"):
            login_response = api_client.post("/auth/login-sms", data=login_data)
            login_data = login_response.json()
            access_token = login_data["accessToken"]
        
        headers = {"Authorization": f"Bearer {access_token}"}
        
        with allure.step("Measure response time"):
            start_time = time.time()
            response = api_client.get("/home/overview", headers=headers)
            end_time = time.time()
            
            response_time = end_time - start_time
            
            allure.attach(f"Response time: {response_time:.3f}s", 
                         name="Performance Result", 
                         attachment_type=allure.attachment_type.TEXT)
        
        with allure.step("Validate response and performance"):
            data = api_client.validate_response(response, 200)
            
            # Performance assertion - should respond within 1 second
            max_response_time = 1.0
            assert response_time < max_response_time, (
                f"Response time {response_time:.3f}s exceeds limit {max_response_time}s"
            )