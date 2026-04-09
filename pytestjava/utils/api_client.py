import os
import time
import json
import logging
from typing import Dict, Any, Optional, List
from requests import Session, Response
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

from config.settings import settings


logger = logging.getLogger(__name__)


class ResponseStore:
    """测试响应的全局存储"""
    _instance = None
    _responses: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def store_response(self, test_name: str, response_data: Dict[str, Any]):
        """存储测试的响应数据"""
        self._responses[test_name] = response_data
    
    def get_response(self, test_name: str) -> Optional[Dict[str, Any]]:
        """获取测试的存储响应"""
        return self._responses.get(test_name)
    
    def get_all_responses(self) -> Dict[str, Dict[str, Any]]:
        """获取所有存储的响应"""
        return self._responses.copy()
    
    def clear(self):
        """清除所有存储的响应"""
        self._responses.clear()


response_store = ResponseStore.get_instance()


class APIClient:
    """用于API测试的HTTP客户端，支持重试和超时"""
    
    def __init__(self):
        self.session = Session()
        if settings.api_version:
            self.base_url = f"{settings.api_base_url}/api/{settings.api_version}"
        else:
            self.base_url = settings.api_base_url
        
        # 配置重试策略
        retry_strategy = Retry(
            total=settings.max_retries,
            backoff_factor=settings.retry_delay,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # 设置默认请求头
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "API-Test-Framework/1.0"
        })
        
        # 存储最后一次响应用于报告
        self.last_response: Optional[Dict[str, Any]] = None
        self.auth_token: Optional[str] = None
    
    def login(self, username: Optional[str] = None, password: Optional[str] = None) -> bool:
        """登录并获取认证令牌"""
        username = username or os.getenv("USERNAME")
        password = password or os.getenv("PASSWORD")
        
        if not username or not password:
            logger.error("用户名和密码必须在.env文件中配置")
            return False
        
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
                    logger.info(f"登录成功，已获取令牌")
                    return True
                else:
                    logger.warning(f"登录失败: {data.get('msg', '未知错误')}")
                    return False
            else:
                logger.warning(f"登录请求失败，状态码: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"登录错误: {str(e)}")
            return False
    
    def set_auth_token(self, token: str):
        """为后续请求设置授权令牌"""
        self.auth_token = f"Bearer {token}"
        self.session.headers.update({
            "Authorization": self.auth_token
        })
    
    def clear_auth(self):
        """清除授权令牌"""
        self.auth_token = None
        if "Authorization" in self.session.headers:
            del self.session.headers["Authorization"]
    
    def _request(self, method: str, endpoint: str, **kwargs) -> Response:
        """执行HTTP请求，包含日志记录和错误处理"""
        url = f"{self.base_url}{endpoint}"
        
        if "timeout" not in kwargs:
            kwargs["timeout"] = (3, 5)
        
        logger.info(f"正在发送 {method} 请求到 {url}")
        
        try:
            response = self.session.request(method, url, **kwargs)
            logger.info(f"响应状态码: {response.status_code}")
            
            if response.text:
                body_preview = response.text[:500] + "..." if len(response.text) > 500 else response.text
                logger.debug(f"响应内容: {body_preview}")
            
            # 存储最后一次响应用于报告
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
            logger.error(f"请求失败: {str(e)}")
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
        """验证响应状态并返回JSON数据"""
        assert response.status_code == expected_status, (
            f"期望状态码 {expected_status}，实际得到 {response.status_code}"
        )
        
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logger.error(f"解析JSON响应失败: {e}")
            raise
    
    def close(self):
        """关闭会话"""
        self.session.close()


# 全局API客户端实例
api_client = APIClient()