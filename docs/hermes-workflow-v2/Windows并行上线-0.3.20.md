# Windows Hermes 并行上线 · 0.3.20

## 本次用户确认的边界

- 允许最终网页及提交接口短暂切换，不清空队列、不终止已接收的生产任务。
- 只做 Windows 数据库备份，本次豁免图片全量备份；图片目录和挂载源不变。
- 不开启每日定时生产，不启用真实发布；发布计划页面继续仅提示开发中。

## 部署结构

- 原 `web-backend-1` / `web-ai-worker-1` / PostgreSQL / Redis / MinIO 不重启。
- 新网页容器 `hermes-frontend` 在 Windows 回环端口 3101 验证；原网页 3000 也保留运行。
  最后只将现有 FRP 的 `localPort` 从 3000 改为 3101 并重启入口进程，公网地址不变。
- 新网页 0.3.20 仅将 `/api/backend/hermes-workflows/*` 和
  `/api/backend/admin/hermes-workflows/*` 转给 `hermes-api:8000`。
- 认证、素材、生图、账号同步、报表和 `/uploads/*` 仍走原 `backend:8000`。
- `hermes-api` 使用原 JWT、数据库与存储配置；独立生命周期只启动 Hermes 定时循环，
  独立数据库租约 `hermes-content-scheduler`，不启动原业务定时循环和大报表预热。
- 普通开发仍使用 `app.main:app`；线上并行部署使用 `app.scripts.hermes_api:create_app --factory`。
  **不要同时启动同版本的普通主 API 与这个旁路服务**，它们的 Hermes 调度作用域不同。
- 新 Worker 从 `hermes-api` 认领任务，文案/提示词/车型/生图接口仍从原后台读取和提交；
  状态、配置、结果、Hermes home 分别持久化到新命名卷，不依赖 Mac 常驻。
- 原有 Compose 项目仍为 `web`。将 `scripts/windows/compose.hermes-release.yml` 安装成
  Windows 项目根目录 `docker-compose.override.yml`，默认 Compose 自动合并。
  不执行旧 `Deploy-Release.ps1`：其显式 `-f` 不读取覆盖文件，且会关闭接单、重启原 Worker。

## 回滚边界

- 保留旧前端容器/镜像与原配置。回滚把 FRP 入口恢复到原 3000 端口；
  不恢复旧数据库覆盖上线后产生的任务。
- 两个迁移仅新增 Hermes 表和字段，数据库迁移应在恢复副本完成演练后执行；上线使用有界锁等待。
- 新任务开始后不得删除 Hermes 命名卷，不得直接强杀 Worker。需要回滚应先恢复旧入口，
  让已经接收的 Hermes 任务继续完成，再处理后台组件。
- 既有生产服务版本保持 0.3.18，网页/Hermes 服务为 0.3.20，是有意的并行模块发布。

## 构建来源

- Web 基线为线上提交 `7b8c1099438d2bb9ada230b9634ab049c1ec64fd`，只叠加本模块与发布适配。
- Hermes API 基础镜像必须在构建前校验 ID 为
  `sha256:e8445cb241cb217b9afdccff866ae1ead7d8ab8dcba810bf13cacd46eb24cb4c`。
  Python 依赖与线上完全一致（pyproject 仅修改版本），不替换 MCP 二进制。
- Worker 0.3.20 重标记已经验收的 `portability-test-20260908-v2`，镜像 ID 必须为
  `sha256:f6c8b7dc0acac89099a8d942f5790799ef9abcffea5fc0e37f095163370ecb7d`。
  Hermes 上游固定提交 `29112bef099274229cadff79cdff7bf7b99c4b77`。
- 不把 `.env`、生产数据库、历史成图放入发布包；运行密钥仅保存在 Windows 受限目录。

## 验收记录

实际构建、恢复、迁移、切换与真实任务结果在执行后补记。此文档不是上线成功声明。

## PostgreSQL 命名兼容修正

恢复副本演练发现 `c3d4e5f6a7b8` 中显式外键名超过 PostgreSQL 的 63 字符限制。
用户明确允许修正后，创建和删除统一使用 `op.f(...)`：SQLAlchemy 在 PostgreSQL 中生成
确定的短名称，在 SQLite 中保留原完整名称，避免破坏已经迁移过的本地数据库回退。
只处理命名，不改变列、外键关系、车型、文案、生图或业务数据。

新增 PG 方言的创建/删除同名及长度校验、SQLite 原名兼容校验；与 SQLite 全量升降迁移
合计 3 项测试通过。仍必须继续在 Windows 的真实 PostgreSQL 恢复副本完成迁移演练。

依据：[Alembic 命名操作](https://alembic.sqlalchemy.org/en/latest/naming.html)、
[SQLAlchemy 长名称截断](https://docs.sqlalchemy.org/en/20/core/constraints.html#truncation-of-long-names)。

## 已获准的对外图片地址适配

真实 Windows 验收任务 #1 已一次完成，Worker 用 Docker 内部地址下载和 OCR 正常；浏览器无法解析
`http://backend:8000/uploads/...`。用户批准后，仅在 `serialize_post` 的响应副本中映射成图及母图：
已知 `backend:8000` / `hermes-api:8000` 的 HTTP `/uploads/` 地址转换为同源路径。
不写回数据库、不变更内容或版本、不改变 Worker 下载路径，外部车型图地址保持不变。
新增 16 项边界/不变性检查，与工作流和 API 生命周期回归共 **51 项通过**。
此修复只需重建及重新加载新 Hermes API；原 API/AI Worker/网页/数据库不重启，不重新生图。
