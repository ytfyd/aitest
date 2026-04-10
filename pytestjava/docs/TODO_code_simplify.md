# 待办事项 - 代码精简与核心流程保障

## 需要关注的事项

### 1. 当前两个分支无 Java 文件差异
- **现象**：`origin/main` 和 `origin/test-feature` 之间没有 Java 文件差异
- **原因**：main 分支只比 test-feature 多了一个 merge commit 和一个删除 .env 的 commit
- **操作指引**：如果需要测试差异检测功能，需要在 test-feature 分支上提交 Java 代码变更

### 2. JCCI 解析错误（39 个文件）
- **现象**：并行解析时 39 个文件报错 `cannot unpack non-iterable NoneType object`
- **原因**：javalang 解析某些复杂 Java 语法时返回 None
- **影响**：不影响核心流程，这些文件会被跳过
- **操作指引**：如需修复，可在 `_parse_with_javalang()` 中增加 None 值检查

### 3. 缓存目录位置
- **位置**：`c:\Users\DELL\Desktop\aitest\campus-master\.jcci_cache`
- **说明**：缓存建在目标项目目录下，切换分支后缓存可能失效
- **操作指引**：如需清理缓存，删除该目录即可

### 4. API 服务器需要启动
- **说明**：测试执行需要 API 服务器（默认 http://localhost:8160）处于运行状态
- **操作指引**：执行测试前确保目标 API 服务已启动

### 5. 企业微信通知配置
- **位置**：`.env` 文件中的 `WECHAT_WEBHOOK_URL`
- **操作指引**：如需启用通知，配置有效的 Webhook URL
