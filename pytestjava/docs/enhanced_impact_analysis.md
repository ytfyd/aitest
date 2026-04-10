# 代码变更影响分析系统 - 规则与说明文档

## 系统概述

本系统通过分析 Git 分支差异，自动检测 Java 代码变更，构建调用图追踪影响传播，识别受影响的 API 端点，并生成自动化测试用例。

### 执行命令

```bash
python run_tests.py --branch origin/test-feature origin/main --git-repo-path "c:\Users\DELL\Desktop\aitest\campus-master"
```

- `--branch SOURCE TARGET`：对比两个远程分支的差异
- `--git-repo-path`：本地 Git 仓库路径（用于构建调用图和影响分析）

---

## 核心流程

```
┌──────────────────────────────────────────────────────────────────┐
│  python run_tests.py --branch origin/test-feature origin/main   │
│                         --git-repo-path "campus-master"         │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤0: Git 准备                                                 │
│  - git fetch --all                                               │
│  - git checkout origin/test-feature (source分支)                 │
│  - 记录原始分支，流程结束后恢复                                    │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤1: JCCIAnalyzer - AST 解析                                  │
│  - 扫描项目所有 Java 文件                                         │
│  - 使用 javalang 解析 AST 结构                                    │
│  - 提取类、方法、字段、注解信息                                     │
│  - 识别 Controller / Service / Repository                        │
│  - 构建完整调用图 (call_graph + reverse_call_graph)               │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤2: ImpactAnalyzer - 影响分析器初始化                          │
│  - 从 JCCI 获取调用图                                             │
│  - 构建方法依赖关系 (dependency_graph)                             │
│  - 构建反向依赖索引 (reverse_dependency_graph)                    │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤3: APIEndpointAnalyzer - 端点分析器初始化                     │
│  - 从 JCCI 获取 Controller 类                                    │
│  - 提取 API 端点 (路径 + HTTP方法)                                │
│  - 分析 Controller → Service 调用关系                             │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤4: CodeChangeDetector - 分支差异检测                         │
│  - git diff origin/main origin/test-feature -- "*.java"          │
│  - 获取变更的 Java 文件列表                                        │
│  - 逐文件获取 old/new 内容                                        │
│  - 解析 Java 签名，识别变更的方法/字段/类                          │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤5: 影响传播分析                                              │
│  - 查找变更方法的调用者 (find_callers)                             │
│  - 查找变更方法的被调用者 (find_callees)                           │
│  - 查找相关 Controller 文件                                       │
│  - 计算影响置信度                                                  │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤6: 生成受影响端点列表                                        │
│  - 变更 Controller 文件中的所有接口                                │
│  - 调用链上的所有接口                                              │
│  - 调用变更方法的所有接口                                          │
│  - 合并去重，按置信度排序                                          │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤7: 合并失败测试用例                                          │
│  - 加载上次失败的测试用例 (failed_tests.json)                     │
│  - 与当前受影响端点合并去重                                        │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤8: 生成测试用例                                              │
│  - 正向测试 (positive)                                            │
│  - 负向测试 (negative)                                            │
│  - 性能测试 (performance)                                         │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤9: 执行测试                                                  │
│  - 运行 pytest                                                    │
│  - 解析测试结果                                                   │
│  - 保存失败测试用例                                                │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤10: 报告与通知                                               │
│  - 生成 HTML 测试报告                                             │
│  - 发送企业微信通知                                                │
│  - 保存影响分析报告 (impact_analysis.json)                        │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│  步骤11: Git 恢复                                                 │
│  - git checkout 回原始分支                                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 核心组件

| 组件 | 文件路径 | 职责 |
|------|----------|------|
| TestRunner | `run_tests.py` | 主入口，协调全流程 |
| EnhancedImpactAnalyzer | `utils/enhanced_impact_analyzer.py` | 整合四大分析组件 |
| JCCIAnalyzer | `utils/jcci_analyzer.py` | AST 解析，构建调用图 |
| ImpactAnalyzer | `utils/impact_analyzer.py` | 影响传播分析 |
| APIEndpointAnalyzer | `utils/api_endpoint_analyzer.py` | API 端点提取与关联 |
| CodeChangeDetector | `utils/code_change_detector.py` | Git 差异检测与变更解析 |
| TestCaseGenerator | `utils/test_generator.py` | 生成 pytest 测试用例 |
| HTMLReportGenerator | `utils/html_report_generator.py` | 生成 HTML 测试报告 |
| WeChatWorkNotifier | `utils/wechat_notifier.py` | 企业微信通知 |

---

## 规则详解

### 规则1：Git 准备规则

**位置**：`run_tests.py::prepare_git_repo()`

**规则**：
- 执行分析前必须先 `git fetch --all` 更新远程引用
- 然后 `git checkout` 到 source 分支（如 origin/test-feature），确保本地代码与源分支一致
- 记录原始分支名，流程结束后必须恢复

**实现**：
```python
def prepare_git_repo(repo_path, source_branch, target_branch):
    # 1. 记录当前分支
    original_branch = git rev-parse --abbrev-ref HEAD
    
    # 2. 更新远程引用
    git fetch --all --prune
    
    # 3. 切换到源分支
    git checkout source_branch
    
    return original_branch
