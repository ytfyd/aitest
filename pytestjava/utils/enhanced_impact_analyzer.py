import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

from .code_change_detector import CodeChangeDetector
from .impact_analyzer import ImpactAnalyzer
from .api_endpoint_analyzer import APIEndpointAnalyzer
from .spoon_analyzer import CodeChange, ChangeType, APIEndpoint

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
    """Enhanced impact analyzer using Spoon framework for comprehensive analysis"""
    
    def __init__(self, repo_path: str, project_path: str = None):
        self.repo_path = Path(repo_path).resolve()
        self.project_path = Path(project_path).resolve() if project_path else self.repo_path
        
        logger.info(f"Initializing EnhancedImpactAnalyzer for {self.project_path}")
        
        self.code_change_detector = CodeChangeDetector(str(self.repo_path), str(self.project_path))
        self.impact_analyzer = ImpactAnalyzer(str(self.project_path))
        self.api_endpoint_analyzer = APIEndpointAnalyzer(str(self.project_path))
    
    def analyze(self, commit_range: str = "HEAD~1..HEAD", max_impact_depth: int = 5) -> AnalysisResult:
        """Perform comprehensive impact analysis"""
        logger.info(f"Starting impact analysis for commit range: {commit_range}")
        
        changed_files = self.code_change_detector.get_changed_files(commit_range)
        logger.info(f"Found {len(changed_files)} changed Java files")
        
        all_changes = self.code_change_detector.analyze_all_changes(commit_range)
        logger.info(f"Detected {sum(len(changes) for changes in all_changes.values())} code changes")
        
        flat_changes = []
        for file_path, changes in all_changes.items():
            flat_changes.extend(changes)
        
        impact_paths = self.impact_analyzer.analyze_impact(flat_changes, max_impact_depth)
        impact_summary = self.impact_analyzer.get_impact_summary(impact_paths)
        logger.info(f"Found {len(impact_paths)} impact paths")
        
        affected_endpoints = self.api_endpoint_analyzer.find_affected_endpoints(flat_changes, impact_paths)
        endpoint_summary = self.api_endpoint_analyzer.get_endpoint_summary(affected_endpoints)
        logger.info(f"Found {len(affected_endpoints)} affected API endpoints")
        
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
                'repo_path': str(self.repo_path)
            }
        )
        
        return analysis_result
    
    def get_affected_endpoints_for_testing(self, commit_range: str = "HEAD~1..HEAD") -> List[Dict[str, str]]:
        """Get affected endpoints in a format suitable for test generation"""
        analysis_result = self.analyze(commit_range)
        
        endpoints = []
        for endpoint_impact in analysis_result.affected_endpoints:
            endpoint = endpoint_impact['endpoint']
            
            endpoint_info = {
                'method': endpoint['http_method'],
                'path': endpoint['path'],
                'full_endpoint': f"{endpoint['http_method']} {endpoint['path']}",
                'file': endpoint['file_path'],
                'impact_type': endpoint_impact['impact_type'],
                'confidence': endpoint_impact['confidence']
            }
            endpoints.append(endpoint_info)
        
        return endpoints
    
    def get_change_summary(self, commit_range: str = "HEAD~1..HEAD") -> Dict:
        """Get a summary of changes without full impact analysis"""
        return self.code_change_detector.get_change_summary(commit_range)
    
    def get_all_api_endpoints(self) -> List[Dict[str, str]]:
        """Get all API endpoints in the project"""
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
        """Save detailed analysis report to a JSON file"""
        analysis_result = self.analyze(commit_range)
        
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        analysis_result.save_to_file(str(output_file))
        logger.info(f"Analysis report saved to {output_file}")
        
        return str(output_file)
    
    def print_summary(self, commit_range: str = "HEAD~1..HEAD"):
        """Print a human-readable summary of the analysis"""
        analysis_result = self.analyze(commit_range)
        
        print("\n" + "="*80)
        print("增强版代码变更影响分析报告")
        print("="*80)
        print(f"\n分析时间: {analysis_result.timestamp}")
        print(f"提交范围: {analysis_result.commit_range}")
        print(f"项目路径: {analysis_result.analysis_metadata['project_path']}")
        
        print(f"\n变更文件数: {len(analysis_result.changed_files)}")
        for file in analysis_result.changed_files:
            print(f"  - {file}")
        
        print(f"\n代码变更统计:")
        summary = analysis_result.impact_summary
        print(f"  - 新增方法: {summary.get('added_methods', 0)}")
        print(f"  - 修改方法: {summary.get('modified_methods', 0)}")
        print(f"  - 删除方法: {summary.get('deleted_methods', 0)}")
        print(f"  - 新增字段: {summary.get('added_fields', 0)}")
        print(f"  - 修改字段: {summary.get('modified_fields', 0)}")
        print(f"  - 删除字段: {summary.get('deleted_fields', 0)}")
        
        print(f"\n影响分析:")
        print(f"  - 直接影响: {summary.get('direct_impacts', 0)}")
        print(f"  - 间接影响: {summary.get('indirect_impacts', 0)}")
        print(f"  - 字段影响: {summary.get('field_impacts', 0)}")
        print(f"  - 受影响方法数: {len(summary.get('affected_methods', []))}")
        print(f"  - 受影响类数: {len(summary.get('affected_classes', []))}")
        
        print(f"\nAPI端点影响:")
        endpoint_summary = analysis_result.endpoint_summary
        print(f"  - 受影响端点总数: {endpoint_summary.get('total_affected_endpoints', 0)}")
        print(f"  - 直接修改: {endpoint_summary.get('direct_modifications', 0)}")
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
            print(f"   影响路径: {' -> '.join(endpoint_impact['impact_path'])}")
        
        print("\n" + "="*80)
