# 生图主备入口调度

状态：本地候选，用户已授权提交并冻结为 `v0.5.0`；不推送、不部署。用户确认所有入口连续失败两次后保留任务，等待恢复，并设置等待上限。10 月 20 日按“准备上线”要求，在既有隔离工作区合并待发布异步补丁；下文首轮记录保留，最新准备进度和冻结授权见文末。

## 基线和范围

- 规则重读：共同流程 2026-09-30，SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。
- 主工作区 `codex/v0.3.29-workbench-fix`，HEAD `e6a18580c7782db6bea4140b87544e4753573654`；其他既有脏改动保留，不自动提交/推送。
- 风险 R2：生成调度、跨进程容量、失败重试和任务恢复。只进行本地隔离测试，无生产配置或数据变更、无付费生图。
- 本轮文件：`ai_provider_routing.py`、`ai_image_provider_service.py`、`ai_image_service.py`、`ai_image_progress.py`、`config.py`、专项测试及本文。无迁移、依赖升级或权限变化。
- 修改前 SHA256：provider service `48f4a116cda2dc6a4b3c5ccb1747082d454b796066d26f5cc5dd9f40adcb2618`；image service `737ff9172fbf43abfd3a9ac11f1b9c3687ccae21a6847bc86e796c71993bfa71`；progress `cf19ab2a8070bb08cee34d878020a03f85b989cd76d04fe89b279e236b7d415b`；config `37418f0133c8fbeee91e9d6ebf3fd4701e7a9324854b634783a189903f823f6b`。

## 行为契约

1. 默认入口优先，随后按 priority、ID 确定备用顺序；只在启用且支持当前模型/模式/参考图的集合里选择。健康主入口满载只排队，不自动用付费备用扩容。
2. 首次入口故障后仅允许单路复试，第二次确认故障才进入冷却。Redis 原子状态/槽位由所有启用新调度的进程共享。故障前仍在途的旧请求不能用迟到结果清除新故障。
3. 冷却默认 60 秒。存在待执行任务时，单路使用真实任务进行半开试跑；成功后新任务恢复该入口优先。没有待执行任务不额外生成测试图，不定时调用会计费的旧 health_check。备用已经受理的任务不搬迁。
4. 明确连接未建立、鉴权/限流拒绝、确认终态失败才允许重投。读超时、未知 5xx/499/408、受理结果不明、部分图片不重新生成。输入错误不作为入口故障。
5. 等待预算沿用 `AI_PROVIDER_WAIT_TIMEOUT_SECONDS=300`，首次无法获得可用入口/名额时启动绝对截止时间，持久化到原任务，切入口/重启不刷新该预算。前面两次调用耗时不提前启动恢复等待计时；已经受理的生成允许完成，仍受原总任务 1800 秒上限约束。预算耗尽保留任务和失败原因。
6. Redis 不可用时显示等待调度恢复，不回退各进程的私有调度。槽位租约覆盖总任务超时加 60 秒；进程死亡后最多等待该租约到期，不因为短心跳抖动重复占用并发。
7. 已完成尝试记录在原任务参数；安全关闭的尝试才允许恢复排队，下一次下发立刻撤销该证明。旧任务未知状态不被批量重跑。

## 配置和兼容

- `AI_PROVIDER_PRIMARY_ROUTING_ENABLED=false` 默认保留旧行为，候选通过后才随明确发布启用。
- `AI_PROVIDER_RECOVERY_PROBE_SECONDS=60`，`AI_PROVIDER_ROUTING_NAMESPACE=ai:image:provider-routing:v1`。
- core/Hermes 相关执行进程启用值、Redis、namespace 必须一致。禁止混合新旧调度运行后宣称跨进程限流有效；正式切换前排空。
- Redis 路由状态不能随意清除；Redis 持久化/恢复行为需发布前检查。回滚先排空，关闭开关恢复旧策略，不删除任务、Redis业务队列或业务数据。
- 与独立 v0.4.2 异步补丁同改 provider service，未来合并须定向审阅并回归按任务 ID 查询、未知结果不重发。没有合并或上线证明。

## 验收计划

用独立临时 Redis Unix socket、临时 SQLite 和 mock 上游验证：主入口严格优先/满载排队、两次切换、跨客户端并发、单路试跑及恢复、全部失败等待/超时/取消、输入错误、部分图片、未知结果、动态禁用/模式筛选、重启保留截止时间、Redis 故障与迟到结果。最后做原生图回归和版本检查；真实上游/Windows 验收留待发布。

## 本轮实际验证与审查

