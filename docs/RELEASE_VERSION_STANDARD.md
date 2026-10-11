# Web 生产版本与发布规范

更新日期：2026-10-10

## 1. 目标

生产环境中的源码、发布包、Docker 镜像、运行容器和发布回执必须能一一对应。任何人都不能通过复用旧标签、手工解压后重新构建或直接执行裸 Compose 命令，让生产环境静默回退到旧逻辑。

已落地的检查由脚本执行；CI 规则只有提交到远端并实际运行后才生效。远端分支/标签保护需另外配置，不能仅凭本文认为已强制执行。

## 日常版本管理

**功能提交、版本标签、生产上线是三件事。** 小功能验证后及时提交保存，不要积累到上线时才一次性提交；只有候选冻结才升版本和打标签，部署成功后再记录线上回执。

### 分支保持精简

当前团队默认只维护 `main` 和一个日常开发分支（统一采用 `codex/develop`）。连续任务复用日常开发分支，用可审阅提交区分功能，不为每个任务或每次版本升级创建新分支，也不强制创建发布分支。`main` 保存已合入且检查通过的代码，实际线上运行版本仍以发布回执和版本标签为准。

只有需要隔离的并行开发，或线上紧急修复不能混入正在开发的功能时，才创建临时 `codex/<任务名>` / `codex/hotfix-<问题>` 分支。临时分支合入、确认无独有提交且无关联工作区依赖后，按用户授权删除本地和远端分支；不能因“已发版”就直接删除。

版本历史由不可变 `vX.Y.Z` 标签保留，不靠永久保留版本分支。现有12个本地分支先核对提交归属和worktree占用；当前脏工作区先按白名单保存，再明确安排日常开发分支及main的衔接，不自动切换、重命名、删除、强制推送或重写历史。本规则不取消共同流程对并行任务隔离的要求。

| 环节 | 后续统一做法 |
|---|---|
| 开始任务 | 记录仓根、分支、HEAD、已有改动；优先复用日常开发分支，仅隔离并行任务时建临时分支。依赖未提交改动时先核对，不从旧 HEAD 随意新建并丢失已有功能 |
| 开发保存 | 一个独立功能/修复一组提交，配对应测试/说明；不以版本发布代替日常代码保存。提交/推送按用户授权执行，不自动把所有文件暂存 |
| 合入 | 通过 PR 审查与适用检查进入 `main`；已有历史分支先梳理，不强制重写 main 或迁移未知工作区 |
| 候选冻结 | 在已审查的提交上冻结明确功能白名单，不额外创建发布分支；冻结后只收阻断修复，其他需求留下一版。同步下表全部版本位置与 CHANGELOG |
| 发布身份 | 新版本使用附注标签 `vX.Y.Z`；标签指向唯一候选提交。禁止 force-push、移动/覆盖历史版本标签、复用生产镜像标签 |
| 上线 | 只部署该提交构建的不可变产物，记录 core/Hermes/发布 Worker 的实际组件身份、迁移头、配置指纹和回滚点 |
| 紧急修复 | 从实际线上标签/提交建立 `codex/hotfix-<问题>`，最小修复、测试、新版本；不能从含下一版功能的脏工作区抽整个目录覆盖生产 |

提交信息示例：`feat(hermes): persist publish schedules`、`fix(ai): preserve scroll position`、`test(release): reject mixed versions`、`docs(release): record migration plan`。提交需可独立理解，不把素材导入、功能修改与生产数据修复混成一条大提交。

版本采用 `X.Y.Z`：兼容修复升补丁，新增产品能力升次版本，不兼容变化升主版本；0.x 阶段重大契约变化也应明确升次版本并列迁移。无需每个开发提交都升版本。此次完整云手机发布闭环属于新增能力，候选版本需按范围确认；之前暂拟的0.3.44不是已经确定或已创建的版本。

| 必须同步的位置 | 校验字段 |
|---|---|
| `frontend/package.json` | version，版本源 |
| `frontend/package-lock.json` | 顶层 version 和 packages[""] 的 version |
| `backend/pyproject.toml` | project.version |
| `backend/app/config.py` | Settings.app_version 默认值 |
| `CHANGELOG.md` | 日常 `[Unreleased]`，冻结时新增该版本的日期及真实变更，不把测试/候选写成上线成功 |

