import json
import logging
import requests
import re
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class SwaggerClient:
    """Swagger API 文档客户端"""
    
    def __init__(self, base_url: str = "http://localhost:8160"):
        self.base_url = base_url
        self.api_docs_url = f"{base_url}/v3/api-docs"
        self._api_docs: Optional[Dict] = None
    
    def fetch_api_docs(self) -> Dict:
        """获取 Swagger API 文档"""
        if self._api_docs is None:
            try:
                response = requests.get(self.api_docs_url, timeout=10)
                response.raise_for_status()
                self._api_docs = response.json()
                logger.info(f"Successfully fetched API docs from {self.api_docs_url}")
            except Exception as e:
                logger.error(f"Failed to fetch API docs: {e}")
                self._api_docs = {}
        return self._api_docs
    
    def get_endpoint_info(self, path_pattern: str, method: str) -> Optional[Dict]:
        """根据路径模式和方法获取接口信息"""
        api_docs = self.fetch_api_docs()
        paths = api_docs.get("paths", {})
        
        for full_path, methods in paths.items():
            if method.lower() in methods:
                if self._path_matches(full_path, path_pattern):
                    return {
                        "full_path": full_path,
                        "method": method.upper(),
                        "parameters": methods[method.lower()].get("parameters", []),
                        "requestBody": methods[method.lower()].get("requestBody"),
                        "summary": methods[method.lower()].get("summary", ""),
                        "tags": methods[method.lower()].get("tags", [])
                    }
        
        return None
    
    def _path_matches(self, full_path: str, pattern: str) -> bool:
        """检查路径是否匹配模式"""
        full_parts = full_path.strip("/").split("/")
        pattern_parts = pattern.strip("/").split("/")
        
        if len(full_parts) != len(pattern_parts):
            return False
        
        for fp, pp in zip(full_parts, pattern_parts):
            if fp.startswith("{") and fp.endswith("}"):
                continue
            if pp.startswith("{") and pp.endswith("}"):
                continue
            if fp.lower() != pp.lower():
                return False
        
        return True
    
    def get_real_path(self, path_pattern: str, method: str) -> str:
        """获取真实的 API 路径"""
        endpoint_info = self.get_endpoint_info(path_pattern, method)
        if endpoint_info:
            return endpoint_info["full_path"]
        return path_pattern
    
    def get_test_data_for_endpoint(self, path_pattern: str, method: str) -> Dict[str, Any]:
        """根据 Swagger 文档生成测试数据"""
        endpoint_info = self.get_endpoint_info(path_pattern, method)
        if not endpoint_info:
            return {}
        
        test_data = {}
        parameters = endpoint_info.get("parameters", [])
        
        for param in parameters:
            param_name = param.get("name")
            param_in = param.get("in")
            schema = param.get("schema", {})
            param_type = schema.get("type", "string")
            param_format = schema.get("format", "")
            required = param.get("required", False)
            description = param.get("description", "")
            
            if param_in == "query":
                test_data[param_name] = self._generate_value_by_type(
                    param_name, param_type, param_format, schema, description
                )
            elif param_in == "path":
                test_data[param_name] = self._generate_value_by_type(
                    param_name, param_type, param_format, schema, description
                )
        
        request_body = endpoint_info.get("requestBody")
        if request_body:
            content = request_body.get("content", {})
            if "application/json" in content:
                schema_ref = content["application/json"].get("schema", {}).get("$ref", "")
                if "LoginBody" in schema_ref:
                    test_data["username"] = "admin"
                    test_data["password"] = "admin123"
                    test_data["code"] = "1234"
                    test_data["uuid"] = "test-uuid"
        
        return test_data
    
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
            if description:
                return f"test_{name}"
            return "test"
        
        if type_name == "boolean":
            return True
        
        if type_name == "array":
            return []
        
        if type_name == "object":
            return {}
        
        return None
    
    def search_endpoints_by_keyword(self, keyword: str) -> List[Dict]:
        """根据关键词搜索接口"""
        api_docs = self.fetch_api_docs()
        paths = api_docs.get("paths", {})
        results = []
        
        keyword_lower = keyword.lower()
        
        for path, methods in paths.items():
            if keyword_lower in path.lower():
                for method, details in methods.items():
                    results.append({
                        "path": path,
                        "method": method.upper(),
                        "summary": details.get("summary", ""),
                        "parameters": details.get("parameters", []),
                        "tags": details.get("tags", [])
                    })
        
        return results
    
    def get_all_endpoints(self) -> List[Dict]:
        """获取所有接口列表"""
        api_docs = self.fetch_api_docs()
        paths = api_docs.get("paths", {})
        results = []
        
        for path, methods in paths.items():
            for method, details in methods.items():
                if method in ["get", "post", "put", "delete", "patch"]:
                    results.append({
                        "path": path,
                        "method": method.upper(),
                        "summary": details.get("summary", ""),
                        "parameters": details.get("parameters", []),
                        "tags": details.get("tags", [])
                    })
        
        return results


swagger_client = SwaggerClient()
