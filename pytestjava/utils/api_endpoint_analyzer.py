"""API端点分析器模块

基于JCCI分析结果，提取Controller方法、追踪服务依赖、计算影响置信度。
核心功能：
- 从JCCI解析结果中提取Controller方法信息
- 追踪Controller方法调用的Service方法
- 分析代码变更对API端点的影响
- 计算影响置信度（基于影响路径深度）
- 生成端点影响摘要统计
"""
import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .jcci_analyzer import JavaElement, CodeChange, ChangeType, APIEndpoint, JavaClassInfo, JavaMethodInfo
from .impact_analyzer import ImpactPath

logger = logging.getLogger(__name__)


# Controller方法信息，包含HTTP接口和服务调用关系
@dataclass
class ControllerMethod:
    class_name: str  # Controller类名
    method_name: str  # 方法名
    http_method: str  # HTTP方法（GET/POST/PUT/DELETE等）
    path: str  # API路径
    file_path: str  # 文件路径
    line_number: int  # 行号
    annotations: List[str]  # 注解列表
    parameters: List[Dict]  # 参数列表
    return_type: str  # 返回值类型
    called_services: List[str] = field(default_factory=list)  # 调用的Service方法列表
    called_methods: List[str] = field(default_factory=list)  # 调用的所有方法列表
    
    def to_dict(self) -> Dict:
        return {
            'class_name': self.class_name,
            'method_name': self.method_name,
            'http_method': self.http_method,
            'path': self.path,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'annotations': self.annotations,
            'parameters': self.parameters,
            'return_type': self.return_type,
            'called_services': self.called_services,
            'called_methods': self.called_methods
        }


# API端点影响信息，描述代码变更对端点的影响程度
@dataclass
class EndpointImpact:
    endpoint: APIEndpoint  # 受影响的API端点
    impact_type: str  # 影响类型（direct_impact/service_dependency/indirect_impact）
    impact_source: str  # 影响来源方法
    confidence: float  # 影响置信度（0-1）
    impact_path: List[str]  # 影响路径
    depth: int = 0  # 影响深度
    
    def to_dict(self) -> Dict:
        return {
            'endpoint': self.endpoint.to_dict(),
            'impact_type': self.impact_type,
            'impact_source': self.impact_source,
            'confidence': self.confidence,
            'impact_path': self.impact_path,
            'depth': self.depth
        }


