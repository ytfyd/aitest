import time
import json
import logging
from typing import Dict, Any, Optional, List
from requests import Session, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import settings


logger = logging.getLogger(__name__)


class APIClient:
    """HTTP client for API testing with retry and timeout support"""
    
    def __init__(self):
        self.session = Session()
        self.base_url = f"{settings.api_base_url}/api/{settings.api_version}"
        
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
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Response:
        """Make HTTP request with logging and error handling"""
        url = f"{self.base_url}{endpoint}"
        
        # Set default timeout
        if "timeout" not in kwargs:
            kwargs["timeout"] = settings.test_timeout
        
        logger.info(f"Making {method} request to {url}")
        
        try:
            response = self.session.request(method, url, **kwargs)
            logger.info(f"Response status: {response.status_code}")
            
            # Log response body for debugging (truncate if too long)
            if response.text:
                body_preview = response.text[:500] + "..." if len(response.text) > 500 else response.text
                logger.debug(f"Response body: {body_preview}")
            
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