import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque

from .jcci_analyzer import JavaElement, CodeChange, ChangeType, JavaClassInfo, JavaMethodInfo, JavaFieldInfo, ImpactNode

logger = logging.getLogger(__name__)


@dataclass
class CallNode:
    class_name: str
    method_name: str
    file_path: str
    line_number: int
    called_methods: List[str] = field(default_factory=list)
    called_by: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            'class_name': self.class_name,
            'method_name': self.method_name,
            'file_path': self.file_path,
            'line_number': self.line_number,
            'called_methods': self.called_methods,
            'called_by': self.called_by
        }


@dataclass
class DependencyEdge:
    from_node: str
    to_node: str
    edge_type: str
    file_path: str
    line_number: int
    
    def to_dict(self) -> Dict:
        return {
            'from_node': self.from_node,
            'to_node': self.to_node,
            'edge_type': self.edge_type,
            'file_path': self.file_path,
            'line_number': self.line_number
        }


@dataclass
class ImpactPath:
    start_element: JavaElement
    end_element: JavaElement
    path: List[str]
    impact_type: str
    confidence: float
    depth: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'start_element': self.start_element.to_dict(),
            'end_element': self.end_element.to_dict(),
            'path': self.path,
            'impact_type': self.impact_type,
            'confidence': self.confidence,
            'depth': self.depth
        }


