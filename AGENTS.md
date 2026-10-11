# Web AI 协作入口

开始分析、修改、测试或发布前，阅读 [两项目共同流程](../PROJECT_WORKFLOW.md)。它仅适用于 Web 与 Phone Cloud，包含风险分级、任务/验收/发布/交接模板与项目附录，是共同开发流程的权威来源。

在外部 worktree/克隆中，若相对路径不可达，读取 `/Users/yyx/ztqc/PROJECT_WORKFLOW.md`，或通过项目负责人取得同版本权威文件；先继续只读调查，不凭记忆开始业务修改。记录修订日期/哈希。已有运行会话必须主动重读，不假设新增 AGENTS 会自动刷新；新会话先确认当前仓根与适用规则。

按任务范围继续阅读：

- [README](README.md)、[当前架构](docs/ARCHITECTURE.md)。前端改动读 [前端约定](frontend/CLAUDE.md) 和 [界面规范](docs/DESIGN_SYSTEM.md)；后端改动读 [后端约定](backend/CLAUDE.md)，接口/注册路径必须与当前源码核对。
- 权限/共享/数据改动读 [数据隔离](docs/DATA_ISOLATION.md)；旧模板/编辑器范围读 [下线说明](docs/EDITOR_TEMPLATE_RETIREMENT.md)，不恢复旧架构、不删除历史业务数据。
- 发布准备读 [版本与发布规范](docs/RELEASE_VERSION_STANDARD.md)、[审计门禁](docs/PRODUCTION_AUDIT_2026-08-17.md)、[发布手册](docs/V0.3_RELEASE_RUNBOOK.md)。保留既有门槛；历史测试数、revision、生产状态需按当前证据核实。
- 涉及 Phone Cloud 时还读其 `AGENTS.md` 和 `docs/PROJECT_DEVELOPMENT.md`，遵守投屏冻结与 D-075，不把 Web 开发授权扩大为设备/媒体操作授权。

默认先只读理解并报告目标、基线/拟动文件、风险/授权、验证计划。只做明确任务中的最小变更；禁止顺带重构、删除、升级依赖、改权限、清理未提交内容。写前重新读取/核对拟动文件；并行修改冲突就暂停该文件写入并报告，不覆盖他人改动。

日常版本管理也必须读 [版本规范](docs/RELEASE_VERSION_STANDARD.md)：一项功能/修复配独立测试与可审阅提交，新增代码不能长期仅留未跟踪状态；提交/推送仍按用户授权。候选冻结时同步版本元信息与CHANGELOG，不修改历史标签，不把临时资料或运行数据加入Git。开发完成执行 `python3 scripts/check_version_control.py`（Python 3.11+）；发布额外执行 `--release`，未通过不得绕过。只报告本地CI改动，未经远端实际核验不声称分支保护已经生效。

分支默认保持 `main` 加一个日常开发分支，连续任务复用开发分支，不为每次任务或发版新建分支；版本用不可变标签保留。仅并行隔离或线上紧急修复使用临时分支，完成后先核对合入、独有提交和worktree依赖，再按授权清理。当前历史分支与脏工作区不自动切换、重命名或删除，具体规则见版本规范。

完成时固定报告本轮文件、实际验证、失败/未验证项、已有改动保留情况及接续待办。SQLite、AST、构建不等于生产通过；没有明确部署授权停在可审阅候选。共同流程是 AI 指令要求，未实现的 CI/自动门禁不能声称已强制执行。