class APIEndpointAnalyzer:
    """使用JCCI分析的增强版API端点分析器
    
    通过以下方式分析API接口及其与变更代码的关系:
    - Controller方法提取
    - 服务依赖追踪
    - 调用链分析
    - 影响置信度计算
    """
    
    def __init__(self, project_path: str, jcci_analyzer=None):
        self.project_path = Path(project_path).resolve()
        self.jcci = jcci_analyzer
        self.controllers: Dict[str, ControllerMethod] = {}
        self.service_to_controllers: Dict[str, List[str]] = defaultdict(list)
        self.method_to_controller: Dict[str, str] = {}
        self._initialized = False
    
    def initialize(self):
        """初始化端点分析器，从JCCI构建或直接扫描Controller文件"""
        if self._initialized:
            return
        
        if self.jcci:
            self._build_from_jcci()
        else:
            self._scan_controllers()
        
        self._initialized = True
        logger.info(f"[APIEndpointAnalyzer] 初始化完成: {len(self.controllers)} 个Controller方法, "
                   f"{len(set(cm.class_name for cm in self.controllers.values()))} 个Controller类, "
                   f"{sum(len(cm.called_services) for cm in self.controllers.values())} 个Service调用关系")
    
    def _build_from_jcci(self):
        """从JCCI分析结果构建端点信息，提取Controller方法和Service调用关系"""
        logger.info(f"[APIEndpointAnalyzer] 从JCCI构建端点分析...")
        
        if not self.jcci._initialized:
            self.jcci.initialize()
        
        controller_count = 0
        endpoint_count = 0
        service_call_count = 0
        
        for class_name, class_info in self.jcci.java_classes.items():
            if not class_info.is_controller:
                continue
            
            controller_count += 1
            base_path = self._extract_base_path_from_class(class_info)
            
            for method_name, method_info in class_info.methods.items():
                if not method_info.is_api or not method_info.http_method:
                    continue
                
                endpoint_count += 1
                path = self._extract_method_path_from_info(method_info, base_path)
                
                controller_method = ControllerMethod(
                    class_name=class_name,
                    method_name=method_name,
                    http_method=method_info.http_method,
                    path=path,
                    file_path=class_info.file_path,
                    line_number=method_info.line_start,
                    annotations=method_info.annotations,
                    parameters=method_info.parameters,
                    return_type=method_info.return_type,
                    called_services=self._extract_service_calls_from_info(method_info, class_info),
                    called_methods=method_info.called_methods
                )
                
                key = f"{class_name}.{method_name}"
                self.controllers[key] = controller_method
                self.method_to_controller[key] = key
                
                for service_call in controller_method.called_services:
                    self.service_to_controllers[service_call].append(key)
                    service_call_count += 1
        
        logger.info(f"[APIEndpointAnalyzer] 端点分析完成: {controller_count} 个Controller类, {endpoint_count} 个API端点, {service_call_count} 个Service调用")
    
    def _extract_base_path_from_class(self, class_info: JavaClassInfo) -> str:
        """从JavaClassInfo中提取Controller类的基础路径"""
        if hasattr(class_info, 'base_path') and class_info.base_path:
            return class_info.base_path
        return ""
    
    def _extract_method_path_from_info(self, method_info: JavaMethodInfo, base_path: str) -> str:
        """拼接Controller基础路径和方法注解路径"""
        if method_info.api_path:
            if method_info.api_path.startswith('/'):
                if base_path:
                    return f"{base_path}{method_info.api_path}".replace("//", "/")
                else:
                    return method_info.api_path
            return f"{base_path}/{method_info.api_path}".replace("//", "/")
        return base_path if base_path else "/"
    
    def _extract_service_calls_from_info(self, method_info: JavaMethodInfo, class_info: JavaClassInfo) -> List[str]:
        """从方法调用关系中提取对@Autowired Service字段的调用"""
        service_calls = []
        
        autowired_fields = {}
        for field_name, field_info in class_info.fields.items():
            if 'Autowired' in field_info.annotations:
                autowired_fields[field_name] = field_info.field_type
        
        for called in method_info.called_methods:
            for field_name, field_type in autowired_fields.items():
                if called.startswith(f"{field_name}."):
                    method_name = called.split('.')[1]
                    service_calls.append(f"{field_type}.{method_name}")
        
        return service_calls
    
    def _scan_controllers(self):
        """扫描项目中所有Java文件，查找Controller类"""
        java_files = list(self.project_path.rglob("*.java"))
        java_files = [f for f in java_files if "target" not in str(f) and "build" not in str(f)]
        
        logger.info(f"Scanning {len(java_files)} Java files for controllers")
        
        for java_file in java_files:
            try:
                self._analyze_controller_file(java_file)
            except Exception as e:
                logger.error(f"Error analyzing {java_file}: {e}")
    
    def _analyze_controller_file(self, java_file: Path):
        """分析单个Controller文件，提取所有API端点方法"""
        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading {java_file}: {e}")
            return
        
        is_controller = any(ann in content for ann in ['@RestController', '@Controller'])
        
        if not is_controller:
            return
        
        class_name = self._extract_class_name(content)
        if not class_name:
            return
        
        base_path = self._extract_base_path(content)
        
        controller_methods = self._extract_controller_methods(content, class_name, base_path, java_file)
        
        for method in controller_methods:
            key = f"{class_name}.{method.method_name}"
            self.controllers[key] = method
            self.method_to_controller[key] = key
            
            for service_call in method.called_services:
                self.service_to_controllers[service_call].append(key)
    
    def _extract_class_name(self, content: str) -> Optional[str]:
        """从Java文件内容中提取类名"""
        pattern = r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?class\s+(\w+)'
        match = re.search(pattern, content)
        return match.group(1) if match else None
    
    def _extract_base_path(self, content: str) -> str:
        """从类注解中提取@RequestMapping基础路径"""
        pattern = r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"'
        match = re.search(pattern, content)
        return match.group(1) if match else ""
    
    def _extract_controller_methods(self, content: str, class_name: str, base_path: str, java_file: Path) -> List[ControllerMethod]:
        """从Controller文件内容中提取所有API端点方法（@GetMapping/@PostMapping等）"""
        methods = []
        
        method_mappings = [
            ('@GetMapping', 'GET'),
            ('@PostMapping', 'POST'),
            ('@PutMapping', 'PUT'),
            ('@DeleteMapping', 'DELETE'),
            ('@PatchMapping', 'PATCH')
        ]
        
        for annotation, http_method in method_mappings:
            pattern = rf'{annotation}\s*\((.*?)\)\s*(?:public|private|protected)?\s*(?:\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\(([^)]*)\)'
            
            for match in re.finditer(pattern, content, re.DOTALL):
                annotation_content = match.group(1)
                method_name = match.group(2)
                params_str = match.group(3)
                
                path = self._extract_path_from_annotation(annotation_content)
                full_path = f"{base_path}{path}".replace("//", "/")
                
                line_number = content[:match.start()].count('\n') + 1
                
                parameters = self._parse_parameters(params_str)
                
                method_pattern = rf'{re.escape(annotation)}\s*\([^)]*\)\s*(?:public|private|protected)?\s*(\w+(?:<[\w\s,<>]+>)?)\s+{re.escape(method_name)}\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{{'
                method_match = re.search(method_pattern, content[match.start():])
                return_type = method_match.group(1) if method_match else "void"
                
                method_body = self._extract_method_body(content, match.start())
                called_services = self._extract_service_calls(method_body, content)
                called_methods = self._extract_all_method_calls(method_body, class_name)
                
                controller_method = ControllerMethod(
                    class_name=class_name,
                    method_name=method_name,
                    http_method=http_method,
                    path=full_path,
                    file_path=str(java_file.relative_to(self.project_path)),
                    line_number=line_number,
                    annotations=[annotation],
                    parameters=parameters,
                    return_type=return_type,
                    called_services=called_services,
                    called_methods=called_methods
                )
                methods.append(controller_method)
        
        request_method_pattern = r'@RequestMapping\s*\((.*?)\)\s*(?:public|private|protected)?\s*(?:\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\(([^)]*)\)'
        
        for match in re.finditer(request_method_pattern, content, re.DOTALL):
            annotation_content = match.group(1)
            method_name = match.group(2)
            params_str = match.group(3)
            
            method_match = re.search(r'method\s*=\s*RequestMethod\.(\w+)', annotation_content)
            if not method_match:
                continue
            
            http_method = method_match.group(1)
            path = self._extract_path_from_annotation(annotation_content)
            full_path = f"{base_path}{path}".replace("//", "/")
            
            line_number = content[:match.start()].count('\n') + 1
            
            parameters = self._parse_parameters(params_str)
            
            method_body = self._extract_method_body(content, match.start())
            called_services = self._extract_service_calls(method_body, content)
            called_methods = self._extract_all_method_calls(method_body, class_name)
            
            controller_method = ControllerMethod(
                class_name=class_name,
                method_name=method_name,
                http_method=http_method,
                path=full_path,
                file_path=str(java_file.relative_to(self.project_path)),
                line_number=line_number,
                annotations=['@RequestMapping'],
                parameters=parameters,
                return_type="Object",
                called_services=called_services,
                called_methods=called_methods
            )
            methods.append(controller_method)
        
        return methods
    
    def _extract_path_from_annotation(self, annotation_content: str) -> str:
        """从注解内容中提取API路径"""
        value_match = re.search(r'value\s*=\s*"([^"]+)"', annotation_content)
        if value_match:
            return value_match.group(1)
        
        simple_match = re.search(r'^\s*"([^"]+)"', annotation_content)
        if simple_match:
            return simple_match.group(1)
        
        return ""
    
    def _parse_parameters(self, params_str: str) -> List[Dict]:
        """解析方法参数字符串，提取参数类型和名称"""
        parameters = []
        
        if not params_str.strip():
            return parameters
        
        for param in params_str.split(','):
            param = param.strip()
            if not param:
                continue
            
            parts = param.split()
            if len(parts) >= 2:
                param_type = parts[-2]
                param_name = parts[-1]
                
                annotations = []
                for part in parts[:-2]:
                    if part.startswith('@'):
                        annotations.append(part)
                
                parameters.append({
                    'type': param_type,
                    'name': param_name,
                    'annotations': annotations
                })
        
        return parameters
    
    def _extract_method_body(self, content: str, start_pos: int) -> str:
        """根据起始位置提取方法体内容"""
        brace_start = content.find('{', start_pos)
        if brace_start == -1:
            return ""
        
        brace_count = 1
        pos = brace_start + 1
        body_end = pos
        
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        
        body_end = pos
        return content[brace_start:body_end]
    
    def _extract_service_calls(self, method_body: str, class_content: str) -> List[str]:
        """从方法体中提取对@Autowired Service字段的调用"""
        service_calls = []
        
        autowired_fields = self._find_autowired_fields(class_content)
        
        for field_name, field_type in autowired_fields.items():
            pattern = rf'{field_name}\s*\.\s*(\w+)\s*\('
            for match in re.finditer(pattern, method_body):
                method_name = match.group(1)
                service_calls.append(f"{field_type}.{method_name}")
        
        return service_calls
    
    def _extract_all_method_calls(self, method_body: str, class_name: str) -> List[str]:
        """从方法体中提取所有方法调用"""
        calls = []
        
        pattern = r'(\w+)\s*\.\s*(\w+)\s*\('
        for match in re.finditer(pattern, method_body):
            object_name = match.group(1)
            method_name = match.group(2)
            calls.append(f"{object_name}.{method_name}")
        
        return list(set(calls))
    
    def _find_autowired_fields(self, content: str) -> Dict[str, str]:
        """查找类中所有@Autowired字段，返回字段名到类型的映射"""
        fields = {}
        
        pattern = r'@Autowired\s+(?:private|public|protected)?\s+(\w+)\s+(\w+)\s*;'
        for match in re.finditer(pattern, content):
            field_type = match.group(1)
            field_name = match.group(2)
            fields[field_name] = field_type
        
        return fields
    
    def find_affected_endpoints(self, changes: List[CodeChange], impact_paths: List[ImpactPath]) -> List[EndpointImpact]:
        """根据代码变更和影响路径，查找所有受影响的API端点
        
        查找策略：
        1. 直接变更的Controller方法 → direct_impact
        2. 影响传播链到达的Controller方法 → 根据深度计算置信度
        3. 变更方法被Controller调用的Service → service_dependency
        """
        self.initialize()
        
        affected_endpoints = []
        processed_endpoints = set()
        
        for change in changes:
            if change.change_type == ChangeType.MODIFIED and change.element.element_type == 'method':
                method_key = change.element.qualified_name
                
                if method_key in self.controllers:
                    controller_method = self.controllers[method_key]
                    
                    endpoint = APIEndpoint(
                        method=f"{controller_method.http_method} {controller_method.path}",
                        path=controller_method.path,
                        http_method=controller_method.http_method,
                        controller_class=controller_method.class_name,
                        method_name=controller_method.method_name,
                        file_path=controller_method.file_path,
                        line_number=controller_method.line_number,
                        annotations=controller_method.annotations
                    )
                    
                    endpoint_key = f"{endpoint.http_method} {endpoint.path}"
                    if endpoint_key not in processed_endpoints:
                        processed_endpoints.add(endpoint_key)
                        
                        impact = EndpointImpact(
                            endpoint=endpoint,
                            impact_type="direct_impact",
                            impact_source=method_key,
                            confidence=1.0,
                            impact_path=[method_key],
                            depth=0
                        )
                        affected_endpoints.append(impact)
        
        for impact_path in impact_paths:
            end_method = impact_path.end_element.qualified_name
            
            if end_method in self.controllers:
                controller_method = self.controllers[end_method]
                
                endpoint = APIEndpoint(
                    method=f"{controller_method.http_method} {controller_method.path}",
                    path=controller_method.path,
                    http_method=controller_method.http_method,
                    controller_class=controller_method.class_name,
                    method_name=controller_method.method_name,
                    file_path=controller_method.file_path,
                    line_number=controller_method.line_number,
                    annotations=controller_method.annotations
                )
                
                endpoint_key = f"{endpoint.http_method} {endpoint.path}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    
                    impact_type, confidence = self._calculate_impact_from_path(impact_path)
                    
                    impact = EndpointImpact(
                        endpoint=endpoint,
                        impact_type=impact_type,
                        impact_source=impact_path.start_element.qualified_name,
                        confidence=confidence,
                        impact_path=impact_path.path,
                        depth=impact_path.depth
                    )
                    affected_endpoints.append(impact)
        
        for change in changes:
            if change.element.element_type == 'method':
                method_key = change.element.qualified_name
                
                for controller_key, controller_method in self.controllers.items():
                    if method_key in controller_method.called_services:
                        endpoint = APIEndpoint(
                            method=f"{controller_method.http_method} {controller_method.path}",
                            path=controller_method.path,
                            http_method=controller_method.http_method,
                            controller_class=controller_method.class_name,
                            method_name=controller_method.method_name,
                            file_path=controller_method.file_path,
                            line_number=controller_method.line_number,
                            annotations=controller_method.annotations
                        )
                        
                        endpoint_key = f"{endpoint.http_method} {endpoint.path}"
                        if endpoint_key not in processed_endpoints:
                            processed_endpoints.add(endpoint_key)
                            
                            impact = EndpointImpact(
                                endpoint=endpoint,
                                impact_type="service_dependency",
                                impact_source=method_key,
                                confidence=0.9,
                                impact_path=[method_key, controller_key],
                                depth=1
                            )
                            affected_endpoints.append(impact)
        
        return affected_endpoints
    
    def _calculate_impact_from_path(self, impact_path: ImpactPath) -> Tuple[str, float]:
        """根据影响路径深度计算影响类型和置信度"""
        depth = impact_path.depth
        
        if depth == 0:
            return ('direct_impact', 1.0)
        elif depth == 1:
            return ('direct_impact', 0.95)
        elif depth == 2:
            return ('method_or_class_dependency', 0.85)
        elif depth == 3:
            return ('indirect_impact', 0.7)
        else:
            return ('indirect_impact', max(0.5, 0.9 - depth * 0.1))
    
    def get_all_endpoints(self) -> List[APIEndpoint]:
        """获取项目中所有API端点信息"""
        self.initialize()
        
        endpoints = []
        
        for controller_method in self.controllers.values():
            endpoint = APIEndpoint(
                method=f"{controller_method.http_method} {controller_method.path}",
                path=controller_method.path,
                http_method=controller_method.http_method,
                controller_class=controller_method.class_name,
                method_name=controller_method.method_name,
                file_path=controller_method.file_path,
                line_number=controller_method.line_number,
                annotations=controller_method.annotations
            )
            endpoints.append(endpoint)
        
        return endpoints
    
    def get_endpoint_summary(self, affected_endpoints: List[EndpointImpact]) -> Dict:
        """生成受影响端点的摘要统计信息"""
        summary = {
            'total_affected_endpoints': len(affected_endpoints),
            'direct_impacts': 0,
            'indirect_impacts': 0,
            'method_dependency_impacts': 0,
            'service_dependencies': 0,
            'endpoints_by_http_method': defaultdict(int),
            'affected_controllers': set(),
            'impact_by_depth': defaultdict(int)
        }
        
        for impact in affected_endpoints:
            if impact.impact_type == 'direct_impact':
                summary['direct_impacts'] += 1
            elif impact.impact_type == 'indirect_impact':
                summary['indirect_impacts'] += 1
            elif impact.impact_type == 'method_or_class_dependency':
                summary['method_dependency_impacts'] += 1
            elif impact.impact_type == 'service_dependency':
                summary['service_dependencies'] += 1
            
            summary['endpoints_by_http_method'][impact.endpoint.http_method] += 1
            summary['affected_controllers'].add(impact.endpoint.controller_class)
            summary['impact_by_depth'][impact.depth] += 1
        
        summary['endpoints_by_http_method'] = dict(summary['endpoints_by_http_method'])
        summary['affected_controllers'] = list(summary['affected_controllers'])
        summary['impact_by_depth'] = dict(summary['impact_by_depth'])
        
        return summary
    
    def get_controller_methods_in_file(self, file_path: str) -> List[ControllerMethod]:
        """根据文件路径获取该文件中所有Controller方法"""
        self.initialize()
        
        methods = []
        normalized_path = file_path.replace('/', '\\')
        
        for controller_method in self.controllers.values():
            method_file = controller_method.file_path.replace('/', '\\')
            if method_file == normalized_path or normalized_path.endswith(method_file) or method_file.endswith(normalized_path):
                methods.append(controller_method)
        
        return methods
