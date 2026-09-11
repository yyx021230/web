# Web 生产版本与发布规范

更新日期：2026-09-10

## 1. 目标

生产环境中的源码、发布包、Docker 镜像、运行容器和发布回执必须能一一对应。任何人都不能通过复用旧标签、手工解压后重新构建或直接执行裸 Compose 命令，让生产环境静默回退到旧逻辑。

本规范由脚本和 CI 强制执行，不依赖人工记忆。

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

## 10. 当前生产迁移状态

2026-09-10 检查发现，生产回执记录核心 `0.3.18 / 7b8c109`，实际后端与 AI Worker 运行的是旧镜像 `0.3.17 / 585c1782e0b0`，且 `ztqc/backend:0.3.17` 标签已被复用并指向另一镜像。

本规范已经在本地代码中建立，但线上仍属于“旧发布体系”。下一次核心发布必须使用高于现有记录的新版本走唯一发布入口，生成第一份包含 `core` 和 MCP 指纹的可信回执；不得拿 `0.3.18` 版本号重新发布。
