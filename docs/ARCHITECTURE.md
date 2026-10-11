# 系统架构

本文描述当前实现。代码和运行配置是最终依据，不再包含已下线的独立模板库和在线编辑器。

## 运行组件

- `frontend/`：Next.js 15 App Router、React 18、TypeScript。`src/app/(main)/` 包含首页、AI 生图、工作台、文案、图库、数据看板和投流等页面；`src/app/admin/` 是管理后台。
- `backend/`：FastAPI、SQLAlchemy、Alembic。`app/api/v1/router.py` 汇集认证、素材、生图、Dify/Hermes 工作流、车型、文案、提示词、小红书和管理接口。
- PostgreSQL：业务数据与任务记录；Redis：后台任务队列及运行状态。生产环境由 `docker-compose.yml` 配置。
- `ai-worker` 和 `ai-postprocess-worker`：分别执行异步生图和图片后处理。只启动 API 不启动 Worker，任务可能一直排队。
- 存储：本地上传目录与对象存储能力按环境配置。图库、参考图和生成结果不能只依赖前端临时文件。
- Hermes：内容工作流有独立发布配置 `scripts/windows/compose.hermes-release.yml`；其前端 API 转发目标可通过 `HERMES_BACKEND_ORIGIN` 与主后端区分。

## 请求与数据流

前端通过 `frontend/next.config.mjs` 将 `/api/backend/:path*` 转发到 FastAPI `/api/v1/:path*`；Hermes 路由优先转发到 Hermes 后端。前端的 `src/services/` 封装业务 API，页面和组件按功能组织。全局色彩在 `src/styles/globals.css`，侧栏和工作区在 `src/components/navigation/workspace-shell.module.css`。

生图使用异步任务流程：

1. 已登录用户调用 `POST /api/v1/ai-image/generate`，服务端返回 `202` 和任务信息。
2. 生图 Worker 从队列处理任务，经 `backend/app/adapters/ai_model/` 中已注册的模型适配器调用上游。
3. 后处理 Worker 处理需要的图片后处理；前端通过任务查询接口获取排队、生成、完成或失败状态，并恢复结果。
4. `POST /api/v1/ai-image/prompt-tools/*` 是提示词辅助接口，不应与生图任务队列混淆。

工作台同时有 Dify 工作流接口和 Hermes 内容工作流接口；两者不是同一个服务实现。小红书同步、账户数据和看板的 API 由后端相应服务负责，修改统计口径时应同时检查数据写入、聚合、权限筛选与前端展示。

### 浏览器登录会话（2026-10-10 本地候选，默认关闭）

`AUTH_BROWSER_SESSIONS_ENABLED` 显式启用新浏览器会话。前端同源 `/api/auth-session/*` 代理到主后端 `/api/v1/auth/session/*`，访问 Token 仅驻留内存，刷新 Cookie 为 HttpOnly、SameSite=Strict，公网必须 HTTPS。`auth_sessions` 存储会话、刷新凭证摘要和使用时间；JWT 的可选 `sid` 关联服务端记录，普通鉴权只读，不写活跃时间。

默认访问 Token 30 分钟、连续3天无前台人工活动失效、绝对30天重新登录；轮询和刷新本身不延长闲置期限。前端续期合并、跨标签 Web Locks、服务端 CAS 和30秒有界幂等处理并发及丢响应。认证失败只允许安全读请求重试，生图/审核/发布等写请求不自动重放；同账号弹窗重登保留主工作区已挂载草稿，生图查询恢复原任务而非新建任务。网络/5xx不清身份，禁用账号、改密、退出与管理员撤销使关联会话失效。

旧 `/auth/login` 的脚本/API Token 仍保留原24小时契约，不享有新会话的即时撤销/闲置规则；Worker、云手机和模型密钥不改变。开启前必须先迁移至 `e61010a0b001`，核对主后端与 Hermes 同一认证库、JWT 密钥和新鉴权代码，配置精确 `AUTH_SESSION_ORIGINS`。测试证据、兼容限制与回滚见 [登录会话任务卡](BROWSER_SESSION_20261010.md)。

### 云手机发布（2026-10-08 本地候选，未部署）

