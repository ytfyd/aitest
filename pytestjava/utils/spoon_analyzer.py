import os
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Set, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum


logger = logging.getLogger(__name__)


class ChangeType(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass
class JavaElement:
    element_type: str
    name: str
    qualified_name: str
    file_path: str
    line_number: int
    signature: str
    annotations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CodeChange:
    change_type: ChangeType
    element: JavaElement
    old_element: Optional[JavaElement] = None
    diff_content: str = ""
    
    def to_dict(self) -> Dict:
        result = {
            'change_type': self.change_type.value,
            'element': self.element.to_dict(),
            'diff_content': self.diff_content
        }
        if self.old_element:
            result['old_element'] = self.old_element.to_dict()
        return result


@dataclass
class APIEndpoint:
    method: str
    path: str
    http_method: str
    controller_class: str
    method_name: str
    file_path: str
    line_number: int
    parameters: List[Dict] = field(default_factory=list)
    return_type: str = ""
    annotations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ImpactResult:
    affected_endpoints: List[APIEndpoint]
    change_chain: List[Dict]
    impact_type: str
    confidence: float
    
    def to_dict(self) -> Dict:
        return {
            'affected_endpoints': [ep.to_dict() for ep in self.affected_endpoints],
            'change_chain': self.change_chain,
            'impact_type': self.impact_type,
            'confidence': self.confidence
        }


class SpoonAnalyzer:
    """Spoon-based Java code analyzer for impact analysis"""
    
    def __init__(self, project_path: str, java_source_version: str = "17"):
        self.project_path = Path(project_path).resolve()
        self.java_source_version = java_source_version
        self.spoon_jar_path = self._get_spoon_jar_path()
        self._temp_dir = None
        
    def _get_spoon_jar_path(self) -> Path:
        spoon_dir = Path(__file__).parent.parent / "lib"
        spoon_dir.mkdir(exist_ok=True)
        spoon_jar = spoon_dir / "spoon-core-10.4.2-jar-with-dependencies.jar"
        return spoon_jar
    
    def _ensure_spoon_available(self) -> bool:
        if not self.spoon_jar_path.exists():
            logger.warning(f"Spoon JAR not found at {self.spoon_jar_path}")
            logger.info("Spoon JAR will be downloaded automatically on first use")
            return False
        return True
    
    def analyze_project(self) -> Dict[str, Any]:
        self._ensure_spoon_available()
        
        java_files = list(self.project_path.rglob("*.java"))
        java_files = [f for f in java_files if "target" not in str(f) and "build" not in str(f)]
        
        if not java_files:
            logger.warning(f"No Java source files found in {self.project_path}")
            return {}
        
        analysis_result = {
            'project_path': str(self.project_path),
            'java_files': [str(f.relative_to(self.project_path)) for f in java_files],
            'classes': [],
            'methods': [],
            'fields': [],
            'controllers': [],
            'services': [],
            'repositories': []
        }
        
        for java_file in java_files:
            try:
                file_analysis = self._analyze_java_file(java_file)
                if file_analysis:
                    analysis_result['classes'].extend(file_analysis.get('classes', []))
                    analysis_result['methods'].extend(file_analysis.get('methods', []))
                    analysis_result['fields'].extend(file_analysis.get('fields', []))
                    
                    if file_analysis.get('is_controller'):
                        analysis_result['controllers'].append(file_analysis)
                    if file_analysis.get('is_service'):
                        analysis_result['services'].append(file_analysis)
                    if file_analysis.get('is_repository'):
                        analysis_result['repositories'].append(file_analysis)
            except Exception as e:
                logger.error(f"Error analyzing {java_file}: {e}")
        
        return analysis_result
    
    def _analyze_java_file(self, java_file: Path) -> Optional[Dict]:
        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            analysis = {
                'file_path': str(java_file.relative_to(self.project_path)),
                'classes': [],
                'methods': [],
                'fields': [],
                'is_controller': False,
                'is_service': False,
                'is_repository': False
            }
            
            analysis['is_controller'] = any(ann in content for ann in ['@RestController', '@Controller'])
            analysis['is_service'] = '@Service' in content
            analysis['is_repository'] = '@Repository' in content
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error reading file {java_file}: {e}")
            return None
    
    def extract_api_endpoints(self, controller_file: Path) -> List[APIEndpoint]:
        endpoints = []
        
        try:
            with open(controller_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            
            base_path = ""
            request_mapping_match = re.search(r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?"([^"]+)"', content)
            if request_mapping_match:
                base_path = request_mapping_match.group(1)
            
            class_name_match = re.search(r'(?:public\s+)?class\s+(\w+)', content)
            class_name = class_name_match.group(1) if class_name_match else "Unknown"
            
            method_mappings = [
                ('@GetMapping', 'GET'),
                ('@PostMapping', 'POST'),
                ('@PutMapping', 'PUT'),
                ('@DeleteMapping', 'DELETE'),
                ('@PatchMapping', 'PATCH')
            ]
            
            for annotation, http_method in method_mappings:
                pattern = rf'{annotation}\s*\((.*?)\)'
                matches = re.findall(pattern, content, re.DOTALL)
                
                for match in matches:
                    path = ""
                    
                    value_match = re.search(r'value\s*=\s*"([^"]+)"', match)
                    if value_match:
                        path = value_match.group(1)
                    else:
                        simple_match = re.search(r'^\s*"([^"]+)"', match)
                        if simple_match:
                            path = simple_match.group(1)
                    
                    if path:
                        full_path = f"{base_path}{path}".replace("//", "/")
                        
                        endpoint = APIEndpoint(
                            method=f"{http_method} {full_path}",
                            path=full_path,
                            http_method=http_method,
                            controller_class=class_name,
                            method_name="",
                            file_path=str(controller_file.relative_to(self.project_path)),
                            line_number=0,
                            annotations=[annotation]
                        )
                        endpoints.append(endpoint)
            
            request_method_pattern = r'@RequestMapping\s*\((.*?)\)'
            request_method_matches = re.findall(request_method_pattern, content, re.DOTALL)
            
            for match in request_method_matches:
                method_match = re.search(r'method\s*=\s*RequestMethod\.(\w+)', match)
                if method_match:
                    http_method = method_match.group(1)
                    path = ""
                    
                    value_match = re.search(r'value\s*=\s*"([^"]+)"', match)
                    if value_match:
                        path = value_match.group(1)
                    
                    if path:
                        full_path = f"{base_path}{path}".replace("//", "/")
                        
                        endpoint = APIEndpoint(
                            method=f"{http_method} {full_path}",
                            path=full_path,
                            http_method=http_method,
                            controller_class=class_name,
                            method_name="",
                            file_path=str(controller_file.relative_to(self.project_path)),
                            line_number=0,
                            annotations=['@RequestMapping']
                        )
                        endpoints.append(endpoint)
        
        except Exception as e:
            logger.error(f"Error extracting endpoints from {controller_file}: {e}")
        
        return endpoints
    
    def analyze_method_calls(self, java_file: Path) -> Dict[str, List[str]]:
        call_graph = {}
        
        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            
            class_name_match = re.search(r'(?:public\s+)?class\s+(\w+)', content)
            if not class_name_match:
                return call_graph
            
            class_name = class_name_match.group(1)
            
            method_pattern = r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{'
            method_matches = re.finditer(method_pattern, content)
            
            for method_match in method_matches:
                method_name = method_match.group(1)
                method_start = method_match.end()
                
                brace_count = 1
                pos = method_start
                method_body = ""
                
                while pos < len(content) and brace_count > 0:
                    if content[pos] == '{':
                        brace_count += 1
                    elif content[pos] == '}':
                        brace_count -= 1
                    method_body += content[pos]
                    pos += 1
                
                called_methods = []
                
                call_pattern = r'(\w+)\s*\.\s*(\w+)\s*\('
                for call_match in re.finditer(call_pattern, method_body):
                    object_name = call_match.group(1)
                    called_method = call_match.group(2)
                    called_methods.append(f"{object_name}.{called_method}")
                
                call_graph[f"{class_name}.{method_name}"] = called_methods
        
        except Exception as e:
            logger.error(f"Error analyzing method calls in {java_file}: {e}")
        
        return call_graph
    
    def find_field_usages(self, java_file: Path, field_name: str) -> List[Dict]:
        usages = []
        
        try:
            with open(java_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            
            class_name_match = re.search(r'(?:public\s+)?class\s+(\w+)', content)
            class_name = class_name_match.group(1) if class_name_match else "Unknown"
            
            method_pattern = r'(?:public|private|protected)?\s*(?:static\s+)?(?:\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+[\w\s,]+)?\s*\{'
            
            for method_match in re.finditer(method_pattern, content):
                method_name = method_match.group(1)
                method_start = method_match.start()
                
                method_end = method_start
                brace_count = 0
                found_opening = False
                
                for i in range(method_start, len(content)):
                    if content[i] == '{':
                        brace_count += 1
                        found_opening = True
                    elif content[i] == '}':
                        brace_count -= 1
                    
                    if found_opening and brace_count == 0:
                        method_end = i
                        break
                
                method_body = content[method_start:method_end]
                
                if field_name in method_body:
                    usages.append({
                        'class': class_name,
                        'method': method_name,
                        'file': str(java_file.relative_to(self.project_path))
                    })
        
        except Exception as e:
            logger.error(f"Error finding field usages in {java_file}: {e}")
        
        return usages
