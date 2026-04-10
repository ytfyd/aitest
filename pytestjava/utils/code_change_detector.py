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
    """使用Git检测代码变更并使用JCCI进行分析"""
    
    def __init__(self, repo_path: str, project_path: str = None):
        try:
            self.repo = Repo(repo_path)
            self.repo_path = Path(repo_path).resolve()
            self.project_path = Path(project_path).resolve() if project_path else self.repo_path
        except InvalidGitRepositoryError:
            raise ValueError(f"'{repo_path}' 不是有效的Git仓库")
        
        self.jcci_analyzer = JCCIAnalyzer(str(self.project_path))
    
    def __del__(self):
        try:
            if hasattr(self, 'repo') and self.repo:
                self.repo.close()
        except Exception:
            pass
    
    def get_changed_files(self, commit_range: str = "HEAD~1..HEAD") -> List[str]:
        is_branch_comparison = ('..' in commit_range and 
                                not commit_range.startswith('HEAD') and
                                not any(c.isdigit() for c in commit_range.split('..')[0][:7]))
        
        if is_branch_comparison:
            logger.info(f"[CodeChangeDetector] 分支对比模式: {commit_range}")
            changed_files = self._get_changed_files_from_branch_diff(commit_range)
        else:
            logger.info(f"[CodeChangeDetector] 提交范围模式: {commit_range}")
            changed_files = self._get_changed_files_from_commit_range(commit_range)
        
        seen = set()
        unique_java_files = []
        for f in changed_files:
            if f and f not in seen:
                seen.add(f)
                unique_java_files.append(f)
        
        logger.info(f"[CodeChangeDetector] 检测到 {len(unique_java_files)} 个变更的Java文件")
        return unique_java_files
    
    def _get_changed_files_from_branch_diff(self, branch_range: str) -> List[str]:
        parts = branch_range.split('..')
        if len(parts) != 2:
            logger.error(f"[CodeChangeDetector] 无效的分支对比格式: {branch_range}")
            return []
        
        target_branch = parts[0].strip()
        source_branch = parts[1].strip()
        logger.info(f"[CodeChangeDetector] 分支对比: {target_branch} vs {source_branch}")
        
        try:
            target_commit = self.repo.commit(target_branch)
            source_commit = self.repo.commit(source_branch)
        except Exception as e:
            logger.error(f"[CodeChangeDetector] 分支引用无效: {e}")
            try:
                logger.info("[CodeChangeDetector] 尝试 git fetch --all ...")
                self.repo.git.fetch('--all', '--prune')
                target_commit = self.repo.commit(target_branch)
                source_commit = self.repo.commit(source_branch)
            except Exception as fetch_error:
                logger.error(f"[CodeChangeDetector] git fetch 后仍失败: {fetch_error}")
                return []
        
        diff_base = target_branch
        try:
            merge_base_output = self.repo.git.merge_base(target_branch, source_branch).strip()
            if merge_base_output:
                diff_base = merge_base_output
                logger.info(f"[CodeChangeDetector] merge-base: {diff_base}")
                
                source_commit_hash = self.repo.commit(source_branch).hexsha
                if diff_base == source_commit_hash:
                    logger.info("[CodeChangeDetector] merge-base 等于 source 分支，target 是 merge commit")
                    target_commit_obj = self.repo.commit(target_branch)
                    if len(target_commit_obj.parents) > 1:
                        for parent in target_commit_obj.parents:
                            if parent.hexsha != source_commit_hash:
                                diff_base = parent.hexsha
                                logger.info(f"[CodeChangeDetector] 使用 target 的非 source parent 作为 base: {diff_base}")
                                break
                    elif len(target_commit_obj.parents) == 1:
                        diff_base = target_commit_obj.parents[0].hexsha
                        logger.info(f"[CodeChangeDetector] 使用 target 的 parent 作为 base: {diff_base}")
        except Exception as e:
            logger.warning(f"[CodeChangeDetector] merge-base 失败，使用target分支: {e}")
        
        try:
            diff_output = self.repo.git.diff(diff_base, source_branch, '--', '*.java', name_only=True)
            if diff_output.strip():
                changed_files = [f.strip() for f in diff_output.split('\n') if f.strip()]
                logger.info(f"[CodeChangeDetector] git diff 发现 {len(changed_files)} 个Java文件变更")
                return changed_files
            else:
                logger.warning("[CodeChangeDetector] 两个分支在Java文件上没有差异")
                return []
        except Exception as diff_error:
            logger.error(f"[CodeChangeDetector] git diff 失败: {diff_error}")
            try:
                base_commit = self.repo.commit(diff_base)
                diff = base_commit.diff(source_commit)
                java_diffs = [item.a_path or item.b_path for item in diff 
                              if (item.a_path or item.b_path or '').endswith('.java')]
                logger.info(f"[CodeChangeDetector] commit.diff() 发现 {len(java_diffs)} 个Java文件变更")
                return java_diffs
            except Exception as fallback_error:
                logger.error(f"[CodeChangeDetector] 备选方案也失败: {fallback_error}")
                return []
    
    def _get_changed_files_from_commit_range(self, commit_range: str) -> List[str]:
        changed_files = []
        try:
            commits = list(self.repo.iter_commits(commit_range))
            if not commits:
                logger.warning(f"[CodeChangeDetector] 提交范围 '{commit_range}' 中未找到提交")
                return []
            
            logger.info(f"[CodeChangeDetector] 找到 {len(commits)} 个提交")
            for commit in commits:
                if commit.parents:
                    diff = commit.parents[0].diff(commit)
                    for item in diff:
                        if item.a_path and item.a_path.endswith('.java'):
                            changed_files.append(item.a_path)
                else:
                    for file_path in commit.stats.files.keys():
                        if file_path.endswith('.java'):
                            changed_files.append(file_path)
        except Exception as e:
            logger.error(f"[CodeChangeDetector] 获取提交范围变更失败: {e}")
        
        return changed_files
    
    def get_file_diff(self, file_path: str, commit_range: str = "HEAD~1..HEAD") -> Tuple[str, str]:
        is_branch_comparison = ('..' in commit_range and 
                                not commit_range.startswith('HEAD') and
                                not any(c.isdigit() for c in commit_range.split('..')[0][:7]))
        
        if is_branch_comparison:
            return self._get_file_diff_from_branch_diff(file_path, commit_range)
        else:
            return self._get_file_diff_from_commit_range(file_path, commit_range)
    
    def _get_file_diff_from_branch_diff(self, file_path: str, branch_range: str) -> Tuple[str, str]:
        old_content = ""
        new_content = ""
        try:
            parts = branch_range.split('..')
            target_branch = parts[0].strip()
            source_branch = parts[1].strip()
            
            diff_base = target_branch
            try:
                merge_base_output = self.repo.git.merge_base(target_branch, source_branch).strip()
                if merge_base_output:
                    diff_base = merge_base_output
                    source_commit_hash = self.repo.commit(source_branch).hexsha
                    if diff_base == source_commit_hash:
                        target_commit_obj = self.repo.commit(target_branch)
                        if len(target_commit_obj.parents) > 1:
                            for parent in target_commit_obj.parents:
                                if parent.hexsha != source_commit_hash:
                                    diff_base = parent.hexsha
                                    break
                        elif len(target_commit_obj.parents) == 1:
                            diff_base = target_commit_obj.parents[0].hexsha
            except Exception:
                pass
            
            base_commit = self.repo.commit(diff_base)
            source_commit = self.repo.commit(source_branch)
            
            try:
                new_content = (source_commit.tree / file_path).data_stream.read().decode('utf-8')
            except Exception:
                new_content = ""
            
            try:
                old_content = (base_commit.tree / file_path).data_stream.read().decode('utf-8')
            except Exception:
                old_content = ""
        except Exception as e:
            logger.error(f"[CodeChangeDetector] 获取分支文件差异失败: {e}")
        
        return old_content, new_content
    
    def _get_file_diff_from_commit_range(self, file_path: str, commit_range: str) -> Tuple[str, str]:
        old_content = ""
        new_content = ""
        try:
            commits = list(self.repo.iter_commits(commit_range))
            if commits:
                latest_commit = commits[0]
                try:
                    new_content = (latest_commit.tree / file_path).data_stream.read().decode('utf-8')
                except Exception:
                    new_content = ""
                
                if latest_commit.parents:
                    try:
                        old_content = (latest_commit.parents[0].tree / file_path).data_stream.read().decode('utf-8')
                    except Exception:
                        old_content = ""
        except Exception as e:
            logger.error(f"[CodeChangeDetector] 获取提交文件差异失败: {e}")
        
        return old_content, new_content
    
    def parse_java_class(self, content: str) -> Optional[ClassSignature]:
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
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        
        class_end = pos
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
        annotations = []
        pattern = r'@\w+(?:\([^)]*\))?'
        for match in re.finditer(pattern, text):
            annotations.append(match.group(0))
        return annotations
    
    def _extract_methods(self, content: str, class_start: int, class_end: int) -> List[MethodSignature]:
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
        changes = []
        old_class = self.parse_java_class(old_content) if old_content else None
        new_class = self.parse_java_class(new_content) if new_content else None
        
        if not old_class and new_class:
            element = JavaElement(
                element_type="class", name=new_class.name, qualified_name=new_class.name,
                file_path=file_path, line_number=new_class.line_number,
                signature=new_class.content[:200], annotations=new_class.annotations
            )
            changes.append(CodeChange(change_type=ChangeType.ADDED, element=element, diff_content=new_class.content))
            return changes
        
        if old_class and not new_class:
            element = JavaElement(
                element_type="class", name=old_class.name, qualified_name=old_class.name,
                file_path=file_path, line_number=old_class.line_number,
                signature=old_class.content[:200], annotations=old_class.annotations
            )
            changes.append(CodeChange(change_type=ChangeType.DELETED, element=element, diff_content=old_class.content))
            return changes
        
        if not old_class or not new_class:
            return changes
        
        old_methods = {m.name: m for m in old_class.methods}
        new_methods = {m.name: m for m in new_class.methods}
        
        for method_name, new_method in new_methods.items():
            if method_name not in old_methods:
                element = JavaElement(
                    element_type="method", name=method_name,
                    qualified_name=f"{new_class.name}.{method_name}",
                    file_path=file_path, line_number=new_method.line_number,
                    signature=f"{new_method.return_type} {method_name}({', '.join(new_method.parameters)})",
                    annotations=new_method.annotations
                )
                changes.append(CodeChange(change_type=ChangeType.ADDED, element=element, diff_content=new_method.content))
            else:
                old_method = old_methods[method_name]
                if old_method.content.strip() != new_method.content.strip():
                    new_element = JavaElement(
                        element_type="method", name=method_name,
                        qualified_name=f"{new_class.name}.{method_name}",
                        file_path=file_path, line_number=new_method.line_number,
                        signature=f"{new_method.return_type} {method_name}({', '.join(new_method.parameters)})",
                        annotations=new_method.annotations
                    )
                    changes.append(CodeChange(
                        change_type=ChangeType.MODIFIED, element=new_element,
                        diff_content=self._get_method_diff(old_method.content, new_method.content)
                    ))
        
        for method_name in old_methods:
            if method_name not in new_methods:
                old_method = old_methods[method_name]
                element = JavaElement(
                    element_type="method", name=method_name,
                    qualified_name=f"{old_class.name}.{method_name}",
                    file_path=file_path, line_number=old_method.line_number,
                    signature=f"{old_method.return_type} {method_name}({', '.join(old_method.parameters)})",
                    annotations=old_method.annotations
                )
                changes.append(CodeChange(change_type=ChangeType.DELETED, element=element, diff_content=old_method.content))
        
        old_fields = {f.name: f for f in old_class.fields}
        new_fields = {f.name: f for f in new_class.fields}
        
        for field_name, new_field in new_fields.items():
            if field_name not in old_fields:
                element = JavaElement(
                    element_type="field", name=field_name,
                    qualified_name=f"{new_class.name}.{field_name}",
                    file_path=file_path, line_number=new_field.line_number,
                    signature=f"{new_field.type} {field_name}", annotations=new_field.annotations
                )
                changes.append(CodeChange(change_type=ChangeType.ADDED, element=element, diff_content=new_field.content))
            else:
                old_field = old_fields[field_name]
                if old_field.content.strip() != new_field.content.strip():
                    new_element = JavaElement(
                        element_type="field", name=field_name,
                        qualified_name=f"{new_class.name}.{field_name}",
                        file_path=file_path, line_number=new_field.line_number,
                        signature=f"{new_field.type} {field_name}", annotations=new_field.annotations
                    )
                    changes.append(CodeChange(
                        change_type=ChangeType.MODIFIED, element=new_element,
                        diff_content=f"Old: {old_field.content}\nNew: {new_field.content}"
                    ))
        
        for field_name in old_fields:
            if field_name not in new_fields:
                old_field = old_fields[field_name]
                element = JavaElement(
                    element_type="field", name=field_name,
                    qualified_name=f"{old_class.name}.{field_name}",
                    file_path=file_path, line_number=old_field.line_number,
                    signature=f"{old_field.type} {field_name}", annotations=old_field.annotations
                )
                changes.append(CodeChange(change_type=ChangeType.DELETED, element=element, diff_content=old_field.content))
        
        return changes
    
    def _get_method_diff(self, old_content: str, new_content: str) -> str:
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
        changed_files = self.get_changed_files(commit_range)
        all_changes = {}
        for file_path in changed_files:
            old_content, new_content = self.get_file_diff(file_path, commit_range)
            changes = self.detect_changes(file_path, old_content, new_content)
            if changes:
                all_changes[file_path] = changes
        return all_changes
    
    def get_change_summary(self, commit_range: str = "HEAD~1..HEAD") -> Dict:
        changed_files = self.get_changed_files(commit_range)
        all_changes = self.analyze_all_changes(commit_range)
        
        summary = {
            'total_files_changed': len(changed_files),
            'total_changes': sum(len(changes) for changes in all_changes.values()),
            'added_methods': 0, 'modified_methods': 0, 'deleted_methods': 0,
            'added_fields': 0, 'modified_fields': 0, 'deleted_fields': 0,
            'added_classes': 0, 'deleted_classes': 0,
            'files': {}
        }
        
        for file_path in changed_files:
            file_summary = {'added': [], 'modified': [], 'deleted': []}
            if file_path in all_changes:
                for change in all_changes[file_path]:
                    key = f"{change.change_type.value}_{change.element.element_type}s"
                    if key in summary:
                        summary[key] += 1
                    if change.change_type == ChangeType.ADDED:
                        file_summary['added'].append(change.element.name)
                    elif change.change_type == ChangeType.MODIFIED:
                        file_summary['modified'].append(change.element.name)
                    elif change.change_type == ChangeType.DELETED:
                        file_summary['deleted'].append(change.element.name)
            summary['files'][file_path] = file_summary
        
        return summary