- Python 3.12.13，解释器 `/tmp/web-image-async-runtime-20261019/bin/python`。工作目录 `/tmp/web-primary-routing-test-u3MfE0`，清空继承环境、`PYTHONDONTWRITEBYTECODE=1`，仅设置测试 PATH/PYTHONPATH；不加载项目业务 `.env`。每个专项测试启动独立临时 Redis Unix socket，禁用 TCP 和落盘，结束即关闭；SQLite 由现有测试 fixture 临时建表并清理。
- 首轮新增专项 25 passed；随后补齐真实 HTTP mock 的图生图、多进程客户端竞争、并发失败、持久等待及回归。
- 最终运行 `python -m pytest -q`，测试文件均位于 `backend/tests/`：`test_ai_primary_routing.py`、`test_ai_provider_routing_refresh.py`、`test_ai_image_count_integrity.py`、`test_ai_image_service.py`、`test_ai_image_providers.py`、`test_ai_image_provider_service_complete.py`、`test_ai_image_shadow.py`、`test_ai_image_reconciliation.py`、`test_hermes_workflows.py`。**230 passed，5 warnings，43.85 秒，退出码 0**，本组无失败/跳过。
- 34 项新专项中包含：API 提交 202、重复提交返回同一任务 ID、真实适配器发出 mock `/images/edits` 请求、两次 429 后转备用、1/4 张图片真实写入临时存储、后处理 Worker 接续、原任务查询完成。分别覆盖 interactive 的 GPT Image 2 和 batch 的 GPT Image 2.5；不是外部模型真实生成或整条 Hermes 文图生产验收。
- 跨两个 Redis 客户端 20 个同时申请共享名额，主入口只占配置的 3 个槽位，健康时无备用分流；冷却结束只允许一个恢复试跑，其他任务可继续备用。并发第二次失败能直接打开熔断，不等待其他慢请求结束；迟到成功不会抹去较新的故障。
- 本轮六个 Python 变更文件 Ruff 通过；`git diff --check` 通过；Python 3.12 执行 `scripts/check_version_control.py` 开发门禁通过，`dirty=true`、版本仍 0.4.1。未执行发布门禁、前端构建或全量后端测试。
- 自审：新调度关闭适配器内部重复提交，由同一个调度器统一计数；本地 HTTP 连接池耗尽不算入口故障；Redis 状态写入失败仍保留已生成图片并停止自动重投；任务证据落盘失败停止重投。没有独立双人审查。
- 自审补充修正并回归：试跑失败后再次进入相同冷却状态也刷新前端进度；恢复等待预算只在首次无法获得入口/名额时启动，避免前面正常调用耗时提前耗尽恢复等待时间。
- 未验证：真实上游生图、生产 Redis 持久化/重启、Windows PostgreSQL 和切换、v0.4.2 异步补丁合并后回归。开关保持默认关闭，已有代码/工作区内容保留，无线上操作。

下一步：与待发布异步补丁合并成明确候选并复跑相关测试，再按实际发布授权统一启用所有生成执行进程；不直接从当前脏工作区打包发布。

## 10 月 20 日发布准备

### 范围和版本

- 复用 `/Users/yyx/.codex/worktrees/image-async-recovery/web`，基线 `ff61ceb406bf91d8a64f183d539c242247e47c3e` / 不可变标签 `v0.4.2`；开始时工作区干净。未移动历史标签，未改主工作区的任何文件。
- 本次候选 `0.5.0`：包含未发布 0.4.2 异步协议，以及上述主备调度；新增调度能力按次版本管理。版本元信息和 CHANGELOG 一致，提交/附注标签仍需明确授权后冻结，不从脏工作区发布。
- 不包含主工作区的投流报表完整性、云手机发布重试、文案处理或其他未提交修改。无新迁移，候选 Alembic head 与当前生产同为 `e61010a0b001`。
- 合并反例先复现：异步 429、401、明确未连接没有正确进入二次尝试，400 被本地提交标记误判为已受理。8 项组合测试初轮 4 失败；修复专用错误状态码与传输原因分类，并且只有真实上游任务 ID 才标记受理。未放宽未知结果重发边界。
- 组合专项随后 78 passed；新增 1/4 张参数覆盖，继续验证异步 POST/GET 与共享调度真实适配器组合（HTTP mock，不是外部计费生图）。

### 本轮只读生产核验

