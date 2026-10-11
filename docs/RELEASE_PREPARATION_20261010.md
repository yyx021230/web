# 2026-10-10 版本更新准备与线上差异

## 结论与任务卡

**状态：调查完成，待补发布条件；没有部署。** 当前线上 core 与 Hermes 主组件均为 `0.3.43 / a9aaaceec458`。本地 HEAD 也是该版本，新增功能仍在未提交工作区，不能直接将整个目录覆盖到 Windows。

建议下一候选版本为 **0.3.44**，仅建议，尚未改版本、提交、打标签或推送。若上线时线上已有更高版本，重新取基线和版本号。

| 项目 | 本轮边界 |
|---|---|
| 目标 | 对清本地与 Windows 线上差异，形成可审阅更新范围、迁移/配置/顺序、验证和回滚清单 |
| 明确不做 | 不部署、不迁移线上、不改线上数据/配置、不清理磁盘、不启动发布、不重发已有内容、不修改 Phone Cloud |
| 风险 | 本轮只读与文档 R0；候选包含迁移/调度/跨组件 R2，实际发布另按 R3 授权 |
| 仓库 | `/Users/yyx/ztqc/web`；聊天 worktree 不作为当前运行源码来源 |
| 分支 / HEAD | `codex/v0.3.29-workbench-fix` / `a9aaaceec4581ece53985db0903aea18e776afb4`，标签 `v0.3.43` |
| 开始基线 | 52 个已有 tracked 变更，新增/删除行 1241/1623；4854 个未跟踪文件，未暂存；均保留 |
| 本轮允许修改 | 仅本文件；调查脚本和脱敏证据放 `/tmp/`，不是发布产物 |
| 规范 | 已重读 Web AGENTS、共同流程及发布规范/审计门禁/手册、数据隔离；共同流程修订 `2026-09-30`，SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b` |
| 授权 | 发布准备和线上只读核对；本轮没有生产写入、清理、发布或真实账号操作授权 |

证据分级：下文“线上实测”为本轮只读观测；“本地代码”为当前工作区行为；历史人工发布参见接入任务卡，不等于本轮完整生产验收。本文不是成功发布回执。

## 1. 线上实际基线

观测时间：北京时间 **2026-10-10 14:43**；补充队列/政策/穿透检查 **14:52**。资源和队列都是当时快照，正式发布前必须重查。

| 项目 | 线上实测 |
|---|---|
| core 后端、AI Worker、后处理 Worker | `ztqc/backend:0.3.43-a9aaaceec458-0c01616a7404` |
| 主前端 | `ztqc/frontend:0.3.43-a9aaaceec458-0c01616a7404`，宿主入口 3000 |
| Hermes API / 生成 Worker | `ztqc/hermes-api:0.3.43-a9aaaceec458` / `ztqc/hermes-worker:0.3.43-a9aaaceec458` |
| 旁路旧前端 | `web-hermes-frontend-1` 仍为 `0.3.38-6d72596f7d05-homepage`，绑定 `127.0.0.1:3101`；未删除 |
| 内网穿透配置 | `C:\ProgramData\frp\frpc.toml`：本地 3000 → 远端 18080；不是指向旧 3101。未在本轮验证公网实际响应或其他代理配置 |
| 版本/就绪 | core `/version`、`/health/ready` 均 HTTP 200，版本 `0.3.43`、commit `a9aaaceec458`、ready |
| 数据库迁移头 | `c47f2a6d9b10`；没有 `hermes_publish_jobs` / `hermes_publish_attempts` |
| 发布调度 | 无独立云手机发布 Worker；新增发布配置未注入现有容器 |
| 存储 | PostgreSQL 卷 `web_pgdata`；core/Hermes API 的 `/app/uploads` 都绑定 `C:\projects\web\uploads` |
| C / D 可用空间 | 约 **5.68 GiB / 20.51 GiB**；数据库约 **5.94 GiB** |
| 排空快照 | AI（含后处理）、Dify、主页同步、Hermes 活跃任务查询为空；近 12 小时执行中小红书调度日志 0；5 条 AI pending/processing 队列长度均 0。不是所有后台任务类型的完整排空证明 |
| Hermes 生成计划 | 1 条，enabled=false；不等于全系统所有定时任务关闭 |

针对本次变更核对了 core/Hermes API 各 12 个后端路径、Hermes Worker 2 个执行路径：现有对应文件都匹配本地 HEAD，新发布运行文件在线上不存在。**只证明这些路径没有发现热补丁漂移，不是全项目逐文件一致性证明。** 前端版本由镜像和回执确认，没有取到 standalone 源码逐文件对比。

### 可信身份记录

| 对象 | 指纹 |
|---|---|
| core 回执 SHA256 | `409d651f59e9ce81e79f2e8960186df9cef82db313ec9c6bc27c73ebe84dc512` |
| Hermes 回执 SHA256 | `ae6f203959aab842c2e6a4cdb8b54f0fd2bd8d0f8247ec1d3669f9746a96d4dc` |
| core 包/源码 SHA256 | `0c01616a7404cd1286406173f7c378e6b8e7730f56b80f0e776a69781905c19a` |
| core 后端镜像 ID | `sha256:5fae87f1a60f56df70bb4221f427bcafa5fa1ef310480bd081f5b39b272b467f` |
| 主前端镜像 ID | `sha256:08ede088d3277fe35a9714ff3b53eedd7a4d67999b0a23ec8229ed02b3d4729d` |
| Hermes API 镜像 ID | `sha256:5cfa1b55fe9a89bf677289f3d3e832fd288a5e4e1b7bf9bb49b3070f0b99e63e` |
| Hermes Worker 镜像 ID | `sha256:ad95d793ca3bf21a60cc0b1a0285eba482f57641cf899f6ce6dc407142b835c8` |
| MCP 源码 / 二进制 SHA256 | `b04ec77b8b8a8f94e93d99bca9ddb3220cdfd72ad0e63ec752e7ff8ccf7af323` / `bc724169dbfc375948ef915ffac49a1f14f30cf51a2bf6d755e269ed7325101d` |
| FRP 配置 SHA256 | `02a3b0f93370b8e97b32dddbd5e39e3ecc1f478393fe3fb2829a5bd48ce6e380` |

core/Hermes 回执路径分别为 `C:\projects\web\.release\current.json`、`.release\hermes\current.json`。Hermes 上版回执记录了 0.3.42 的回滚引用和 Compose 备份路径，但本轮**没有完成包、备份存在性及恢复演练**，不能据此承诺可回滚。

## 2. 本地相对线上新增/变化

| 模块 | 本地候选变化 | 更新影响 |
|---|---|---|
| 工作台审核 → 云手机发布 | 真正持久化发布单/尝试、版本锁、排期/取消/查询、独立 Worker、私有配图快照、精确小红书 ID/槽位解析 | 必须迁移并更新 Hermes API、前端、Worker/配置；旧生成 Worker 不能替代发布 Worker |
| 云手机结果回写 | 按用户最新要求，远端 succeeded → 本地 submitted，页面显示“云手机发布成功”；failed/expired → failed；cancelled → cancelled | 不再以 Web 新增的账号/标题/正文证据作为终态门槛；可选脱敏证据仅留审计。云手机成功不代表平台审核通过或公开可见 |
| 发布不确定状态 | 创建响应丢失、原任务不在最近列表、未知状态不自动重发 | 保留原 ID/尝试；不能把 unknown 当作再次发布授权 |
| 车型准入 | 仅允许能唯一匹配配置案例的车型，歧义/缺失在入队前报错；不再把整个图库车型列表当作可生产列表 | 依赖真实政策案例与图库配置；不复制本地测试案例到线上 |
| 配图提交慢/永久错误 | 参考图预检查限时、保留合法内部上传路径；明确 4xx 拒绝快速结束，容量/429/网络不确定保留原幂等键处理 | core API 与 Hermes 生成 Worker 都要更新；不能只换前端文案 |
| 工作流失败反馈 | 缺文案/母图/配图交付失败给出具体且脱敏原因，不再仅显示退出码 | 保持原失败任务，不自动重新生成或改成成功 |
| 提示词库 | 分类统一显示、来源筛选与分类联动、稳定分页；侧栏标签筛选 | 使用现有业务数据，不等于新增素材导入；未知分类不直接丢弃 |
| 图库/导航 | 图库头部筛选、详情侧栏、图片按原比例完整显示、懒加载；侧栏结构/样式调整 | 界面更新，不搬运图片文件或重建图库数据 |
| 旧未用代码/依赖 | 移除未使用的旧 AI store/registry、Dify SSE 辅助及占位适配器；删除 Zustand、Radix select 依赖引用 | 已有待发布修改，不是本轮新删；锁文件同时变化，没有顺带升级依赖 |
| 文档/样例 | 架构/规范更新及旧样例清理 | 不把整个旧模板编辑器下线算成此次新增，部分早已在 HEAD |

现有 AI 生图仍独立保留；本次新发布闭环不替代生图页面或旧云登发布入口。没有修改投流/运营看板统计口径。

### 必须纳入候选的未跟踪运行文件

以下文件当前尚未进入 Git HEAD，不能只提交已有 tracked diff：

```text
backend/app/adapters/phone_cloud_publish.py
backend/app/alembic/versions/d5a8c2e7f901_cloud_phone_publish_jobs.py
backend/app/models/hermes_publish.py
backend/app/scripts/phone_cloud_publish_worker.py
backend/app/services/hermes_publish_service.py
frontend/src/lib/prompt-library-filter.ts
```

对应新测试也须纳入：后端 `test_cloud_phone_publish.py`、`test_cloud_phone_publish_acceptance_audit.py`、`test_hermes_production_models.py`；Hermes `test_failure_reports.py`、`test_image_submission_rejections.py`。已有修改测试和本次报告按审查范围一起提交，不使用 `git add .`。

### 不随代码版本自动执行或覆盖

- 未跟踪文件主要为 `exports/` 4652 个、`local-reviews/` 157 个；审阅素材、候选图片、临时清单不整批入 Git/部署包。
- 分类 SQL、内部素材刷新/删除、车型图片上传/去水印/回填脚本是单独数据操作，不能因为“存在脚本”就上线执行；已在线上执行过的历史脚本也不重放。
- 本地 `manual.db`、`dev.db`、`.env*`、本地 admin 账户/密码、测试 provider、102 测试排期、案例与临时运行配置均不带到线上。
- 线上用户/角色、负责人分配、Token、密钥、广告账户、图片和数据卷保持原样；不覆盖生产数据库。
- 未跟踪资料如何保留/忽略需先决定，以满足发布入口的干净工作区要求；本轮没有移动、删除或自动忽略它们。

## 3. 迁移、配置与兼容要求

### 数据库

迁移链：`c47f2a6d9b10 → d5a8c2e7f901`。

仅新增两张发布表、索引、外键和唯一约束，没有历史排期回放/自动迁移，不批量更新用户、帖子或报表。每篇一个发布单，request_key 唯一，执行尝试独立留存。上线前仍需隔离 PostgreSQL 演练：从真实结构基线升级、旧版本兼容、约束/锁时间、恢复；本地 SQLite 通过不能替代。

### 新增部署配置

| 配置 | 用途/保守默认 |
|---|---|
| `PHONE_CLOUD_PUBLISH_ENABLED` | `false`；完成配置和验收前不启用真实下发。关闭会使 Worker tick 直接退出，也暂停对账，不会撤回远端已受理任务 |
| `PHONE_CLOUD_PUBLISH_BASE_URL` | 专用服务根地址，优先可信 HTTPS |
| `PHONE_CLOUD_PUBLISH_HTTP_ORIGINS` | 若沿用已批准 HTTP，必须精确来源白名单，不接受任意 HTTP 或关闭 TLS 校验 |
| `PHONE_CLOUD_PUBLISH_USERNAME` / `PHONE_CLOUD_PUBLISH_PASSWORD` | 专用服务普通用户，核对可见设备范围；不复用本地测试/短信管理员凭据，不写入 Git |
| `PHONE_CLOUD_PUBLISH_VERIFIED_XHS_IDS` | 已核验实际登录身份的稳定小红书 ID；不是昵称列表 |
| `PHONE_CLOUD_PUBLISH_IMAGE_ORIGINS` | 可信外部配图 HTTPS 来源；本站 `/uploads/` 应正确解析为共享本地文件 |
| `PHONE_CLOUD_PUBLISH_SNAPSHOT_PATH` | API 与发布 Worker 共用的持久化私有目录，不能在 uploads 内；默认相对目录不能作为正式部署方案 |
| `PHONE_CLOUD_PUBLISH_MAX_IMAGES` | 默认 5；当前 Hermes 单篇仍是一张图，不自动扩成多图生产 |
| `PHONE_CLOUD_PUBLISH_MAX_LATENESS_SECONDS` | 默认 1800；过期排期不突然补发 |
| `PHONE_CLOUD_PUBLISH_MAX_OBSERVE_SECONDS` | 默认 1800；超时保留原任务，不创建第二个任务 |

独立进程入口：`python -m app.scripts.phone_cloud_publish_worker`，领导租约 `cloud-phone-publish-worker`。应与 Hermes API 使用匹配的后端代码/配置和同一数据库、Redis、uploads、私有快照卷；不占生图 Worker 队列。Compose 重启策略、恢复脚本和组件回执也要覆盖它，不能依赖临时终端常驻。

### 组件兼容矩阵

| 组合 | 结论 |
|---|---|
| 新前端 + 旧 Hermes API | 不可用：发布记录/取消等新接口不存在 |
| 新 API + 未迁移库 | 不可用：访问新发布表会失败 |
| 新 API + 新库，但无发布 Worker | 可以保存排期，但到点不会下发 |
| API 与发布 Worker 不共享私有卷 | 排期快照不能可靠读取，不能启用发布 |
| 新代码 + 旧政策案例 | 新准入不能修复政策过期，生成仍会被既有安全检查拒绝 |
| 新 Web + 现有云手机用户 API | 使用已有 login/devices/publish-tasks/cancel 契约，不要求本轮修改 Phone Cloud；上线仍需只读核实真实版本、认证与账号映射 |
| 旧应用 + 新增发布表 | 结构为 additive，预期可忽略新表；实际 PG 兼容仍待演练。回滚前先处理发布 Worker，不删发布记录 |

远端创建仍无持久幂等、仅最近 100 条列表、无稳定帖子 ID/单查回调等限制仍在，不能承诺所有账号永不失败；Web 默认不重发不确定请求。

## 4. 当前阻断项与处理顺序

| 优先级 | 阻断/待办 | 完成标准 |
|---|---|---|
| P0 | C 盘空间不足 | 现有 Deploy-Release 要求 C 可用 >=数据库大小+8 GiB，当前约需 13.94 GiB，实际 5.68；D 要求 >=20 GiB，实际20.51仅略高。先经用户确认清理/迁移方案，保留备份与构建空间，不能自行删数据/镜像 |
| P0 | 政策配置过期 | 线上11个案例含C11，但 policy_deadline 均2026-09-30、public_deadline“9月底前”。现有生产代码按任务日期拒绝过期案例；确认10月真实政策/资料和展示后更新，不猜价格、不只改截止日、不打开过期绕过开关 |
| P0 | 新发布基础设施尚未进部署链 | 补发布 Worker、私有持久卷/权限、配置注入、组件身份/启动恢复及回滚路径，并做隔离部署验证 |
| P0 | 发布脚本组件范围不完整 | core 入口不会自动升级 Hermes；现有 Hermes 发布脚本不创建新发布 Worker/私有卷。`compose.hermes-release.yml` 模板仍写0.3.21，不能直接覆盖实际线上 override |
| P0 | 发布候选未冻结 | 按白名单审查暂存，处理未跟踪资料保留方式，形成干净提交、版本和标签；frontend当前0.3.43，backend源码默认0.3.31，不等于生产0.3.31；新版本需统一运行注入身份 |
| P0 | PostgreSQL 迁移/恢复未演练 | 在获准隔离 PG/备份副本验证，不拿生产首次试迁移；记录revision、行数/约束/锁时长及恢复结果 |
| P0 | 回滚产物/备份未确认可用 | 只读确认0.3.43包、镜像、配置、挂载及一次发布备份的可用性；实际恢复演练通过。一次发布备份不等于重新启用用户已关闭的每日备份 |
| P1 | 生产业务/权限与账号验收 | 普通用户/部门负责人/管理员、生产素材可用性、服务账号设备可见性、稳定ID/槽位、页面完整链路；真实生成/发布另明确账号、内容和次数 |

11 个案例的政策来源已读出日期但未做新政策导入，也未触发生成确认错误。根据既有 `validate_policy_dates()` 和当前 Worker 的日期参数可判断其会阻止10月新生成，属于**现有配置问题，不是此次发布改坏的**。

## 5. 本轮实际验证

后端使用 Python 3.12.13 隔离环境 `/tmp/ztqc-publish-test-20261008`，移除真实凭据、关闭发布、测试 fixture 使用临时 PID SQLite；socket.connect 审计钩子禁止真实外联。前端 Node v25.9.0，使用已有依赖，没有升级或安装依赖。

| 检查 | 本轮结果/证据 |
|---|---|
| Alembic 图 | `scripts/check_alembic_heads.py`，单头 `d5a8c2e7f901` |
| 发布契约 / 已跟踪秘密扫描 | `scripts/check_release_contract.py`、`scripts/check_tracked_secrets.py` 通过；新文件纳入候选后仍需再扫描 |
| 后端定向9文件 | 158 passed，20.23秒；覆盖新增发布/迁移/车型准入、工作流、提示词稳定分页、旧模块下线及发布保护 |
| Hermes 执行器全量 | `python -m pytest -q ops/xhs_hermes/tests`，787 passed，0.90秒 |
| 前端类型 | `npm run type-check` 通过 |
| 前端覆盖率 | `npm run test:coverage`，14文件138 passed；配置指定4个核心文件：语句/行94.16%、分支84.27%、函数75.92%。不是全前端覆盖率；移除已删除文件的统计目标，门槛未下调 |
| 前端生产构建 | `npm run build` 在不含`.env*`的 `/tmp/ztqc-release-preflight-20261010.eGKNx2` 副本通过，34页；没有覆盖运行中的`.next` |
| 后端全量覆盖率 | 清代理复跑 **965 passed / 0 failed**，230.73秒，应用分支统计口径总覆盖率 **71.00%**，达到70%门槛，31条警告 |
| diff格式 | `git diff --check` 通过；新增文档另用no-index检查 |

定向文件为 `test_fresh_database_migration.py`、`test_cloud_phone_publish.py`、`test_cloud_phone_publish_acceptance_audit.py`、`test_hermes_workflows.py`、`test_hermes_production_models.py`、`test_prompt_api_complete.py`、`test_prompt_feed_stability.py`、`test_editor_retirement.py`、`test_release_guards.py`。

全量后端命令为 `pytest -q --cov=app --cov-branch --cov-report=term:skip-covered --cov-fail-under=70`。首轮957 passed / 8 failed、覆盖70.63%；失败涉及HTTPX读取本机`socks5`代理而隔离环境缺该可选支持，不能当作业务通过。复跑仅移除测试进程代理变量，保留外联禁止和原测试，不修改业务代码/测试断言；最终965项全部通过，覆盖率71.00%。仅隔离测试进程清代理，没有更改系统代理或线上环境。

非阻塞警告包括既有 crypt 弃用、Browserslist 数据较旧等；不为消除警告顺带升级。历史调度领导测试和前端滚动测试时序波动见接入任务卡，本轮通过也不证明长期稳定性根因已消除。

未运行：真实 PostgreSQL 迁移/恢复、Windows新镜像构建、正式版浏览器全角色验收、并发长测、本轮付费生成或真机发布、Phone Cloud全系统审查、发布后的资源观察。没有降低原门槛或豁免上述发布条件。

### 脱敏证据

- `/tmp/ztqc-release-audit-20261010.json`：初次成功的容器/回执/挂载/源码校验，0600。
- `/tmp/ztqc-release-supplement-20261010.json`：14:52只读数据库、队列、案例日期及FRP配置补充，0600。
- `/tmp/ztqc-release-backend-tests-20261010.log`：清代理后的全量复跑日志。
- `/tmp/ztqc-release-frontend-build-20261010.log`：本轮隔离前端构建结果。

补充盘点曾遇SSH255、Windows输出编码及大命令/标准输入超时，未据此判断网站故障；保留首次成功快照，改用小型只读探针取得补充证据。临时证据不是长期备份，正式发布需保存脱敏清单及不可变产物。

## 6. 拟定发布步骤与停止条件

以下仅计划，**尚未执行，不构成上线授权**：

1. 解决空间、政策资料、部署脚本/私有卷、新Worker及PG演练；冻结完整候选与配置模板，复跑适用检查。
2. 用户确认具体版本/变更集合、目标Windows、维护窗口/允许中断、真实验收范围和回滚授权。确认不可变旧包/镜像、当次备份及恢复证据。
3. 通过正式入口预构建新core和Hermes相关镜像。以实际线上Compose覆盖项为基线最小合入，不套用旧0.3.21模板、不用tar目录覆盖裸Compose上线。
4. 切换前重查线上回执/发布锁、所有任务队列/活跃任务，排空后迁移新增表；保持Compose项目`web`和生产挂载源不变。
5. 协调切换core、Hermes API/生成Worker和前端；新发布Worker先以关闭状态部署，核验版本、ready、新接口、私有卷及配置。不能让新前端长时间连旧API。
6. 获准后核验生产账号/槽位与内容，有限开启发布，按批准范围做单账号再双设备验收。仅查询原任务核对，不以重新发布当验证；不沿用本地测试排期或复制历史任务。
7. 核对版本、两份组件回执、镜像ID、`Assert-ReleaseState.ps1`、数据库/图片挂载，以及登录、生图、任务中心、小红书同步、两看板、提示词筛选、生成审核排期链路。观察窗口建议至少30分钟，具体在审批时确定；完成后才写生产验收完成。

停止条件：空间门槛失败、迁移/备份失败、挂载变化、组件身份不一致、新接口500/404、快照不可读、错账号/重复下发、已有任务被中断、队列持续增长或资源异常。停止扩大范围，按已批准回滚方案处理，不自动清库/重发。

回滚原则：停止新下发、查询已受理原任务，不把关闭Worker视作撤回；恢复经过核验的0.3.43不可变镜像/配置，不重建历史镜像；保留新增发布表和unknown/submitted审计记录。当前通用Rollback-Release包含数据库恢复动作，**不能在新业务写入后直接照跑整库覆盖**，须先完成此次additive迁移的兼容回滚方案。Phone Cloud/ADB/投屏/FRP不随本次Web回滚重启或改动。

## 7. 交接

本轮新增本报告，未修改业务代码、既有diff、线上配置/数据或运行服务，没有Git提交/标签/推送。自审为本助手按diff与调用链核对，不冒充独立双人审查。

下一步优先补**部署链与隔离PG验证**，并由用户确认C盘空间处理和10月政策资料。完成后再冻结0.3.44候选、取得发布授权；目前不能仅凭本地页面可用就直接上线。

相关规范：[版本发布规范](RELEASE_VERSION_STANDARD.md)、[发布手册](V0.3_RELEASE_RUNBOOK.md)、[审计门禁](PRODUCTION_AUDIT_2026-08-17.md)、[云手机接入与历次验收记录](CLOUD_PHONE_PUBLISH_INTEGRATION_20261008.md)。

### 后续版本治理注记

用户随后要求规范版本管理，见[2026-10-10治理规则与验证](RELEASE_VERSION_STANDARD.md)。后端包/默认版本已对齐0.3.43；素材审阅/运行目录仅加入忽略、未删除；发布入口增加版本/记录/附注标签检查，未改变Git引用或生产版本。上文变更数量和空间是盘点时快照，不是治理后的当前Git状态。0.3.44仅此前暂拟，最终按发布范围确认版本；原磁盘、政策、PG和发布基础设施阻断未因此解除。

### 后续浏览器会话候选注记（2026-10-10）

随后已按用户授权完成本地浏览器登录会话改造，见[任务卡与最终证据](BROWSER_SESSION_20261010.md)。新增候选迁移头为 `e61010a0b001`（位于 `d5a8c2e7f901` 之后）；上述原盘点迁移头/测试数保留为当时记录，不作为当前候选结果。新会话模型、服务、路由、迁移、前端同源会话代理及测试均须纳入明确审阅范围，不能漏掉未跟踪文件。

本轮最终后端1020项通过、覆盖71.06%，前端180项通过，类型/构建及隔离PostgreSQL升级/降级/再升级、独立连接并发验证通过；浏览器已验证闲置到期弹窗、同账号重登保留挂载草稿、刷新恢复与临时故障不误退出。隔离库生图任务及发布单均为0；未动线上、现有本地业务库或生产服务。

发布时保持 `AUTH_BROWSER_SESSIONS_ENABLED=false` 为默认兼容策略；启用前必须完成正式HTTPS、精确Origin、Cookie/代理检查、主API/Hermes共认证库/密钥及新版鉴权验证。该候选不是通过修改配置就能直接在现有公网HTTP入口启用。隔离PG演练不代替生产备份副本恢复、Windows部署链及正式全角色验收；其余阻断仍需按原清单解决。

2026-10-11追加复查修复了跨标签退出后的迟到身份写回和旧JWT到期误归类，补充竞态/活跃/权限回归；输入框滚动测试先出现一次时序失败，确定为未等待按钮RAF聚焦，仅修正测试等待，不改变滚动业务代码。最终前端全量连续3轮均189项通过，后端重跑1020项通过、覆盖71.06%，类型/隔离构建通过。详见会话任务卡追加记录；未提交、推送、部署、启用会话或改动业务库。

### 2026-10-11 生产空间清理回执

任务 `20261011-windows-release-space`，用户先授权通过 VPN SSH 更新，检查发现空间及候选门禁未满足后，明确要求先清理不要的文件。本轮风险 R3，仅执行下列白名单清理，没有部署、重启、迁移或业务数据操作。重读共同流程（2026-09-30，同上 SHA256）及 Web 入口；实际源仓仍为上述脏工作区，已有改动全部保留，本轮只追加本节。

- 目标主机经已知 SSH 主机密钥连接确认是 `DESKTOP-8V8N4PE`。检查时 core/Hermes 主服务仍为 0.3.43；数据库大小 6,482,787,687 字节，迁移头 `c47f2a6d9b10`。
- 执行 `docker builder prune --force --filter "until=168h" --reserved-space 5GB`，实际报告回收 **12.47GB** 缓存。没有执行 image/container/volume/system prune。缓存清理不等于 Windows 虚拟磁盘压缩，D 盘此时可用空间未增加；未停止 WSL/Docker 或压缩 VHDX。
- 精确删除 C 盘 `.release` 中 0.3.22 / 0.3.27 / 0.3.28 三份旧 `predeploy-source-*.tar.gz`，以及 D 盘 `ztqc-release-archive` 中 0.3.3 / 0.3.4 / 0.3.14 / 0.3.15 / 0.3.5 / 0.3.16 六个旧发布包。删除前核对文件年龄、类型、大小/时间及当前两份发布回执无文件名引用；共 **9 个文件、9.750 GiB**。这些更早版本的本机文件副本已删除，不能再依赖它们做本机历史回退；没有删除 Git 历史或版本标签。
- 保留当前 0.3.43、上一版 0.3.42 的源码快照/版本包、当前回执指向的 `D:\ztqc-backups\web\20260923_123403`、Hermes 回滚配置和其他数据库备份；本轮未证明整套恢复演练通过。
- Windows 可用空间：C **10.89 → 16.07 GiB**，D **19.57 → 24.05 GiB**。达到当前发布脚本 C>=数据库大小+8GiB、D>=20GiB 的空间门槛；正式构建/备份前仍须重新检查。
- 删除后核验容器 ID/镜像引用及全部镜像 ID 清单不变、两份当前回执 SHA256 不变、受保护文件仍存在。主网页 `/` 和后端 `/health/ready` 均 HTTP 200，ready；容器未重启，数据库大小/迁移头未变。没有运行生成、同步或真实发布作为测试。

精确路径、删除前长度/时间、受保护材料、容器/镜像及磁盘前后快照留在 Windows `C:\projects\web\runtime\maintenance\cleanup-20261011-115602.json`，状态 `verified`。一次性脚本同目录 `cleanup-obsolete-artifacts-20261011.ps1`，不会定时运行。首次通过 EncodedCommand 传递清理脚本被 Windows 命令行长度限制拒绝，未执行删除；改为上传已审查脚本后成功执行。

剩余门禁：候选仍未提交/冻结新版本（发布检查拒绝 dirty 及非新附注标签），云手机发布 Worker/私有卷/部署恢复链、生产备份恢复验收等仍需完成。空间清理不代表已发布或其他门禁已解除；浏览器新会话仍默认关闭，不在公网 HTTP 上强行启用。

### 0.4.0 分阶段发布任务（2026-10-11）

用户随后授权继续，并明确接受先部署代码、核验后逐项启用。风险 R3，目标仍为上述 Windows Web 主机；不操作 Phone Cloud 服务、设备、FRP 或真实发布，不复制本地业务库/账号/政策/素材到生产。采用 0.4.0 标识新增产品能力，保留原日常分支和全部历史标签，不为此次新建日常分支，不自动推送远端。

本次冻结已验证的提示词/图库/导航、Hermes 生产与失败处理、审核发布/人工上传、可选浏览器会话、相应测试及版本门禁；素材导入、历史账户数据修复、爬虫等未跟踪操作脚本不纳入发布、不执行，仍留在原工作区。发布使用干净的独立提交检出，从 Git HEAD 导出，不为清理原工作区删除或忽略新代码。

- 初始阶段 `AUTH_BROWSER_SESSIONS_ENABLED=false`，`PHONE_CLOUD_PUBLISH_ENABLED=false`；没有部署/启用实际下发 Worker，不将“代码上线”描述为“自动发布已启用”。页面应明确提示未启用，允许保存草稿/审核/计划；启用仍须独立核验生产身份、私有快照卷及独立 Worker/恢复链。
- core 与 Hermes API/生产 Worker 都更新到同一候选提交；使用既有独立发布入口，协调维护窗口，不能长期让新前端连接旧 Hermes API。若任一组件失败，停止放开入口，恢复已验证的应用镜像/配置，不重发任务。
- 新增发布表及会话表为 additive；新增显式 `PreserveAdditiveSchema`，仅允许已审计 `c47f2a6d9b10 -> e61010a0b001` 的应用回退保留新增表，不重放整库备份。原默认恢复模式不变；正式入口通过显式环境开关传递，SSH 密码改为环境传入并强制已知主机校验。
- 线上 11 个车型政策此前均截止9月底，本次不猜新政策、不写10月价格/截止日。新车型生产可用性仍需补充真实政策；旧生图模块不受此项配置约束。
- 已运行新候选检查：后端全量1020通过，应用分支统计覆盖71.07%；前端189通过，配置指定核心文件行/语句93.86%、分支83.66%、函数75.92%，不是全前端覆盖；类型检查通过。版本与回滚保护19项通过，秘密扫描、发布契约、Bash语法通过，迁移单头 `e61010a0b001`。后端使用上述独立Python3.12、隔离PG Unix socket并禁止外联，无业务库写入。
- 发布前数据库备份已生成 `D:\ztqc-backups\web\20261011_121635`，沿用正式备份脚本 `-RetentionDays 0 -SkipUploads`：没有开启每日备份、删除旧备份或复制图库。该备份不含图片副本，不得宣称全量 uploads 恢复已验证。备份副本恢复/迁移及 Windows 构建、启动、业务核验仍在执行，尚未记录发布成功。

本次测试日志在本机 `/tmp/ztqc-release-040-backend.log`、`/tmp/ztqc-release-040-frontend.log`；后续实际提交/镜像/回执和验证结果以执行后追加记录为准。

### 0.4.0 代码阶段实际发布回执（2026-10-11）

状态：**core / Hermes 代码已部署，开关分阶段保持关闭，非完整自动发布验收**。用户明确接受此范围。正式源提交 `6ad44254ccc06396e9f6ad1bdac88810ad2bb32d`、附注标签 `v0.4.0`；复用原开发分支，未推送远端、未移动历史标签。正式包由干净独立检出 `/tmp/ztqc-release-040-6ad44254` 的 HEAD 生成；原工作区其他删除、审计资料、素材导入及修复脚本保持原样，没有纳入部署或执行。

**恢复与迁移演练**：发布前备份 `D:\ztqc-backups\web\20261011_121635` 在 Windows 独立 PostgreSQL 容器恢复，网络为 `none`，独立 D 盘数据目录，限制 CPU 1 / 内存 768MiB，没有连接生产数据卷或启动业务 Worker。2026-10-11 12:30:59~12:40:34（北京时间）完成恢复、`c47f2a6d9b10 -> d5a8c2e7f901 -> e61010a0b001` 升级和旧生产应用 ORM 读库。升级前后用户50、环境179、笔记29,854、广告账户202、Hermes帖子630，全部数量一致；三张新增表合计0行。临时数据库容器及其数据目录已移除，保留 `D:\ztqc-release-rehearsal\20261011-123059\verification.json`。这是数据库备份恢复/应用兼容演练，不包含 uploads 恢复、发布 Worker 故障演练或完整业务指标对账；未单独采集 DDL 锁时长。

| 组件/材料 | 本轮实际身份 |
|---|---|
| core 正式入口 | `deploy-to-windows.sh`，`PRESERVE_ADDITIVE_SCHEMA=true`，使用上述已恢复验证的备份；未开启每日备份 |
| core 成功时间 | 2026-10-11 12:52:02，北京时间 |
| core 包 SHA256 | `714b267a9e2f5310f0a877c05fce9daccec490b29463e3e0f2f962264df99eba` |
| core 镜像标签 | `0.4.0-6ad44254ccc0-714b267a9e2f`，backend / AI Worker / 后处理 Worker 镜像ID一致 |
| backend 镜像ID | `sha256:752179d5c94e4caa26654412c7391c0d12278a15419aede2e50231a186d4cd50` |
| frontend 镜像ID | `sha256:db178ccf03f1b55005eb1629f0d99ce45907e805f09f06148f01cf7de0f17519` |
| MCP | 源码/二进制指纹与此前0.3.43完全一致，未额外引入抓取组件变更 |
| Hermes 正式入口 | `scripts/windows/Deploy-HermesWorkerRelease.ps1`，由同一HEAD的ZIP生成，配套更新期间主前端短暂关闭，核验后重新开放 |
| Hermes 成功时间 | 2026-10-11 12:53:20，北京时间；API / 生成Worker均为0.4.0 / `6ad44254ccc0` |
| Hermes ZIP SHA256 | `a0e8c30826c1d85abce7f829397c0d38dfdbd27339eeedce9ed81479a1b81a71` |
| Hermes API 镜像ID | `sha256:f22849c9aabd1437d7048713127e1631377222da042843aca557dfb34bae4b87` |
| Hermes 生成Worker 镜像ID | `sha256:f68a9d174e00e2f1e137c4f1532dd7573e8acb540be14525fc4fd271daee6c11`，10个新鲜工作槽位，内部提示词目录748条 |
| 生产迁移头 | `e61010a0b001`；上述业务表数量仍一致；发布任务、发布尝试、浏览器会话各0行，无历史排期重放 |

**线上核验**：两份组件回执、`/version`、`/health/ready`、`Assert-ReleaseState.ps1` 均通过。PostgreSQL / Redis / MinIO / 旧旁路前端的容器ID、镜像和启动时间不变，全部原挂载保留。Hermes API 的 uploads 源路径从 Docker 返回的 Windows 写法变成 `/run/desktop/mnt/host/c/projects/web/uploads`，按明确的 Docker Desktop host-drive 映射核对为同一 `C:\projects\web\uploads`，其 junction 仍指向 `D:\projects\web\uploads`；另抽查3张现有图片，主前端代理与 Hermes API 的文件前16KiB均与核心容器实际文件一致，没有创建或改写图片。

57项有界、顺序 GET 冒烟通过：8个页面入口、匿名鉴权、6类现有角色（管理员/小红书负责人/品牌负责人/投手/运营/普通用户）的身份、新工作流初始化/发布记录、模型/历史查询、非管理员后台拒绝、三类提示词筛选、车型品牌、账号、任务中心/定时日志，以及管理员/小红书负责人/投手的昨日看板查询；另有上述6次图片读取。角色检查在容器内签发10分钟令牌，仅访问本机同源代理，不输出令牌，不等同于真实密码登录或浏览器全角色交互验收。看板查询可能正常写缓存，没有创建生成、同步、排期或发布任务。公网 `http://47.98.127.132:18080/ai` 跟随正常登录跳转后HTTP200。