class ImpactAnalyzer:
    """使用JCCI调用图分析的增强版影响分析器
    
    通过以下方式分析代码变更影响的传播:
    - 调用图遍历
    - 依赖链追踪
    - 基于深度的置信度计算
    """
    
    def __init__(self, project_path: str, jcci_analyzer=None):
        self.project_path = Path(project_path).resolve()
        self.jcci = jcci_analyzer
        self.call_graph: Dict[str, CallNode] = {}
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_dependency_graph: Dict[str, Set[str]] = defaultdict(set)
        self.class_to_file: Dict[str, str] = {}
        self.method_to_class: Dict[str, str] = {}
        self.class_methods: Dict[str, Set[str]] = defaultdict(set)
        self._initialized = False
    
    def initialize(self):
        if self._initialized:
            return
        
        if self.jcci:
            self._build_from_jcci()
        else:
            self._build_call_graph()
        
        self._build_reverse_dependencies()
        self._initialized = True
        logger.info(f"[ImpactAnalyzer] 初始化完成: {len(self.call_graph)} 个方法节点, {len(self.class_to_file)} 个类, {sum(len(deps) for deps in self.dependency_graph.values())} 个依赖关系")
    
    def _build_from_jcci(self):
        logger.info(f"[ImpactAnalyzer] 从JCCI构建调用图...")
        
        if not self.jcci._initialized:
            self.jcci.initialize()
        
        method_count = 0
        dependency_count = 0
        
        for class_name, class_info in self.jcci.java_classes.items():
            self.class_to_file[class_name] = class_info.file_path
            
            for method_name, method_info in class_info.methods.items():
                node_key = f"{class_name}.{method_name}"
                self.method_to_class[node_key] = class_name
                self.class_methods[class_name].add(node_key)
                
                self.call_graph[node_key] = CallNode(
                    class_name=class_name,
                    method_name=method_name,
                    file_path=class_info.file_path,
                    line_number=method_info.line_start,
                    called_methods=method_info.called_methods
                )
                method_count += 1
                
                for called_method in method_info.called_methods:
                    self.dependency_graph[node_key].add(called_method)
                    dependency_count += 1
        
        logger.info(f"[ImpactAnalyzer] 调用图构建完成: {method_count} 个方法, {dependency_count} 个依赖关系")
    
    def _build_call_graph(self):
        java_files = list(self.project_path.rglob("*.java"))
        java_files = [f for f in java_files if "target" not in str(f) and "build" not in str(f)]
        
        logger.info(f"Building call graph from {len(java_files)} Java files")
        
        for java_file in java_files:
            try:
                self._analyze_file(java_file)
            except Exception as e:
                logger.error(f"Error analyzing {java_file}: {e}")
    
    def _analyze_file(self, java_file: Path):
        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Error reading {java_file}: {e}")
            return
        
        class_name = self._extract_class_name(content)
        if not class_name:
            return
        
        self.class_to_file[class_name] = str(java_file.relative_to(self.project_path))
        
        methods = self._extract_methods(content, class_name)
        
        for method_sig, method_info in methods.items():
            node_key = f"{class_name}.{method_info['name']}"
            self.method_to_class[node_key] = class_name
            self.class_methods[class_name].add(node_key)
            
            called_methods = self._extract_method_calls(method_info['body'], class_name)
            
            self.call_graph[node_key] = CallNode(
                class_name=class_name,
                method_name=method_info['name'],
                file_path=str(java_file.relative_to(self.project_path)),
                line_number=method_info['line_number'],
                called_methods=called_methods
            )
            
            for called_method in called_methods:
                self.dependency_graph[node_key].add(called_method)
    
    def _extract_class_name(self, content: str) -> Optional[str]:
        pattern = r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?class\s+(\w+)'
        match = re.search(pattern, content)
        return match.group(1) if match else None
    
    def _extract_methods(self, content: str, class_name: str) -> Dict[str, Dict]:
        methods = {}
        
        method_pattern = r'(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(?:\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\(([^)]*)\)(?:\s+throws\s+[\w\s,]+)?\s*\{'
        
        for match in re.finditer(method_pattern, content):
            method_name = match.group(1)
            
            if method_name in ['if', 'for', 'while', 'switch', 'catch', 'class', 'interface']:
                continue
            
            line_number = content[:match.start()].count('\n') + 1
            
            body_start = match.end()
            body_end = self._find_method_end(content, body_start)
            body = content[body_start:body_end]
            
            methods[method_name] = {
                'name': method_name,
                'line_number': line_number,
                'body': body
            }
        
        return methods
    
    def _find_method_end(self, content: str, start: int) -> int:
        brace_count = 1
        pos = start
        
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        
        return pos
    
    def _extract_method_calls(self, method_body: str, current_class: str) -> List[str]:
        calls = []
        
        patterns = [
            r'(\w+)\s*\.\s*(\w+)\s*\(',
            r'(\w+)\s*\(',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, method_body):
                if len(match.groups()) == 2:
                    object_name = match.group(1)
                    method_name = match.group(2)
                    
                    if object_name in ['this', 'super']:
                        calls.append(f"{current_class}.{method_name}")
                    elif object_name[0].isupper():
                        calls.append(f"{object_name}.{method_name}")
                    else:
                        calls.append(f"{object_name}.{method_name}")
                else:
                    method_name = match.group(1)
                    if method_name not in ['if', 'for', 'while', 'switch', 'catch', 'return', 'new', 'throw']:
                        calls.append(f"{current_class}.{method_name}")
        
        return list(set(calls))
    
    def _build_reverse_dependencies(self):
        for node_key, node in self.call_graph.items():
            for called_method in node.called_methods:
                self.reverse_dependency_graph[called_method].add(node_key)
    
    def find_callers(self, method_key: str, depth: int = 5) -> List[Tuple[str, int]]:
        callers = []
        visited = set()
        queue = deque([(method_key, 0)])
        
        while queue:
            current, current_depth = queue.popleft()
            
            if current_depth > depth:
                break
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.reverse_dependency_graph:
                for caller in self.reverse_dependency_graph[current]:
                    if caller not in visited:
                        callers.append((caller, current_depth + 1))
                        queue.append((caller, current_depth + 1))
        
        return callers
    
    def find_callees(self, method_key: str, depth: int = 5) -> List[Tuple[str, int]]:
        callees = []
        visited = set()
        queue = deque([(method_key, 0)])
        
        while queue:
            current, current_depth = queue.popleft()
            
            if current_depth > depth:
                break
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.call_graph:
                for callee in self.call_graph[current].called_methods:
                    if callee not in visited:
                        callees.append((callee, current_depth + 1))
                        queue.append((callee, current_depth + 1))
        
        return callees
    
    def analyze_impact(self, changes: List[CodeChange], max_depth: int = 5) -> List[ImpactPath]:
        self.initialize()
        
        impact_paths = []
        
        for change in changes:
            if change.element.element_type == 'method':
                method_key = change.element.qualified_name
                
                callers = self.find_callers(method_key, max_depth)
                
                for caller_key, depth in callers:
                    if caller_key in self.call_graph:
                        caller_node = self.call_graph[caller_key]
                        
                        caller_element = JavaElement(
                            element_type="method",
                            name=caller_node.method_name,
                            qualified_name=caller_key,
                            file_path=caller_node.file_path,
                            line_number=caller_node.line_number,
                            signature=f"{caller_node.method_name}()"
                        )
                        
                        impact_type, confidence = self._calculate_impact_type_and_confidence(
                            depth, 
                            change.change_type,
                            caller_key,
                            method_key
                        )
                        
                        impact_path = ImpactPath(
                            start_element=change.element,
                            end_element=caller_element,
                            path=[method_key, caller_key],
                            impact_type=impact_type,
                            confidence=confidence,
                            depth=depth
                        )
                        impact_paths.append(impact_path)
            
            elif change.element.element_type == 'field':
                field_name = change.element.name
                class_name = change.element.qualified_name.split('.')[0]
                
                for node_key, node in self.call_graph.items():
                    if node.class_name == class_name:
                        file_path = self.class_to_file.get(class_name, "")
                        
                        try:
                            with open(self.project_path / file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            
                            if field_name in content:
                                caller_element = JavaElement(
                                    element_type="method",
                                    name=node.method_name,
                                    qualified_name=node_key,
                                    file_path=file_path,
                                    line_number=node.line_number,
                                    signature=f"{node.method_name}()"
                                )
                                
                                impact_path = ImpactPath(
                                    start_element=change.element,
                                    end_element=caller_element,
                                    path=[change.element.qualified_name, node_key],
                                    impact_type="field_usage",
                                    confidence=0.8,
                                    depth=1
                                )
                                impact_paths.append(impact_path)
                        except Exception:
                            pass
        
        return impact_paths
    
    def _calculate_impact_type_and_confidence(self, depth: int, change_type: ChangeType, caller_key: str, changed_method: str) -> Tuple[str, float]:
        if depth == 1:
            return ('direct_impact', 1.0)
        elif depth == 2:
            caller_class = caller_key.split('.')[0]
            changed_class = changed_method.split('.')[0]
            
            if caller_class == changed_class:
                return ('method_or_class_dependency', 0.85)
            else:
                return ('method_or_class_dependency', 0.8)
        elif depth == 3:
            return ('indirect_impact', 0.7)
        elif depth == 4:
            return ('indirect_impact', 0.6)
        else:
            return ('indirect_impact', max(0.5, 0.9 - depth * 0.1))
    
    def get_impact_summary(self, impact_paths: List[ImpactPath]) -> Dict:
        summary = {
            'total_impacts': len(impact_paths),
            'direct_impacts': 0,
            'indirect_impacts': 0,
            'method_dependency_impacts': 0,
            'field_impacts': 0,
            'affected_methods': set(),
            'affected_classes': set(),
            'impact_by_depth': defaultdict(int),
            'impact_by_type': defaultdict(int)
        }
        
        for path in impact_paths:
            if path.impact_type == 'direct_impact':
                summary['direct_impacts'] += 1
            elif path.impact_type == 'indirect_impact':
                summary['indirect_impacts'] += 1
            elif path.impact_type == 'method_or_class_dependency':
                summary['method_dependency_impacts'] += 1
            elif path.impact_type == 'field_usage':
                summary['field_impacts'] += 1
            
            summary['affected_methods'].add(path.end_element.qualified_name)
            summary['affected_classes'].add(path.end_element.qualified_name.split('.')[0])
            
            summary['impact_by_depth'][path.depth] += 1
            summary['impact_by_type'][path.impact_type] += 1
        
        summary['affected_methods'] = list(summary['affected_methods'])
        summary['affected_classes'] = list(summary['affected_classes'])
        summary['impact_by_depth'] = dict(summary['impact_by_depth'])
        summary['impact_by_type'] = dict(summary['impact_by_type'])
        
        return summary
    
    def find_affected_controllers(self, impact_paths: List[ImpactPath]) -> List[str]:
        affected_controllers = []
        
        for path in impact_paths:
            end_method = path.end_element.qualified_name
            class_name = end_method.split('.')[0]
            
            file_path = self.class_to_file.get(class_name, "")
            if not file_path:
                continue
            
            full_path = self.project_path / file_path
            if not full_path.exists():
                continue
            
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if any(ann in content for ann in ['@RestController', '@Controller']):
                    if any(ann in content for ann in ['@GetMapping', '@PostMapping', '@PutMapping', '@DeleteMapping', '@RequestMapping']):
                        affected_controllers.append(end_method)
            except Exception:
                pass
        
        return list(set(affected_controllers))
    
    def get_methods_in_class(self, class_name: str) -> Set[str]:
        return self.class_methods.get(class_name, set())
    
    def get_call_chain_depth(self, from_method: str, to_method: str, max_depth: int = 10) -> Optional[int]:
        if from_method == to_method:
            return 0
        
        visited = set()
        queue = deque([(from_method, 0)])
        
        while queue:
            current, depth = queue.popleft()
            
            if depth > max_depth:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.call_graph:
                for called in self.call_graph[current].called_methods:
                    if called == to_method:
                        return depth + 1
                    if called not in visited:
                        queue.append((called, depth + 1))
        
        return None