- 2026-10-20 17:55~18:02 CST：core `/version` 为 `0.4.1/e6a18580c778`，`/health/ready` 的数据库、Redis、存储均 OK；11 个运行容器，未重启任何容器、Docker、代理或服务。
- C 盘空余 38,088,802,304 字节（约 35.47 GiB）；D 盘 42,177,146,880 字节（约 39.28 GiB）；业务库 7,296,892,263 字节（约 6.80 GiB）。当前空间通过原最低门槛，构建/备份后仍需重新检查。
- 查询时 AI processing=2、无活跃 Hermes 创作任务；仅是时间点快照，不视为已排空。正式切换须重新核验全部任务类型、数据库与 Redis 队列。
- 仅 provider 5（GPT Image 2，30 路）和 14（GPT Image 2.5，15 路）启用，均为默认主入口，`api_mode` 均未配置；目前没有启用的备用。保留原禁用状态，不擅自激活其他供应商。
- Redis AOF 开启，最近 AOF 写入与 RDB 保存正常。生产 shadow/reconciliation 均 false，等待上限 300 秒。新调度默认 false，不自动开启影子或恢复执行权。
- 实际 Hermes Worker 的 `XHS_BACKEND_BASE_URL=http://backend:8000/api/v1`，创作 10 路、图片 3 路；其生图提交进入 core 队列，因此这次不需要重建/重启 Hermes Worker 或改其文图生产逻辑。主备调度执行于 core AI Worker。
- core 回执 hash `7393A20C820D145589DDCB1E7A1EBD7DD644750B039EB08D43930927244AAA2D`；Hermes 回执 hash `88BA88E0DFD4AE195BD3FE23F20067AB1AABF5C0BCCE78EAB97A82E1D68F6955`。不改写回执。
- `C:\projects\web\uploads` 仍为指向 `D:\projects\web\uploads` 的业务目录 junction，不得当成旧目录清理。
- 最新发现的备份目录 `D:\ztqc-backups\web\20261012_092241` 仅包含数据库 dump（1,351,938,126 字节）与 manifest；三个现存 manifest 均无 uploads 归档。旧备份不算本次新恢复点，也未证明图库已有独立完整备份。

### 切换计划和阻断项

1. 完成候选回归、自审和授权后白名单提交/附注标签；执行发布版版本门禁，通过后才从 HEAD 生成正式不可变包。不能复用 v0.4.2 或生产 0.4.1 标签。
2. 核对既有不可变回滚镜像/包、挂载、MCP 指纹和发布锁；在原 Windows 存储上完成新数据库备份及隔离恢复演练，确认图库完整备份方案/实际证据。禁止搬到用户 Mac，禁止删除图库、业务数据库或历史任务来腾空间。
3. 当前发布脚本使用 `Backup-Release.ps1 -SkipUploads`，但审计/手册要求可恢复的图库备份；现有备份证据不满足，不能借脚本可执行而绕过门槛。本轮不擅改门禁、不开始大容量备份或停服。
4. 在切换窗口排空全部在途任务；正式 `deploy-to-windows.sh` 先构建再切换 core。保留 Hermes 组件回执/镜像，不重启 Docker、FRP、数据库或 Redis。
5. 备份生产配置后，在 core API/AI Worker 共用 `backend/.env` 一致启用 `AI_PROVIDER_PRIMARY_ROUTING_ENABLED=true`，保留 `AI_PROVIDER_RECOVERY_PROBE_SECONDS=60`、等待上限 300 秒与统一 namespace。仅 provider 5 按已核实能力 opt-in `api_mode=sub2api_async`；provider 14 未核实 async 能力，保持原协议。其余开关、keys、并发数、启用状态不改变。
6. 验证正式版本回执、ready、`Assert-ReleaseState.ps1`、容器镜像/挂载与用户核心功能；真实生图需确认本次授权范围/最多 2 次预算，不用旧未知任务做试验。检查原任务 ID、上游 ID、图片数量、后处理及可访问性。观察真实请求；不人为打坏线上入口来证明切换。
7. 停止条件：版本/挂载不一致、重发未知任务、图片数量回归、队列卡住、Redis/数据库异常。回滚使用原不可变产物及原配置，排空后关闭新调度，保留新业务写入；不运行会恢复旧整库的默认回滚路径，需使用已核实的应用级回退方案。

真实生产生成、候选镜像、最新备份恢复演练、图库备份、发布和线上观察目前均未完成；不能标记“可直接切换”或“生产验收通过”。

### 合并候选的实际验证与交接

