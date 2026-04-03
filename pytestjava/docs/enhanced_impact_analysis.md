# 增强版代码变更影响分析系统 - 完整规则文档

## ⚠️ 核心流程（重要：每次修改前必读）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          完整分析流程                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   本地Git仓库 (已clone)                                                      │
│          ↓                                                                  │
│   分析 HEAD~1..HEAD 提交范围                                                 │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤1: JCCIAnalyzer (AST解析器)    │                                   │
│   │  - 扫描所有Java文件                  │                                   │
│   │  - 使用javalang解析AST结构           │                                   │
│   │  - 提取类、方法、字段、注解信息       │                                   │
│   │  - 识别Controller/Service/Repository │                                   │
│   │  - 构建完整调用图                    │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤2: ImpactAnalyzer (影响分析器)  │                                   │
│   │  - 从JCCI获取调用图                  │                                   │
│   │  - 构建方法依赖关系                  │                                   │
│   │  - 构建反向依赖索引                  │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤3: APIEndpointAnalyzer (端点)   │                                   │
│   │  - 从JCCI获取Controller类           │                                   │
│   │  - 提取API端点信息                   │                                   │
│   │  - 分析Controller-Service依赖        │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤4: CodeChangeDetector (变更)    │                                   │
│   │  - 检测Git提交变更文件               │                                   │
│   │  - 解析Java签名                     │                                   │
│   │  - 识别变更的方法/字段/类            │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤5: 影响传播分析                 │                                   │
│   │  - 查找变更方法的调用者              │                                   │
│   │  - 查找变更方法的被调用者            │                                   │
│   │  - 查找相关Controller文件            │                                   │
│   │  - 计算影响置信度                    │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤6: 生成受影响端点列表           │                                   │
│   │  - 变更Controller中的所有接口        │                                   │
│   │  - 调用链上的所有接口                │                                   │
│   │  - 调用变更方法的所有接口            │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤7: 合并失败测试用例             │                                   │
│   │  - 加载上次失败的测试用例            │                                   │
│   │  - 与当前受影响端点合并              │                                   │
│   │  - 去重处理                         │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤8: 生成测试用例                 │                                   │
│   │  - 正向测试用例 (positive)           │                                   │
│   │  - 负向测试用例 (negative)           │                                   │
│   │  - 性能测试用例 (performance)        │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤9: 执行测试                     │                                   │
│   │  - 运行pytest                        │                                   │
│   │  - 解析测试结果                      │                                   │
│   │  - 保存失败测试用例                  │                                   │
│   └─────────────────────────────────────┘                                   │
│          ↓                                                                  │
│   ┌─────────────────────────────────────┐                                   │
│   │  步骤10: 生成报告和通知              │                                   │
│   │  - 生成HTML测试报告                  │                                   │
│   │  - 发送企业微信通知                  │                                   │
│   │  - 保存分析报告                      │                                   │
│   └─────────────────────────────────────┘                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 核心组件对应文件

| 组件 | 文件路径 | 功能 |
|------|----------|------|
| JCCIAnalyzer | `utils/jcci_analyzer.py` | 基于javalang的AST解析Java代码结构 |
| ImpactAnalyzer | `utils/impact_analyzer.py` | 构建调用图，分析影响传播 |
| APIEndpointAnalyzer | `utils/api_endpoint_analyzer.py` | 关联API端点与变更 |
| CodeChangeDetector | `utils/code_change_detector.py` | 检测Git提交变更，解析Java签名 |
| EnhancedImpactAnalyzer | `utils/enhanced_impact_analyzer.py` | 整合所有分析组件（主入口） |
| TestCaseGenerator | `utils/test_generator.py` | 生成pytest测试用例 |
| TestRunner | `run_tests.py` | 测试执行主入口 |

---

## 规则详解

### 规则1：初始化扫描规则

**位置**：`utils/jcci_analyzer.py::JCCIAnalyzer.initialize()`

**规则内容**：
```
初始化时必须扫描所有Java文件，构建完整的调用图
```

**实现细节**：
```python
def initialize(self, incremental: bool = False, changed_files: List[str] = None):
    # 始终扫描所有文件，不使用增量模式
    logger.info(f"[JCCIAnalyzer] 开始扫描 {len(java_files)} 个Java文件")
    self._scan_java_files()
    self._build_call_graph()
```

**日志输出**：
```
[JCCIAnalyzer] 开始扫描 183 个Java文件
[JCCIAnalyzer] AST解析完成: 144 个类 (Controllers: 12, Services: 35, Repositories: 8)
[JCCIAnalyzer] 调用图构建完成: 566 个方法, 1234 个调用关系
```

---

### 规则2：调用图构建规则

**位置**：`utils/jcci_analyzer.py::JCCIAnalyzer._build_call_graph()`

**规则内容**：
```
调用图必须包含所有方法及其调用关系
```