```

**为什么 checkout 到 source 分支**：构建调用图需要基于最新的源分支代码进行 AST 解析。

---

### 规则2：分支差异检测规则

**位置**：`utils/code_change_detector.py::CodeChangeDetector.get_changed_files()`

**规则**：
- `--branch SOURCE TARGET` 参数转换为 commit_range 格式：`TARGET..SOURCE`
- 例如 `--branch origin/test-feature origin/main` → `origin/main..origin/test-feature`
- 使用 `git diff TARGET SOURCE -- "*.java" --name-only` 获取差异文件列表

**方向说明**：
- `origin/main..origin/test-feature` 表示"从 main 到 test-feature 的变化"
- 即 test-feature 分支相对于 main 分支新增/修改/删除的内容

**实现**：
```python
def _get_changed_files_from_branch_diff(self, branch_range):
    target_branch, source_branch = branch_range.split('..')
    
    # 主方案：git diff
    diff_output = self.repo.git.diff(target_branch, source_branch, '--', '*.java', name_only=True)
    
    # 备选方案：commit.diff()
    if not diff_output:
        diff = target_commit.diff(source_commit)
        java_diffs = [item.a_path for item in diff if item.a_path.endswith('.java')]
```

---

### 规则3：JCCI AST 解析规则

**位置**：`utils/jcci_analyzer.py::JCCIAnalyzer.initialize()`

**规则**：
- 初始化时扫描项目所有 Java 文件（排除 target/build 目录）
- 使用 javalang 库解析 AST 结构
- 提取每个类的：包名、导入、父类、接口、字段、方法、注解
- 识别 Spring 注解标记的 Controller / Service / Repository
- 构建两个调用图：
  - `call_graph`：方法 → 它调用的方法列表
  - `reverse_call_graph`：方法 → 调用它的方法列表

**性能优化**：
- 支持缓存（`.jcci_cache` 目录），缓存命中率可达 78%+
- 支持并行扫描，加速比可达 10x+

**日志输出**：
```
[JCCIAnalyzer] AST解析完成: 143 个类 (Controllers: 16, Services: 12, Repositories: 0)
[JCCIAnalyzer] 调用图构建完成: 566 个方法, 1234 个调用关系
```

---

### 规则4：影响传播分析规则

**位置**：`utils/impact_analyzer.py::ImpactAnalyzer`

**规则**：
- 从 JCCI 获取调用图，构建方法依赖关系和反向依赖索引
- `find_callers(method_key, depth=5)`：查找谁调用了该方法（向上传播）
- `find_callees(method_key, depth=5)`：查找该方法调用了谁（向下传播）
- 最大传播深度默认 5 层

**实现**：
```python
def _build_from_jcci(self):
    for class_name, class_info in self.jcci.java_classes.items():
        for method_name, method_info in class_info.methods.items():
            node_key = f"{class_name}.{method_name}"
            self.call_graph[node_key] = CallNode(
                called_methods=method_info.called_methods
            )
            for called_method in method_info.called_methods:
                self.dependency_graph[node_key].add(called_method)