- 使用 Python 3.12.13 独立运行时，`/tmp/web-image-async-tests-20261019.py` 禁止 dotenv、真实凭据、外部 socket 及本地业务 DB/Redis 端口；测试临时 SQLite/Unix-socket Redis，不改业务库。工作目录为隔离工作区 `backend`。
- 全量命令：`env -i PATH=/tmp/web-image-async-runtime-20261019/bin:/opt/homebrew/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /tmp/web-image-async-runtime-20261019/bin/python /tmp/web-image-async-tests-20261019.py -q tests --cov=app --cov-branch --cov-report=term --cov-fail-under=70 --disable-warnings`。**1116 passed，3 skipped，31 warnings，覆盖 71.38%，416.11 秒，退出码 0**。此轮收集后又把组合测试参数扩展为 1/4 张，未冒称这 8 个新增参数已包含于该全量数字。
- 最终组合专项同环境执行 `-q tests/test_ai_primary_routing.py tests/test_openai_image_tasks.py tests/test_openai_image_tasks_integration.py --disable-warnings`：**86 passed，1 warning，20.40 秒，退出码 0**。扩展夹具初轮因 `_extract_image_urls` mock lambda 漏掉 provider 参数造成 10 失败，修正为真实三参签名后通过，未改业务代码来适应错误夹具。
- 前端 `npm run type-check` 通过。首次默认并发 coverage 184 passed / 5 failed，其中 4 项 5 秒超时、1 项异步列表断言失败；与全量后端同时运行时本机负载较高。不改业务源码、不放宽超时，后端结束后执行 `npm run test:coverage -- --maxWorkers=1 --minWorkers=1`：**19 文件 / 189 tests 全通过**，指定范围语句/行 93.86%、分支 83.66%、函数 75.92%。单 worker 全量重跑不复现，仍保留初轮失败记录，未宣称默认高并发环境已验证稳定。
- 元信息更新为 0.5.0 后 `npm run build` 通过，34 路由；未修改前端业务源码。没有依赖升级；保留 Vite CJS/Browserslist 既有警告。
- Ruff 7 个相关 Python 文件、`git diff --check`、单 Alembic head、发布契约、tracked secrets 扫描通过；新文件另行自审未发现真实凭据。版本管理临时仓回归 16 项通过。
- `/opt/homebrew/bin/python3.12 scripts/check_version_control.py` 通过，明确 `dirty=true,version=0.5.0`。`--release --tag v0.5.0` 按预期拒绝：未提交工作区、缺少附注版本标签。已向用户请求此候选的本地提交/标签授权，未收到确认前不冻结、不推送、不绕过。
- 2026-10-20 18:08 CST 线上 `Assert-ReleaseState.ps1` 实际返回 `verified=true`；全部版本、镜像、MCP、Worker、前端与后处理检查为 true。这只证明当前 0.4.1 基线一致，不是候选的生产验收。
- 自审已逐项核对合并 diff、适配器调用、401/429/未连接与结果不明边界、单/四图、任务持久化与 GET 恢复、core/Hermes 调用路径；无独立双人审查。
- 本轮改动仅在上述隔离 worktree：新增路由/专项测试/本文，合并 config、provider service、image service、progress；修正异步适配器错误分类；同步 CHANGELOG、前后端版本元信息。主工作区所有原改动完整保留，生产只读，无配置写入、付费请求或任务重试。
- 交接状态：**本地候选 / 待冻结授权与生产备份门槛**。下一步不是直接切换：先完成白名单提交标签、正式发布检查、备份/恢复及图库备份证据，再准备不可变包和镜像，最后在获准窗口排空切换。

### 本地冻结授权（2026-10-20）

- 用户明确回复“允许提交并冻结候选”，范围仅异步生图与主备入口调度；授权本地提交和附注标签 `v0.5.0`，不推送、不立即切线上。前文“待冻结授权”为历史准备状态，本条取代该授权缺口。
- 复用原隔离分支 `codex/hotfix-image-async-20261019`，原 HEAD/标签 `ff61ceb406bf91d8a64f183d539c242247e47c3e` / `v0.4.2` 保持不动，不新建分支、不重写历史。新提交身份由 `git rev-parse v0.5.0^{commit}` 获取。
- 白名单为 12 个文件：`CHANGELOG.md`；`backend/app/adapters/ai_model/openai_image_tasks.py`；`backend/app/config.py`；`backend/app/services/ai_image_progress.py`、`ai_image_provider_service.py`、`ai_image_service.py`、`ai_provider_routing.py`；`backend/tests/test_ai_primary_routing.py`；`backend/pyproject.toml`；`frontend/package.json`、`frontend/package-lock.json`；本文。除更新冻结状态外，不再修改上一轮已验证的业务实现。
- 冻结步骤：重新运行 86 项组合专项及静态/版本检查，精确暂存白名单、检查 staged diff 与秘密扫描，创建本地提交和附注标签，再执行 `scripts/check_version_control.py --release --tag v0.5.0`。以实际命令结果为准，不用文档宣称尚未执行的门禁通过。
- 提交前本轮实际复验：同上隔离命令组合专项 **86 passed、1 warning、20.84 秒**；7 个 Python 文件 Ruff、开发版本检查、staged diff 格式与包含新增文件的 tracked-secret 扫描均通过。业务实现未再次改动；未重复全量后端/前端构建，也未将上轮结果改写成本轮重新运行。
- 仍保留的发布阻断：最新备份/恢复演练、图库完整备份、候选镜像及真实生产验收；本地 Git 发布门禁通过不解除这些门槛。主工作区已有改动原样保留，线上任务、配置、数据库与服务不在本轮操作范围。