**实现细节**：
```python
def _build_call_graph(self):
    for class_name, class_info in self.java_classes.items():
        for method_name, method_info in class_info.methods.items():
            method_key = f"{class_name}.{method_name}"
            for called in method_info.called_methods:
                self.call_graph[method_key].add(called)
                self.reverse_call_graph[called].add(method_key)
```

---

### 规则3：影响分析器初始化规则

**位置**：`utils/impact_analyzer.py::ImpactAnalyzer.initialize()`

**规则内容**：
```
从JCCI获取调用图，构建方法依赖关系和反向依赖索引
```

**实现细节**：
```python
def initialize(self):
    self._build_from_jcci()
    self._build_reverse_dependencies()
```

**日志输出**：
```
[ImpactAnalyzer] 从JCCI构建调用图...
[ImpactAnalyzer] 调用图构建完成: 566 个方法, 1234 个依赖关系
[ImpactAnalyzer] 初始化完成: 566 个方法节点, 144 个类, 1234 个依赖关系
```

---

### 规则4：端点分析器初始化规则

**位置**：`utils/api_endpoint_analyzer.py::APIEndpointAnalyzer.initialize()`

**规则内容**：
```
从JCCI获取Controller类，提取API端点信息
```

**实现细节**：
```python
def initialize(self):
    self._build_from_jcci()
```

**日志输出**：
```
[APIEndpointAnalyzer] 从JCCI构建端点分析...
[APIEndpointAnalyzer] 端点分析完成: 12 个Controller类, 56 个API端点, 89 个Service调用
[APIEndpointAnalyzer] 初始化完成: 56 个Controller方法, 12 个Controller类, 89 个Service调用关系
```

---

### 规则5：扫描范围规则

**位置**：`utils/enhanced_impact_analyzer.py::get_affected_endpoints_for_testing()`

**规则内容**：
```
扫描文件 = 变更文件 + 所有和变更文件有依赖关系的Controller文件
```

**实现细节**：
```python
# 1. 获取变更文件中的Controller文件
for file_path in analysis_result.changed_files:
    if 'Controller' in file_path:
        changed_controller_files.add(normalized_path)

# 2. 获取相关Controller文件
related_controllers = self.jcci_analyzer._find_related_controllers(analysis_result.changed_files)
for controller_file in related_controllers:
    changed_controller_files.add(normalized_path)
```

---

### 规则6：受影响接口识别规则

**位置**：`utils/enhanced_impact_analyzer.py::get_affected_endpoints_for_testing()`

**规则内容**：
```
受影响接口 = 
    1. 变更相互依赖的Controller文件中的所有接口
    2. 变更方法调用链上的所有接口
    3. 调用变更方法的所有接口
```

**实现细节**：

**第一层：变更Controller文件中的所有接口**
```python
for controller_file in changed_controller_files:
    controller_methods = self.api_endpoint_analyzer.get_controller_methods_in_file(controller_file)
    for controller_method in controller_methods:
        # 添加所有Controller方法
```

**第二层：变更方法调用链上的所有接口**
```python
for modified_method in directly_modified_methods:
    callees = self._find_all_callees(modified_method, max_depth=5)
    affected_methods.update(callees)
```

**第三层：调用变更方法的所有接口**
```python
for modified_method in directly_modified_methods:
    callers = self._find_all_callers(modified_method, max_depth=5)
    affected_methods.update(callers)
```

---

### 规则7：置信度计算规则

**位置**：`utils/enhanced_impact_analyzer.py::get_affected_endpoints_for_testing()`

**规则内容**：
```
置信度基于影响类型和调用链深度计算
```

**置信度对照表**：

| 影响类型 | 置信度 | 说明 |
|---------|--------|------|
| direct_impact | 1.0 | 直接修改的Controller方法 |
| service_dependency | 0.9 | Controller调用的Service被修改 |
| method_dependency | 0.85 | 方法直接调用依赖 |
| indirect_impact | 0.5-0.7 | 间接影响（基于深度） |

**实现细节**：
```python
if controller_key in directly_modified_methods:
    impact_type = 'direct_impact'
    confidence = 1.0
elif impact_type == 'service_dependency':
    confidence = 0.9
elif impact_type == 'indirect_impact':
    confidence = max(0.5, 0.8 - depth * 0.1)
```

---

### 规则8：失败测试用例重试规则

**位置**：`run_tests.py::TestRunner`

**规则内容**：
```
失败测试用例会在下次运行时自动重试
```

**实现细节**：

**加载失败测试用例**：
```python
def _load_failed_tests(self) -> list:
    if not self.failed_tests_file.exists():
        return []
    
    with open(self.failed_tests_file, 'r', encoding='utf-8') as f:
        failed_tests = json.load(f)
    logger.info(f"Loaded {len(failed_tests)} failed test cases from last run")
    return failed_tests
```