2026-10-10新增自主上传入口（本地候选）：`POST /api/v1/hermes-workflows/upload-post`接收multipart图片和metadata，不调用模型、不自动审核或发布。复用`hermes_workflow_runs/posts`，来源标记`user_upload`；多图有序URL写入帖子JSON，文件写现有存储，发布计划固定全部图片快照。草稿在发布页恢复，不混入AI创作列表。仍需原账户人工确认后排期，执行由同一独立发布Worker控制，不新增数据库表或另开发布队列。

Hermes 排期通过 `hermes_publish_jobs` 和 `hermes_publish_attempts` 固定审核内容、账号、配图摘要与发布尝试。独立进程 `python -m app.scripts.phone_cloud_publish_worker` 使用独立 DB 领导租约，与生图 Worker、原云登发布队列分离；API 本身不会启动它。实际下发默认关闭，不重放旧排期。

现有 Phone Cloud 用户发布 API 缺少远端幂等、按 ID 单查和实际登录身份核验。Web 因此按稳定小红书 ID 精确匹配设备/槽位，仅允许人工核验 ID 白名单；下发结果不明进入 `unknown`，禁止自动重发。按用户 2026-10-10 确认的状态口径，云手机 `succeeded` 直接映射为兼容状态 `submitted`，界面显示“云手机发布成功”；失败/超时映射为失败，取消映射为已取消。该成功表示云手机执行成功，不表示小红书审核通过或公开可见。私有图片快照必须独立持久化，不能放进公开 uploads。配置、接口、测试与上线前缺口见 [接入任务卡](CLOUD_PHONE_PUBLISH_INTEGRATION_20261008.md)。

2026-10-09 跨仓安全候选包含 `expectedXhsId`、执行器身份/文案回读和最终点击最多一次；此候选未整体上线。2026-10-10 按用户明确要求，撤销 Web 本地新增的账号/标题/正文证据终态门槛：不再写入新快照的 `publish_proof_required`；旧字段继续兼容但不影响状态，返回的脱敏证明仅供审计，缺失或冲突不覆盖云手机的成功状态。本轮未修改或部署云端/Agent，也未移除 Web 的发布前审核版本、账号绑定和禁止未知结果自动重发保护；远端持久幂等/按 ID 查询、目标图片身份和顺序核验仍未完成。

## 扩展与发布

### 云手机账号登记补充（2026-10-11 本地候选）

云手机独立账号复用 `xhs_environments` 的创作账号记录，以 `phone-cloud:<稳定小红书ID>` 明确标识来源，不伪造云登环境 ID；`is_phone_cloud` 为计算属性，没有新增表或字段。实际云登身份已存在时优先复用，重复身份和其他用户归属冲突需人工解决，不能抢占。独立登记脚本先检查发布白名单及云手机唯一设备/槽位，再事务写入账号和 `user_xhs_environments` 归属，不创建发布任务。

Hermes 直接读取已分配账号，因此可以使用此类账号创作、审核和排期。云登环境列表、浏览器状态、采集执行环境和创作中心定时同步仅包含浏览器账号；云登远端缺失检测不会将云手机账号停用，直接请求启动/停止其浏览器也会拒绝。

管理员手动创建任务可显式设置 `use_existing_policy=true`；服务端保存操作者及确认时间，生成 Worker 仅对该任务使用既有政策，正常任务的政策同步/过期检查不变。不改政策日期或价格，指令保留原有效期并禁止描述成当前有效；实际发布前仍需审核生成文案，不能用该参数保证模型不会写错。当前尚未部署此补充，也未登记生产102。

## 扩展约定

- 新增生图模型时，实现 `backend/app/adapters/ai_model/base.py` 中的接口，在 `backend/app/adapters/ai_model/__init__.py` 注册，并补充任务链路测试。目录中的文件本身不会自动启用模型。
- 数据库结构变化必须使用 Alembic 迁移；不要以本地 SQLite 代替生产 PostgreSQL 验证迁移。
- 发布前执行前端类型检查、测试、构建及相关后端测试。Windows 正式发布、备份、回滚以 `docs/V0.3_RELEASE_RUNBOOK.md` 和实际部署脚本为准，不直接覆盖线上数据卷或密钥。
- 认证、用户数据隔离和共享规则参见 `docs/DATA_ISOLATION.md`。