CI 的 `0.3.0-ci` 运行注入只标识临时测试镜像，不替代源码版本或生产身份。生产版本以回执、镜像和 `/version` 一致为准。历史 v0.3.43 是轻量标签，保持不动；附注标签规则从新版本执行，不追溯改写历史。

### 代码与数据分开

Git 管源代码、迁移、测试、锁文件、脱敏配置样例、版本记录；不管生产数据库、运行配置、图片输出、导出素材和私有发布快照。`exports/`、`local-reviews/`、`.release/`、`private_publish_snapshots/` 已加入忽略规则，只排除跟踪，不删除文件，不移动当前数据。

禁止 `git add .` 整包提交未知改动、`git add -f` 强行纳入运行数据、为清干净执行 `git clean/reset --hard`。普通新代码未跟踪仍会阻断发布，不能靠扩大 ignore 隐藏。既有 `backend/.env.test` 是精确保留的测试 fixture；不是允许其他 `.env.test` 或真实环境文件入库，秘密扫描仍执行。

导入脚本/SQL即使入Git，也不在部署时自动执行；单列数据变更范围、审批和回滚。**切换旧代码不等于数据库能直接切回**，不得用本地DB覆盖线上；新增数据后的回滚遵守第7节和当前迁移兼容计划。

### 自动检查与人工门禁

检查脚本只读，不提交、不打标签、不连接远端；回归测试仅在临时Git仓库创建测试提交/标签/归档，不修改业务仓。使用 Python 3.11+：

```bash
python3 scripts/check_version_control.py
python3 -m unittest discover -s scripts/tests -p 'test_version_control.py' -v
python3 scripts/check_version_control.py --release --tag vX.Y.Z
```

日常模式允许开发工作区有改动，但输出 `dirty=true`，校验版本位置、Unreleased和Git索引中的运行数据。发布模式额外要求干净工作区、附注版本标签指向HEAD，以及当前版本有有效日期/内容的更新记录。校验失败不会自动修复或删除文件。

core正式入口在编译MCP、创建发布包、访问Windows之前运行发布检查；保留已有远端版本单调递增、排空、备份、迁移、健康和回执校验。旧 `scripts/build_release_package.sh` 仅从通过检查的HEAD生成**源码归档**，无Linux MCP及生产身份，不能当成生产包；默认文件名为`web-source-*`，拒绝覆盖已有归档或把归档写入仓库。

若本机`python3`仍是3.9，应显式设置`PYTHON_BIN`为已有3.11+解释器；不自动修改系统Python。发布CI覆盖main推送、面向main的PR和v标签；前端类型/测试覆盖率/构建、后端应用分支覆盖>=70%、版本/秘密/发布契约检查都必须通过。前端阈值沿用现有配置，当前仅指定核心文件，不能宣传为全前端70%/75%覆盖。

需要仓库管理员单独配置的远端保护：main禁止直接/强制推送及删除、PR至少一次人工审查与状态检查；`v*`标签禁止覆盖/删除并限制创建者。**本轮只改本地CI文件，未修改GitHub规则、未运行远端CI，也未实现生产自动发布。** 状态检查通过不替代上线授权、PG演练或真实业务验收。

## 2. 组件边界

- `core`：Web 后端、AI Worker、核心前端和数据库迁移，由 `deploy-to-windows.sh` 发布。
- `hermes`：独立工作流组件，使用 `.release/hermes/current.json` 记录版本。
- Hermes 发布只能在核心回执中追加组件指针，禁止修改 `core.version`、`core.commit`、`core.imageTag`、`core.backendImageId` 等核心字段。
- 只改某个组件时只升级该组件，不得用旧核心包覆盖整个 `C:\projects\web`。

## 3. 唯一版本身份

每个核心发布由以下字段共同标识：

```text
应用版本 + Web Git commit + 发布包 SHA256 + MCP 源码 SHA256 + MCP 二进制 SHA256
```

Docker 标签格式固定为：

```text
<version>-<commit>-<package-sha256前12位>
```

例如：

```text
ztqc/backend:0.3.20-a1b2c3d4e5f6-91f2d3c4b5a6
```

禁止使用 `latest`、单独版本号或任何可被覆盖的标签作为生产运行标签。相同版本号不得再次发布；正常发布必须高于发布回执和当前运行镜像中的版本。降级只能走显式回滚流程。

