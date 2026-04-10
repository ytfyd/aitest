import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import deque

from .code_change_detector import CodeChangeDetector
from .jcci_analyzer import JCCIAnalyzer, JavaElement, CodeChange, ChangeType, APIEndpoint
from .impact_analyzer import ImpactAnalyzer, ImpactPath
from .api_endpoint_analyzer import APIEndpointAnalyzer, EndpointImpact

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    timestamp: str
    commit_range: str
    changed_files: List[str]
    code_changes: List[Dict]
    impact_summary: Dict
    affected_endpoints: List[Dict]
    endpoint_summary: Dict
    analysis_metadata: Dict
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def save_to_file(self, file_path: str):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class EnhancedImpactAnalyzer:
    """增强版影响分析器 - 整合JCCI/Impact/APIEndpoint/CodeChange四大组件"""
    
    def __init__(self, repo_path: str, project_path: str = None):
        self.repo_path = Path(repo_path).resolve()
        self.project_path = Path(project_path).resolve() if project_path else self.repo_path
        
        self.jcci_analyzer = JCCIAnalyzer(str(self.project_path))
        self.code_change_detector = CodeChangeDetector(str(self.repo_path), str(self.project_path))
        self.impact_analyzer = ImpactAnalyzer(str(self.project_path), jcci_analyzer=self.jcci_analyzer)
        self.api_endpoint_analyzer = APIEndpointAnalyzer(str(self.project_path), jcci_analyzer=self.jcci_analyzer)
        
        self._initialized = False
    
    def initialize(self):
        if self._initialized:
            return
        
        logger.info("[EnhancedImpactAnalyzer] 初始化分析器...")
        self.jcci_analyzer.initialize()
        self.impact_analyzer.initialize()
        self.api_endpoint_analyzer.initialize()
        self._initialized = True
        
        logger.info(f"[EnhancedImpactAnalyzer] 初始化完成: "
                   f"{len(self.jcci_analyzer.java_classes)} 个类, "
                   f"{len(self.impact_analyzer.call_graph)} 个方法节点, "
                   f"{len(self.api_endpoint_analyzer.controllers)} 个Controller方法")
    
    def analyze(self, commit_range: str = "HEAD~1..HEAD", max_impact_depth: int = 5) -> AnalysisResult:
        self.initialize()
        
        logger.info(f"[EnhancedImpactAnalyzer] 开始影响分析: {commit_range}")
        
        changed_files = self.code_change_detector.get_changed_files(commit_range)
        logger.info(f"[EnhancedImpactAnalyzer] 发现 {len(changed_files)} 个变更的Java文件")
        
        all_changes = self.code_change_detector.analyze_all_changes(commit_range)
        flat_changes = []
        for file_path, changes in all_changes.items():
            flat_changes.extend(changes)
        logger.info(f"[EnhancedImpactAnalyzer] 检测到 {len(flat_changes)} 个代码变更")
        
        impact_paths = self.impact_analyzer.analyze_impact(flat_changes, max_impact_depth)
        impact_summary = self.impact_analyzer.get_impact_summary(impact_paths)
        logger.info(f"[EnhancedImpactAnalyzer] 发现 {len(impact_paths)} 条影响路径")
        
        affected_endpoints = self.api_endpoint_analyzer.find_affected_endpoints(flat_changes, impact_paths)
        endpoint_summary = self.api_endpoint_analyzer.get_endpoint_summary(affected_endpoints)
        logger.info(f"[EnhancedImpactAnalyzer] 发现 {len(affected_endpoints)} 个受影响的API端点")
        
        return AnalysisResult(
            timestamp=datetime.now().isoformat(),
            commit_range=commit_range,
            changed_files=changed_files,
            code_changes=[change.to_dict() for change in flat_changes],
            impact_summary=impact_summary,
            affected_endpoints=[impact.to_dict() for impact in affected_endpoints],
            endpoint_summary=endpoint_summary,
            analysis_metadata={
                'max_impact_depth': max_impact_depth,
                'project_path': str(self.project_path),
                'repo_path': str(self.repo_path),
                'analyzer': 'JCCI'
            }
        )
    
    def get_affected_endpoints_for_testing(self, commit_range: str = "HEAD~1..HEAD") -> List[Dict[str, str]]:
        self.initialize()
        
        analysis_result = self.analyze(commit_range)
        
        processed_endpoints = set()
        endpoints = []
        
        changed_controller_files = set()
        for file_path in analysis_result.changed_files:
            if 'Controller' in file_path or 'controller' in file_path.lower():
                normalized = file_path.replace('/', '\\')
                for prefix in ['campus-master\\', 'campus-master/']:
                    if normalized.startswith(prefix):
                        normalized = normalized[len(prefix):]
                        break
                changed_controller_files.add(normalized)
        
        directly_modified_methods = set()
        for change_dict in analysis_result.code_changes:
            if change_dict.get('element', {}).get('element_type') == 'method':
                directly_modified_methods.add(change_dict['element']['qualified_name'])
        
        affected_methods = set(directly_modified_methods)
        for method_key in directly_modified_methods:
            for caller, d in self.impact_analyzer.find_callers(method_key, depth=5):
                affected_methods.add(caller)
            for callee, d in self.impact_analyzer.find_callees(method_key, depth=5):
                affected_methods.add(callee)
        
        related_controllers = self.jcci_analyzer._find_related_controllers(analysis_result.changed_files)
        for controller_file in related_controllers:
            normalized = controller_file.replace('/', '\\')
            for prefix in ['campus-master\\', 'campus-master/']:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break
            changed_controller_files.add(normalized)
        
        for controller_file in changed_controller_files:
            controller_methods = self.api_endpoint_analyzer.get_controller_methods_in_file(controller_file)
            for cm in controller_methods:
                endpoint_key = f"{cm.http_method} {cm.path}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    controller_key = f"{cm.class_name}.{cm.method_name}"
                    if controller_key in directly_modified_methods:
                        impact_type, confidence = 'direct_impact', 1.0
                    else:
                        impact_type, confidence = 'service_dependency', 0.9
                    endpoints.append({
                        'method': cm.http_method,
                        'path': cm.path,
                        'full_endpoint': f"{cm.http_method} {cm.path}",
                        'file': cm.file_path,
                        'impact_type': impact_type,
                        'confidence': confidence
                    })
        
        for endpoint_impact in analysis_result.affected_endpoints:
            endpoint = endpoint_impact['endpoint']
            endpoint_key = f"{endpoint['http_method']} {endpoint['path']}"
            if endpoint_key not in processed_endpoints:
                processed_endpoints.add(endpoint_key)
                impact_type = endpoint_impact['impact_type']
                confidence = endpoint_impact['confidence']
                depth = endpoint_impact.get('depth', 0)
                if impact_type == 'service_dependency':
                    confidence = 0.9
                elif impact_type == 'indirect_impact':
                    confidence = max(0.5, 0.8 - depth * 0.1)
                endpoints.append({
                    'method': endpoint['http_method'],
                    'path': endpoint['path'],
                    'full_endpoint': f"{endpoint['http_method']} {endpoint['path']}",
                    'file': endpoint['file_path'],
                    'impact_type': impact_type,
                    'confidence': confidence
                })
        
        for affected_method in affected_methods:
            for ep in self._find_controller_endpoints_for_method(affected_method):
                endpoint_key = f"{ep['method']} {ep['path']}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    endpoints.append(ep)
        
        logger.info(f"[EnhancedImpactAnalyzer] 受影响端点: {len(endpoints)} 个")
        return endpoints
    
    def _find_controller_endpoints_for_method(self, method_key: str) -> List[Dict[str, str]]:
        endpoints = []
        if '.' not in method_key:
            return endpoints
        
        class_name = method_key.rsplit('.', 1)[0]
        method_name = method_key.rsplit('.', 1)[1]
        
        for controller_key, cm in self.api_endpoint_analyzer.controllers.items():
            if controller_key == method_key:
                impact_type = 'direct_impact'
                confidence = 1.0
                endpoints.append({
                    'method': cm.http_method,
                    'path': cm.path,
                    'full_endpoint': f"{cm.http_method} {cm.path}",
                    'file': cm.file_path,
                    'impact_type': impact_type,
                    'confidence': confidence
                })
            elif controller_key in self.impact_analyzer.call_graph:
                called_methods = self.impact_analyzer.call_graph[controller_key].called_methods
                if method_key in called_methods:
                    impact_type = 'service_dependency'
                    confidence = 0.9
                    endpoints.append({
                        'method': cm.http_method,
                        'path': cm.path,
                        'full_endpoint': f"{cm.http_method} {cm.path}",
                        'file': cm.file_path,
                        'impact_type': impact_type,
                        'confidence': confidence
                    })
                elif any(called.endswith(f'.{method_name}') for called in called_methods):
                    impact_type = 'method_dependency'
                    confidence = 0.85
                    endpoints.append({
                        'method': cm.http_method,
                        'path': cm.path,
                        'full_endpoint': f"{cm.http_method} {cm.path}",
                        'file': cm.file_path,
                        'impact_type': impact_type,
                        'confidence': confidence
                    })
        
        return endpoints
    
    def get_change_summary(self, commit_range: str = "HEAD~1..HEAD") -> Dict:
        return self.code_change_detector.get_change_summary(commit_range)
    
    def save_analysis_report(self, output_path: str, commit_range: str = "HEAD~1..HEAD"):
        analysis_result = self.analyze(commit_range)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        analysis_result.save_to_file(str(output_file))
        logger.info(f"Analysis report saved to {output_file}")
        return str(output_file)
