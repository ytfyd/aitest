import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from collections import deque

from .code_change_detector import CodeChangeDetector
from .jcci_analyzer import JCCIAnalyzer, JavaElement, CodeChange, ChangeType, APIEndpoint, DiffResult
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
    """Enhanced impact analyzer using JCCI framework for comprehensive analysis
    
    Based on JCCI (Java Code Commit Impact) methodology:
    - Uses javalang for Java AST parsing
    - Uses unidiff for Git diff parsing
    - Builds call graph for impact propagation
    - Traces impact from changed code to Controller layer
    """
    
    def __init__(self, repo_path: str, project_path: str = None):
        self.repo_path = Path(repo_path).resolve()
        self.project_path = Path(project_path).resolve() if project_path else self.repo_path
        
        logger.info(f"Initializing EnhancedImpactAnalyzer for {self.project_path}")
        
        self.jcci_analyzer = JCCIAnalyzer(str(self.project_path))
        
        self.code_change_detector = CodeChangeDetector(str(self.repo_path), str(self.project_path))
        
        self.impact_analyzer = ImpactAnalyzer(str(self.project_path), jcci_analyzer=self.jcci_analyzer)
        
        self.api_endpoint_analyzer = APIEndpointAnalyzer(str(self.project_path), jcci_analyzer=self.jcci_analyzer)
        
        self._initialized = False
    
    def initialize(self, incremental: bool = False):
        if self._initialized:
            return
        
        logger.info(f"[EnhancedImpactAnalyzer] ========== 开始初始化分析器 ==========")
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤1: 初始化 JCCIAnalyzer (AST解析器)")
        self.jcci_analyzer.initialize()
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤2: 初始化 ImpactAnalyzer (影响分析器)")
        self.impact_analyzer.initialize()
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤3: 初始化 APIEndpointAnalyzer (端点分析器)")
        self.api_endpoint_analyzer.initialize()
        
        self._initialized = True
        
        logger.info(f"[EnhancedImpactAnalyzer] ========== 初始化完成 ==========")
        logger.info(f"[EnhancedImpactAnalyzer] 汇总: "
                   f"{len(self.jcci_analyzer.java_classes)} 个类, "
                   f"{len(self.impact_analyzer.call_graph)} 个方法节点, "
                   f"{len(self.api_endpoint_analyzer.controllers)} 个Controller方法")
    
    def analyze(self, commit_range: str = "HEAD~1..HEAD", max_impact_depth: int = 5) -> AnalysisResult:
        logger.info(f"[EnhancedImpactAnalyzer] ========== 开始影响分析 ==========")
        
        is_branch_mode = '..' in commit_range and not commit_range.startswith('HEAD')
        if is_branch_mode:
            parts = commit_range.split('..')
            target_branch = parts[0] if len(parts) > 0 else 'unknown'
            source_branch = parts[1] if len(parts) > 1 else 'unknown'
            logger.info(f"[EnhancedImpactAnalyzer] 分支对比模式: {source_branch} vs {target_branch}")
        else:
            logger.info(f"[EnhancedImpactAnalyzer] 提交范围: {commit_range}, 最大影响深度: {max_impact_depth}")
        
        self.initialize()
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤4: 检测变更文件")
        changed_files = self.code_change_detector.get_changed_files(commit_range)
        logger.info(f"[EnhancedImpactAnalyzer] 发现 {len(changed_files)} 个变更的Java文件")
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤5: 分析代码变更详情")
        all_changes = self.code_change_detector.analyze_all_changes(commit_range)
        total_changes = sum(len(changes) for changes in all_changes.values())
        logger.info(f"[EnhancedImpactAnalyzer] 检测到 {total_changes} 个代码变更")
        
        flat_changes = []
        for file_path, changes in all_changes.items():
            flat_changes.extend(changes)
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤6: 分析影响传播路径")
        impact_paths = self.impact_analyzer.analyze_impact(flat_changes, max_impact_depth)
        impact_summary = self.impact_analyzer.get_impact_summary(impact_paths)
        logger.info(f"[EnhancedImpactAnalyzer] 发现 {len(impact_paths)} 条影响路径")
        
        logger.info(f"[EnhancedImpactAnalyzer] 步骤7: 识别受影响的API端点")
        affected_endpoints = self.api_endpoint_analyzer.find_affected_endpoints(flat_changes, impact_paths)
        endpoint_summary = self.api_endpoint_analyzer.get_endpoint_summary(affected_endpoints)
        logger.info(f"[EnhancedImpactAnalyzer] 发现 {len(affected_endpoints)} 个受影响的API端点")
        
        logger.info(f"[EnhancedImpactAnalyzer] ========== 影响分析完成 ==========")
        
        analysis_result = AnalysisResult(
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
        
        return analysis_result
    
    def get_affected_endpoints_for_testing(self, commit_range: str = "HEAD~1..HEAD") -> List[Dict[str, str]]:
        self.initialize()
        
        analysis_result = self.analyze(commit_range)
        
        endpoints = []
        processed_endpoints = set()
        changed_controller_files = set()
        directly_modified_methods = set()
        affected_methods = set()
        
        for file_path in analysis_result.changed_files:
            if 'Controller' in file_path or 'controller' in file_path.lower():
                normalized_path = file_path.replace('/', '\\')
                changed_controller_files.add(normalized_path)
        
        logger.info(f"[EnhancedImpactAnalyzer] 变更的Controller文件: {len(changed_controller_files)} 个")
        for f in changed_controller_files:
            logger.debug(f"  - {f}")
        
        for change_dict in analysis_result.code_changes:
            if change_dict.get('element', {}).get('element_type') == 'method':
                qualified_name = change_dict['element']['qualified_name']
                directly_modified_methods.add(qualified_name)
                affected_methods.add(qualified_name)
        
        logger.info(f"[EnhancedImpactAnalyzer] 直接修改的方法: {len(directly_modified_methods)} 个")
        for m in directly_modified_methods:
            logger.debug(f"  - {m}")
        
        for impact_path in analysis_result.impact_summary.get('affected_methods', []):
            affected_methods.add(impact_path)
        
        logger.info(f"[EnhancedImpactAnalyzer] 从影响摘要获取的方法: {len(analysis_result.impact_summary.get('affected_methods', []))} 个")
        
        for modified_method in directly_modified_methods:
            callers = self._find_all_callers(modified_method, max_depth=5)
            affected_methods.update(callers)
            if callers:
                logger.debug(f"[EnhancedImpactAnalyzer] 方法 {modified_method} 的调用者: {len(callers)} 个")
        
        for modified_method in directly_modified_methods:
            callees = self._find_all_callees(modified_method, max_depth=5)
            affected_methods.update(callees)
            if callees:
                logger.debug(f"[EnhancedImpactAnalyzer] 方法 {modified_method} 调用的方法: {len(callees)} 个")
        
        logger.info(f"[EnhancedImpactAnalyzer] 受影响的方法总数: {len(affected_methods)} 个")
        
        related_controllers = self.jcci_analyzer._find_related_controllers(analysis_result.changed_files)
        for controller_file in related_controllers:
            normalized_path = controller_file.replace('/', '\\')
            if normalized_path not in changed_controller_files:
                changed_controller_files.add(normalized_path)
        
        logger.info(f"[EnhancedImpactAnalyzer] 相关Controller文件总数: {len(changed_controller_files)} 个")
        
        for controller_file in changed_controller_files:
            controller_methods = self.api_endpoint_analyzer.get_controller_methods_in_file(controller_file)
            
            for controller_method in controller_methods:
                endpoint_key = f"{controller_method.http_method} {controller_method.path}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    
                    controller_key = f"{controller_method.class_name}.{controller_method.method_name}"
                    
                    if controller_key in directly_modified_methods:
                        impact_type = 'direct_impact'
                        confidence = 1.0
                    else:
                        impact_type = 'direct_impact'
                        confidence = 1.0
                    
                    endpoint_info = {
                        'method': controller_method.http_method,
                        'path': controller_method.path,
                        'full_endpoint': f"{controller_method.http_method} {controller_method.path}",
                        'file': controller_method.file_path,
                        'impact_type': impact_type,
                        'confidence': confidence
                    }
                    endpoints.append(endpoint_info)
        
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
                
                endpoint_info = {
                    'method': endpoint['http_method'],
                    'path': endpoint['path'],
                    'full_endpoint': f"{endpoint['http_method']} {endpoint['path']}",
                    'file': endpoint['file_path'],
                    'impact_type': impact_type,
                    'confidence': confidence
                }
                endpoints.append(endpoint_info)
        
        for affected_method in affected_methods:
            controller_endpoints = self._find_controller_endpoints_for_method(affected_method)
            for endpoint_info in controller_endpoints:
                endpoint_key = f"{endpoint_info['method']} {endpoint_info['path']}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    endpoints.append(endpoint_info)
        
        logger.info(f"Total endpoints for testing: {len(endpoints)} (from {len(changed_controller_files)} changed controller files, {len(affected_methods)} affected methods)")
        
        return endpoints
    
    def _find_all_callers(self, method_key: str, max_depth: int = 5) -> Set[str]:
        callers = set()
        visited = set()
        queue = [(method_key, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            
            if depth > max_depth:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.impact_analyzer.reverse_dependency_graph:
                for caller in self.impact_analyzer.reverse_dependency_graph[current]:
                    callers.add(caller)
                    if caller not in visited:
                        queue.append((caller, depth + 1))
        
        return callers
    
    def _find_all_callees(self, method_key: str, max_depth: int = 5) -> Set[str]:
        callees = set()
        visited = set()
        queue = [(method_key, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            
            if depth > max_depth:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.impact_analyzer.dependency_graph:
                for callee in self.impact_analyzer.dependency_graph[current]:
                    callees.add(callee)
                    if callee not in visited:
                        queue.append((callee, depth + 1))
        
        return callees
    
    def _find_controller_endpoints_for_method(self, method_key: str) -> List[Dict[str, str]]:
        endpoints = []
        
        class_name = method_key.split('.')[0] if '.' in method_key else method_key
        method_name = method_key.split('.')[1] if '.' in method_key else None
        
        if not method_name:
            return endpoints
        
        for controller_key, controller_method in self.api_endpoint_analyzer.controllers.items():
            if controller_key == method_key or controller_key.endswith(f'.{method_name}'):
                impact_type = 'method_dependency'
                confidence = 0.85
                
                if controller_key in self.impact_analyzer.call_graph:
                    called_methods = self.impact_analyzer.call_graph[controller_key].called_methods
                    if method_key in called_methods:
                        impact_type = 'service_dependency'
                        confidence = 0.9
                
                endpoint_info = {
                    'method': controller_method.http_method,
                    'path': controller_method.path,
                    'full_endpoint': f"{controller_method.http_method} {controller_method.path}",
                    'file': controller_method.file_path,
                    'impact_type': impact_type,
                    'confidence': confidence
                }
                endpoints.append(endpoint_info)
        
        return endpoints
    
    def _calculate_method_dependency_impact(self, controller_key: str, directly_modified_methods: set) -> tuple:
        if not directly_modified_methods:
            return ('method_or_class_dependency', 0.6)
        
        controller_class = controller_key.split('.')[0] if '.' in controller_key else controller_key
        
        same_class_modified = False
        for modified_method in directly_modified_methods:
            modified_class = modified_method.split('.')[0] if '.' in modified_method else ""
            if modified_class == controller_class:
                same_class_modified = True
                break
        
        min_depth = float('inf')
        has_call_dependency = False
        
        for modified_method in directly_modified_methods:
            depth = self._find_reverse_call_depth(controller_key, modified_method)
            if depth is not None:
                has_call_dependency = True
                min_depth = min(min_depth, depth)
        
        if has_call_dependency:
            if min_depth == 0:
                return ('direct_impact', 1.0)
            elif min_depth == 1:
                return ('method_or_class_dependency', 0.8)
            elif min_depth == 2:
                return ('method_or_class_dependency', 0.7)
            else:
                return ('indirect_impact', max(0.5, 0.8 - (min_depth - 1) * 0.1))
        elif same_class_modified:
            return ('method_or_class_dependency', 0.65)
        else:
            return ('method_or_class_dependency', 0.6)
    
    def _find_reverse_call_depth(self, controller_method: str, modified_method: str, max_depth: int = 5) -> Optional[int]:
        if controller_method == modified_method:
            return 0
        
        visited = set()
        queue = deque([(controller_method, 0)])
        
        while queue:
            current, depth = queue.popleft()
            
            if depth > max_depth:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.impact_analyzer.call_graph:
                called_methods = self.impact_analyzer.call_graph[current].called_methods
                
                for called in called_methods:
                    if called == modified_method:
                        return depth + 1
                    
                    if called not in visited:
                        queue.append((called, depth + 1))
        
        return None
    
    def get_change_summary(self, commit_range: str = "HEAD~1..HEAD") -> Dict:
        return self.code_change_detector.get_change_summary(commit_range)
    
    def get_all_api_endpoints(self) -> List[Dict[str, str]]:
        self.initialize()
        
        all_endpoints = self.api_endpoint_analyzer.get_all_endpoints()
        
        endpoints = []
        for endpoint in all_endpoints:
            endpoint_info = {
                'method': endpoint.http_method,
                'path': endpoint.path,
                'full_endpoint': f"{endpoint.http_method} {endpoint.path}",
                'file': endpoint.file_path,
                'controller_class': endpoint.controller_class,
                'method_name': endpoint.method_name
            }
            endpoints.append(endpoint_info)
        
        return endpoints
    
    def save_analysis_report(self, output_path: str, commit_range: str = "HEAD~1..HEAD"):
        analysis_result = self.analyze(commit_range)
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        analysis_result.save_to_file(str(output_file))
        logger.info(f"Analysis report saved to {output_file}")
        
        return str(output_file)
    
    def print_summary(self, commit_range: str = "HEAD~1..HEAD"):
        analysis_result = self.analyze(commit_range)
        
        print("\n" + "="*80)
        print("JCCI增强版代码变更影响分析报告")
        print("="*80)
        print(f"\n分析时间: {analysis_result.timestamp}")
        print(f"提交范围: {analysis_result.commit_range}")
        print(f"项目路径: {analysis_result.analysis_metadata['project_path']}")
        print(f"分析器: {analysis_result.analysis_metadata.get('analyzer', 'JCCI')}")
        
        print(f"\n变更文件数: {len(analysis_result.changed_files)}")
        for file in analysis_result.changed_files:
            print(f"  - {file}")
        
        print(f"\n代码变更统计:")
        summary = analysis_result.impact_summary
        print(f"  - 直接影响: {summary.get('direct_impacts', 0)}")
        print(f"  - 方法/类依赖影响: {summary.get('method_dependency_impacts', 0)}")
        print(f"  - 间接影响: {summary.get('indirect_impacts', 0)}")
        print(f"  - 字段影响: {summary.get('field_impacts', 0)}")
        print(f"  - 受影响方法数: {len(summary.get('affected_methods', []))}")
        print(f"  - 受影响类数: {len(summary.get('affected_classes', []))}")
        
        print(f"\n影响深度分布:")
        for depth, count in summary.get('impact_by_depth', {}).items():
            print(f"  - 深度 {depth}: {count} 个影响")
        
        print(f"\nAPI端点影响:")
        endpoint_summary = analysis_result.endpoint_summary
        print(f"  - 受影响端点总数: {endpoint_summary.get('total_affected_endpoints', 0)}")
        print(f"  - 直接影响: {endpoint_summary.get('direct_modifications', 0)}")
        print(f"  - 间接影响: {endpoint_summary.get('indirect_impacts', 0)}")
        print(f"  - 服务依赖: {endpoint_summary.get('service_dependencies', 0)}")
        
        print(f"\n按HTTP方法分类:")
        for method, count in endpoint_summary.get('endpoints_by_http_method', {}).items():
            print(f"  - {method}: {count}")
        
        print(f"\n受影响的Controller:")
        for controller in endpoint_summary.get('affected_controllers', []):
            print(f"  - {controller}")
        
        print("\n" + "="*80)
        print("受影响的API端点详情:")
        print("="*80)
        
        for i, endpoint_impact in enumerate(analysis_result.affected_endpoints, 1):
            endpoint = endpoint_impact['endpoint']
            print(f"\n{i}. {endpoint['http_method']} {endpoint['path']}")
            print(f"   Controller: {endpoint['controller_class']}.{endpoint['method_name']}")
            print(f"   文件: {endpoint['file_path']}:{endpoint['line_number']}")
            print(f"   影响类型: {endpoint_impact['impact_type']}")
            print(f"   置信度: {endpoint_impact['confidence']:.2f}")
            print(f"   影响深度: {endpoint_impact.get('depth', 0)}")
            print(f"   影响路径: {' -> '.join(endpoint_impact['impact_path'])}")
        
        print("\n" + "="*80)