## 4. 唯一发布入口

核心生产发布只能执行：

```bash
cd /Users/yyx/ztqc/web
WIN_PASS='<Windows SSH 密码>' ./deploy-to-windows.sh
```

发布脚本强制要求：

- Web 工作区无未提交或未跟踪改动。
- `HEAD` 存在与 `frontend/package.json` 版本一致的 `v<version>` 标签。
- MCP 编译目标固定为 Linux amd64，并记录源码树与二进制 SHA256。
- 发布包只从 Git `HEAD` 导出，不从当前脏工作区打包。
- 候选镜像在停服务前完成构建和 Python 编译检查。
- 同一台生产主机同一时间只允许一个发布进程；SSH 断开不代表远端发布已终止。
- 发布进程必须持有跨进程独占锁，源码快照和环境备份必须按不可变版本身份隔离。
- 停止入口前必须重新读取发布回执；构建期间若已有相同或更高版本上线，旧候选必须退出。
- 生产机必须安装 `ZTQC Production Recovery` 任务：系统启动后及每 5 分钟检查一次；
  Docker Desktop 或应用入口不可用时按可信发布回执恢复，且发布锁占用期间不得介入。
- AI、生图、Dify、小红书同步、报表和发布任务全部排空后才切换。
- 数据库迁移、健康检查、数据挂载检查与版本一致性检查全部通过。

禁止以下生产操作：

```text
tar 解压业务代码后手工 docker compose up -d --build
docker tag 新镜像覆盖旧版本标签
复制单个 backend/frontend 目录后重建同名版本
用历史源码重新 build 作为回滚
直接修改 .release/current.json 冒充发布成功
```

## 5. 发布回执

唯一核心版本真相位于：

```text
C:\projects\web\.release\current.json
```

回执至少保存：

- 应用版本、Web commit、构建时间和部署时间。
- 发布包路径与完整 SHA256。
- 不可变镜像标签、后端镜像引用与镜像 ID。
- MCP 源码 SHA256 与 Linux 二进制 SHA256。
- 发布前备份目录。

历史记录追加到 `.release/history.ndjson`，不得覆盖。发布完成前先写候选回执，只有运行容器验证通过后才能原子替换 `current.json`。

## 6. 启动与恢复

Docker 或 Windows 重启后，核心服务只能通过以下脚本恢复：

```powershell
cd C:\projects\web
.\scripts\windows\Start-Production.ps1 -Restart
```

该脚本从 `current.json` 读取固定镜像标签，把版本身份重新写入根 `.env`，使用 `--no-build` 启动后端与 AI Worker，并校验：

- 后端与 AI Worker 使用同一个镜像 ID。
- 容器版本、commit、源码指纹与回执一致。
- 镜像内置版本、commit、源码指纹与回执一致。
- MCP 源码和二进制指纹与回执一致。

校验失败时必须停止处理版本切换，不能用“服务能打开”代替版本验收。

## 7. 回滚

回滚只能使用历史发布包、对应的不可变镜像和该版本发布前备份：

```powershell
.\scripts\windows\Rollback-Release.ps1 `
  -BackupDir '<备份目录>' `
  -PackagePath '<历史发布包>' `
  -Version '<目标版本>' `
  -Commit '<目标 commit>' `
  -ConfirmRollback