**合并测试用例**：
```python
def generate_tests(self, endpoints: list) -> str:
    # 加载上次失败的测试用例
    failed_endpoints = self._load_failed_tests()
    
    # 合并当前端点和失败端点（去重）
    all_endpoints = []
    endpoint_set = set()
    
    for endpoint in endpoints:
        endpoint_key = f"{endpoint['method']}_{endpoint['path']}"
        if endpoint_key not in endpoint_set:
            endpoint_set.add(endpoint_key)
            all_endpoints.append(endpoint)
    
    for endpoint in failed_endpoints:
        endpoint_key = f"{endpoint['method']}_{endpoint['path']}"
        if endpoint_key not in endpoint_set:
            endpoint_set.add(endpoint_key)
            all_endpoints.append(endpoint)
```

**保存失败测试用例**：
```python
def _save_failed_tests(self, test_results: dict):
    failed_endpoints = []
    for fail in test_results.get('failed_details', []):
        method = fail.get('method', 'GET')
        path = fail.get('path', '/')
        failed_endpoints.append({
            'method': method,
            'path': path,
            'full_endpoint': f"{method} {path}",
            'test_name': test_name
        })
    
    with open(self.failed_tests_file, 'w', encoding='utf-8') as f:
        json.dump(failed_endpoints, f, ensure_ascii=False, indent=2)
```

---

### 规则9：测试用例生成规则

**位置**：`utils/test_generator.py::TestCaseGenerator`

**规则内容**：
```
每个受影响接口生成三类测试用例：
1. 正向测试用例（positive）
2. 负向测试用例（negative）
3. 性能测试用例（performance）
```

**测试用例命名规范**：
```
test_{endpoint_path}_{test_type}

示例：
- test_system_menu_treeselect_positive
- test_system_menu_treeselect_negative_invalid_params
- test_system_menu_treeselect_performance
```

**正向测试用例**：
```python
@pytest.mark.positive
@pytest.mark.smoke
def test_{endpoint_name}_positive():
    """测试 {method} {path} - 正向测试用例"""
    
    # 准备测试数据
    test_data = {test_data}
    
    # 发起API请求
    response = api_client.{method}('{path}', params={params})
    
    # 存储响应结果
    save_response('test_{endpoint_name}_positive', {
        'status_code': response.status_code,
        'response': response.json()
    })
    
    # 验证响应
    assert response.status_code == 200
    data = response.json()
    assert data.get('code') == 200
```

**负向测试用例**：
```python
@pytest.mark.negative
@pytest.mark.regression
def test_{endpoint_name}_negative_{scenario}():
    """测试 {method} {path} - 负向测试用例: {scenario}"""
    
    # 准备无效测试数据
    test_data = {invalid_data}
    
    # 发起API请求
    response = api_client.{method}('{path}', data=test_data)
    
    # 验证错误响应
    assert response.status_code == {expected_status}
    error_data = response.json()
    assert 'errorCode' in error_data
```

**性能测试用例**：
```python
@pytest.mark.performance
@pytest.mark.slow
def test_{endpoint_name}_performance():
    """测试 {method} {path} - 性能测试用例"""
    import time
    import statistics
    
    # 性能测试配置
    num_requests = 10
    max_response_time = 2.0
    avg_response_time = 1.0
    
    # 记录响应时间
    response_times = []
    
    for i in range(num_requests):
        start_time = time.time()
        response = api_client.{method}('{path}', params={params})
        end_time = time.time()
        response_times.append(end_time - start_time)
        
        assert response.status_code == 200
    
    # 计算性能指标
    avg_time = statistics.mean(response_times)
    max_time = max(response_times)
    p95_time = statistics.quantiles(response_times, n=20)[18]
    
    # 验证性能指标
    assert avg_time <= avg_response_time
    assert max_time <= max_response_time
```

---

### 规则10：API端点路径提取规则

**位置**：`utils/jcci_analyzer.py`

**规则内容**：
```
路径拼接规则：
- Controller类上的 @RequestMapping 提供基础路径
- 方法上的 @GetMapping/@PostMapping 等提供方法路径
- 最终路径 = 基础路径 + 方法路径
```

**示例**：
```java
@RestController
@RequestMapping("/system/menu")  // base_path
public class SysMenuController {
    
    @DeleteMapping("/{menuId}")  // method_path
    public R remove(@PathVariable Long menuId) {
        // 最终路径: DELETE /system/menu/{menuId}
    }
}
```

---

### 规则11：身份认证规则

**位置**：`utils/api_client.py`

**规则内容**：
```
所有API请求必须携带有效的认证Token
```

**认证流程**：
```
1. 调用登录接口获取Token
2. 将Token存储到session
3. 后续请求自动携带Token
```

