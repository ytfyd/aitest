import os
import re
from typing import List, Dict, Set, Optional
from git import Repo, Commit
from git.diff import Diff


class GitChangeDetector:
    """Detect API changes by analyzing git commits"""
    
    def __init__(self, repo_path: str = "."):
        self.repo = Repo(repo_path)
        self.api_patterns = [
            r"@RestController",
            r"@RequestMapping",
            r"@GetMapping",
            r"@PostMapping",
            r"@PutMapping",
            r"@DeleteMapping",
            r"@PatchMapping",
            r"@Controller",
            r"@RestControllerAdvice"
        ]
    
    def get_changed_files(self, commit_range: str = "HEAD~1..HEAD") -> List[str]:
        """Get list of changed files in the specified commit range"""
        changed_files = []
        
        try:
            # Parse commit range
            commits = list(self.repo.iter_commits(commit_range))
            
            if not commits:
                # If no commits in range, check current changes
                changed_files = [item.a_path for item in self.repo.index.diff(None)]
                changed_files.extend([item.a_path for item in self.repo.index.diff("HEAD")])
            else:
                # Get changed files from commits
                for commit in commits:
                    if commit.parents:
                        diff = commit.parents[0].diff(commit)
                        changed_files.extend([item.a_path for item in diff])
        
        except Exception as e:
            print(f"Error getting changed files: {e}")
            # Fallback to current changes
            changed_files = [item.a_path for item in self.repo.index.diff(None)]
            changed_files.extend([item.a_path for item in self.repo.index.diff("HEAD")])
        
        # Filter for Java files only
        java_files = [f for f in changed_files if f.endswith('.java')]
        # Remove duplicates while maintaining order
        seen = set()
        unique_java_files = []
        for f in java_files:
            if f not in seen:
                seen.add(f)
                unique_java_files.append(f)
        return unique_java_files
    
    def extract_api_endpoints(self, file_path: str) -> List[Dict[str, str]]:
        """Extract API endpoints from a Java file"""
        endpoints = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # Look for class-level annotations
                class_pattern = r'@RestController.*?class\s+(\w+).*?@RequestMapping\("([^"]+)"\)'
                class_matches = re.findall(class_pattern, content, re.DOTALL)
                
                base_path = ""
                if class_matches:
                    base_path = class_matches[0][1]
                
                # Look for method-level mappings
                method_patterns = [
                    (r'@GetMapping\("([^"]+)"\)', 'GET'),
                    (r'@PostMapping\("([^"]+)"\)', 'POST'),
                    (r'@PutMapping\("([^"]+)"\)', 'PUT'),
                    (r'@DeleteMapping\("([^"]+)"\)', 'DELETE'),
                    (r'@PatchMapping\("([^"]+)"\)', 'PATCH'),
                    (r'@RequestMapping\(.*?method\s*=\s*RequestMethod\.(GET|POST|PUT|DELETE|PATCH).*?value\s*=\s*"([^"]+)"\)', 'DYNAMIC')
                ]
                
                for pattern, method in method_patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        if isinstance(match, tuple):
                            if len(match) == 2:
                                actual_method, path = match
                                method = actual_method
                            else:
                                path = match[0]
                        else:
                            path = match
                        
                        full_path = f"{base_path}{path}".replace("//", "/")
                        endpoints.append({
                            'file': file_path,
                            'method': method,
                            'path': full_path,
                            'full_endpoint': f"{method} {full_path}"
                        })
        
        except Exception as e:
            print(f"Error extracting endpoints from {file_path}: {e}")
        
        return endpoints
    
    def detect_api_changes(self, commit_range: str = "HEAD~1..HEAD") -> Dict[str, List[Dict[str, str]]]:
        """Detect all API changes in the specified commit range"""
        changed_files = self.get_changed_files(commit_range)
        
        all_endpoints = []
        for file_path in changed_files:
            endpoints = self.extract_api_endpoints(file_path)
            all_endpoints.extend(endpoints)
        
        return {
            'changed_files': changed_files,
            'affected_endpoints': all_endpoints
        }
    
    def get_endpoint_signature(self, endpoint: Dict[str, str]) -> str:
        """Generate a unique signature for an endpoint"""
        return f"{endpoint['method']}:{endpoint['path']}"
    
    def compare_endpoints(self, old_endpoints: List[Dict[str, str]], 
                         new_endpoints: List[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
        """Compare two sets of endpoints to detect changes"""
        old_signatures = {self.get_endpoint_signature(e) for e in old_endpoints}
        new_signatures = {self.get_endpoint_signature(e) for e in new_endpoints}
        
        added = [e for e in new_endpoints if self.get_endpoint_signature(e) not in old_signatures]
        removed = [e for e in old_endpoints if self.get_endpoint_signature(e) not in new_signatures]
        
        # For modified endpoints, we need more sophisticated comparison
        common_signatures = old_signatures.intersection(new_signatures)
        modified = []
        
        for sig in common_signatures:
            old_ep = next(e for e in old_endpoints if self.get_endpoint_signature(e) == sig)
            new_ep = next(e for e in new_endpoints if self.get_endpoint_signature(e) == sig)
            
            # Simple comparison - in real implementation, you'd compare method signatures
            if old_ep != new_ep:
                modified.append({
                    'old': old_ep,
                    'new': new_ep
                })
        
        return {
            'added': added,
            'removed': removed,
            'modified': modified
        }