import time
import json
import logging
from typing import Dict, Any, Optional, List
from requests import Session, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import settings


logger = logging.getLogger(__name__)


class ResponseStore:
    """Global store for test responses"""
    _instance = None
    _responses: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def store_response(self, test_name: str, response_data: Dict[str, Any]):
        """Store response data for a test"""
        self._responses[test_name] = response_data
    
    def get_response(self, test_name: str) -> Optional[Dict[str, Any]]:
        """Get stored response for a test"""
        return self._responses.get(test_name)
    
    def get_all_responses(self) -> Dict[str, Dict[str, Any]]:
        """Get all stored responses"""
        return self._responses.copy()
    
    def clear(self):
        """Clear all stored responses"""
        self._responses.clear()


response_store = ResponseStore.get_instance()


class APIClient:
    """HTTP client for API testing with retry and timeout support"""
    
    def __init__(self):
        self.session = Session()
        if settings.api_version:
            self.base_url = f"{settings.api_base_url}/api/{settings.api_version}"
        else:
            self.base_url = settings.api_base_url
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=settings.max_retries,
            backoff_factor=settings.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set default headers
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "API-Test-Framework/1.0"
        })
        
        # Store last response for reporting
        self.last_response: Optional[Dict[str, Any]] = None
        self.auth_token: Optional[str] = None
    
    def login(self, username: str = "admin", password: str = "admin123") -> bool:
        """Login and get authentication token"""
        try:
            login_data = {"username": username, "password": password}
            response = self.session.post(
                f"{self.base_url}/login",
                data=json.dumps(login_data),
                timeout=(3, 5)
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("code") == 200 and data.get("token"):
                    self.auth_token = f"Bearer {data['token']}"
                    self.session.headers.update({
                        "Authorization": self.auth_token
                    })
                    logger.info(f"Login successful, token obtained")
                    return True
                else:
                    logger.warning(f"Login failed: {data.get('msg', 'Unknown error')}")
                    return False
            else:
                logger.warning(f"Login request failed with status {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return False
    
    def set_auth_token(self, token: str):
        """Set authorization token for subsequent requests"""
        self.auth_token = f"Bearer {token}"
        self.session.headers.update({
            "Authorization": self.auth_token
        })
    
    def clear_auth(self):
        """Clear authorization token"""
        self.auth_token = None
        if "Authorization" in self.session.headers:
            del self.session.headers["Authorization"]
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Response:
        """Make HTTP request with logging and error handling"""
        url = f"{self.base_url}{endpoint}"
        
        if "timeout" not in kwargs:
            kwargs["timeout"] = (3, 5)
        
        logger.info(f"Making {method} request to {url}")
        
        try:
            response = self.session.request(method, url, **kwargs)
            logger.info(f"Response status: {response.status_code}")
            
            if response.text:
                body_preview = response.text[:500] + "..." if len(response.text) > 500 else response.text
                logger.debug(f"Response body: {body_preview}")
            
            # Store last response for reporting
            try:
                response_json = response.json()
            except:
                response_json = {"raw_text": response.text}
            
            self.last_response = {
                "status_code": response.status_code,
                "url": url,
                "method": method,
                "endpoint": endpoint,
                "response": response_json
            }
            
            return response
            
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            raise
    
    def get(self, endpoint: str, **kwargs) -> Response:
        return self._request("GET", endpoint, **kwargs)
    
    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> Response:
        if data:
            kwargs["data"] = json.dumps(data)
        return self._request("POST", endpoint, **kwargs)
    
    def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None, **kwargs) -> Response:
        if data:
            kwargs["data"] = json.dumps(data)
        return self._request("PUT", endpoint, **kwargs)
    
    def delete(self, endpoint: str, **kwargs) -> Response:
        return self._request("DELETE", endpoint, **kwargs)
    
    def validate_response(self, response: Response, expected_status: int = 200) -> Dict[str, Any]:
        """Validate response status and return JSON data"""
        assert response.status_code == expected_status, (
            f"Expected status {expected_status}, got {response.status_code}"
        )
        
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            raise
    
    def close(self):
        """Close the session"""
        self.session.close()


# Global API client instance
api_client = APIClient()