**实现细节**：
```python
def authenticate(self):
    # 调用登录接口
    login_data = {
        "username": settings.username,
        "password": settings.password
    }
    response = self.session.post(f"{self.base_url}/login", json=login_data)
    
    # 提取Token
    token = response.json().get('token')
    
    # 设置Authorization header
    self.session.headers.update({
        'Authorization': f'Bearer {token}'
    })
```

---

### 规则12：测试报告生成规则

**位置**：`run_tests.py::TestRunner.generate_html_report()`

**规则内容**：
```
测试报告必须包含以下内容：
1. 测试概览（总数、通过、失败、跳过）
2. 影响分析详情
3. 文件变更详情
4. 测试用例详情
5. 失败用例详情
```

---

### 规则13：企业微信通知规则

**位置**：`utils/wechat_notifier.py`

**规则内容**：
```
测试完成后发送企业微信通知，包含：
1. 测试概览
2. 失败用例列表
3. 测试报告链接
```

---

## 日志输出规范

### 初始化阶段日志

```
[EnhancedImpactAnalyzer] ========== 开始初始化分析器 ==========
[EnhancedImpactAnalyzer] 步骤1: 初始化 JCCIAnalyzer (AST解析器)
[JCCIAnalyzer] 开始扫描 183 个Java文件
[JCCIAnalyzer] AST解析完成: 144 个类 (Controllers: 12, Services: 35, Repositories: 8)
[JCCIAnalyzer] 调用图构建完成: 566 个方法, 1234 个调用关系
[EnhancedImpactAnalyzer] 步骤2: 初始化 ImpactAnalyzer (影响分析器)
[ImpactAnalyzer] 从JCCI构建调用图...
[ImpactAnalyzer] 调用图构建完成: 566 个方法, 1234 个依赖关系
[EnhancedImpactAnalyzer] 步骤3: 初始化 APIEndpointAnalyzer (端点分析器)
[APIEndpointAnalyzer] 从JCCI构建端点分析...
[APIEndpointAnalyzer] 端点分析完成: 12 个Controller类, 56 个API端点, 89 个Service调用
[EnhancedImpactAnalyzer] ========== 初始化完成 ==========
[EnhancedImpactAnalyzer] 汇总: 144 个类, 566 个方法节点, 56 个Controller方法
```

### 影响分析阶段日志

```
[EnhancedImpactAnalyzer] ========== 开始影响分析 ==========
[EnhancedImpactAnalyzer] 提交范围: HEAD~1..HEAD, 最大影响深度: 5
[EnhancedImpactAnalyzer] 步骤4: 检测变更文件
[EnhancedImpactAnalyzer] 发现 2 个变更的Java文件
[EnhancedImpactAnalyzer] 步骤5: 分析代码变更详情
[EnhancedImpactAnalyzer] 检测到 3 个代码变更
[EnhancedImpactAnalyzer] 步骤6: 分析影响传播路径
[EnhancedImpactAnalyzer] 发现 5 条影响路径
[EnhancedImpactAnalyzer] 步骤7: 识别受影响的API端点
[EnhancedImpactAnalyzer] 发现 8 个受影响的API端点
[EnhancedImpactAnalyzer] ========== 影响分析完成 ==========
[EnhancedImpactAnalyzer] 变更的Controller文件: 1 个
[EnhancedImpactAnalyzer] 直接修改的方法: 2 个
[EnhancedImpactAnalyzer] 受影响的方法总数: 15 个
[EnhancedImpactAnalyzer] 相关Controller文件总数: 3 个
Total endpoints for testing: 8 (from 3 changed controller files, 15 affected methods)
```

---

## 使用方法

### 基本使用

```python
from utils.enhanced_impact_analyzer import EnhancedImpactAnalyzer

# 初始化分析器
analyzer = EnhancedImpactAnalyzer(
    repo_path="/path/to/java/project",
    project_path="/path/to/java/project"
)

# 获取受影响的API端点
endpoints = analyzer.get_affected_endpoints_for_testing("HEAD~1..HEAD")

# 执行完整分析
result = analyzer.analyze("HEAD~1..HEAD")

# 保存分析报告
analyzer.save_analysis_report("impact_analysis.json", "HEAD~1..HEAD")
```

### 命令行执行

```bash
# 执行测试
python run_tests.py --commit-range HEAD~1..HEAD

# 指定Git仓库路径
python run_tests.py --git-repo-path /path/to/repo

# 指定配置文件
python run_tests.py --config .env
```

---

## 故障排查

---

## 性能指标

- **项目规模**：183个Java文件
- **初始化时间**：~2秒（构建调用图）
- **单次分析时间**：<1秒
- **内存占用**：适中（调用图缓存）

---

## 依赖安装

```bash
pip install javalang==0.13.0
pip install unidiff==0.7.5
pip install pytest
pip install requests
pip install python-dotenv
```