```

回滚禁止重新构建历史镜像。脚本会先验证发布包与镜像源码指纹一致，缓存当前可信恢复脚本，恢复数据库后只启动已有镜像，最后重写并验证回滚回执。

上段描述通用脚本的现有动作，不代表每次回滚都能安全整库恢复。数据库已有新业务写入或此次迁移为additive时，须先验证应用兼容与保留新数据的回滚方案；未完成前不直接执行该数据库恢复路径，也不为此删除发布记录。

## 8. 紧急修复

紧急修复也必须创建新版本、commit 和标签，不能覆盖当前版本。若任务未排空，先恢复服务稳定性，待任务完成后再发布；禁止为了赶时间强制替换正在处理生图或同步任务的后端和 Worker。

任何绕过规范的临时命令都不能成为永久启动方式。确需人工救援时，只允许启动当前容器或运行 `Start-Production.ps1`，不得重建镜像。

Docker Desktop 自启动不能只依赖当前用户的注册表 `Run` 项，因为它仅在图形用户登录后执行。
Docker Desktop 启动任务必须以专用 Windows 用户、`Password` 登录类型和最高权限运行；
健康恢复任务使用 SYSTEM。密码只写入 Windows 任务计划程序凭据存储，不得写进仓库、
脚本参数默认值或日志。

## 9. 发布验收

发布结束必须同时通过：

```text
GET /version 的 version、commit 与目标一致
GET /health/ready 返回 ready
Assert-ReleaseState.ps1 返回 verified=true
后端与 AI Worker 镜像 ID 一致
PostgreSQL 与 uploads 挂载源未变化
登录、生图、任务中心、小红书同步、运营看板和投流看板冒烟通过
```

只要其中一项失败，发布状态就是失败，必须自动恢复上一版本，不能写入成功回执。

## 10. 历史生产迁移问题与当前核对

2026-09-10 检查发现，生产回执记录核心 `0.3.18 / 7b8c109`，实际后端与 AI Worker 运行的是旧镜像 `0.3.17 / 585c1782e0b0`，且 `ztqc/backend:0.3.17` 标签已被复用并指向另一镜像。

以上为2026-09-10的历史故障，不代表当前仍运行旧镜像。2026-10-10只读核对确认core和Hermes主组件均为0.3.43，主入口/回执匹配；仍有旧旁路前端及新云手机发布基础设施待补。当前差异、空间/政策/迁移/回滚阻断见[发布准备](RELEASE_PREPARATION_20261010.md)。下一次发布使用高于实际线上记录的新版本，不重新发布0.3.18或覆盖0.3.43标签。

## 11. 本轮版本治理记录

- 任务/状态：`20261010-version-management`，本地候选，未提交/推送/上线；用户要求规范后续版本管理。
- 基线：`/Users/yyx/ztqc/web`，`codex/v0.3.29-workbench-fix`，HEAD `a9aaaceec4581ece53985db0903aea18e776afb4`；原52个tracked变更及既有未跟踪代码/资料完整保留。聊天worktree另有独立修改，不混合、不搬运。
- 规范：主动重读共同流程2026-09-30，SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。风险R2（发布门禁），仅本地开发/隔离验证；无生产操作授权。
- 范围：本规范、README/AGENTS入口、CHANGELOG、Git忽略、五处版本校验/测试、CI、两个打包/部署入口及发布契约；后端仅默认版本和包元信息对齐0.3.43，未改已有发布逻辑/配置。
- 已保留历史：v0.1.0、v0.2.0、v0.3.0及后续标签仍在；本轮不改Git引用。新增能力写入Unreleased，补0.3.41~0.3.43遗漏历史，未虚构新版本上线。
- 实际验证（2026-10-10）：临时Git/打包/部署拦截回归16项通过；开发检查通过，发布检查因dirty工作区及历史轻量标签按预期拒绝；发布契约、秘密扫描、Ruff、Bash语法、CI YAML/门禁接线检查通过。独立Python3.12、临时SQLite、清凭据/代理及禁止外联的全量后端965 passed，覆盖71.00%，218.63秒；前端138 passed，指定范围语句/行94.16%、分支84.27%、函数75.92%。保留31条既有后端警告及前端工具警告，未降低门槛。
- 初轮问题：CLI测试误用本机Python3.9，改为测试解释器且给旧Python明确报错；新增归档反例发现macOS逻辑/物理路径差异，归一物理仓根后通过。不为通过测试绕过门禁。未运行远端CI、Windows镜像/PG演练、真实生成/发布；本轮无前端业务源码变化，未重复生产构建。
- 本轮文件：`.gitignore`、`.github/workflows/ci.yml`、`AGENTS.md`、`README.md`、`CHANGELOG.md`、本规范及发布准备的后续注记；`backend/pyproject.toml`、`backend/app/config.py`仅版本两行；`deploy-to-windows.sh`、`scripts/build_release_package.sh`、`scripts/check_release_contract.py`；新增` scripts/check_version_control.py`、`scripts/tests/test_version_control.py`。自审已核对新增门禁和打包调用链，无独立双人审查。
- 接续：审查候选、授权后分批提交推送并配置远端保护；本轮不替用户决定版本冻结/上线。磁盘、政策、PG迁移、新Worker等原发布阻断继续有效。
