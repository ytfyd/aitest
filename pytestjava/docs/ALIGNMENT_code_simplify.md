# 对齐文档 - 代码精简与核心流程保障

## 原始需求
1. 保证 `enhanced_impact_analysis.md` 核心流程正常
2. 保证较好性能的情况下，精简代码（目前太过复杂，不容易维护）
3. 执行 `python run_tests.py --branch origin/test-feature origin/main --git-repo-path "c:\Users\DELL\Desktop\aitest\campus-master"` 时：
   - 对比 origin/test-feature 和 origin/main 两个分支代码差异
   - 构建调用地图和分析时使用 campus-master 目录
   - 构建调用地图和分析前要先更新本地目录代码（git fetch + git checkout）
4. 其它命令和参数暂时不需要支持，核心流程不变
5. 验证成功后重写 `enhanced_impact_analysis.md` 文档

## 边界确认
- **保留**: 核心分析流程（JCCI→Impact→APIEndpoint→CodeChange→影响传播→测试生成→执行→报告）
- **保留**: 性能优化（缓存、并行扫描）
- **保留**: `--branch` 和 `--git-repo-path` 参数
- **移除**: `--auto-pull`, `--no-auto-pull`, `--force-sync`, `--git-status` 等非核心参数
- **移除**: GitManager（git_manager.py）- 功能合并到 run_tests.py
- **精简**: run_tests.py 中大量冗余的测试结果解析代码
- **精简**: code_change_detector.py 中重复的诊断/建议逻辑
- **精简**: enhanced_impact_analyzer.py 中重复的影响分析方法
- **保留**: settings.py、.env 配置体系

## 现有项目问题分析

### 问题1: run_tests.py 过于臃肿（814行）
- `_parse_test_results` 方法约200行，逻辑极其复杂
- `_extract_test_data_from_file` 等辅助方法冗余
- GitManager 集成代码占大量空间但非核心

### 问题2: git_manager.py 独立模块但功能简单
- 核心功能就是 fetch + checkout，不需要独立模块
- 与 run_tests.py 中的 fetch 逻辑重复

### 问题3: code_change_detector.py 冗余诊断逻辑
- `_diagnose_branch_issue` 约50行诊断代码
- `_suggest_local_alternatives` 约30行建议代码
- 这些在正常流程中不应出现，过度防御性编程

### 问题4: enhanced_impact_analyzer.py 重复方法
- `_find_all_callers` / `_find_all_callees` 与 ImpactAnalyzer 中的方法重复
- `_find_controller_endpoints_for_method` 逻辑冗余
- `_calculate_method_dependency_impact` / `_find_reverse_call_depth` 很少被使用

### 问题5: 分支对比时未先更新本地代码
- 当前只执行 git fetch，但未 checkout 到目标分支
- 构建调用地图时使用的是本地工作目录代码，可能不是目标分支代码

### 问题6: CodeChangeDetector 和 EnhancedImpactAnalyzer 各自创建 JCCIAnalyzer 实例
- TestRunner 中: `self.enhanced_analyzer = EnhancedImpactAnalyzer(repo_path, repo_path)` 
- 同时: `self.code_change_detector = CodeChangeDetector(repo_path, repo_path)` (内部又创建 JCCIAnalyzer)
- EnhancedImpactAnalyzer 内部也创建 CodeChangeDetector
- 导致 JCCIAnalyzer 被创建3次，重复解析

## 需求理解
核心流程:
```
git fetch + checkout → git diff(分支差异) → JCCI扫描(构建调用图) → 影响分析 → 端点分析 → 生成受影响接口列表 → 生成测试 → 执行测试 → 报告
```

关键修改:
1. 分支对比前先更新本地代码到目标分支
2. 合并重复的 JCCIAnalyzer 实例
3. 精简 run_tests.py
4. 移除 GitManager 独立模块
5. 精简诊断和冗余代码

## 疑问澄清
1. ✅ 分支对比时，本地代码应该 checkout 到哪个分支？→ 应该 checkout 到 source 分支（test-feature），因为要基于最新代码构建调用图
2. ✅ 是否保留企业微信通知？→ 保留，属于核心流程步骤10
3. ✅ 是否保留 HTML 报告？→ 保留，属于核心流程步骤10
4. ✅ 是否保留失败测试用例重试？→ 保留，属于核心流程步骤7
