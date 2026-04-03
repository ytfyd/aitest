import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple
from dataclasses import dataclass, field
from git import Repo, Commit
from git.diff import Diff
from git.exc import InvalidGitRepositoryError

from .jcci_analyzer import JCCIAnalyzer, JavaElement, CodeChange, ChangeType

logger = logging.getLogger(__name__)


@dataclass
class MethodSignature:
    name: str
    return_type: str
    parameters: List[str]
    annotations: List[str]
    line_number: int
    body_start: int
    body_end: int
    content: str


@dataclass
class FieldSignature:
    name: str
    type: str
    annotations: List[str]
    line_number: int
    content: str


@dataclass
class ClassSignature:
    name: str
    annotations: List[str]
    methods: List[MethodSignature]
    fields: List[FieldSignature]
    line_number: int
    content: str


class CodeChangeDetector:
    """Detect code changes using Git and analyze with JCCI"""
    
    def __init__(self, repo_path: str, project_path: str = None):
        try:
            self.repo = Repo(repo_path)
            self.repo_path = Path(repo_path).resolve()
            self.project_path = Path(project_path).resolve() if project_path else self.repo_path
        except InvalidGitRepositoryError:
            raise ValueError(
                f"'{repo_path}' is not a valid Git repository. "
                f"Please initialize a Git repository first: cd {repo_path} && git init"
            )
        
        self.jcci_analyzer = JCCIAnalyzer(str(self.project_path))
        self._temp_dir = None
    
    def __del__(self):
        try:
            if hasattr(self, 'repo') and self.repo:
                self.repo.close()
        except Exception:
            pass
    
    def get_changed_files(self, commit_range: str = "HEAD~1..HEAD") -> List[str]:
        """Get list of changed Java files in the specified commit range (committed changes only)"""
        changed_files = []
        
        # Only check for committed changes in the specified range
        try:
            commits = list(self.repo.iter_commits(commit_range))
            
            if not commits:
                try:
                    all_commits = list(self.repo.iter_commits())
                    if all_commits:
                        first_commit = all_commits[-1]
                        if first_commit.parents:
                            diff = first_commit.parents[0].diff(first_commit)
                            changed_files.extend([item.a_path for item in diff if item.a_path and item.a_path.endswith('.java')])
                        else:
                            for file_path in first_commit.stats.files.keys():
                                if file_path.endswith('.java'):
                                    changed_files.append(file_path)
                except Exception as e:
                    logger.error(f"Error getting changed files: {e}")
            else:
                for commit in commits:
                    if commit.parents:
                        diff = commit.parents[0].diff(commit)
                        changed_files.extend([item.a_path for item in diff if item.a_path and item.a_path.endswith('.java')])
                    else:
                        for file_path in commit.stats.files.keys():
                            if file_path.endswith('.java'):
                                changed_files.append(file_path)
        
        except Exception as e:
            logger.error(f"Error getting commits: {e}")
            try:
                all_commits = list(self.repo.iter_commits())
                if all_commits:
                    first_commit = all_commits[-1]
                    if not first_commit.parents:
                        for file_path in first_commit.stats.files.keys():
                            if file_path.endswith('.java'):
                                changed_files.append(file_path)
            except Exception as e2:
                logger.error(f"Error in fallback: {e2}")
        
        # Remove duplicates
        seen = set()
        unique_java_files = []
        for f in changed_files:
            if f and f not in seen:
                seen.add(f)
                unique_java_files.append(f)
        
        return unique_java_files
    
    def get_file_diff(self, file_path: str, commit_range: str = "HEAD~1..HEAD") -> Tuple[str, str]:
        """Get old and new content of a file from commits only"""
        old_content = ""
        new_content = ""
        
        # Get content from commits in the specified range
        try:
            commits = list(self.repo.iter_commits(commit_range))
            
            if commits:
                latest_commit = commits[0]
                
                # Get new content from latest commit
                try:
                    new_content = (latest_commit.tree / file_path).data_stream.read().decode('utf-8')
                    logger.info(f"Read new version from commit {latest_commit.hexsha[:7]} for {file_path}")
                except Exception:
                    new_content = ""
                    logger.warning(f"File {file_path} not found in commit {latest_commit.hexsha[:7]}")
                
                # Get old content from parent commit
                if latest_commit.parents:
                    try:
                        old_content = (latest_commit.parents[0].tree / file_path).data_stream.read().decode('utf-8')
                        logger.info(f"Read old version from parent commit for {file_path}")
                    except Exception:
                        old_content = ""
                        logger.info(f"File {file_path} is new (not in parent commit)")
            else:
                logger.warning(f"No commits found in range {commit_range}")
        except Exception as e:
            logger.error(f"Error getting file diff from commits: {e}")
        
        return old_content, new_content
    
    def parse_java_class(self, content: str) -> Optional[ClassSignature]:
        """Parse a Java class and extract its signature"""
        if not content:
            return None
        
        class_pattern = r'(?:public\s+|private\s+|protected\s+)?(?:abstract\s+|final\s+)?(?:class|interface|enum)\s+(\w+)(?:\s+extends\s+\w+)?(?:\s+implements\s+[\w\s,]+)?\s*\{'
        class_match = re.search(class_pattern, content)
        
        if not class_match:
            return None
        
        class_name = class_match.group(1)
        class_start = class_match.end()
        line_number = content[:class_match.start()].count('\n') + 1
        
        class_annotations = self._extract_annotations(content[:class_match.start()])
        
        brace_count = 1
        pos = class_start
        class_end = class_start
        
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        
        class_end = pos
        class_body = content[class_start:class_end]
        
        methods = self._extract_methods(content, class_start, class_end)
        fields = self._extract_fields(content, class_start, class_end)
        
        return ClassSignature(
            name=class_name,
            annotations=class_annotations,
            methods=methods,
            fields=fields,
            line_number=line_number,
            content=content
        )
    
    def _extract_annotations(self, text: str) -> List[str]:
        """Extract annotations from text"""
        annotations = []
        pattern = r'@\w+(?:\([^)]*\))?'
        for match in re.finditer(pattern, text):
            annotations.append(match.group(0))
        return annotations
    
    def _extract_methods(self, content: str, class_start: int, class_end: int) -> List[MethodSignature]:
        """Extract method signatures from class body"""
        methods = []
        class_body = content[class_start:class_end]
        
        method_pattern = r'((?:@\w+(?:\([^)]*\))?\s*)*)((?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?(?:\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*\(((?:[^()]|\([^()]*\))*)\)(?:\s+throws\s+[\w\s,]+)?)\s*(?:\{|;)'
        
        for match in re.finditer(method_pattern, class_body):
            annotations_str = match.group(1)
            method_name = match.group(3)
            params_str = match.group(4)
            
            if method_name in ['if', 'for', 'while', 'switch', 'catch', 'class', 'interface']:
                continue
            
            line_number = class_body[:match.start()].count('\n') + 1
            
            method_annotations = self._extract_annotations(annotations_str)
            
            return_type = match.group(2).split(method_name)[0].strip().split()[-1] if method_name else "void"
            
            parameters = []
            if params_str.strip():
                param_parts = []
                current_param = ""
                paren_depth = 0
                
                for char in params_str:
                    if char == '(':
                        paren_depth += 1
                        current_param += char
                    elif char == ')':
                        paren_depth -= 1
                        current_param += char
                    elif char == ',' and paren_depth == 0:
                        param_parts.append(current_param.strip())
                        current_param = ""
                    else:
                        current_param += char
                
                if current_param.strip():
                    param_parts.append(current_param.strip())
                
                for param in param_parts:
                    param = param.strip()
                    if param:
                        param_clean = re.sub(r'@\w+(?:\([^)]*\))?\s*', '', param)
                        parts = param_clean.split()
                        if len(parts) >= 2:
                            parameters.append(parts[-2])
            
            body_start = match.end()
            body_end = body_start
            
            if match.group(0).rstrip().endswith('{'):
                brace_count = 1
                pos = body_start
                while pos < len(class_body) and brace_count > 0:
                    if class_body[pos] == '{':
                        brace_count += 1
                    elif class_body[pos] == '}':
                        brace_count -= 1
                    pos += 1
                body_end = pos
            
            method_content = class_body[match.start():body_end]
            
            methods.append(MethodSignature(
                name=method_name,
                return_type=return_type,
                parameters=parameters,
                annotations=method_annotations,
                line_number=line_number,
                body_start=class_start + match.start(),
                body_end=class_start + body_end,
                content=method_content
            ))
        
        return methods
    
    def _extract_fields(self, content: str, class_start: int, class_end: int) -> List[FieldSignature]:
        """Extract field signatures from class body"""
        fields = []
        class_body = content[class_start:class_end]
        
        field_pattern = r'(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?(?:transient\s+)?(?:volatile\s+)?(\w+(?:<[\w\s,<>]+>)?)\s+(\w+)\s*(?:=|;)'
        
        for match in re.finditer(field_pattern, class_body):
            field_type = match.group(1)
            field_name = match.group(2)
            
            if field_type in ['return', 'if', 'for', 'while', 'switch', 'catch', 'throw', 'new']:
                continue
            
            line_number = class_body[:match.start()].count('\n') + 1
            
            field_annotations = self._extract_annotations(class_body[:match.start()])
            
            field_content = match.group(0)
            
            fields.append(FieldSignature(
                name=field_name,
                type=field_type,
                annotations=field_annotations,
                line_number=line_number,
                content=field_content
            ))
        
        return fields
    
    def detect_changes(self, file_path: str, old_content: str, new_content: str) -> List[CodeChange]:
        """Detect changes between old and new versions of a file"""
        changes = []
        
        old_class = self.parse_java_class(old_content) if old_content else None
        new_class = self.parse_java_class(new_content) if new_content else None
        
        if not old_class and new_class:
            element = JavaElement(
                element_type="class",
                name=new_class.name,
                qualified_name=new_class.name,
                file_path=file_path,
                line_number=new_class.line_number,
                signature=new_class.content[:200],
                annotations=new_class.annotations
            )
            changes.append(CodeChange(
                change_type=ChangeType.ADDED,
                element=element,
                diff_content=new_class.content
            ))
            return changes
        
        if old_class and not new_class:
            element = JavaElement(
                element_type="class",
                name=old_class.name,
                qualified_name=old_class.name,
                file_path=file_path,
                line_number=old_class.line_number,
                signature=old_class.content[:200],
                annotations=old_class.annotations
            )
            changes.append(CodeChange(
                change_type=ChangeType.DELETED,
                element=element,
                diff_content=old_class.content
            ))
            return changes
        
        if not old_class or not new_class:
            return changes
        
        old_methods = {m.name: m for m in old_class.methods}
        new_methods = {m.name: m for m in new_class.methods}
        
        for method_name, new_method in new_methods.items():
            if method_name not in old_methods:
                element = JavaElement(
                    element_type="method",
                    name=method_name,
                    qualified_name=f"{new_class.name}.{method_name}",
                    file_path=file_path,
                    line_number=new_method.line_number,
                    signature=f"{new_method.return_type} {method_name}({', '.join(new_method.parameters)})",
                    annotations=new_method.annotations
                )
                changes.append(CodeChange(
                    change_type=ChangeType.ADDED,
                    element=element,
                    diff_content=new_method.content
                ))
            else:
                old_method = old_methods[method_name]
                if old_method.content.strip() != new_method.content.strip():
                    old_element = JavaElement(
                        element_type="method",
                        name=method_name,
                        qualified_name=f"{old_class.name}.{method_name}",
                        file_path=file_path,
                        line_number=old_method.line_number,
                        signature=f"{old_method.return_type} {method_name}({', '.join(old_method.parameters)})",
                        annotations=old_method.annotations
                    )
                    new_element = JavaElement(
                        element_type="method",
                        name=method_name,
                        qualified_name=f"{new_class.name}.{method_name}",
                        file_path=file_path,
                        line_number=new_method.line_number,
                        signature=f"{new_method.return_type} {method_name}({', '.join(new_method.parameters)})",
                        annotations=new_method.annotations
                    )
                    changes.append(CodeChange(
                        change_type=ChangeType.MODIFIED,
                        element=new_element,
                        old_element=old_element,
                        diff_content=self._get_method_diff(old_method.content, new_method.content)
                    ))
        
        for method_name, old_method in old_methods.items():
            if method_name not in new_methods:
                element = JavaElement(
                    element_type="method",
                    name=method_name,
                    qualified_name=f"{old_class.name}.{method_name}",
                    file_path=file_path,
                    line_number=old_method.line_number,
                    signature=f"{old_method.return_type} {method_name}({', '.join(old_method.parameters)})",
                    annotations=old_method.annotations
                )
                changes.append(CodeChange(
                    change_type=ChangeType.DELETED,
                    element=element,
                    diff_content=old_method.content
                ))
        
        old_fields = {f.name: f for f in old_class.fields}
        new_fields = {f.name: f for f in new_class.fields}
        
        for field_name, new_field in new_fields.items():
            if field_name not in old_fields:
                element = JavaElement(
                    element_type="field",
                    name=field_name,
                    qualified_name=f"{new_class.name}.{field_name}",
                    file_path=file_path,
                    line_number=new_field.line_number,
                    signature=f"{new_field.type} {field_name}",
                    annotations=new_field.annotations
                )
                changes.append(CodeChange(
                    change_type=ChangeType.ADDED,
                    element=element,
                    diff_content=new_field.content
                ))
            else:
                old_field = old_fields[field_name]
                if old_field.content.strip() != new_field.content.strip():
                    old_element = JavaElement(
                        element_type="field",
                        name=field_name,
                        qualified_name=f"{old_class.name}.{field_name}",
                        file_path=file_path,
                        line_number=old_field.line_number,
                        signature=f"{old_field.type} {field_name}",
                        annotations=old_field.annotations
                    )
                    new_element = JavaElement(
                        element_type="field",
                        name=field_name,
                        qualified_name=f"{new_class.name}.{field_name}",
                        file_path=file_path,
                        line_number=new_field.line_number,
                        signature=f"{new_field.type} {field_name}",
                        annotations=new_field.annotations
                    )
                    changes.append(CodeChange(
                        change_type=ChangeType.MODIFIED,
                        element=new_element,
                        old_element=old_element,
                        diff_content=f"Old: {old_field.content}\nNew: {new_field.content}"
                    ))
        
        for field_name, old_field in old_fields.items():
            if field_name not in new_fields:
                element = JavaElement(
                    element_type="field",
                    name=field_name,
                    qualified_name=f"{old_class.name}.{field_name}",
                    file_path=file_path,
                    line_number=old_field.line_number,
                    signature=f"{old_field.type} {field_name}",
                    annotations=old_field.annotations
                )
                changes.append(CodeChange(
                    change_type=ChangeType.DELETED,
                    element=element,
                    diff_content=old_field.content
                ))
        
        return changes
    
    def _get_method_diff(self, old_content: str, new_content: str) -> str:
        """Get a simple diff between old and new method content"""
        old_lines = old_content.strip().split('\n')
        new_lines = new_content.strip().split('\n')
        
        diff_lines = []
        
        for i, line in enumerate(old_lines):
            if i >= len(new_lines) or line != new_lines[i]:
                diff_lines.append(f"- {line}")
        
        for i, line in enumerate(new_lines):
            if i >= len(old_lines) or line != old_lines[i]:
                diff_lines.append(f"+ {line}")
        
        return '\n'.join(diff_lines[:20])
    
    def analyze_all_changes(self, commit_range: str = "HEAD~1..HEAD") -> Dict[str, List[CodeChange]]:
        """Analyze all changes in the specified commit range"""
        changed_files = self.get_changed_files(commit_range)
        
        all_changes = {}
        
        for file_path in changed_files:
            old_content, new_content = self.get_file_diff(file_path, commit_range)
            changes = self.detect_changes(file_path, old_content, new_content)
            
            if changes:
                all_changes[file_path] = changes
        
        return all_changes
    
    def get_change_summary(self, commit_range: str = "HEAD~1..HEAD") -> Dict:
        """Get a summary of all changes"""
        changed_files = self.get_changed_files(commit_range)
        all_changes = self.analyze_all_changes(commit_range)
        
        summary = {
            'total_files_changed': len(changed_files),
            'total_changes': sum(len(changes) for changes in all_changes.values()),
            'added_methods': 0,
            'modified_methods': 0,
            'deleted_methods': 0,
            'added_fields': 0,
            'modified_fields': 0,
            'deleted_fields': 0,
            'added_classes': 0,
            'deleted_classes': 0,
            'files': {}
        }
        
        for file_path in changed_files:
            file_summary = {
                'added': [],
                'modified': [],
                'deleted': []
            }
            
            if file_path in all_changes:
                for change in all_changes[file_path]:
                    if change.element.element_type == 'method':
                        if change.change_type == ChangeType.ADDED:
                            summary['added_methods'] += 1
                            file_summary['added'].append(change.element.name)
                        elif change.change_type == ChangeType.MODIFIED:
                            summary['modified_methods'] += 1
                            file_summary['modified'].append(change.element.name)
                        elif change.change_type == ChangeType.DELETED:
                            summary['deleted_methods'] += 1
                            file_summary['deleted'].append(change.element.name)
                    elif change.element.element_type == 'field':
                        if change.change_type == ChangeType.ADDED:
                            summary['added_fields'] += 1
                            file_summary['added'].append(change.element.name)
                        elif change.change_type == ChangeType.MODIFIED:
                            summary['modified_fields'] += 1
                            file_summary['modified'].append(change.element.name)
                        elif change.change_type == ChangeType.DELETED:
                            summary['deleted_fields'] += 1
                            file_summary['deleted'].append(change.element.name)
                    elif change.element.element_type == 'class':
                        if change.change_type == ChangeType.ADDED:
                            summary['added_classes'] += 1
                        elif change.change_type == ChangeType.DELETED:
                            summary['deleted_classes'] += 1
            
            summary['files'][file_path] = file_summary
        
        return summary