首次验收脚本未跟随首页307跳转、漏写小红书路由自身`/xhs`前缀，以及直接字符串比较 Docker 两种挂载写法，均产生测试工具失败；核对当前源码/实际挂载后只修正临时验收脚本并全量重跑通过，没有为通过验收修改生产业务逻辑或放宽角色权限。首次失败不计作通过。

切换后首轮约8分钟观察，6个已更新应用容器无HTTP500、Traceback、ERROR行、OOM或重启；ready持续正常。C可用13.57GiB、D可用22.79GiB，较清理后减少主要包括当次不可变包/源码回退快照及一次备份，保留本版/上版产物。该短观察不是30分钟高峰长测、并发生成或真实发布稳定性保证。

**保留开关及接续**：主API和Hermes实测 `AUTH_BROWSER_SESSIONS_ENABLED=false`、`PHONE_CLOUD_PUBLISH_ENABLED=false`。尚未部署实际云手机发布Worker或共享私有快照卷，不能宣称到点自动发布可用；未操作 Phone Cloud / ADB / FRP，也未真实发帖。新浏览器3天闲置会话须待HTTPS、精确Origin和跨组件认证验收后开启。11个车型案例的旧政策期限仍为9月底，未猜测或修改10月政策；Hermes正式生产前还需补真实资料。旧独立AI生图保留，本轮只查其模型/历史，没有付费调用验收。