```

---

### 规则5：API 端点提取规则

**位置**：`utils/api_endpoint_analyzer.py::APIEndpointAnalyzer`

**规则**：
- 从 JCCI 获取 Controller 类，提取 API 端点
- 路径拼接：`base_path + method_path`
  - 类上 `@RequestMapping("/system/menu")` → base_path
  - 方法上 `@GetMapping("/{menuId}")` → method_path
  - 最终路径：`/system/menu/{menuId}`
- HTTP 方法从注解提取：`@GetMapping` → GET, `@PostMapping` → POST

---

### 规则6：受影响接口识别规则

**位置**：`utils/enhanced_impact_analyzer.py::EnhancedImpactAnalyzer.get_affected_endpoints_for_testing()`

**规则**：受影响接口 = 以下三类之和（去重）

**第一类：变更 Controller 文件中的所有接口**
```
如果变更文件是 Controller → 该 Controller 的所有 API 端点都受影响
```

**第二类：影响传播链上的接口**
```
变更方法 → find_callers(向上) → 找到调用它的 Controller 方法 → 该端点受影响
变更方法 → find_callees(向下) → 找到它调用的 Service → 该 Service 关联的端点受影响
```

**第三类：相关 Controller 接口**
```
通过 JCCI._find_related_controllers() 找到与变更文件有依赖关系的 Controller
→ 这些 Controller 的所有端点受影响
```

---

### 规则7：置信度计算规则

**位置**：`utils/enhanced_impact_analyzer.py::get_affected_endpoints_for_testing()`

| 影响类型 | 置信度 | 说明 |
|---------|--------|------|
| direct_impact | 1.0 | 直接修改的 Controller 方法 |
| service_dependency | 0.9 | Controller 调用的 Service 被修改 |
| method_dependency | 0.85 | 方法直接调用依赖 |
| indirect_impact | 0.5-0.7 | 间接影响（置信度 = max(0.5, 0.8 - depth × 0.1)） |

---

### 规则8：失败测试用例重试规则

**位置**：`run_tests.py::TestRunner`

**规则**：
- 每次测试执行后，失败的测试用例保存到 `test-reports/failed_tests.json`
- 下次运行时自动加载并合并到当前测试列表中
- 合并时按 `method + path` 去重

---

### 规则9：测试用例生成规则

**位置**：`utils/test_generator.py::TestCaseGenerator`

**规则**：每个受影响接口生成三类测试用例

| 类型 | pytest marker | 说明 |
|------|---------------|------|
| 正向测试 | `@pytest.mark.positive` `@pytest.mark.smoke` | 验证正常请求返回 200 |
| 负向测试 | `@pytest.mark.negative` `@pytest.mark.regression` | 验证异常参数返回错误码 |
| 性能测试 | `@pytest.mark.performance` `@pytest.mark.slow` | 验证响应时间在阈值内 |

**命名规范**：`test_{endpoint_path}_{test_type}`

---

### 规则10：缓存与性能规则

**位置**：`utils/jcci_analyzer.py`, `utils/cache_manager.py`, `utils/performance_optimizer.py`

**规则**：
- 缓存目录：`{project_path}/.jcci_cache`
- 缓存 TTL：24 小时
- 缓存最大容量：500 MB
- 并行扫描：自动根据 CPU 核心数设置 worker 数量
- 增量模式：当变更文件数 < 50 时启用增量分析

---

## 数据流向

```
Git 仓库 (campus-master)
    │
    ├── git diff ──→ CodeChangeDetector ──→ 变更文件列表 + 变更详情
    │
    ├── Java 文件 ──→ JCCIAnalyzer ──→ 调用图 (call_graph + reverse_call_graph)
    │                                    ├── 类信息 (java_classes)
    │                                    └── API 端点 (controllers)
    │
    ├── 调用图 ──→ ImpactAnalyzer ──→ 影响路径 (impact_paths)
    │                                  └── 依赖关系 (dependency_graph)
    │
    ├── 变更详情 + 影响路径 ──→ APIEndpointAnalyzer ──→ 受影响端点列表
    │
    └── 受影响端点 ──→ TestCaseGenerator ──→ pytest 测试文件
                                            ──→ pytest 执行 ──→ 测试结果
                                                                ├── HTML 报告
                                                                ├── 企业微信通知
                                                                └── failed_tests.json
```

---

## 配置说明

### 敏感配置（.env 文件）

```env
# Git 认证
GIT_USERNAME=your_username
GIT_PASSWORD=your_password
GIT_TOKEN=your_token

# 远程仓库地址
GIT_REMOTE_URL=https://github.com/ytfyd/aitest.git

# 企业微信通知
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx

# API 测试目标
API_BASE_URL=http://localhost:8160
```

### 非敏感配置（config/settings.py）

```python
environment = "test"           # 默认环境
git_repo_path = "."            # Git 仓库本地路径（可通过 --git-repo-path 覆盖）
jcci_cache_enabled = True      # 启用缓存
jcci_cache_ttl_hours = 24      # 缓存有效期
jcci_max_workers = "auto"      # 并行 worker 数量
```

### 命令行参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `--branch SOURCE TARGET` | 对比两个远程分支 | `--branch origin/test-feature origin/main` |
| `--git-repo-path PATH` | 本地 Git 仓库路径 | `--git-repo-path "c:\path\to\repo"` |
| `--commit-range RANGE` | 提交范围（默认 HEAD~1..HEAD） | `--commit-range abc123..def456` |

---

## 关键注意事项

1. **Git 准备顺序**：必须先 fetch 再 checkout，确保远程分支引用是最新的
2. **分支方向**：`--branch SOURCE TARGET` 转换为 `TARGET..SOURCE`，检测的是 SOURCE 相对于 TARGET 的变化
3. **调用图构建**：基于 checkout 后的源分支代码构建，确保调用图反映最新代码
4. **缓存一致性**：切换分支后缓存可能失效，系统会自动检测并重新解析
5. **分支恢复**：无论流程成功或失败，都会在 finally 块中恢复原始分支
6. **字典转换**：缓存反序列化时，methods 和 fields 字典中的值需要转换为 JavaMethodInfo / JavaFieldInfo 对象
