"""JCCI (Java Code Commit Impact) 分析器模块

基于javalang的Java AST解析器，用于构建调用图并追踪代码变更影响。
核心功能：
- 使用javalang进行Java AST解析，提取类、方法、字段信息
- 使用unidiff进行Git差异解析
- 构建方法调用图（正向和反向），用于影响传播分析
- 从变更代码追踪影响到Controller层API端点
- 支持超级优化模式（缓存、多线程、增量扫描等6大策略）

主要数据结构：
- JavaClassInfo: Java类信息（包名、注解、方法、字段等）
- JavaMethodInfo: 方法信息（参数、返回值、调用关系、API路径等）
- JavaFieldInfo: 字段信息（类型、注解等）
- DiffResult: Git差异结果（新增行、删除行、变更方法等）
- ImpactNode: 影响节点（影响类型、深度、子节点等）
"""
import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

try:
    import javalang
    JAVALANG_AVAILABLE = True
except ImportError:
    JAVALANG_AVAILABLE = False
    logging.warning("javalang not installed. Install with: pip install javalang")

try:
    from unidiff import PatchSet
    UNIDIFF_AVAILABLE = True
except ImportError:
    UNIDIFF_AVAILABLE = False
    logging.warning("unidiff not installed. Install with: pip install unidiff")

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# 导入性能优化模块
try:
    from .performance_optimizer import PerformanceOptimizer, get_performance_optimizer
    OPTIMIZER_AVAILABLE = True
except ImportError:
    OPTIMIZER_AVAILABLE = False
    logging.warning("性能优化模块不可用，将使用标准扫描模式")


logger = logging.getLogger(__name__)


# 代码变更类型枚举
class ChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


# Java元素（类、方法、字段）的基本信息
@dataclass
class JavaElement:
    element_type: str  # 元素类型（class/method/field）
    name: str  # 元素名称
    qualified_name: str  # 限定名（类名.方法名）
    file_path: str  # 文件路径
    line_number: int  # 行号
    signature: str  # 方法签名
    annotations: List[str] = field(default_factory=list)  # 注解列表
    
    def to_dict(self) -> Dict:
        return asdict(self)


# 代码变更记录，包含变更类型和变更前后的元素信息
@dataclass
class CodeChange:
    change_type: ChangeType  # 变更类型
    element: JavaElement  # 变更后的元素
    old_element: Optional[JavaElement] = None  # 变更前的元素
    diff_content: str = ""  # 差异内容
    
    def to_dict(self) -> Dict:
        result = {
            'change_type': self.change_type.value,
            'element': self.element.to_dict(),
            'diff_content': self.diff_content
        }
        if self.old_element:
            result['old_element'] = self.old_element.to_dict()
        return result


# API端点信息，描述一个HTTP接口
@dataclass
class APIEndpoint:
    method: str  # 接口标识（如 "GET /api/list"）
    path: str  # API路径
    http_method: str  # HTTP方法（GET/POST/PUT/DELETE等）
    controller_class: str  # Controller类名
    method_name: str  # 方法名
    file_path: str  # 文件路径
    line_number: int  # 行号
    parameters: List[Dict] = field(default_factory=list)  # 参数列表
    return_type: str = ""  # 返回值类型
    annotations: List[str] = field(default_factory=list)  # 注解列表
    
    def to_dict(self) -> Dict:
        return asdict(self)


# Java类信息，包含类的完整解析结果
@dataclass
class JavaClassInfo:
    file_path: str  # 文件路径
    package_name: str  # 包名
    class_name: str  # 类名
    imports: List[str]  # 导入列表
    extends: Optional[str]  # 父类名
    implements: List[str]  # 实现的接口列表
    fields: Dict[str, 'JavaFieldInfo']  # 字段字典
    methods: Dict[str, 'JavaMethodInfo']  # 方法字典
    annotations: List[str]  # 类注解列表
    is_controller: bool  # 是否Controller类
    is_service: bool  # 是否Service类
    is_repository: bool  # 是否Repository类
    line_start: int  # 起始行号
    line_end: int  # 结束行号
    base_path: str = ""  # Controller基础路径（@RequestMapping值）
    
    def to_dict(self) -> Dict:
        return {
            'file_path': self.file_path,
            'package_name': self.package_name,
            'class_name': self.class_name,
            'imports': self.imports,
            'extends': self.extends,
            'implements': self.implements,
            'fields': {k: v.to_dict() for k, v in self.fields.items()},
            'methods': {k: v.to_dict() for k, v in self.methods.items()},
            'annotations': self.annotations,
            'is_controller': self.is_controller,
            'is_service': self.is_service,
            'is_repository': self.is_repository,
            'line_start': self.line_start,
            'line_end': self.line_end,
            'base_path': self.base_path
        }


# Java方法信息，包含方法签名、调用关系和API映射
@dataclass
class JavaMethodInfo:
    method_name: str  # 方法名
    return_type: str  # 返回值类型
    parameters: List[Dict]  # 参数列表
    line_start: int  # 起始行号
    line_end: int  # 结束行号
    body: str  # 方法体内容
    annotations: List[str]  # 方法注解列表
    called_methods: List[str]  # 调用的方法列表
    used_fields: List[str]  # 使用的字段列表
    is_api: bool  # 是否API接口方法
    api_path: Optional[str]  # API路径
    http_method: Optional[str]  # HTTP方法
    
    def to_dict(self) -> Dict:
        return asdict(self)


# Java字段信息
@dataclass
class JavaFieldInfo:
    field_name: str  # 字段名
    field_type: str  # 字段类型
    line_number: int  # 行号
    annotations: List[str]  # 字段注解列表
    
    def to_dict(self) -> Dict:
        return asdict(self)


# Git差异解析结果，记录文件的变更行和变更方法
@dataclass
class DiffResult:
    file_path: str  # 文件路径
    lines_added: List[int]  # 新增行号列表
    lines_removed: List[int]  # 删除行号列表
    content_added: List[str]  # 新增内容列表
    content_removed: List[str]  # 删除内容列表
    changed_methods: Dict[str, Dict]  # 变更方法字典
    changed_fields: Dict[str, Dict]  # 变更字段字典
    
    def to_dict(self) -> Dict:
        return asdict(self)


# 影响传播节点，描述代码变更的影响链路
@dataclass
class ImpactNode:
    class_name: str  # 类名
    method_name: str  # 方法名
    file_path: str  # 文件路径
    impact_type: str  # 影响类型（direct_impact/service_dependency/indirect_impact）
    depth: int  # 影响深度（距离变更点的跳数）
    children: List['ImpactNode'] = field(default_factory=list)  # 子影响节点列表
    
    def to_dict(self) -> Dict:
        return {
            'class_name': self.class_name,
            'method_name': self.method_name,
            'file_path': self.file_path,
            'impact_type': self.impact_type,
            'depth': self.depth,
            'children': [c.to_dict() for c in self.children]
        }