core回执 `C:\projects\web\.release\current.json`；Hermes回执 `.release\hermes\current.json`；完整核验/脚本/脱敏冒烟在 `C:\projects\web\runtime\maintenance\release-040-verification.json`、`release-040-smoke.log`、`ztqc-040-*.ps1` / `.py`。原配置/回执/容器基线在同目录 `release-040-baseline`；core源码回退快照为 `.release\predeploy-source-0.4.0-6ad44254ccc0-714b267a9e2f.tar.gz`，Hermes回退配置在 `D:\ztqc-hermes-release\0.4.0\private\service-before-20261011_125250`。回退仍应保留新增表/审计数据，不能直接调用通用整库恢复覆盖新写入。本机详细执行日志为 `/tmp/ztqc-release-040-{deploy,hermes,verification,smoke,observation}.log`。本节为部署后追加记录，不改已冻结v0.4.0标签，也未自动推送。

### 0.4.0 用户授权后的线上验收（2026-10-11）

任务：部署后真实登录与有界验收，风险 R3。用户提供既有 `admin` 账号并明确授权仅一次真实生图、不发帖。共同流程修订日期2026-09-30、SHA256仍为 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`；只操作此前获准的生产入口及主机，不改业务代码、生产配置、密码、角色、账号分配、开关或定时任务，不重启服务，不调用上游数据同步，不创建工作流或发布任务。以下为本轮实际验证，不代替全功能、全指标准确性或高峰压测。

| 范围 | 实际验证结果与边界 |
|---|---|
| 浏览器真实登录 | 公网入口正常登录，显示admin；刷新后仍能恢复身份和生图历史。未修改或保存密码 |
| 一次真实生图 | GPT Image 2、3:4、单张、低质量；任务37577，北京时间13:41:21创建、13:41:59完成，耗时37.998秒，无任务错误。未再次生成 |
| 图片与持久化 | 文件 `dadef223862f4db5933c954be5b952e6.png`，2,414,377字节；PIL文件校验通过，实际1086x1448，精确3:4，浏览器大图加载正常。请求768x1024，实际返回并非同像素尺寸；刷新后该条历史仍存在 |
| 后处理证据边界 | 实际生成Worker及后处理Worker的去水印、严格模式均为true。终态参数会清理中间字段，不能用中间字段不存在判定跳过处理。影子审计开关为false，任务无影子阶段记录；Worker未输出此次INFO阶段日志，无法提供独立的远端去水印原始回执，不将文件有效等同于水印移除效果独立验收 |
| 页面/接口冒烟 | 57项原有检查本轮重新执行通过，另28项扩展检查通过，共85项；另6次既有图片读取。覆盖6类既有角色权限、匿名拒绝、越权读取生图任务拒绝、参数边界、五类缓存报表、任务/历史/工作流查询、投流筛选和导出。角色接口使用10分钟临时令牌，不是6类用户真实密码登录 |
| 投流浏览器操作 | 默认30天及切换张婷成功；原范围显示28个有投流数据账号。再切换2026-10-10单日后显示13个、消耗约954元、转化50，加载完成且数据替换。不能据此宣称已与上游逐账户对账 |
| 运营浏览器操作 | 默认范围及2026-10-10单日均正常加载，无卡死。昨日明确显示笔记未入库、客资统计已更新，笔记相关指标为0；负责人总表仍展示最新分配18人/145账号。本轮没有补抓数据，0值不是本次接口超时证明 |
| 导出 | 品牌/笔记导出HTTP200，xlsx可读，列数9/15。选中的账户10071215在该日导出仅表头；验证的是空数据导出格式，不是非空明细金额核对 |
| 工作台/审核/排期界面 | 工作流广场、单篇配置/历史图文和排期页正常打开。admin没有绑定创作账号，下发按钮禁用，未更改归属。排期页明确提示实际云手机发布未开启，发布任务及尝试均0；未点击审核、保存排期、上传或真实发布 |

本轮最后保存的接口结果：`/tmp/ztqc-040-acceptance-smoke.log`、`/tmp/ztqc-040-acceptance-api.log`，57/28项再次通过。昨天看板经容器内同源前端代理约0.06~0.11秒返回，属于缓存/本机路径，不是公网完整渲染耗时。参考类型接口约3.65秒，未优化或掩盖。浏览器首次直接打开投流页有一次导航工具超时，原页随后正常渲染且后续操作完成；不能仅据此认定后端故障或宣称穿透链路已解决。原生日期输入的自动化fill未提交React草稿，改用实际键盘选择后应用成功，未为测试改业务代码。

**约30分钟日志窗口**：北京时间13:35~14:05，backend/Hermes API无ERROR、Traceback或匹配HTTP500行；6个已更新容器均运行、重启0、OOM=false，ready的数据库/Redis/存储均正常。前端有2条 `Failed to find Server Action "x"`，时间13:53:18、14:01:42；当前源码未找到该Server Action，检查中未复现用户页面失败。缺少请求来源证据，暂不能确定是旧客户端还是其他请求，保留为待定位事项，不记作零错误。生成及后处理Worker窗口内没有日志输出，不能用0日志证明所有阶段均可追溯。

14:05资源采样：backend约395MiB/CPU0.82%，frontend约81MiB/CPU0.55%，Hermes API约162MiB/CPU0.23%；C可用13.56GiB、D可用22.78GiB。BlockIO为容器累计值，不作磁盘瞬时利用率证明；没有执行多用户高峰或10任务并发压测。观察JSON保存在 Windows `C:\projects\web\runtime\maintenance\release-040-acceptance-observation.json`，本机副本 `/tmp/ztqc-040-acceptance-observation.log`。生图浏览器截图 `/tmp/ztqc-040-acceptance-image.jpg`。

结论：本轮已验证的代码阶段功能可用；仍保持浏览器新会话与云手机实际发布关闭。开启前继续完成HTTPS/认证、真实车型政策、生产发布账号/私有卷/Worker及独立发布验收；当前admin无创作绑定也须在明确业务归属后处理。本轮只追加验收记录，未提交、推送、改标签或再次部署。

### 后续发布连接配置应用（2026-10-11）

用户要求接入并继续推进后，15:05 北京时间仅重建 Hermes API、启动同版独立 `phone-cloud-publish-worker`；专用普通身份沿用 `web-publish-102-test`，Web 白名单仅102，实际下发和浏览器新会话均仍false。其他9个原容器未重启，未迁移、覆盖或恢复数据库。API/Worker 真实只读鉴权、102唯一槽位解析、持续租约、API写/Worker只读私有快照挂载、核心版本及5项同源只读接口验证通过；远端原任务仍3条，线上发布单/尝试均0条，没有真实发帖。

独立配置回执在 `D:\ztqc-private\web\phone-cloud-publish\receipt.json`，索引为 `.release\phone-cloud-publish\current.json`，原 override 私有副本保留。既有 core/Hermes 回执、镜像和标签不变；本轮配置不是新增业务版本。后续版本更新须同步新发布 Worker 与私有目录，当前正式发布工具尚未自动纳入它；未新增每日备份、未演练新组件的实际回退。

完整证据、首次验收脚本数组误判及修正重跑、指纹与剩余阻断见 [发布接入任务卡追加回执](CLOUD_PHONE_PUBLISH_INTEGRATION_20261008.md)。102 尚无线上创作账号，管理员仍0个绑定；现有11个车型销售政策仍过期。连接已接通不等于账号已登记、真实生产配置有效或实际发布已启用；这两项完善前不扩大账号范围、不自动生成或发帖。
