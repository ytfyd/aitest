"""影响传播分析器模块

基于JCCI调用图分析代码变更的影响传播路径，通过BFS遍历查找
变更方法的调用者和被调用者，计算影响置信度。
"""

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
    """调用图节点，表示一个方法及其调用关系"""
    class_name: str          # 类名
    method_name: str         # 方法名
    file_path: str           # 文件路径
    line_number: int         # 行号
    called_methods: List[str] = field(default_factory=list)  # 该方法调用的其他方法列表
    called_by: List[str] = field(default_factory=list)       # 调用该方法的方法列表
    
    def to_dict(self) -> Dict:
        """将调用节点转换为字典格式"""
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
    """依赖边，表示两个方法之间的依赖关系"""
    from_node: str    # 调用方方法全限定名
    to_node: str      # 被调用方方法全限定名
    edge_type: str    # 依赖类型（如 method_call, field_access）
    file_path: str    # 文件路径
    line_number: int  # 行号
    
    def to_dict(self) -> Dict:
        """将依赖边转换为字典格式"""
        return {
            'from_node': self.from_node,
            'to_node': self.to_node,
            'edge_type': self.edge_type,
            'file_path': self.file_path,
            'line_number': self.line_number
        }


@dataclass
class ImpactPath:
    """影响路径，从变更代码到受影响代码的传播路径"""
    start_element: JavaElement  # 变更起始元素
    end_element: JavaElement    # 受影响的终止元素
    path: List[str]             # 传播路径上的方法全限定名列表
    impact_type: str            # 影响类型（direct_impact / indirect_impact / method_or_class_dependency / field_usage）
    confidence: float           # 影响置信度（0-1）
    depth: int = 0              # 传播深度
    
    def to_dict(self) -> Dict:
        """将影响路径转换为字典格式"""
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
    - 调用图遍历（BFS广度优先搜索）
    - 依赖链追踪（正向和反向依赖）
    - 基于深度的置信度计算
    
    使用方式:
        analyzer = ImpactAnalyzer(project_path, jcci_analyzer=jcci)
        analyzer.initialize()
        impact_paths = analyzer.analyze_impact(code_changes)
    """
    
    def __init__(self, project_path: str, jcci_analyzer=None):
        """初始化影响分析器
        
        参数:
            project_path: Java项目根路径
            jcci_analyzer: JCCI分析器实例（可选，优先使用）
        """
        self.project_path = Path(project_path).resolve()
        self.jcci = jcci_analyzer
        self.call_graph: Dict[str, CallNode] = {}                              # 方法全限定名 → CallNode
        self.dependency_graph: Dict[str, Set[str]] = defaultdict(set)          # 方法 → 它依赖的方法集合
        self.reverse_dependency_graph: Dict[str, Set[str]] = defaultdict(set)  # 方法 → 依赖它的方法集合
        self.class_to_file: Dict[str, str] = {}                                # 类名 → 文件路径
        self.method_to_class: Dict[str, str] = {}                              # 方法全限定名 → 所属类名
        self.class_methods: Dict[str, Set[str]] = defaultdict(set)             # 类名 → 该类的方法集合
        self._initialized = False
    
    def initialize(self):
        """初始化分析器，构建调用图和依赖关系索引"""
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
        """从JCCI分析结果构建调用图（优先使用JCCI AST解析结果）"""
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
        """通过正则表达式扫描Java文件构建调用图（JCCI不可用时的降级方案）"""
        java_files = list(self.project_path.rglob("*.java"))
        java_files = [f for f in java_files if "target" not in str(f) and "build" not in str(f)]
        
        logger.info(f"Building call graph from {len(java_files)} Java files")
        
        for java_file in java_files:
            try:
                self._analyze_file(java_file)
            except Exception as e:
                logger.error(f"Error analyzing {java_file}: {e}")
    
    def _analyze_file(self, java_file: Path):
        """分析单个Java文件，提取类和方法调用关系
        
        参数:
            java_file: Java文件路径
        """
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
        """从Java文件内容中提取类名
        
        参数:
            content: Java文件内容
            
        返回:
            类名字符串，未找到则返回None
        """
        pattern = r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?class\s+(\w+)'
        match = re.search(pattern, content)
        return match.group(1) if match else None
    
    def _extract_methods(self, content: str, class_name: str) -> Dict[str, Dict]:
        """从Java文件内容中提取所有方法签名和方法体
        
        参数:
            content: Java文件内容
            class_name: 所属类名
            
        返回:
            方法名字典 {method_name: {name, line_number, body}}
        """
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
        """通过括号匹配找到方法体的结束位置
        
        参数:
            content: 文件内容
            start: 方法体开始位置（左括号之后）
            
        返回:
            方法体结束位置索引
        """
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
        """从方法体中提取所有方法调用
        
        参数:
            method_body: 方法体代码字符串
            current_class: 当前类名
            
        返回:
            被调用的方法全限定名列表（去重）
        """
        calls = []
        
        patterns = [
            r'(\w+)\s*\.\s*(\w+)\s*\(',   # 对象方法调用: obj.method()
            r'(\w+)\s*\(',                  # 直接方法调用: method()
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
        """构建反向依赖索引：被调用方法 → 调用它的方法集合"""
        for node_key, node in self.call_graph.items():
            for called_method in node.called_methods:
                self.reverse_dependency_graph[called_method].add(node_key)
    
    def find_callers(self, method_key: str, depth: int = 5) -> List[Tuple[str, int]]:
        """查找谁调用了指定方法（向上传播，BFS）
        
        参数:
            method_key: 方法全限定名（如 "SysMenuServiceImpl.selectMenuList"）
            depth: 最大传播深度，默认5层
            
        返回:
            调用者列表 [(调用方方法全限定名, 传播深度), ...]
        """
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
        """查找指定方法调用了谁（向下传播，BFS）
        
        参数:
            method_key: 方法全限定名
            depth: 最大传播深度，默认5层
            
        返回:
            被调用者列表 [(被调用方法全限定名, 传播深度), ...]
        """
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
        """分析代码变更的影响传播路径
        
        对每个变更的方法，通过BFS查找其调用者，构建影响路径；
        对每个变更的字段，查找同类中使用该字段的方法。
        
        参数:
            changes: 代码变更列表
            max_depth: 最大影响传播深度，默认5层
            
        返回:
            影响路径列表
        """
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
                # 字段变更：查找同类中使用该字段的方法
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
        """根据传播深度和变更类型计算影响类型和置信度
        
        参数:
            depth: 传播深度（1=直接调用，2=间接调用...）
            change_type: 变更类型（ADDED/MODIFIED/DELETED）
            caller_key: 调用方方法全限定名
            changed_method: 变更方法全限定名
            
        返回:
            (影响类型, 置信度) 元组
        """
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
        """生成影响分析摘要统计
        
        参数:
            impact_paths: 影响路径列表
            
        返回:
            包含各类影响统计的字典
        """
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
        """从影响路径中找到受影响的Controller方法
        
        通过检查受影响方法所属类是否包含@RestController/@Controller和
        HTTP映射注解来识别Controller端点。
        
        参数:
            impact_paths: 影响路径列表
            
        返回:
            受影响的Controller方法全限定名列表（去重）
        """
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
        """获取指定类中的所有方法全限定名
        
        参数:
            class_name: 类名
            
        返回:
            方法全限定名集合
        """
        return self.class_methods.get(class_name, set())
    
    def get_call_chain_depth(self, from_method: str, to_method: str, max_depth: int = 10) -> Optional[int]:
        """计算两个方法之间的调用链深度（BFS）
        
        参数:
            from_method: 起始方法全限定名
            to_method: 目标方法全限定名
            max_depth: 最大搜索深度，默认10
            
        返回:
            调用链深度（0表示同一方法），不可达返回None
        """
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