class JCCIAnalyzer:
    """基于JCCI的Java代码变更影响分析器
    
    基于JCCI（Java代码提交影响）方法论:
    - 使用javalang进行Java AST解析
    - 使用unidiff进行Git差异解析
    - 构建调用图用于影响传播
    - 从变更代码追踪影响到Controller层
    
    性能优化（6大策略）:
    - 策略1: 智能缓存（避免重复解析）
    - 策略2: 多线程并行扫描
    - 策略3: 智能增量模式
    - 策略4: 文件过滤（排除target/build等）
    - 策略5: 两阶段懒加载
    - 策略6: 动态进度条显示
    """
    
    def __init__(self, project_path: str, enable_optimization: bool = True):
        self.project_path = Path(project_path).resolve()
        self.java_classes: Dict[str, JavaClassInfo] = {}
        self.call_graph: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_call_graph: Dict[str, Set[str]] = defaultdict(set)
        self.class_to_file: Dict[str, str] = {}
        self.method_to_class: Dict[str, str] = {}
        self._initialized = False
        self._incremental_mode = False
        self._scanned_files: Set[str] = set()
        
        # 性能优化配置
        self.enable_optimization = enable_optimization and OPTIMIZER_AVAILABLE
        self.optimizer: Optional[PerformanceOptimizer] = None
        
        if self.enable_optimization:
            try:
                # 从 settings 读取性能优化配置
                from config.settings import settings
                
                self.optimizer = PerformanceOptimizer(
                    project_path=str(self.project_path),
                    cache_dir=settings.jcci_cache_dir,
                    max_workers=None if settings.jcci_max_workers == "auto" else int(settings.jcci_max_workers),
                    enable_cache=settings.jcci_cache_enabled,
                    enable_parallel=settings.jcci_enable_optimization,
                    enable_incremental=settings.jcci_incremental_mode in ["auto", "true"],
                    enable_filter=True,
                    enable_lazy_loading=settings.jcci_lazy_loading,
                    cache_max_size_mb=settings.jcci_cache_max_size_mb,
                    cache_ttl_hours=settings.jcci_cache_ttl_hours
                )
            except Exception as e:
                logger.warning(f"性能优化引擎初始化失败: {e}，将使用标准模式")
                self.enable_optimization = False
    
    def initialize(self, incremental: bool = True, changed_files: List[str] = None):
        """
        初始化JCCI分析器（支持超级优化模式）
        
        参数:
            incremental: 是否启用增量模式（默认True）
            changed_files: 变更文件列表（用于增量模式优化）
        """
        if self._initialized:
            return
        
        if not JAVALANG_AVAILABLE:
            logger.warning("javalang not available, using fallback regex-based parsing")
        
        self._incremental_mode = incremental
        
        if self.enable_optimization and self.optimizer:
            # 🚀 使用超级优化引擎
            logger.info(f"[JCCIAnalyzer] 初始化（🚀 超级优化模式）")
            self._scan_java_files_optimized(changed_files)
        else:
            # 标准模式（原有逻辑）
            logger.info(f"[JCCIAnalyzer] 初始化（标准模式）")
            self._scan_java_files()
        
        self._build_call_graph()
        self._initialized = True
        
        logger.info(f"[JCCIAnalyzer] 初始化完成: {len(self.java_classes)} 个类, "
                   f"{len(self.call_graph)} 个调用节点")
    
    def _scan_java_files_incremental(self, changed_files: List[str]):
        """增量扫描Java文件，仅解析变更文件和相关Controller"""
        files_to_scan = set()
        
        for file_path in changed_files:
            if not file_path.endswith('.java'):
                continue
            
            java_file = self.project_path / file_path
            if java_file.exists():
                files_to_scan.add(str(java_file))
        
        related_controllers = self._find_related_controllers(changed_files)
        files_to_scan.update(related_controllers)
        
        logger.info(f"Scanning {len(files_to_scan)} Java files (incremental mode): {len(changed_files)} changed + {len(related_controllers)} related controllers")
        
        for file_path_str in files_to_scan:
            java_file = Path(file_path_str)
            try:
                class_info = self._parse_java_file(java_file)
                if class_info:
                    self.java_classes[class_info.class_name] = class_info
                    self.class_to_file[class_info.class_name] = str(java_file.relative_to(self.project_path))
                    self._scanned_files.add(str(java_file.relative_to(self.project_path)))
            except Exception as e:
                logger.error(f"Error parsing {java_file}: {e}")
    
    def _find_controller_files(self) -> Set[str]:
        """查找项目中所有Controller文件"""
        controller_files = set()
        
        java_files = list(self.project_path.rglob("*Controller.java"))
        java_files = [f for f in java_files if "target" not in str(f) and "build" not in str(f)]
        
        for java_file in java_files:
            controller_files.add(str(java_file))
        
        logger.info(f"Found {len(controller_files)} controller files")
        return controller_files
    
    def _find_related_controllers(self, changed_files: List[str]) -> Set[str]:
        """查找与变更文件相关的Controller文件"""
        related_controllers = set()
        
        changed_classes = set()
        for file_path in changed_files:
            if not file_path.endswith('.java'):
                continue
            
            normalized = file_path.replace('/', '\\')
            for prefix in ['campus-master\\', 'campus-master/']:
                if normalized.startswith(prefix):
                    normalized = normalized[len(prefix):]
                    break
            
            java_file = self.project_path / normalized
            if java_file.exists():
                try:
                    with open(java_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    class_match = re.search(r'(?:public\s+)?class\s+(\w+)', content)
                    if class_match:
                        changed_classes.add(class_match.group(1))
                except Exception as e:
                    logger.warning(f"Error reading {java_file}: {e}")
        
        if not changed_classes:
            return self._find_controller_files()
        
        controller_files = self._find_controller_files()
        
        for controller_file in controller_files:
            try:
                with open(controller_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                for changed_class in changed_classes:
                    if changed_class in content:
                        related_controllers.add(controller_file)
                        break
                
                imports = re.findall(r'import\s+[\w.]+\.(\w+);', content)
                for imp in imports:
                    for changed_class in changed_classes:
                        if imp == changed_class:
                            related_controllers.add(controller_file)
                            break
                            
            except Exception as e:
                logger.warning(f"Error reading {controller_file}: {e}")
        
        logger.info(f"Found {len(related_controllers)} related controllers for {len(changed_classes)} changed classes")
        return related_controllers
    
    def _scan_java_files_optimized(self, changed_files: List[str] = None):
        """
        🚀 使用超级优化引擎扫描Java文件（整合6大策略）
        
        策略组合:
        1. 智能缓存 - 避免重复解析未变更的文件
        2. 多线程并行 - 利用多核CPU加速
        3. 增量模式 - 仅扫描变更文件+相关依赖
        4. 文件过滤 - 排除target/build/test等目录
        5. 进度显示 - 实时进度条+性能统计
        """
        
        # 获取所有Java文件
        java_files = list(self.project_path.rglob("*.java"))
        
        logger.info(f"[JCCIAnalyzer] 🚀 开始超级优化扫描")
        logger.info(f"[JCCIAnalyzer] 发现 {len(java_files)} 个Java文件")
        
        # 使用优化器执行扫描
        result = self.optimizer.optimized_scan(
            java_files=java_files,
            parse_func=self._parse_java_file,  # 传入解析函数
            changed_files=changed_files
        )
        
        # 提取结果
        optimized_results = result.get('results', {})
        stats = result.get('stats', {})
        
        # 将优化结果转换为java_classes格式
        for class_name, class_info in optimized_results.items():
            if isinstance(class_info, dict):
                # 如果是字典，需要转换回 JavaClassInfo 对象
                converted_info = self._dict_to_java_class_info(class_name, class_info)
                self.java_classes[class_name] = converted_info
                self.class_to_file[class_name] = converted_info.file_path
            else:
                # 如果已经是对象
                self.java_classes[class_info.class_name] = class_info
                file_path_str = class_info.file_path if hasattr(class_info, 'file_path') and class_info.file_path else class_name + ".java"
                try:
                    self.class_to_file[class_info.class_name] = str(Path(file_path_str).relative_to(self.project_path))
                except ValueError:
                    self.class_to_file[class_info.class_name] = file_path_str
        
        # 输出优化统计
        speedup = stats.get('speedup_factor', 0)
        elapsed = stats.get('elapsed_time', 0)
        cache_hit_rate = stats.get('cache_hit_rate', 0)
        
        controller_count = sum(1 for cls in self.java_classes.values() 
                             if getattr(cls, 'is_controller', False))
        service_count = sum(1 for cls in self.java_classes.values() 
                          if getattr(cls, 'is_service', False))
        repository_count = sum(1 for cls in self.java_classes.values() 
                              if getattr(cls, 'is_repository', False))
        
        logger.info(f"[JCCIAnalyzer] 🚀 超级优化扫描完成:")
        logger.info(f"  ✅ 解析类数: {len(self.java_classes)} "
                   f"(Controllers: {controller_count}, Services: {service_count}, Repositories: {repository_count})")
        logger.info(f"  ⏱️  总耗时: {elapsed:.3f}秒 (加速 {speedup:.1f}x)")
        logger.info(f"  💾 缓存命中率: {cache_hit_rate:.1f}%")
    
    def _scan_java_files(self):
        """标准模式扫描所有Java文件"""
        java_files = list(self.project_path.rglob("*.java"))
        java_files = [f for f in java_files if "target" not in str(f) and "build" not in str(f)]
        
        logger.info(f"[JCCIAnalyzer] 开始扫描 {len(java_files)} 个Java文件")
        
        controller_count = 0
        service_count = 0
        repository_count = 0
        
        if TQDM_AVAILABLE and len(java_files) > 0:
            pbar = tqdm(java_files, desc="扫描Java文件", unit="个", 
                       ascii=True, dynamic_ncols=True, leave=True)
            for java_file in pbar:
                pbar.set_postfix_str(f"当前: {java_file.name}")
                try:
                    class_info = self._parse_java_file(java_file)
                    if class_info:
                        self.java_classes[class_info.class_name] = class_info
                        self.class_to_file[class_info.class_name] = str(java_file.relative_to(self.project_path))
                        
                        if class_info.is_controller:
                            controller_count += 1
                            logger.debug(f"[JCCIAnalyzer] 发现Controller: {class_info.class_name} ({len(class_info.methods)} 个方法)")
                        elif class_info.is_service:
                            service_count += 1
                        elif class_info.is_repository:
                            repository_count += 1
                except Exception as e:
                    logger.error(f"Error parsing {java_file}: {e}")
            pbar.close()
        else:
            for java_file in java_files:
                try:
                    class_info = self._parse_java_file(java_file)
                    if class_info:
                        self.java_classes[class_info.class_name] = class_info
                        self.class_to_file[class_info.class_name] = str(java_file.relative_to(self.project_path))
                        
                        if class_info.is_controller:
                            controller_count += 1
                            logger.debug(f"[JCCIAnalyzer] 发现Controller: {class_info.class_name} ({len(class_info.methods)} 个方法)")
                        elif class_info.is_service:
                            service_count += 1
                        elif class_info.is_repository:
                            repository_count += 1
                except Exception as e:
                    logger.error(f"Error parsing {java_file}: {e}")
        
        logger.info(f"[JCCIAnalyzer] AST解析完成: {len(self.java_classes)} 个类 "
                   f"(Controllers: {controller_count}, Services: {service_count}, Repositories: {repository_count})")
    
    def _dict_to_java_class_info(self, class_name: str, class_dict: Dict) -> JavaClassInfo:
        """将字典转换为JavaClassInfo对象，用于缓存结果的反序列化"""
        methods = {}
        for m_name, m_data in class_dict.get('methods', {}).items():
            if isinstance(m_data, dict):
                methods[m_name] = JavaMethodInfo(
                    method_name=m_data.get('method_name', m_name),
                    return_type=m_data.get('return_type', 'void'),
                    parameters=m_data.get('parameters', []),
                    line_start=m_data.get('line_start', 0),
                    line_end=m_data.get('line_end', 0),
                    body=m_data.get('body', ''),
                    annotations=m_data.get('annotations', []),
                    called_methods=m_data.get('called_methods', []),
                    used_fields=m_data.get('used_fields', []),
                    is_api=m_data.get('is_api', False),
                    api_path=m_data.get('api_path'),
                    http_method=m_data.get('http_method')
                )
            else:
                methods[m_name] = m_data
        
        fields = {}
        for f_name, f_data in class_dict.get('fields', {}).items():
            if isinstance(f_data, dict):
                fields[f_name] = JavaFieldInfo(
                    field_name=f_data.get('field_name', f_name),
                    field_type=f_data.get('field_type', ''),
                    line_number=f_data.get('line_number', 0),
                    annotations=f_data.get('annotations', [])
                )
            else:
                fields[f_name] = f_data
        
        return JavaClassInfo(
            file_path=class_dict.get('file_path', ''),
            package_name=class_dict.get('package_name', ''),
            class_name=class_name,
            imports=class_dict.get('imports', []),
            extends=class_dict.get('extends'),
            implements=class_dict.get('implements', []),
            fields=fields,
            methods=methods,
            annotations=class_dict.get('annotations', []),
            is_controller=class_dict.get('is_controller', False),
            is_service=class_dict.get('is_service', False),
            is_repository=class_dict.get('is_repository', False),
            line_start=class_dict.get('line_start', 0),
            line_end=class_dict.get('line_end', 0),
            base_path=class_dict.get('base_path', '')
        )
    
    def _parse_java_file(self, java_file: Path) -> Optional[JavaClassInfo]:
        """解析单个Java文件，优先使用javalang AST解析，失败则回退到正则解析"""
        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if JAVALANG_AVAILABLE:
                return self._parse_with_javalang(java_file, content)
            else:
                return self._parse_with_regex(java_file, content)
                
        except Exception as e:
            logger.error(f"Error reading {java_file}: {e}")
            return None
    
    def _parse_with_javalang(self, java_file: Path, content: str) -> Optional[JavaClassInfo]:
        """使用javalang进行AST解析Java文件，提取类、方法、字段信息"""
        try:
            tree = javalang.parse.parse(content)
            
            package_name = ""
            if tree.package:
                package_name = tree.package.name
            
            imports = []
            if tree.imports:
                imports = [imp.path for imp in tree.imports]
            
            for type_decl in tree.types:
                if not isinstance(type_decl, (javalang.tree.ClassDeclaration, javalang.tree.InterfaceDeclaration)):
                    continue
                
                class_name = type_decl.name
                annotations = []
                if type_decl.annotations:
                    annotations = [ann.name for ann in type_decl.annotations]
                
                extends = None
                if type_decl.extends:
                    extends = type_decl.extends.name if hasattr(type_decl.extends, 'name') else str(type_decl.extends)
                
                implements = []
                if type_decl.implements:
                    for impl in type_decl.implements:
                        impl_name = impl.name if hasattr(impl, 'name') else str(impl)
                        implements.append(impl_name)
                
                fields = {}
                methods = {}
                
                for member in type_decl.body:
                    if isinstance(member, javalang.tree.FieldDeclaration):
                        for declarator in member.declarators:
                            pos = member.position if member.position else 0
                            if isinstance(pos, tuple):
                                pos = pos[0] if pos else 0
                            field_info = JavaFieldInfo(
                                field_name=declarator.name,
                                field_type=member.type.name if member.type and hasattr(member.type, 'name') else ("unknown" if not member.type else str(member.type)),
                                line_number=pos,
                                annotations=[ann.name for ann in (member.annotations or [])]
                            )
                            fields[declarator.name] = field_info
                    
                    elif isinstance(member, javalang.tree.MethodDeclaration):
                        method_info = self._parse_method_with_javalang(member, content, class_name, annotations, fields)
                        methods[member.name] = method_info
                        self.method_to_class[f"{class_name}.{member.name}"] = class_name
                
                is_controller = any(ann in ['RestController', 'Controller'] for ann in annotations)
                is_service = 'Service' in annotations
                is_repository = 'Repository' in annotations
                
                base_path = ""
                if type_decl.annotations:
                    for ann in type_decl.annotations:
                        if ann.name == 'RequestMapping':
                            base_path = self._extract_path_from_javalang_annotation(ann) or ""
                            break
                
                return JavaClassInfo(
                    file_path=str(java_file.relative_to(self.project_path)),
                    package_name=package_name,
                    class_name=class_name,
                    imports=imports,
                    extends=extends,
                    implements=implements,
                    fields=fields,
                    methods=methods,
                    annotations=annotations,
                    is_controller=is_controller,
                    is_service=is_service,
                    is_repository=is_repository,
                    line_start=type_decl.position[0] if isinstance(type_decl.position, tuple) else (type_decl.position if type_decl.position else 0),
                    line_end=0,
                    base_path=base_path
                )
            
            return None
            
        except TypeError as e:
            logger.debug(f"javalang type error (likely NoneType unpack) for {java_file}: {e}, falling back to regex")
            return self._parse_with_regex(java_file, content)
        except Exception as e:
            logger.debug(f"javalang parsing failed for {java_file}, falling back to regex: {e}")
            return self._parse_with_regex(java_file, content)
    
    def _parse_method_with_javalang(self, method_decl, content: str, class_name: str, class_annotations: List[str], fields: Dict[str, JavaFieldInfo] = None) -> JavaMethodInfo:
        """使用javalang解析方法声明，提取方法信息和调用关系"""
        method_name = method_decl.name
        if method_decl.return_type:
            return_type = method_decl.return_type.name if hasattr(method_decl.return_type, 'name') else str(method_decl.return_type)
        else:
            return_type = "void"
        
        parameters = []
        if method_decl.parameters:
            for param in method_decl.parameters:
                param_type_name = "unknown"
                if param.type:
                    if hasattr(param.type, 'name'):
                        param_type_name = param.type.name
                    else:
                        param_type_name = str(param.type)
                parameters.append({
                    'type': param_type_name,
                    'name': param.name,
                    'varargs': param.varargs if hasattr(param, 'varargs') else False
                })
        
        annotations = []
        if method_decl.annotations:
            annotations = [ann.name for ann in method_decl.annotations]
        
        line_start = method_decl.position if method_decl.position else 0
        if isinstance(line_start, tuple):
            line_start = line_start[0] if line_start else 0
        line_end = line_start
        
        body = ""
        if method_decl.body:
            body = self._extract_method_body(content, line_start)
            line_end = line_start + body.count('\n')
        
        called_methods = self._extract_method_calls(body, class_name, fields)
        used_fields = self._extract_field_usages(body)
        
        is_api, api_path, http_method = self._extract_api_info_from_javalang_annotations(method_decl.annotations, class_annotations)
        
        return JavaMethodInfo(
            method_name=method_name,
            return_type=return_type,
            parameters=parameters,
            line_start=line_start,
            line_end=line_end,
            body=body,
            annotations=annotations,
            called_methods=called_methods,
            used_fields=used_fields,
            is_api=is_api,
            api_path=api_path,
            http_method=http_method
        )
    
    def _parse_with_regex(self, java_file: Path, content: str) -> Optional[JavaClassInfo]:
        """正则表达式回退解析Java文件，当javalang不可用或解析失败时使用"""
        package_match = re.search(r'package\s+([\w.]+)\s*;', content)
        package_name = package_match.group(1) if package_match else ""
        
        imports = re.findall(r'import\s+([\w.]+)\s*;', content)
        
        class_match = re.search(r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?(?:class|interface)\s+(\w+)(?:\s+extends\s+([\w,.\s]+?))?(?:\s+implements\s+([\w\s,]+))?\s*\{', content)
        if not class_match:
            return None
        
        class_name = class_match.group(1)
        extends = class_match.group(2)
        implements = [impl.strip() for impl in (class_match.group(3) or "").split(',')] if class_match.group(3) else []
        
        class_annotations = re.findall(r'@(\w+)', content[:class_match.start()])
        class_base_path = self._extract_class_base_path(content[:class_match.start()])
        
        fields = self._extract_fields_regex(content)
        methods = self._extract_methods_regex(content, class_name, class_annotations, class_base_path, fields)
        
        is_controller = any(ann in ['RestController', 'Controller'] for ann in class_annotations)
        is_service = 'Service' in class_annotations
        is_repository = 'Repository' in class_annotations
        
        return JavaClassInfo(
            file_path=str(java_file.relative_to(self.project_path)),
            package_name=package_name,
            class_name=class_name,
            imports=imports,
            extends=extends,
            implements=implements,
            fields=fields,
            methods=methods,
            annotations=class_annotations,
            is_controller=is_controller,
            is_service=is_service,
            is_repository=is_repository,
            line_start=content[:class_match.start()].count('\n') + 1,
            line_end=content.count('\n') + 1,
            base_path=class_base_path
        )
    
    def _extract_class_base_path(self, content_before_class: str) -> str:
        """从类声明前的内容中提取@RequestMapping的基础路径"""
        match = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"', content_before_class)
        if match:
            return match.group(1)
        return ""
    
    def _extract_fields_regex(self, content: str) -> Dict[str, JavaFieldInfo]:
        """使用正则表达式提取类中的字段信息"""
        fields = {}
        
        field_pattern = r'(?:@[\w.]+\s*)*(?:private|public|protected)\s+(\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*[;=]'
        
        for match in re.finditer(field_pattern, content):
            field_type = match.group(1)
            field_name = match.group(2)
            
            line_num = content[:match.start()].count('\n') + 1
            
            annotations = re.findall(r'@(\w+)', content[max(0, match.start()-200):match.start()])
            
            fields[field_name] = JavaFieldInfo(
                field_name=field_name,
                field_type=field_type,
                line_number=line_num,
                annotations=annotations
            )
        
        return fields
    
    def _extract_methods_regex(self, content: str, class_name: str, class_annotations: List[str], class_base_path: str = "", fields: Dict[str, JavaFieldInfo] = None) -> Dict[str, JavaMethodInfo]:
        """使用正则表达式提取类中的方法信息"""
        methods = {}
        
        if fields is None:
            fields = {}
        
        method_pattern = r'((?:@[\w.]+\s*\((?:"[^"]*"|\'[^\']*\'|[^()])*\)\s*)*)(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\(([^)]*)\)(?:\s+throws\s+[\w\s,]+)?\s*\{'
        
        for match in re.finditer(method_pattern, content):
            annotations_str = match.group(1)
            return_type = match.group(2)
            method_name = match.group(3)
            params_str = match.group(4)
            
            if method_name in ['if', 'for', 'while', 'switch', 'catch', 'class']:
                continue
            
            annotations = re.findall(r'@(\w+)', annotations_str)
            
            line_start = content[:match.start()].count('\n') + 1
            
            body = self._extract_method_body(content, line_start)
            line_end = line_start + body.count('\n')
            
            parameters = self._parse_parameters(params_str)
            
            called_methods = self._extract_method_calls(body, class_name, fields)
            used_fields = self._extract_field_usages(body)
            
            is_api, api_path, http_method = self._extract_api_info_from_annotations(annotations_str, class_base_path)
            
            methods[method_name] = JavaMethodInfo(
                method_name=method_name,
                return_type=return_type,
                parameters=parameters,
                line_start=line_start,
                line_end=line_end,
                body=body,
                annotations=annotations,
                called_methods=called_methods,
                used_fields=used_fields,
                is_api=is_api,
                api_path=api_path,
                http_method=http_method
            )
            
            self.method_to_class[f"{class_name}.{method_name}"] = class_name
        
        additional_methods = self._extract_methods_with_nested_params(content, class_name, class_annotations, class_base_path, fields)
        for method_name, method_info in additional_methods.items():
            if method_name not in methods:
                methods[method_name] = method_info
                self.method_to_class[f"{class_name}.{method_name}"] = class_name
        
        return methods
    
    def _extract_methods_with_nested_params(self, content: str, class_name: str, class_annotations: List[str], class_base_path: str = "", fields: Dict[str, JavaFieldInfo] = None) -> Dict[str, JavaMethodInfo]:
        """提取包含嵌套参数注解的方法（正则回退方案）"""
        methods = {}
        
        if fields is None:
            fields = {}
        
        lines = content.split('\n')
        i = 0
        processed_methods = set()
        
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            if stripped.startswith('@') and not re.search(r'(?:public|private|protected)\s+', line):
                annotations = []
                annotation_lines = []
                
                while i < len(lines):
                    current_stripped = lines[i].strip()
                    if current_stripped.startswith('@') and not re.search(r'(?:public|private|protected)\s+', lines[i]):
                        annotations.append(current_stripped)
                        annotation_lines.append(lines[i])
                        i += 1
                    else:
                        break
                
                while i < len(lines):
                    current_stripped = lines[i].strip()
                    if current_stripped == '' or current_stripped.startswith('*') or current_stripped.startswith('/**'):
                        i += 1
                    else:
                        break
                
                if i < len(lines):
                    method_line = lines[i]
                    
                    if re.search(r'(?:public|private|protected)\s+', method_line):
                        method_match = re.search(r'(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\(', method_line)
                        
                        if method_match:
                            return_type = method_match.group(1)
                            method_name = method_match.group(2)
                            
                            if method_name in ['if', 'for', 'while', 'switch', 'catch', 'class']:
                                i += 1
                                continue
                            
                            if method_name in processed_methods:
                                i += 1
                                continue
                            
                            params_str = self._extract_method_params(content, i + 1)
                            
                            line_start = i + 1
                            body = self._extract_method_body_from_line(content, line_start)
                            line_end = line_start + body.count('\n')
                            
                            annotations_str = '\n'.join(annotation_lines)
                            
                            parameters = self._parse_parameters(params_str)
                            
                            called_methods = self._extract_method_calls(body, class_name, fields)
                            used_fields = self._extract_field_usages(body)
                            
                            is_api, api_path, http_method = self._extract_api_info_from_annotations(annotations_str, class_base_path)
                            
                            methods[method_name] = JavaMethodInfo(
                                method_name=method_name,
                                return_type=return_type,
                                parameters=parameters,
                                line_start=line_start,
                                line_end=line_end,
                                body=body,
                                annotations=[ann.strip() for ann in annotations],
                                called_methods=called_methods,
                                used_fields=used_fields,
                                is_api=is_api,
                                api_path=api_path,
                                http_method=http_method
                            )
                            processed_methods.add(method_name)
                            i += 1
                            continue
            
            i += 1
        
        return methods
    
    def _extract_method_params(self, content: str, line_num: int) -> str:
        """从指定行提取方法参数字符串"""
        lines = content.split('\n')
        if line_num > len(lines):
            return ""
        
        line = lines[line_num - 1]
        
        start_idx = line.find('(')
        if start_idx == -1:
            return ""
        
        params = []
        paren_count = 1
        i = start_idx + 1
        
        while i < len(line) and paren_count > 0:
            char = line[i]
            if char == '(':
                paren_count += 1
            elif char == ')':
                paren_count -= 1
            elif char == '"':
                i += 1
                while i < len(line) and line[i] != '"':
                    if line[i] == '\\':
                        i += 1
                    i += 1
            elif char == "'":
                i += 1
                while i < len(line) and line[i] != "'":
                    if line[i] == '\\':
                        i += 1
                    i += 1
            
            if paren_count > 0:
                params.append(char)
            i += 1
        
        return ''.join(params)
    
    def _extract_method_body_from_line(self, content: str, line_start: int) -> str:
        """从指定行号提取方法体"""
        lines = content.split('\n')
        if line_start > len(lines):
            return ""
        
        start_idx = line_start - 1
        
        brace_count = 0
        found_start = False
        body_lines = []
        
        for i in range(start_idx, len(lines)):
            line = lines[i]
            
            for char in line:
                if char == '{':
                    brace_count += 1
                    found_start = True
                elif char == '}':
                    brace_count -= 1
            
            body_lines.append(line)
            
            if found_start and brace_count == 0:
                break
        
        return '\n'.join(body_lines)
    
    def _extract_method_body(self, content: str, line_start: int) -> str:
        """根据起始行号提取方法体内容"""
        lines = content.split('\n')
        if line_start > len(lines):
            return ""
        
        start_idx = line_start - 1
        
        brace_count = 0
        found_start = False
        body_lines = []
        
        for i in range(start_idx, len(lines)):
            line = lines[i]
            
            for char in line:
                if char == '{':
                    brace_count += 1
                    found_start = True
                elif char == '}':
                    brace_count -= 1
            
            body_lines.append(line)
            
            if found_start and brace_count == 0:
                break
        
        return '\n'.join(body_lines)
    
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
                
                annotations = [p for p in parts[:-2] if p.startswith('@')]
                
                parameters.append({
                    'type': param_type,
                    'name': param_name,
                    'annotations': annotations
                })
        
        return parameters
    
    def _extract_method_calls(self, body: str, current_class: str, fields: Dict[str, JavaFieldInfo] = None) -> List[str]:
        """从方法体中提取方法调用关系"""
        called_methods = []
        
        if fields is None:
            fields = {}
        
        patterns = [
            r'(\w+)\s*\.\s*(\w+)\s*\(',
            r'(\w+)\s*\(',
        ]
        
        for pattern in patterns:
            for match in re.finditer(pattern, body):
                if len(match.groups()) == 2:
                    object_name = match.group(1)
                    method_name = match.group(2)
                    
                    if object_name in ['this', 'super']:
                        called_methods.append(f"{current_class}.{method_name}")
                    elif object_name[0].isupper():
                        called_methods.append(f"{object_name}.{method_name}")
                    else:
                        if object_name in fields:
                            field_type = fields[object_name].field_type
                            if '<' in field_type:
                                field_type = field_type.split('<')[0]
                            called_methods.append(f"{field_type}.{method_name}")
                        else:
                            called_methods.append(f"{object_name}.{method_name}")
                else:
                    method_name = match.group(1)
                    if method_name not in ['if', 'for', 'while', 'switch', 'catch', 'return', 'new', 'throw']:
                        called_methods.append(f"{current_class}.{method_name}")
        
        return list(set(called_methods))
    
    def _extract_field_usages(self, body: str) -> List[str]:
        """从方法体中提取字段使用情况"""
        used_fields = []
        
        pattern = r'\bthis\.(\w+)\b'
        used_fields.extend(re.findall(pattern, body))
        
        return list(set(used_fields))
    
    def _extract_api_info_from_javalang_annotations(self, method_annotations, class_annotations: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        """从javalang注解对象中提取API信息（路径、HTTP方法）"""
        is_api = False
        api_path = None
        http_method = None
        
        http_mappings = {
            'GetMapping': 'GET',
            'PostMapping': 'POST',
            'PutMapping': 'PUT',
            'DeleteMapping': 'DELETE',
            'PatchMapping': 'PATCH'
        }
        
        if method_annotations:
            for ann in method_annotations:
                if ann.name in http_mappings:
                    is_api = True
                    http_method = http_mappings[ann.name]
                    api_path = self._extract_path_from_javalang_annotation(ann)
                    break
                elif ann.name == 'RequestMapping':
                    is_api = True
                    method_match = None
                    if ann.element and isinstance(ann.element, list):
                        for elem in ann.element:
                            if hasattr(elem, 'name') and elem.name == 'method':
                                val = getattr(elem, 'value', None)
                                if val and hasattr(val, 'member'):
                                    method_match = val.member
                                break
                    http_method = method_match or 'GET'
                    api_path = self._extract_path_from_javalang_annotation(ann)
                    break
        
        if not is_api and 'RequestMapping' in class_annotations:
            is_api = True
            http_method = http_method or 'GET'
        
        if api_path and not api_path.startswith('/'):
            api_path = f"/{api_path}"
        elif is_api and api_path is None:
            api_path = ""
        
        return is_api, api_path, http_method
    
    def _extract_path_from_javalang_annotation(self, ann) -> Optional[str]:
        """从javalang注解对象中提取路径值，处理Literal/Element/list/str四种类型"""
        if ann.element is None:
            return None
        
        try:
            # 情况1：注解值为Literal，如@GetMapping("/list")
            if isinstance(ann.element, javalang.tree.Literal):
                val = ann.element.value
                if isinstance(val, str):
                    return val.strip('"').strip("'")
                return None
            
            # 情况2：注解值为Element列表，如@RequestMapping(value="/list", method=RequestMethod.GET)
            if isinstance(ann.element, list):
                for elem in ann.element:
                    if not hasattr(elem, 'name'):
                        continue
                    if elem.name in ('value', 'path'):
                        val = getattr(elem, 'value', None)
                        if val is None:
                            continue
                        # value可能是Literal对象
                        if isinstance(val, javalang.tree.Literal):
                            if isinstance(val.value, str):
                                return val.value.strip('"').strip("'")
                        # value可能直接是字符串
                        elif isinstance(val, str):
                            return val.strip('"').strip("'")
                        # value可能有.value属性
                        elif hasattr(val, 'value'):
                            inner_val = val.value
                            if isinstance(inner_val, str):
                                return inner_val.strip('"').strip("'")
                # 如果没找到value/path，检查第一个元素是否是Literal（简写形式）
                if len(ann.element) > 0:
                    first_elem = ann.element[0]
                    if isinstance(first_elem, javalang.tree.Element):
                        val = getattr(first_elem, 'value', None)
                        if val and isinstance(val, javalang.tree.Literal) and isinstance(val.value, str):
                            return val.value.strip('"').strip("'")
                return None
            
            # 情况3：注解值为单个Element对象
            if hasattr(ann.element, 'name'):
                if ann.element.name in ('value', 'path'):
                    val = getattr(ann.element, 'value', None)
                    if val is None:
                        return None
                    if isinstance(val, javalang.tree.Literal):
                        if isinstance(val.value, str):
                            return val.value.strip('"').strip("'")
                    elif isinstance(val, str):
                        return val.strip('"').strip("'")
                    elif hasattr(val, 'value'):
                        inner_val = val.value
                        if isinstance(inner_val, str):
                            return inner_val.strip('"').strip("'")
            
            # 情况4：注解值直接是字符串
            if isinstance(ann.element, str):
                return ann.element.strip('"').strip("'")
            
        except Exception as e:
            logger.debug(f"提取注解路径失败: {e}, ann.name={ann.name}, ann.element type={type(ann.element)}")
        
        return None

    def _extract_api_info(self, method_annotations: List[str], class_annotations: List[str]) -> Tuple[bool, Optional[str], Optional[str]]:
        """从注解名称列表中提取API信息（简化版，不提取路径）"""
        is_api = False
        api_path = None
        http_method = None
        
        base_path = ""
        for ann in class_annotations:
            if ann == 'RequestMapping':
                is_api = True
        
        http_mappings = {
            'GetMapping': 'GET',
            'PostMapping': 'POST',
            'PutMapping': 'PUT',
            'DeleteMapping': 'DELETE',
            'PatchMapping': 'PATCH'
        }
        
        for ann in method_annotations:
            if ann in http_mappings:
                is_api = True
                http_method = http_mappings[ann]
            elif ann == 'RequestMapping':
                is_api = True
        
        return is_api, api_path, http_method
    
    def _extract_api_info_from_annotations(self, annotations_str: str, class_base_path: str = "") -> Tuple[bool, Optional[str], Optional[str]]:
        """从注解字符串中提取API信息（路径、HTTP方法）"""
        is_api = False
        api_path = None
        http_method = None
        
        http_mappings = {
            'GetMapping': ('GET', r'@GetMapping\s*\([^)]*\)'),
            'PostMapping': ('POST', r'@PostMapping\s*\([^)]*\)'),
            'PutMapping': ('PUT', r'@PutMapping\s*\([^)]*\)'),
            'DeleteMapping': ('DELETE', r'@DeleteMapping\s*\([^)]*\)'),
            'PatchMapping': ('PATCH', r'@PatchMapping\s*\([^)]*\)')
        }
        
        for mapping_name, (method, pattern) in http_mappings.items():
            if f'@{mapping_name}' in annotations_str:
                is_api = True
                http_method = method
                match = re.search(pattern, annotations_str)
                if match:
                    annotation_content = match.group(0)
                    path_match = re.search(r'(?:value|path)\s*=\s*"([^"]+)"', annotation_content)
                    if path_match:
                        api_path = path_match.group(1)
                    else:
                        simple_match = re.search(r'@\w+Mapping\s*\(\s*"([^"]+)"', annotation_content)
                        if simple_match:
                            api_path = simple_match.group(1)
                break
        
        if '@RequestMapping' in annotations_str and not is_api:
            is_api = True
            method_match = re.search(r'method\s*=\s*RequestMethod\.(\w+)', annotations_str)
            if method_match:
                http_method = method_match.group(1)
            else:
                http_method = 'GET'
            
            path_match = re.search(r'(?:value|path)\s*=\s*"([^"]+)"', annotations_str)
            if path_match:
                api_path = path_match.group(1)
        
        if api_path:
            if not api_path.startswith('/'):
                api_path = f"/{api_path}"
        elif is_api:
            api_path = ""
        
        return is_api, api_path, http_method
    
    def _extract_base_path_from_annotations(self, class_annotations: List[str], annotations_str: str) -> str:
        """从类注解中提取基础路径"""
        base_path = ""
        
        for ann in class_annotations:
            if ann == 'RequestMapping' or ann == 'RestController':
                base_path = ""
                break
        
        return base_path
    
    def _build_call_graph(self):
        """构建方法调用图（正向和反向），用于影响传播分析"""
        logger.info(f"[JCCIAnalyzer] 开始构建调用图...")
        
        method_count = 0
        call_relation_count = 0
        
        for class_name, class_info in self.java_classes.items():
            for method_name, method_info in class_info.methods.items():
                method_key = f"{class_name}.{method_name}"
                method_count += 1
                
                for called in method_info.called_methods:
                    self.call_graph[method_key].add(called)
                    self.reverse_call_graph[called].add(method_key)
                    call_relation_count += 1
        
        logger.info(f"[JCCIAnalyzer] 调用图构建完成: {method_count} 个方法, {call_relation_count} 个调用关系")
    
    def parse_diff(self, diff_content: str) -> List[DiffResult]:
        """解析Git差异内容，提取文件变更信息"""
        if not UNIDIFF_AVAILABLE:
            logger.warning("unidiff not available, using fallback diff parsing")
            return self._parse_diff_regex(diff_content)
        
        results = []
        
        try:
            patch_set = PatchSet(diff_content)
            
            for patch in patch_set:
                if not patch.path.endswith('.java'):
                    continue
                
                if '.git' in patch.path or 'src/test/' in patch.path:
                    continue
                
                lines_added = []
                lines_removed = []
                content_added = []
                content_removed = []
                
                for hunk in patch:
                    for line in hunk:
                        if line.is_added:
                            lines_added.append(line.target_line_no)
                            content_added.append(line.value)
                        elif line.is_removed:
                            lines_removed.append(line.source_line_no)
                            content_removed.append(line.value)
                
                changed_methods = self._find_changed_methods(patch.path, lines_added + lines_removed)
                changed_fields = self._find_changed_fields(patch.path, lines_added + lines_removed)
                
                results.append(DiffResult(
                    file_path=patch.path,
                    lines_added=lines_added,
                    lines_removed=lines_removed,
                    content_added=content_added,
                    content_removed=content_removed,
                    changed_methods=changed_methods,
                    changed_fields=changed_fields
                ))
        
        except Exception as e:
            logger.error(f"Error parsing diff: {e}")
        
        return results
    
    def _parse_diff_regex(self, diff_content: str) -> List[DiffResult]:
        """使用正则表达式解析Git差异（unidiff不可用时的回退方案）"""
        results = []
        
        file_pattern = r'diff --git a/(.*?) b/(.*?)\n'
        file_matches = re.finditer(file_pattern, diff_content)
        
        for match in file_matches:
            file_path = match.group(2)
            
            if not file_path.endswith('.java'):
                continue
            
            lines_added = []
            lines_removed = []
            content_added = []
            content_removed = []
            
            hunk_pattern = rf'diff --git a/{re.escape(file_path)} b/{re.escape(file_path)}.*?@@ -(\d+),?\d* \+(\d+),?\d* @@(.*?)(?=diff --git|$)'
            hunk_match = re.search(hunk_pattern, diff_content, re.DOTALL)
            
            if hunk_match:
                hunk_content = hunk_match.group(3)
                added_line_num = int(hunk_match.group(2))
                
                for line in hunk_content.split('\n'):
                    if line.startswith('+') and not line.startswith('+++'):
                        lines_added.append(added_line_num)
                        content_added.append(line[1:])
                        added_line_num += 1
                    elif line.startswith('-') and not line.startswith('---'):
                        lines_removed.append(added_line_num)
                        content_removed.append(line[1:])
                    elif not line.startswith('\\'):
                        added_line_num += 1
            
            changed_methods = self._find_changed_methods(file_path, lines_added + lines_removed)
            changed_fields = self._find_changed_fields(file_path, lines_added + lines_removed)
            
            results.append(DiffResult(
                file_path=file_path,
                lines_added=lines_added,
                lines_removed=lines_removed,
                content_added=content_added,
                content_removed=content_removed,
                changed_methods=changed_methods,
                changed_fields=changed_fields
            ))
        
        return results
    
    def _find_changed_methods(self, file_path: str, changed_lines: List[int]) -> Dict[str, Dict]:
        """根据变更行号查找受影响的方法"""
        changed_methods = {}
        
        class_name = Path(file_path).stem
        
        if class_name not in self.java_classes:
            return changed_methods
        
        class_info = self.java_classes[class_name]
        
        for method_name, method_info in class_info.methods.items():
            for line in changed_lines:
                if method_info.line_start <= line <= method_info.line_end:
                    changed_methods[method_name] = {
                        'line_start': method_info.line_start,
                        'line_end': method_info.line_end,
                        'is_api': method_info.is_api,
                        'api_path': method_info.api_path,
                        'http_method': method_info.http_method
                    }
                    break
        
        return changed_methods
    
    def _find_changed_fields(self, file_path: str, changed_lines: List[int]) -> Dict[str, Dict]:
        """根据变更行号查找受影响的字段"""
        changed_fields = {}
        
        class_name = Path(file_path).stem
        
        if class_name not in self.java_classes:
            return changed_fields
        
        class_info = self.java_classes[class_name]
        
        for field_name, field_info in class_info.fields.items():
            if field_info.line_number in changed_lines:
                changed_fields[field_name] = {
                    'line_number': field_info.line_number,
                    'field_type': field_info.field_type
                }
        
        return changed_fields
    
    def analyze_impact(self, diff_results: List[DiffResult], max_depth: int = 5) -> List[ImpactNode]:
        """分析代码变更的影响，返回影响节点列表"""
        impact_nodes = []
        
        for diff_result in diff_results:
            class_name = Path(diff_result.file_path).stem
            
            for method_name in diff_result.changed_methods:
                method_key = f"{class_name}.{method_name}"
                
                impact_chain = self._trace_impact_chain(method_key, max_depth)
                
                if impact_chain:
                    impact_nodes.extend(impact_chain)
        
        return impact_nodes
    
    def _trace_impact_chain(self, changed_method: str, max_depth: int) -> List[ImpactNode]:
        """追踪影响链，通过反向调用图查找所有受影响的调用者"""
        impact_nodes = []
        visited = set()
        
        callers = self._find_all_callers(changed_method, max_depth, visited)
        
        for caller, depth in callers:
            caller_class = caller.split('.')[0] if '.' in caller else caller
            
            if caller_class in self.java_classes:
                class_info = self.java_classes[caller_class]
                
                is_controller = class_info.is_controller
                
                impact_type = 'direct_impact' if depth == 1 else 'method_or_class_dependency' if depth == 2 else 'indirect_impact'
                if is_controller:
                    impact_type = 'direct_impact' if depth == 1 else 'service_dependency' if depth == 2 else 'indirect_impact'
                
                impact_node = ImpactNode(
                    class_name=caller_class,
                    method_name=caller.split('.')[1] if '.' in caller else caller,
                    file_path=class_info.file_path,
                    impact_type=impact_type,
                    depth=depth
                )
                impact_nodes.append(impact_node)
        
        return impact_nodes
    
    def _find_all_callers(self, method_key: str, max_depth: int, visited: Set[str]) -> List[Tuple[str, int]]:
        """使用BFS查找方法的所有调用者"""
        callers = []
        queue = [(method_key, 0)]
        
        while queue:
            current, depth = queue.pop(0)
            
            if depth > max_depth:
                continue
            
            if current in visited:
                continue
            
            visited.add(current)
            
            if current in self.reverse_call_graph:
                for caller in self.reverse_call_graph[current]:
                    if caller not in visited:
                        callers.append((caller, depth + 1))
                        queue.append((caller, depth + 1))
        
        return callers
    
    def get_api_endpoints(self) -> List[APIEndpoint]:
        """获取项目中所有API端点信息"""
        endpoints = []
        
        for class_name, class_info in self.java_classes.items():
            if not class_info.is_controller:
                continue
            
            base_path = self._extract_base_path(class_info)
            
            for method_name, method_info in class_info.methods.items():
                if method_info.is_api and method_info.http_method:
                    path = self._extract_method_path(method_info, base_path)
                    
                    endpoint = APIEndpoint(
                        method=f"{method_info.http_method} {path}",
                        path=path,
                        http_method=method_info.http_method,
                        controller_class=class_name,
                        method_name=method_name,
                        file_path=class_info.file_path,
                        line_number=method_info.line_start,
                        parameters=method_info.parameters,
                        return_type=method_info.return_type,
                        annotations=method_info.annotations
                    )
                    endpoints.append(endpoint)
        
        return endpoints
    
    def _extract_base_path(self, class_info: JavaClassInfo) -> str:
        """从JavaClassInfo中提取Controller类的base_path"""
        if hasattr(class_info, 'base_path') and class_info.base_path:
            return class_info.base_path
        return ""
    
    def _extract_method_path(self, method_info: JavaMethodInfo, base_path: str) -> str:
        """拼接Controller基础路径和方法路径"""
        if method_info.api_path:
            return f"{base_path}{method_info.api_path}".replace("//", "/")
        
        return base_path if base_path else "/"
    
    def get_class_info(self, class_name: str) -> Optional[JavaClassInfo]:
        return self.java_classes.get(class_name)
    
    def get_method_info(self, class_name: str, method_name: str) -> Optional[JavaMethodInfo]:
        class_info = self.java_classes.get(class_name)
        if class_info:
            return class_info.methods.get(method_name)
        return None
    
    def get_call_graph(self) -> Dict[str, Set[str]]:
        """获取正向调用图"""
        return dict(self.call_graph)
    
    def get_reverse_call_graph(self) -> Dict[str, Set[str]]:
        """获取反向调用图"""
        return dict(self.reverse_call_graph)
