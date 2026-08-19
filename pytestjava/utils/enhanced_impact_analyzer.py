"""增强版影响分析器模块

整合JCCI/Impact/APIEndpoint/CodeChange四大组件，提供完整的代码变更影响分析。
核心功能：
- 检测代码变更（Git diff + JCCI AST解析）
- 追踪影响传播链（调用图BFS遍历）
- 识别受影响的API端点（4类影响分析）
- 生成分析报告和测试建议

4类影响分析：
1. 直接变更Controller中的接口 → direct_impact
2. 影响传播链上的接口 → 根据深度计算置信度
3. 相关Controller接口 → service_dependency
4. 通过Service调用关系的Controller → service_dependency
"""
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


# 分析结果数据类，包含完整的变更影响分析结果
@dataclass
class AnalysisResult:
    timestamp: str  # 分析时间戳
    commit_range: str  # 提交范围
    changed_files: List[str]  # 变更文件列表
    code_changes: List[Dict]  # 代码变更详情
    impact_summary: Dict  # 影响摘要统计
    affected_endpoints: List[Dict]  # 受影响的API端点列表
    endpoint_summary: Dict  # 端点影响摘要
    analysis_metadata: Dict  # 分析元数据
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def save_to_file(self, file_path: str):
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


class EnhancedImpactAnalyzer:
    """增强版影响分析器 - 整合JCCI/Impact/APIEndpoint/CodeChange四大组件"""
    
    def __init__(self, repo_path: str, project_path: str = None):
        """初始化增强版影响分析器
        
        参数:
            repo_path: Git仓库路径
            project_path: Java项目路径（默认与repo_path相同）
        """
        self.repo_path = Path(repo_path).resolve()
        self.project_path = Path(project_path).resolve() if project_path else self.repo_path
        
        self.jcci_analyzer = JCCIAnalyzer(str(self.project_path))
        self.code_change_detector = CodeChangeDetector(str(self.repo_path), str(self.project_path))
        self.impact_analyzer = ImpactAnalyzer(str(self.project_path), jcci_analyzer=self.jcci_analyzer)
        self.api_endpoint_analyzer = APIEndpointAnalyzer(str(self.project_path), jcci_analyzer=self.jcci_analyzer)
        
        self._initialized = False
    
    def initialize(self):
        """初始化所有分析组件（JCCI/Impact/APIEndpoint）"""
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
        """执行完整的影响分析流程
        
        流程: 变更检测 → 代码变更分析 → 影响传播追踪 → 端点影响识别
        参数:
            commit_range: Git提交范围
            max_impact_depth: 最大影响传播深度
        """
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
        """获取需要测试的受影响API端点列表（4类影响分析）
        
        4类影响:
        1. 直接变更Controller文件中的所有接口
        2. 影响传播链上的接口
        3. 相关Controller中的接口
        4. 通过变更类名查找直接关联的Controller接口
        """
        self.initialize()
        
        analysis_result = self.analyze(commit_range)
        
        processed_endpoints = set()
        endpoints = []
        
        # ===== 第一类：变更Controller文件中的所有接口 =====
        changed_controller_files = set()
        for file_path in analysis_result.changed_files:
            normalized = file_path.replace('/', '\\')
            for prefix in ['campus-master\\', 'campus-master/']:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break
            # 判断是否Controller文件 - 不仅靠文件名，也通过JCCI分析结果判断
            changed_controller_files.add(normalized)
        
        # 通过JCCI查找变更文件对应的类
        changed_class_names = set()
        for file_path in analysis_result.changed_files:
            normalized = file_path.replace('/', '\\')
            for prefix in ['campus-master\\', 'campus-master/']:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break
            # 查找这个文件路径对应的类
            for class_name, class_info in self.jcci_analyzer.java_classes.items():
                class_file = class_info.file_path.replace('/', '\\')
                if class_file == normalized or normalized.endswith(class_file) or class_file.endswith(normalized):
                    changed_class_names.add(class_name)
        
        # 收集所有变更方法（从code_changes中获取）
        directly_modified_methods = set()
        for change_dict in analysis_result.code_changes:
            if change_dict.get('element', {}).get('element_type') == 'method':
                directly_modified_methods.add(change_dict['element']['qualified_name'])
        
        # 扩展：通过变更文件路径查找该文件中所有方法（不仅是code_changes中检测到的）
        all_methods_in_changed_files = set()
        for class_name in changed_class_names:
            class_info = self.jcci_analyzer.java_classes.get(class_name)
            if class_info:
                for method_name in class_info.methods:
                    method_key = f"{class_name}.{method_name}"
                    all_methods_in_changed_files.add(method_key)
        
        logger.info(f"[EnhancedImpactAnalyzer] 变更类: {changed_class_names}")
        logger.info(f"[EnhancedImpactAnalyzer] 变更类中所有方法: {len(all_methods_in_changed_files)} 个")
        logger.info(f"[EnhancedImpactAnalyzer] 直接修改方法: {len(directly_modified_methods)} 个")
        
        # ===== 第二类：影响传播链上的接口 =====
        # 收集所有受影响的方法（变更方法 + 调用者 + 被调用者）
        affected_methods = set(all_methods_in_changed_files)
        for method_key in all_methods_in_changed_files:
            for caller, d in self.impact_analyzer.find_callers(method_key, depth=5):
                affected_methods.add(caller)
            for callee, d in self.impact_analyzer.find_callees(method_key, depth=5):
                affected_methods.add(callee)
        
        # ===== 第三类：相关Controller接口 =====
        related_controllers = self.jcci_analyzer._find_related_controllers(analysis_result.changed_files)
        for controller_file in related_controllers:
            normalized = controller_file.replace('/', '\\')
            for prefix in ['campus-master\\', 'campus-master/']:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break
            changed_controller_files.add(normalized)
        
        # 处理变更Controller文件中的所有接口
        for controller_file in changed_controller_files:
            controller_methods = self.api_endpoint_analyzer.get_controller_methods_in_file(controller_file)
            for cm in controller_methods:
                endpoint_key = f"{cm.http_method} {cm.path}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    controller_key = f"{cm.class_name}.{cm.method_name}"
                    if controller_key in directly_modified_methods:
                        impact_type, confidence = 'direct_impact', 1.0
                    elif controller_key in all_methods_in_changed_files:
                        impact_type, confidence = 'direct_impact', 0.95
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
        
        # 处理APIEndpointAnalyzer检测到的影响端点
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
        
        # 处理受影响方法对应的Controller端点
        for affected_method in affected_methods:
            for ep in self._find_controller_endpoints_for_method(affected_method):
                endpoint_key = f"{ep['method']} {ep['path']}"
                if endpoint_key not in processed_endpoints:
                    processed_endpoints.add(endpoint_key)
                    endpoints.append(ep)
        
        # ===== 第四类：通过变更类名查找直接关联的Controller =====
        # 遍历所有Controller，如果Controller调用了变更类的方法，则该Controller的所有端点都受影响
        for class_name in changed_class_names:
            class_info = self.jcci_analyzer.java_classes.get(class_name)
            if class_info and not class_info.is_controller:
                # 变更的是Service/Component类，查找调用了该类的Controller
                for controller_key, cm in self.api_endpoint_analyzer.controllers.items():
                    # 检查Controller方法是否调用了变更类的方法
                    for called_method in cm.called_methods:
                        if called_method.startswith(f"{class_name}."):
                            endpoint_key = f"{cm.http_method} {cm.path}"
                            if endpoint_key not in processed_endpoints:
                                processed_endpoints.add(endpoint_key)
                                endpoints.append({
                                    'method': cm.http_method,
                                    'path': cm.path,
                                    'full_endpoint': f"{cm.http_method} {cm.path}",
                                    'file': cm.file_path,
                                    'impact_type': 'service_dependency',
                                    'confidence': 0.9
                                })
                            break
        
        logger.info(f"[EnhancedImpactAnalyzer] 受影响端点: {len(endpoints)} 个")
        return endpoints
    
    def _find_controller_endpoints_for_method(self, method_key: str) -> List[Dict[str, str]]:
        """根据方法键查找对应的Controller端点，支持接口→实现类映射"""
        endpoints = []
        if '.' not in method_key:
            return endpoints
        
        class_name = method_key.rsplit('.', 1)[0]
        method_name = method_key.rsplit('.', 1)[1]
        
        # 查找接口对应的实现类（如ISysMenuService -> SysMenuServiceImpl）
        impl_class_name = self._resolve_implementation_class(class_name)
        search_class_names = {class_name}
        if impl_class_name and impl_class_name != class_name:
            search_class_names.add(impl_class_name)
        
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
                # 精确匹配
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
                else:
                    # 模糊匹配：检查接口/实现类的方法调用
                    found = False
                    for search_class in search_class_names:
                        search_key = f"{search_class}.{method_name}"
                        if search_key in called_methods:
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
                            found = True
                            break
                    if not found:
                        # 更宽松的匹配：方法名相同
                        if any(called.endswith(f'.{method_name}') for called in called_methods):
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
    
    def _resolve_implementation_class(self, class_name: str) -> Optional[str]:
        """通过implements关系查找接口的实现类"""
        for cn, class_info in self.jcci_analyzer.java_classes.items():
            if class_info.implements:
                for impl in class_info.implements:
                    if impl == class_name:
                        return cn
        return None
    
    def get_change_summary(self, commit_range: str = "HEAD~1..HEAD") -> Dict:
        """获取代码变更摘要信息"""
        return self.code_change_detector.get_change_summary(commit_range)
    
    def save_analysis_report(self, output_path: str, commit_range: str = "HEAD~1..HEAD"):
        """保存分析报告到JSON文件"""
        analysis_result = self.analyze(commit_range)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        analysis_result.save_to_file(str(output_file))
        logger.info(f"Analysis report saved to {output_file}")
        return str(output_file)
