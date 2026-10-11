# 云手机发布接入任务卡

- 日期：2026-10-08；状态：本地候选，待真机/PG 验收，未部署。
- 授权：本地开发与隔离/mock 测试；不访问真实设备、不真实发布、不迁移业务数据库。
- 风险：R2（鉴权、权限、迁移、后台调度）；真实发布与上线另需 R3 授权。
- 共同规范：2026-09-30，SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`，本轮已重读。
- Web 基线：`a9aaaceec4581ece53985db0903aea18e776afb4`，`codex/v0.3.29-workbench-fix`；既有提示词/图库/侧栏/旧模块下线等修改不动。
- 拟动范围：Hermes 排期页面/API/服务、发布模型/迁移、新适配器/Worker/测试；不改生图、旧云登发布、Phone Cloud Agent、投屏/ADB。
- 原文件 SHA256：config `dd8bf46bdae460b2e30f3d3dba75c8db105626f5b51157c33916a7e103d278f3`；Hermes service `86481c19471430a4b3b4371bbc9b2bf958c0e343e6d33d3d22d3ed487a2b04c0`；planner `f8e25d27bba70922a56fcf84d68f7a6527f17634ff057668f3174e84c0d5646c`。拟动已有文件开始时无 Git 修改。

## 接入契约

只接现有用户接口：`POST /api/v1/auth/login`、`GET /api/v1/user/devices`、`POST/GET /api/v1/user/automation/xhs-publish-tasks`、`POST .../{jobId}/cancel`。服务端专用普通用户，Token 不传前端；稳定小红书 ID 精确匹配设备/槽位，无昵称回退。

当前创建接口不幂等、列表仅最近 100 条、无单查/回调/帖子 ID，配置槽位不等于实际登录账号。Web 不能假装已补齐远端能力：提交前持久化 submitting；响应丢失标 unknown，不自动重发；查不到已受理任务标 unknown；succeeded 标 submitted（待核验），不标 published。默认不下发，启用后仍只允许人工核验过身份的 ID 白名单。

## 验收与实施

1. 审核版本/账号/图片固定快照，独立持久化发布单及尝试记录；图片复制到非公开快照目录。
2. 排期保存、改期、取消、查看状态；普通用户仅自身内容与仍授权的账号。
3. 独立 Worker、DB CAS 领取、设备锁、忙碌退避、重启恢复；不占用生图队列。
4. Mock 验证鉴权刷新、精确账号匹配、素材限制、重复/超时/取消/迟到/失去权限、跨用户隔离。
5. 类型检查、前端交互、Hermes 后端回归、临时 SQLite 迁移；生产 PG、真机、线上配置待授权验收。

## 发布与回滚边界

仅新增表，不迁移/重放旧排期，不自动发布历史内容。先迁移与 API，再启动默认关闭的独立 Worker。旧应用可忽略新表；回滚关闭/停止发布 Worker，保留发布记录，不能删除 unknown/submitted 记录或直接重发。

### 配置及启动（待授权执行，不是本轮操作回执）

| 环境变量 | 默认/用途 |
|---|---|
| `PHONE_CLOUD_PUBLISH_ENABLED` | `false`；实际下发总开关，停止下发不等于撤回已受理任务 |
| `PHONE_CLOUD_PUBLISH_BASE_URL` | 空；管理员提供的 HTTPS 根地址，不复用短信管理员凭据 |
| `PHONE_CLOUD_PUBLISH_HTTP_ORIGINS` | 空；2026-10-08 新增显式 HTTP 根来源白名单，只有运营者明确批准的精确来源可使用 HTTP；不关闭 HTTPS 校验、不自动降级、不跟随重定向 |
| `PHONE_CLOUD_PUBLISH_USERNAME` / `PHONE_CLOUD_PUBLISH_PASSWORD` | 空；平台专用普通用户，服务端 Token 过期/401 后重新登录，不送浏览器 |
| `PHONE_CLOUD_PUBLISH_VERIFIED_XHS_IDS` | 空；逗号分隔，须在真实 App 上核验登录身份；配置昵称不算核验 |
| `PHONE_CLOUD_PUBLISH_IMAGE_ORIGINS` | 空；外部配图 HTTPS 来源精确白名单，仅授信运营方控制的主机；不跟随重定向 |
| `PHONE_CLOUD_PUBLISH_SNAPSHOT_PATH` | `./private_publish_snapshots`；API 和 Worker 必须访问同一持久化私有目录，并纳入备份；不能在 uploads 内 |
| `PHONE_CLOUD_PUBLISH_MAX_IMAGES` | `5`，允许配置 1–9；AI生产每篇仍一张配图，2026-10-10自主上传入口按此上限支持有序多图，不改变AI生产编辑功能 |
| `PHONE_CLOUD_PUBLISH_MAX_LATENESS_SECONDS` | `1800`；排期过期太久时停止，不能把数日前排期突然发布 |
| `PHONE_CLOUD_PUBLISH_MAX_OBSERVE_SECONDS` | `1800`；从提交租约结束点计算等待预算，超时进 unknown，不重建任务 |

迁移链为 `c47f2a6d9b10 -> d5a8c2e7f901`。仅隔离验证后、获准上线时运行 `alembic upgrade head`，再切换新 API/前端。启动入口为后端目录下 `python -m app.scripts.phone_cloud_publish_worker`；本轮没有自动加入 Compose、没有启动真实 Worker。

### Web 接口与使用

- 保存：`POST /api/v1/hermes-workflows/publish-plan`，`items` 最多 40 篇，每项带 `post_id`、原审核账号 `environment_id`、`scheduled_at`、`expected_version`。无时区按北京时间，有时区先转北京时间；换目标账号须重做审核。
- 记录：`GET /api/v1/hermes-workflows/publish-jobs?page=1&limit=40`；普通用户仅自己的发布单。管理员同名接口位于 `/api/v1/admin/hermes-workflows/`，沿用 require_admin，不新增应用权限规则。
- 取消：`POST /api/v1/hermes-workflows/publish-jobs/{id}/cancel`；未下发可取消，下发中/手机执行中只请求取消，不承诺撤稿。
- 页面：`/workflows/hermes/publish`。勾选已审核内容、填写时间、确认保存；每 5 秒在可见页面读取发布记录。提交状态/unknown 禁止再次勾选排期，保存失败不清空输入也不自动重试 POST。
- 内容修改/重新审核会取消未执行的排期；执行中、unknown、submitted 锁住内容。保存响应丢失后，完全相同的排期重试是本地幂等的，不会创建第二个发布单。
- 同手机预检查串行，不同手机可分别排队执行；创建时 Phone Cloud 的物理设备锁是最终权威，Web 预检查不等于远端排他预约。
- 查询结果没有变化时不重复写业务表；执行尝试保留素材摘要、目标槽位、错误码。已知 ID 的超时/列表缺失单保留 24 小时迟到回查窗口（每批至多 200 条），之后仍保留记录交人工核查，不自动补发。

### 上线前待办/限制

1. 在获准的隔离 PostgreSQL 演练真实基线升级、旧版本兼容、行数/锁时长/恢复。SQLite 和 PostgreSQL DDL 编译不是生产迁移通过。
2. 配置专用普通用户及已核验的小红书 ID/设备槽位，检查可信配图域名、私有快照卷共享/备份。现有审核只有图片 URL，本轮固定的是保存排期时读取的图片 bytes，要求审核图 URL 不被原地覆盖；不宣称远端实际身份已自动核验。
3. 先一个获准账号、设备和内容做受控真实发布，再双设备验收；需单独授权内容、次数、停止条件。当前没有真机/线上证据，也未在真实浏览器验收新页面。
4. `unknown/submitted` 当前只能查看并对账，尚无“人工核验确认/解除后重发”按钮；不能用直接改库绕过锁。正式完成闭环需补人工对账能力，或升级 Phone Cloud 幂等/单查/帖子事实协议。
5. Phone Cloud API 本轮按本地文档/源码核对，实际部署版本待核实。响应丢失但没有 jobId 时不能按标题自行认领任务。远端 failed/expired/cancelled 也按 unknown 处理，禁止自动重试。
6. 发布前全量后端覆盖率、前端覆盖率及正式发布门禁仍需执行；本轮相关回归不是发布豁免。

## 验证回执

使用独立 Python 3.12.13 测试环境 `/private/tmp/ztqc-publish-test-20261008`，沿用 pyproject 依赖；没有替换现有 Python 3.9 venv、更新锁文件或迁移业务 DB。Node v25.9.0。

- 后端命令：`python -m pytest -q tests/test_cloud_phone_publish.py tests/test_hermes_workflows.py tests/test_hermes_api_lifecycle.py tests/test_hermes_image_urls.py tests/test_scheduler_leader.py tests/test_fresh_database_migration.py tests/test_hermes_postgres_migration_names.py tests/test_ai_image_count_integrity.py --tb=short --show-capture=no`。最终 **140 项通过**；覆盖真实 Web ASGI 保存/权限/状态接口 + HTTP MockTransport 云手机鉴权/下发/查询，未访问外部服务。新发布专项还包括 PostgreSQL DDL 编译，仅是静态验证。
- 前端：`npm run type-check` 通过；`npm test` 14 文件、136 项通过（排期 12 项）；`npm run build` 在不含 `.env*` 的临时前端副本通过，34 页，未写运行中的 `.next`。
- 迁移图检查：单头 `d5a8c2e7f901`。临时 SQLite 空库全量升降/重升、旧头增量升级/退回通过；未迁移本地业务库或线上库。
- 自审：核对精确账号/槽位、服务端鉴权、用户隔离、内容锁/CAS、双 Worker、取消/迟到/断线不重发、摘要保留、默认关闭及新表 additive。修复初轮迁移双头、保存后异步属性过期，以及回归测试没有真正保存排期的问题；没有用失败的初轮结果当通过证据。
- 非阻塞警告：passlib crypt 弃用、Vite CJS 提示、Browserslist 数据较旧；本轮不升级依赖。
- 保留既有提示词/图库/侧栏/旧模块下线等修改。未修改 Phone Cloud 仓/Agent、未部署、未提交/推送、未发出真实发布任务。上述上线待办不因 mock 通过而取消。

## 本轮文件与交接

- 新增：`backend/app/models/hermes_publish.py`、`backend/app/alembic/versions/d5a8c2e7f901_cloud_phone_publish_jobs.py`、`backend/app/adapters/phone_cloud_publish.py`、`backend/app/services/hermes_publish_service.py`、`backend/app/scripts/phone_cloud_publish_worker.py`、`backend/tests/test_cloud_phone_publish.py` 和本任务卡。
- 修改：`backend/app/config.py`、`backend/app/models/__init__.py`、两个 Hermes API 文件、`backend/app/services/hermes_workflow_service.py`、`backend/tests/test_hermes_workflows.py`、`backend/tests/test_fresh_database_migration.py`；前端 `HermesPublishPlanner.tsx`、对应测试、`hermesWorkflowApi.ts`；架构文档仅补候选说明，保留其原有修改。
- 失败/未验证：本轮最终选定回归无失败；初轮失败已修复并重跑。真实云手机发布、生产部署版本、真实浏览器观感、真实 PG 演练及全量发布覆盖率仍未验证。人工对账处置入口未实现，不能声称完整公开发布闭环已验收。
- 接续：先验收本地候选和专用账号/私有卷配置，再申请明确真机测试范围；PG、真实账号和发布门禁通过后才能申请上线。不得从整个脏工作区直接打包部署。

## 102 号真机验收前置检查（2026-10-08）

- 本轮用户新增授权：用 102 号手机的测试账户实际走生成、审核、排期和发布。按最小范围限定一篇新内容、一张配图、一次发布；结果不明不重复下发。此授权不包含生产迁移、部署、共享服务重启、Phone Cloud Agent 改动或其他账号操作。
- 共同规范已主动重读，修订日期/哈希未变；既有候选及其他工作区修改保留。本轮仅补此回执，没有修改业务代码、设备配置或业务数据库。
- 本轮实际验证：使用现有短信管理员配置进行只读认证和设备列表查询，均 HTTP 200。102 号稳定设备 ID 为 `adb:10AF1D0CNM0091C`，listed、在线、available、busy=false；app1 配置为“测试账号”，小红书 ID `9559989255667`，槽位无占用。设备配置不构成实际 App 登录身份的证据，身份核验仍未完成。
- 发布前置失败：当前平台 HTTP 地址可响应，但对应 HTTPS 的系统证书校验报 self-signed certificate；未关闭 TLS 校验，也未自动接受浏览器证书警告。本地发布专用普通用户配置为空，未把短信管理员凭据改作发布凭据。
- 生成前置未满足：本地未找到 Hermes Worker 所需的 `INTERNAL_RELAY_API_KEY` 及其完整生产运行配置；已有 Web 生图/提示词助手密钥不被擅自替换为 Hermes 内部中转凭据。生产来源素材、当前政策及真实生成仍待配置后验收。
- 运行边界：未启动真实生成/发布 Worker，未创建远端发布任务，没有新增测试帖子；文案、配图、审核、排期、最终帖子事实均不能记为通过。既有本地 mock 验证不能代替本次真机验收。
- 接续缺口：取得已有可信 HTTPS/受信任证书配置、发布专用账号及 Hermes 生产运行配置的位置；核验实际登录身份后，在隔离本地数据库中启动一篇受控全链路。此时再记录 run/post/publish/远端任务 ID、耗时及最终帖子证据。

### 用户确认 HTTP 与配置后的追加回执

- 用户明确表示本次不需要 HTTPS 证书，并要求配置发布账号；提供模型中转根地址 `http://47.98.127.132:48731/v1` 与 `gpt-5.5`，但没有提供 API Key。前述 HTTPS/专用账号缺口是上一阶段状态，不再作为本次待办。
- 本轮最小代码变更：`backend/app/config.py` 新增默认空的 HTTP 根来源白名单，`backend/app/adapters/phone_cloud_publish.py` 仅对该白名单精确来源放行 HTTP，`backend/tests/test_cloud_phone_publish.py` 补充 9 个场景；其余既有修改保留。没有将任意 HTTP 全局放行，也未使用 `verify=False`。
- 真实账号配置：创建 `web-publish-102-test`，角色 user（非 admin），平台返回 HTTP 201，用户 ID `e99fe715-9a3b-41dd-bab9-c8f3dd7f5342`；普通用户登录和设备查询 HTTP 200。沿用平台现有普通用户权限，未修改权限规则；本次 Web 测试范围仍只允许 102 号。
- 凭据自动生成并保存在 Git 已忽略的 `backend/.env.publish-test-20261008`，权限 `0600`；未写入代码、文档或日志。该文件不是默认 `.env`，仅测试进程显式加载；实际发布总开关保持 false，账号身份核验白名单保持空，不能因此自动发布历史内容。
- 本轮实际验证：真实 Web `PhoneCloudPublisher.devices()` 成功，精确解析 `9559989255667 -> adb:10AF1D0CNM0091C / app1`。浏览器使用专用账号登录平台成功，并为 102 号建立一次核验投屏；当前画面出现“零跑情报员”名称，但未完成实际小红书 ID 核验，不能仅凭昵称启用发布。控制会话已结束，API 确认 available=true、busy=false、busyReasons=[]；没有操作其他手机、改 Phone Cloud Agent 或重启 ADB。
- 模型证据：Hermes 当前 `copy_model`、`image_plan_model` 已是 `gpt-5.5`；该中转 `/v1/models` 无凭据访问返回 HTTP 401。本机 Codex 的 API Key 字段为空；已有提示词助手属于另一个提供商，未将其凭据发送到此中转，亦未读取或挪用 Codex OAuth token。用户提供的 `wire_api=responses` 不自动证明当前 Hermes 的 chat/completions 契约被中转支持，拿到密钥后需真实核对。
- 验证命令：独立 Python 3.12 环境运行 `python -m pytest -q tests/test_cloud_phone_publish.py tests/test_hermes_api_lifecycle.py tests/test_hermes_workflows.py --tb=short --show-capture=no`，85 passed，24.19 秒；仍有 passlib crypt 弃用警告。隔离回归不等于真机发布成功。
- 剩余与状态：等待用户指定该中转 API Key 的现有文件/环境变量位置，随后验证模型契约、实际 App 身份及一篇完整生成/审核/排期/发布。真实生成及远端发布任务数仍为 0；没有业务数据库迁移、线上代码部署、提交/推送。本轮状态为本地候选、真机全链路待验收。

### 收到密钥后的真实生成与发布素材验收

- 本轮用户提供内部中转密钥，已写入上述 Git 忽略、0600 的测试配置；未回显或写进文档/代码。实际 `/v1/models` HTTP 200，列出 `gpt-5.5`；最小 `/v1/chat/completions` 调用 HTTP 200，约 2.3 秒，确认 Hermes 当前调用契约可用。线上来源 Token 首次返回 401，使用已获授权的管理员登录接口刷新后成功，仅更新私有测试配置。
- 实际来源自检通过：2054 条文案（本次类型可用 7 条）、748 条内部提示词（安全可用 376 条）、2907 条车型术语、A05 图库 10 张。没有用外部素材或反推提示词代替这些库。
- 使用临时 SQLite `/private/tmp/ztqc-102-e2e-20261008/acceptance.db`，隔离普通用户和环境 `91021008`；通过真实 Web ASGI 接口创建并领取 run `1`，完成实际 Hermes 图文生产，再通过完成接口入库 post `1`。真实生图任务为 `36897`，只生成一篇、一张图。文案母本 `596`、内部提示词 `90`；文案 42.365 秒，图像规划 19.315 秒，生图 48.868 秒，整个生产 121.82 秒。交付 production_ready=true、OCR 无硬错误。
- 产物标题为「零跑A05看车前测试」。正文和图片只涉及看车前观察问题，明确测试属性；没有价格、促销、配置或试驾结论。既有政策截至 9 月 30 日，未绕过过期校验，使用单独的中性测试 case 和既有 `--cases`/`--no-policy-sync` 入口。
- 实际检查图文后，调用普通用户审核接口 approve，HTTP 200；这是代理检查并提交测试审核，不是用户本人在新页面完成手动审核。创建时首次显式 hero 参数因隔离库缺少参考记录返回 400，改用已有自动选取后通过，未将失败请求记为通过。
- 历史去重未验收：生产 Web 未找到该测试账号对应环境，隔离测试来源仅对 `91021008` 返回空历史，并明确记录未验证近 7 天去重；真实库、模型及图片调用未 mock。新排期页面的浏览器交互、真实 PG 迁移仍未测试。
- 真机身份证据：102 号 App 主页显示「零跑情报员」，小红书 ID `95998925567`；平台 app1 配置却是 `9559989255667`。投屏截图保存在 `/private/tmp/ztqc-102-identity.jpg`，放大 ID 截图 `/private/tmp/ztqc-102-identity-id.png`。已向用户确认是否修正映射并以当前 App 账号测试；确认前不改平台配置、不加入身份白名单、不下发发布。
- 本轮实际发现并修复发布素材上限问题：生成 PNG 为 3,328,285 bytes，超过 Phone Cloud 3,000,000 bytes 限制；发布快照使用 lossless WebP 后为 2,390,446 bytes，解码尺寸与 RGB 像素逐字节相同。原图不覆盖，不裁切、不缩放、不有损压缩；源 SHA256 `bb1699c59108a70eba844f94bfa7101993c644905ffeabd74a16e9abf0881434`、发送快照 SHA256 `1883bdc0c03a8dbea30f4a919595ffbfd3dcc22d4d10bfc5fc1fb42adf00c399` 均保留。
- 最小新增变更仅为 `backend/app/adapters/phone_cloud_publish.py`、`backend/tests/test_cloud_phone_publish.py` 和本回执：来源读取上限 25MB，发送仍 3MB；仅静态 RGB/RGBA PNG、最多 800 万像素可尝试无损编码，保留 ICC/Exif，验证解码像素相同。小图不重编码；无法无损满足限制、大像素、非支持格式或非法内容拒绝下发，没有有损回退。
- 最新实际回归：独立 Python 3.12 运行 `python -m pytest -q tests/test_cloud_phone_publish.py tests/test_hermes_api_lifecycle.py tests/test_hermes_workflows.py tests/test_hermes_image_urls.py --tb=short --show-capture=no`，**110 passed，9.56 秒**；包括真实无损编码、全透明/半透明/不透明像素保留、不可压缩拒绝、源图保留、快照下发 MIME 和像素边界。仍有 passlib crypt 弃用警告。上述回归和素材准备不是手机发布成功证据。
- 再次实际查询平台：102 available=true、busy=false、busyReasons=[]；专用用户发布任务为 0。核验控制会话已结束，没有遗留生成/发布常驻 Worker，没有发出远端发布单。实际排期、手机发布和最终帖子事实未完成，不能声称全链路已通过。
- 可接续产物在 `/private/tmp/ztqc-102-e2e-20261008/output/2026-10-08/`（交付 HTML、delivery、checkpoint、生成图）；测试状态与审核记录在同一临时根目录。确认正确账号后复用 run/post/图片，继续排期并下发一次；不重新生成或重复发布。临时目录不是长期备份。
- 本轮保留所有既有未提交改动；未修改 Phone Cloud 仓/Agent，未迁移业务数据库、部署代码、重启共享服务、提交或推送。状态仍为本地候选、真机全链路待验收。

### 用户确认修正映射后的单篇真实发布回执

- 用户明确要求「修正然后审核通过，然后发布」。本轮仅授权 102/app1 的映射修正及上一阶段生成的单篇内容；不扩展为新版本代码部署、其他手机操作或更多内容发布。共同规范已重读，2026-09-30 及 SHA256 未变；上述既有修改保留。
- 平台原账号配置备份在 `/private/tmp/ztqc-102-e2e-20261008/102-account-mapping-before.json`，权限 0600。使用管理员 `PUT /api/v1/devices/{deviceId}/xhs-accounts` 将 102/app1 小红书 ID 从 `9559989255667` 修正为 `95998925567`，HTTP 200；其他字段和 app2 保持原值。普通发布账号重新查询后精确、唯一解析到 `adb:10AF1D0CNM0091C / app1`。
- 只同步修正临时验收库的环境 `91021008`；确认 post `1` 的已审核状态、原题文和版本，不重复生成。通过真实普通用户 Web ASGI `POST /publish-plan` 保存一条排期，HTTP 200，job `1`，北京时间 `2026-10-08 18:14:26.635874`。发布开关和核验 ID 只在隔离测试进程内启用；默认配置仍关闭且白名单空，未启动常驻发布 Worker。
- 单次 Web Worker tick 在排期到期后固定图片快照、审核版本、账号身份，保存 submitting 尝试再创建远端任务。专用普通用户仅创建 **1** 条任务：`fb8f63e0-f2ca-4cfe-93b4-d022093ae153`。后续仅查原任务，不再调用创建或重试。远端创建 `18:14:50.224`、领取 `18:14:54.770`、完成 `18:15:36.542`（北京时间），受理到完成 46.318 秒，返回 `succeeded`、runner exitCode=0。
- 实际 Agent 日志含 `open_publish_entry`、`open_publish_album`、`select_publish_image`、`set_publish_title`、`set_publish_content`、`click_final_publish`、`publish_confirmed`；执行模式 `windows_airtest_poco`，结果文案「已点击发布并确认发布结果」。Web 原发布单经真实 poll 转为 `submitted`，禁止再次排期；没有伪造 published 状态或改库解除内容锁。
- 平台完成后在 102 建立一次核验控制会话，实际打开新帖「零跑A05看车前测试」，核对作者「零跑情报员」、配图、完整正文和原生话题；页面标记「公开可见」。截图 `/private/tmp/ztqc-102-published.png`（图文顶部）、`/private/tmp/ztqc-102-published-body.png`（完整正文）。已验证本账号 App 中存在真实新帖；未用另一外部账号核验公开访问，也未取得稳定 note ID，因此不将该证据扩大成公开审核/跨账号可见的保证。
- 核验控制已结束；虽然结束操作的浏览器工具等待超时，随后的真实 API 确认 102 available=true、busy=false、busyReasons=[]，发布任务总数仍为 1。没有重复结束/重发、没有设备重启、Agent/ADB/媒体改动或遗留常驻 Worker。
- 本轮文件：仅扩展私有临时验收脚本/状态和本任务记录，并在 Phone Cloud 主文档补配置与验收回执；没有新增业务代码变更、依赖变更、业务数据库迁移或 Web/Phone Cloud 代码部署。既有未提交改动完整保留，未提交/推送。
- 验收结论：单篇「真实生成 → 测试审核 → Web 排期 → 独立 Worker → 102 真机发布 → App 实帖核查」完成。此前 110 项回归为上一阶段实际结果，本轮未将其重新计为新执行。候选功能仍未上线；新工作台浏览器交互、真实 PostgreSQL 迁移、多设备并发和人工对账入口仍待后续验收，不能用此次单设备成功豁免正式发布门禁。

### 2026-10-09 本地手动测试服务启动

- 用户要求启动本地服务并自行测试流程。本轮无业务代码修改、线上部署或生产数据库操作；共同规范哈希仍为 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`，既有工作区修改保留。
- 前端 `http://127.0.0.1:3000`、API `http://127.0.0.1:8000`；Python 3.12 使用上一轮隔离运行环境。操作脚本 `/private/tmp/ztqc_web_manual_20261009.py`，测试根目录 `/private/tmp/ztqc-web-manual-20261009`。使用本地 dev.db/uploads 的独立 copy-on-write 副本；仅副本迁移 `c47f2a6d9b10 -> d5a8c2e7f901`，原库不迁移。
- 隔离库新增普通测试用户 `local102`（密码保存在 0600 runtime.json，不写入本文），只分配环境 `91021009 / 102测试账号 / 95998925567`。A05 图库元数据通过已授权线上只读接口补入副本，共 10 张 OSS 图，不改线上数据。测试 case 沿用中性 A05 内容边界，不使用过期销售政策、不绕过日期校验。
- 启动 API、AI Worker、去水印 Worker、Hermes Worker 和独立发布 Worker；测试进程移除终端代理影响，Redis 使用独立 `local-manual-20261009:` 队列前缀，Hermes 输出用新的专用目录。仅在测试 API 进程内禁用定时循环和看板预热；未修改应用默认调度逻辑。没有旧未完成 AI/Hermes 任务，新增发布表为 0 行，不重放历史排期。
- 测试发布进程只启用已核验的 102/app1 ID 白名单。用户在本地 UI 审核并确认新排期后会真实发布至该手机；启动和只读验证本身没有提交新内容。全局 .env.publish-test-20261008 仍保持默认关闭，不启用其他账号。
- 实际 HTTP 200：健康/就绪、登录/当前用户、bootstrap、reference-types、run 列表、publish-jobs、A05 图片、AI models；前端同源登录及工作流代理验证通过。工作台、批量、单篇、发布和 AI 页面 HTTP 200；Hermes 心跳和发布 Worker 租约更新正常。最初临时脚本模型导入路径和环境标识错误已修正并重新启动；探测不存在的 review/providers 路径返回 404，已核对实际审核在创作组件内、模型接口为 `/ai-image/models`，没有为错误探测修改业务路由。
- 真实只读生产前检查 `preflight` 通过：Hermes Python 3.11.15、Apple Vision OCR、relay models 含 gpt-5.5、本地鉴权、557 条文案（当前默认条件可用 1 条）、109 条内部提示词（中性 case 安全可用 8 条）、2900 条车型术语和 A05 10 张图。此次 model_calls=0、image_tasks_submitted=0；推荐从单篇页面生成 1 篇。原本地素材库较旧，不将单篇预检扩大为所有类型/多篇生产能力通过。
- 本轮仅更新本任务记录及私有临时运行脚本/副本；未执行新的生图、远端发布、浏览器人工审核、多设备或 PG 验收。用户接下来从 `/workflows/hermes/single` 完成自己的手动全流程；临时目录不是长期备份。进程启动命令为上述 Python 3.12 调用临时脚本的 `api / ai_worker / ai_postprocess_worker / hermes / phone_cloud_publish_worker`，前端覆盖两个 backend origin 为本地并用 `NEXT_PUBLIC_API_URL=/api/backend` 启动 npm dev；不能直接把此测试命令当作生产启动方式。

### 2026-10-09 单篇 run 11 缺交付文件排查与本地修复

- 用户手动选择 `product_features / cards / replica`，本地 run `11` 在选素材阶段退出。真实日志 `/private/tmp/ztqc-web-manual-20261009/hermes-output/run-11/worker.log` 最后一行是「文案类型 product_features 可用母文不足：0条；未调用生成接口」，并非生成模型或手机发布失败。前一轮仅自动类型单篇预检通过，不能代表任意用户类型通过；本地旧文案 557 条、内部提示词 109 条，与当前线上库不一致。
- 本轮只读查询当前来源：线上文案 2054 条，现有严格校验可用 1731 条，其中配置亮点 23 条；公开内部提示词 748 条，中性 case 安全池 376 条，其中 cards 5 条。保留精确类型选择和现有准入校验，不回退为其他类型、不编写伪造母文。
- 操作脚本 `/private/tmp/ztqc_manual_materials_20261009.py` 仅把上述所选类型的 23 条母文及 5 组已公开内部提示词/图补入隔离测试库；按内容或稳定来源键去重，新本地 ID，不覆盖既有记录，不读取或导入其他用户私有提示词，不改线上或原 dev.db。提示词保留原提示词与图的对应关系及线上图片来源，不反推提示词。导入清单 `product-features-cards-import.json` 为 0600；导入前 SQLite backup `before-selected-materials.db` 已核对文案 563、提示词 1543，导入后 586、1548，均包含既有软删除记录。
- 最小代码修复 `ops/xhs_hermes/web_worker.py`：缺 manifest 时有限读取最后 16KB 日志，仅识别已知格式、已知类型的素材不足终行，以中文类型名报告；其他错误仍保留原摘要，不把任意 traceback、密钥或 Cookie 发到用户端。成功退出或此前重试的旧错误不冒充当前失败；不新增生成/发布重试。修改前 worker SHA256 `ddc0db7806280e9080dbb219607034f57ff732b6d86b5d794f26ea30f09f2c43`，此前该文件没有未提交改动。
- 新回归 `ops/xhs_hermes/tests/test_failure_reports.py` 覆盖具体缺素材失败经过真实 run_once 报告 `/fail`、只执行一次不重试、中文映射、日志读取边界、缺日志、原始秘密/未知类型不回传、旧错误不能掩盖新错误及退出 0 不能套旧错误。独立 Python 3.12 执行 `python -m pytest -q ops/xhs_hermes/tests/test_failure_reports.py ops/xhs_hermes/tests/test_production_latency.py ops/xhs_hermes/tests/test_portable_runtime.py ops/xhs_hermes/tests/test_selection_types.py --tb=short`，**116 passed，0.36 秒**；diff --check 通过。离线回归没有访问模型或手机。
- 按数据库保存的用户 run 11 原参数构建配置，通过实际本地 API 再执行只读 self-check：`product_features + cards` 可用母文 23、匹配安全提示词 5、A05 图片 10；模型目录、OCR、鉴权、存储通过，model_calls=0、image_tasks_submitted=0。没有用自动类型的预检代替此次精确类型检查，也没有将预检声称为重新生成全链路通过。
- 仅排空/重启本地 Hermes Worker 加载修复，API、前端、AI/后处理/发布 Worker 未重启；核对没有活动生产 run、发布表仍 0 行。run 11 保留原失败证据，不改状态、不自动重建任务，由用户刷新并用原选择重新提交。真实新图文与发布仍待用户此次手动验收；原未提交改动保留，未部署/提交/推送。

### 2026-10-09 全文案类型本地素材覆盖补齐

- 用户手动改选后，本地 run 11 当前保存参数为 `buying_guide / cards`，再次报购车攻略可用母文 0。上一阶段只补配置亮点，未覆盖全部可选类型；该阶段的单类型通过不能作为其他类型通过证据。共同规范主动重读，修订日期及哈希未变；本轮仅修复隔离手动测试环境的数据准备，不新增业务代码或放宽生产准入。
- 线上仅做来源库 GET：2054 条文案，按现有生产规则合格 1731 条；七类分别为政策快讯 1253、价格方案 356、选车对比 18、购车攻略 22、试驾测评 7、配置亮点 23、用车生活 37。内部提示词只保留 `is_public=true / source_kind=internal` 的 748 组原始提示词与配图，不导入私有提示词、外部素材或反推提示词。文案接口实际 `owner=false` 为共享查询，与旧数据隔离文档的私有文案描述不一致；沿用现有权限，不在此任务更改隔离规则。首次分段读取文案遇到重复 ID，已中止且未写库；改为与生产读取一致的单次 limit 5000，并核验返回总数完整，不静默截断。
- 临时操作脚本 `/private/tmp/ztqc_manual_all_types_20261009.py`，来源快照 `all-types-source.json`、映射清单 `all-types-import.json` 均在专用测试根目录、0600。写前独立备份 `before-all-types-materials.db`；脚本核对目标必须是该根目录的 `manual.db`、没有活动生成任务，按活动文案内容或公开内部提示词/图片对及来源键去重。只新增 1707 条文案、737 组提示词/图、4 个带本地测试前缀的分类；已有行不覆盖、不恢复软删除、不删除。新行归本地测试用户，原有资料和分类完整保留；未改原 dev.db、线上库、Phone Cloud 或服务运行配置，没有重启进程。
- 真实普通测试账号接口验证：完整文案库 2287 条、合格母文 1731 条；上述七类合格数量与来源一致。公开内部提示词 851 组（包含保留的旧本地资料），中性案例安全池 384 组，cards 可用 5 组；真实 reference-types HTTP 200。全行对比导入前备份：文案总行数 586 -> 2293、提示词 1548 -> 2285、分类 70 -> 74，三个表旧行缺失/改变均为 0；差异仅新增，计数含软删除记录。证据 `all-types-local-coverage.json`、`all-types-integrity.json`。
- 按 run 11 当前数据库参数构建配置，运行 `python /private/tmp/ztqc_manual_all_types_20261009.py preflight`：`buying_guide + cards` 的实际鉴权、运行环境、OCR、模型目录、存储、资料检查均通过；母文 22、母图 5、A05 图库 10。`model_calls=0 / image_tasks_submitted=0`，不声称重新生成通过。
- 另外运行脚本 `selection`，以当前测试账号的真实 API 数据、实际 `prepare_portfolio` 选材函数检查全部七种文案搭配 cards，以及购车攻略搭配全部八种图片类型（重叠组合只测一次）：13 组通过，1 组中性案例 table 可用安全母版 0，按预期拦截；没有伪造价格或绕过报价资料要求。核验选中母文/母图确实属于指定类型，并执行主/备用选材，不只是统计行数。账号历史实际返回 0 条，因此没有验证非空近 7 天历史去重。初轮临时验证脚本把附加了选材元数据的整条母文与来源 dict 比较导致断言失败，修正为来源 ID 归属核对后重新跑完；未修改业务选择器。证据 `all-types-selection.json`。
- 本轮重新运行四项 Hermes 回归文件（failure_reports、production_latency、portable_runtime、selection_types）：116 passed，0.35 秒；这些是离线回归，不代表付费生成或真机发布。run 11 保留 failed、原参数和失败证据，不自动重跑；发布表仍 0 行，未创建新的生成或发布任务。用户刷新类型资料后用原选择重新提交，图文生成、内容审核和新排期由用户继续手动验收。
- 本轮仓内文件仅追加本任务记录；上一阶段 worker 修复/测试及所有其他既有未提交修改保留，未提交、推送或部署。状态：隔离本地素材准备修复完成，真实新图文待用户验收。临时文件不作为长期备份，正式上线仍需原有迁移、权限、生成及发布门禁。

### 2026-10-09 单篇没有配图的只读排查

- 用户继续手动测试后提示「交付缺少标题、正文或可访问配图」。当前 run 11 选择已改为 `buying_guide / hero / light`；不拿上一轮 cards 参数冒充本次参数。日志确认本轮读取 2287 条文案、851 条内部提示词，购车攻略可用 22 条，素材准入通过；文案 49.993 秒、图片规划 10.683 秒，随后提交本地 AI task 310，约 6.05 秒进入图片失败，不是上一轮缺母文错误。
- 真实 `ai_tasks` 记录：模型 `gptimage2`，入口 `DuckCoding GPT Image 2`，适配类型 `openai_images`，上游模型 `gpt-image-2`；上游响应 HTTP 503、error.type=server_error，正文错误为账户请求超过速率限制，traceid `d795b4dec1bcdc1841c21172d3fbc3f7`。任务 failed、result_urls=[]；没有收到图片，不能说是配图地址裂开或去水印失败，也不能凭此证明上游是否计费。
- 交付与状态核对：post 22 已有标题「零跑A05测试看车清单」和正文；checkpoint 保存 image task 310、原始生图计划和上游错误，candidate 的 image_url/local_image/OCR 均为空、hard_pass=false。本轮生成入口没有返回可交付图片，不是网页把已成功的图藏起来。
- 错误呈现问题：`ingest_generated_post` 对缺 image_url 写入笼统缺图摘要；`web_worker` 对非零退出的 candidate 用通用退出码摘要。因此上游限流原因留在 AI task/checkpoint，没有在工作流失败说明准确展示。此为已定位的业务错误展示缺口，本轮未修改服务/Worker 逻辑或将任务标成功。
- 安全边界：当前 provider 异常路径把已发出的 HTTP 5xx 标为 result_unknown，Hermes 将其视为 review_required，自动恢复明确跳过此状态。没有重复生成、换入口、改 task/run/post 状态或下发发布；应先确认入口额度/恢复情况及原任务结果，避免未知结果重复计费。本轮仅只读查库/日志/源码并追加本记录，既有修改保留，没有部署/重启；未调用模型、未运行新生成验收，未把上一轮 116 项回归当作本轮通过证据。

### 2026-10-09 用户要求本地生图切内部入口

- 用户明确要求「换成内部的」。范围限定当前隔离手动测试环境，不修改线上、原 dev.db、Phone Cloud、任务状态或已有内容，不自动重跑 task 310/run 11。共同规范重读，修订日期/哈希不变；仓内已有代码改动保留，本轮不改业务代码或权限。
- 原因核实：本地内部 provider 4「codex」虽启用且默认，但 `supports_image_input=false`，Hermes 必带车型参考图，实际选择器因此排除它；默认标志不是强制路由。当前来源的既有内部入口配置（只读查询空 model filter，避开默认建档分支）明确支持图生图，根地址 `http://47.98.127.132:48731/v1`、`openai_images / gpt-image-2`。内部旧密钥及已授权 relay 密钥分别 GET models 均 HTTP 200，列出该模型；沿用内部入口既有密钥，不迁移外部提供商密钥、不调用付费 health-check。
- 临时脚本 `/private/tmp/ztqc_manual_internal_provider_20261009.py` 仅对目标 `manual.db` 经 ORM 写配置，先检查没有活动 AI/Hermes 任务；变更前/后配置证据保存为专用根目录 `internal-provider-before.json / internal-provider-after.json`（0600）。本地 Image 2 只启用/default provider 4，关闭其他 Image 2 入口，打开文/图输入，沿用现有内部 endpoint/model/key；按当前来源补 send_size/send_n/300 秒 timeout，测试并发仍为 2。旧 unhealthy 状态置 unknown（不是伪造生图健康），历史计数和任务结果保留。Image 2.5 配置逐字段对比不变，所有入口记录不删除。
- 实际本地选择器 `_acquire_provider_slot` 的 20 次文生图/图生图检查均选择 4，及时释放槽位，没有请求上游生成；适配器的 HTTP MockTransport 验证带车型参考图走 `/v1/images/edits`，multipart 含 image、正确模型和 1536x2048 尺寸，只发一次，模拟返回一张图。模拟生成仅说明请求组装正确，不是内部真实图生图成功。本轮已真实验证鉴权/模型目录，但没有付费生成、去水印或新发布。
- 隔离回归使用 Python 3.12、PID 独立测试 DB、清空真实凭据且发布关闭，运行 `tests/test_ai_provider_routing_refresh.py / tests/test_ai_image_count_integrity.py`：61 passed，17.50 秒、3 个既有弃用警告。首次清空凭据的启动命令误把 ACCESS_TOKEN_EXPIRE_MINUTES 同时清空，配置解析失败且测试未运行；改为仅按凭据后缀匹配后重跑通过，未改应用配置解析或测试代码。
- 不需要重启 API/Worker，运行选择器每次读取数据库新配置；后续新 Image 2 任务只用内部入口，旧 review_required 不自动重发。证据 `internal-provider-readonly-audit.json / internal-provider-verification.json`。本轮仓内文件只有本记录追加，配置仅在隔离副本生效；未部署、提交或推送，现有所有业务修改保留。新任务实际图片结果仍待用户手动验收。

### 2026-10-09 旧失败任务复用与缺图错误提示修复

- 状态：本地候选。主动重读共同规范（2026-09-30，SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`）、README、架构、后端约定与数据隔离；基线仍为 `codex/v0.3.29-workbench-fix / a9aaaceec4581ece53985db0903aea18e776afb4`，大批既有未提交改动保留。本次为 R2 失败交付契约修复，不做生产操作、Phone Cloud 修改、迁移或新付费调用。
- 本轮实际只读证据：最新仍是 run 11 / post 22 / AI task 310，没有新的内部生图任务。11:39:49 再次执行只输出 resume，image_failed 耗时 0 秒；checkpoint 中 review_required 直接返回原结果。切换 provider 不改变旧任务结果。没有用户操作审计证明由哪个按钮触发此次复用，不能推断用户已下发新任务；现有创作提交接口会创建新 run，不能把普通刷新等同于重生。原真实错误仍是 DuckCoding HTTP 503 限流，不是内部入口已再次生成失败。
- 根因分层：生成端未返回配图；未知结果防重复保护按设计停止；交付 manifest 只传 image_status，没有传递安全失败分类，API 将任何缺图合并为缺标题/正文/配图，最终 run 又只显示退出码。前一轮只验证内部选路和模拟请求，没有实测新图片成功，不能宣称完整重试通过。
- 最小代码范围：`ops/xhs_hermes/run_daily_8x5.py` 在 manifest 增加可选 `image_failure_code`，仅输出固定枚举，原始上游正文不回传；`backend/app/services/hermes_workflow_service.py` 分开标题/正文/配图校验，以固定中文消息区分限流且待核验、未知结果、后处理失败、待查询与生成/检查失败，run 摘要使用已校验帖子的具体失败说明。兼容旧 worker 只带 review_required 的情况；不改变路由、生成参数、重试次数、审核门槛或未知结果保护。新 API + 旧 worker 可回退通用待核验提示；旧 API + 新 worker 忽略附加字段，不需迁移。回滚本轮代码不删除任务数据。
- 修改前哈希：runner `311983d40bb90c4b225fbdeed85b878ea72a832db05583fa6bad664103b2f0bc`；service `7dfba43c209af37d7c3a56d4249b06736fca76769d4149f465553026c49eedec`；backend 测试 `b1e22c8fe215f1776d6bdfa69fed48a9913f1f694943f65aaa5b49f2a17be1ef`。已核对 service/测试既有修改为本会话发布接入工作，本次仅追加失败提示及回归，不覆盖既有修改。
- 实际离线验证：Python 3.12 执行 `python -m pytest -q ops/xhs_hermes/tests/test_failure_reports.py ops/xhs_hermes/tests/test_production_latency.py ops/xhs_hermes/tests/test_portable_runtime.py ops/xhs_hermes/tests/test_selection_types.py --tb=short`，123 passed / 0.49 秒。新增 runner 回归覆盖故障分类、原始秘密不导出、旧 review_required checkpoint 不提交新任务且保留限流分类。backend 独立 PID 测试库、清除真实凭据/关闭发布后执行 `tests/test_hermes_workflows.py tests/test_hermes_image_urls.py tests/test_hermes_api_lifecycle.py`，60 passed / 9.71 秒、1 个既有 crypt 弃用警告。新增接口回归覆盖逐篇不完整交付被拒绝、完成回调记录具体原因、用户 GET 刷新后保留、重复回调幂等、旧 worker 兼容、未知字段不泄露上游原文；不是仅测字符串函数。diff --check 通过。
- 当前本地记录修复：私有临时脚本 `/private/tmp/ztqc_manual_failure_notice_20261009.py` 核对目标仅隔离 `manual.db`、run 11/post 22/task 310 身份和失败证据、无活动工作流后，只更新 source_detail 的安全错误分类/说明及 run.error。修改前完整相关字段备份到专用根目录 `run-11-failure-notice-before.json`（0600）；标题、正文、image_url、hard_pass、任务状态保持不变，不清 checkpoint、不创建新任务。只重启本地 API 加载新服务代码，前端、AI/后处理/Hermes/发布 worker 不重启；线上、原 dev.db 和 .env 未改。
- 真实本地用户路径只读验证：通过 `http://127.0.0.1:3000/api/backend` 登录隔离测试用户并 GET run 11，HTTP 200，标题/正文存在，配图仍为空，显示「生图上游限流，未返回配图；原生图任务结果待核验，未自动重新生成」。未声称浏览器截图验收或真实图片生成通过。已询问用户是否允许保留文案、仅经内部入口新生成这 1 张图；收到确认前不重发未知任务，不发布内容。
- 本轮仓内文件共 5 个：runner、service、`ops/xhs_hermes/tests/test_production_latency.py`、`backend/tests/test_hermes_workflows.py` 与本记录；原 worker 修复及其他既有内容保留。自审通过范围/兼容/不重复付费/错误脱敏检查，无独立审查或生产验收。未运行生产 PostgreSQL、付费生图、去水印和手机发布验收，未部署、提交或推送。

### 2026-10-09 保存发布计划误报配图来源未授权

- 状态：本地候选已加载，待用户再次保存。共同规范重读（2026-09-30 / SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`）、Web README/架构/后端约定/隔离规范已核对；Git 分支/HEAD 不变，既有未提交改动保留。R2 本站素材读取修复，不修改 Phone Cloud、设备、发布协议或权限，不执行真实发布。
- 本轮实际证据：用户已创建新 run 12/post 23，状态 approved，实际配图为本站 `http://127.0.0.1:8000/uploads/ai-images/a2e534eee6bd4f69b75d2b000378cbd7.png`，publish_status=not_requested，发布表 0 行。这次不是 run 11 的缺配图；图片已存在。PublishAssets.fetch 仅将相对 /uploads 和已知 Docker 地址映射为磁盘文件，忽略已配置 uploads_public_base_url 下的绝对本站地址，随后误走外部 HTTPS 来源白名单并报 publish_image_origin_denied。失败发生在素材快照阶段，尚未创建发布单或联系手机。
- 最小范围：`backend/app/adapters/phone_cloud_publish.py` 仅在 local 存储模式、地址协议/完整 netloc 与已配置 uploads_public_base_url 一致、路径位于其 /uploads/ 挂载下且无用户名密码时，按现有上传目录读取；不为 localhost/127.0.0.1 或任意 HTTP 建通配白名单。继续保留路径解码后 resolve、目录边界、文件存在、大小/格式及私有快照校验；其余外部来源仍必须 HTTPS + 显式来源白名单 + 公网地址，禁止重定向。无需迁移、改 DB/配图 URL、重新审核或重新生成。修改前适配器 SHA256 `bbd703fb7521d1bdbc90dcd7734cb732dce2c16fd394ffbbbd671919cbe40bb8`；测试 `ea0321b2ed77c02ae7c5fb2e89b8da6dae94456f2826459458335a1d57efcc18`，均为本会话已有发布接入文件，未覆盖他人修改。
- 先加回归后复现：两种配置本站源（本地 HTTP、含挂载前缀的 HTTPS）及真实 publish-plan API 保存测试在修复前均失败，3 failed / 63 deselected，错误与用户一致。修复后以独立 Python 3.12、PID 隔离 SQLite、移除真实凭据、关闭发布运行 `python -m pytest -q tests/test_cloud_phone_publish.py tests/test_hermes_workflows.py tests/test_hermes_api_lifecycle.py tests/test_hermes_image_urls.py --tb=short --show-capture=no`：126 passed / 18.54 秒、1 个既有 crypt 弃用警告。新增 9 项覆盖本地真实文件读取/冻结、禁止 HTTP 回取、异端口/伪装域名/内嵌凭据/非上传路径/穿越/越界符号链接拒绝、真实保存排期接口生成 scheduled 快照且远端任务和尝试为 0。未将模拟保存当作真机发布成功。
- 实际手动测试环境验证：调用真实 PublishAssets.freeze 读取 post 23 的真实 PNG，得到 1 张 1,687,504 bytes / image/png 私有快照，未改原图、无转码；未发远端请求，发布表仍 0 行。核对 active_ai=0、active_hermes=0、publish_jobs=0 后，仅重启本地 API 加载修复；其余 Worker、前端、线上及原 dev.db/.env 均未修改。通过前端同源代理登录/GET run 12 及发布列表，HTTP 200，post 23 仍 approved、有图、无新增发布单。没有替用户点击保存，以免到期自动触发真实发布。
- 本轮文件：适配器、`backend/tests/test_cloud_phone_publish.py`、本记录。diff --check 通过，自审确认仅本站文件来源兼容、不放宽任意内网访问、不改变审核/幂等/未知结果保护；无独立审查。保留所有前轮代码及历史任务，未部署、提交或推送。用户可直接重试保存；浏览器保存后的排期、真实云手机执行和生产 PG 验收本轮未执行。回滚只撤本轮本站地址映射，既有任务与私有快照不删除。

### 2026-10-09 排期完成后的全账号上线就绪复核

- 状态：**待验收，不具备全账号无条件启用的结论**。本轮授权为检查与本地隔离验证，不包含再次真实发布、设备控制、部署或服务重启。工作目录为实际运行代码所在的 `/Users/yyx/ztqc/web`，不是当前聊天的另一 worktree；HEAD 仍为 `a9aaaceec4581ece53985db0903aea18e776afb4`。共同规范重读，日期/哈希仍为 2026-09-30 / `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。
- 本轮只读事实：隔离库 run 12/post 23 的发布单为 1 条、尝试为 1 条，均关联原远端任务 `d3408913-e381-46d7-b6b2-4ef16d2416e9`；北京时间 15:00:02 下发、15:00:58 完成手机提交。远端列表中的标题和完整正文与冻结快照逐字一致，Web 为 submitted、published_at 为空；用户反馈已实际发布，不把 Web 缺少核验记录解释成没有发布。另一个成功任务创建于 10 月 8 日，不是今天排期重复下发。本轮结束前隔离库活动发布单为 0，没有新增远端任务。
- 内容配置问题：run 12 的 policy_snapshot 使用 `a05-test-neutral`，其政策文字明确要求标题或正文注明测试内容，因此此次带“测试”是生成输入污染，不是手机擅自改写。当前隔离环境仍引用该案例；正式使用前须恢复经过核实的业务案例及正常图文生成输入，重新生成并人工审核。不得仅去掉“测试”字样就宣称内容合格，也不修改已发布快照或自动补发。
- 本轮云手机清单快照：125 台设备、250 个启用槽位条目，其中 111 个没有小红书 ID；139 个非空 ID 无重复。按 Web 当前配置准入检查，134 个通过、2 个设备未就绪、3 个忙碌。空槽位不是已绑定业务账号，就绪只说明配置/在线状态，不证明 App 实际登录身份或发布权限。当前**隔离测试环境**已核验 ID 白名单只有 1 个；不是生产 Web 的全账号配置审计。

#### 上线前仍需补齐或验收

| 优先级 | 本地代码证据与边界 | 下一步 |
|---|---|---|
| P0 防错账号 | Web 按稳定 ID 解析设备/槽位，但创建载荷只有 deviceId/xhsAppSlot；Agent 交给 Python 的载荷也不包含预期账号 ID。`run_publish` 没有发布前实际 App 身份核验，人工白名单无法发现之后发生的切号。 | 将预期小红书 ID 贯穿下发与执行，在真实 App 核验一致后才允许最终发布；未核验账号继续拒绝启用。 |
| P0 防错配图 | `preparePublishImages` 导入后依赖相册最新优先；`select_gallery_images` 实际按位置选择最前 N 个缩略图，仅使用 remotePaths 的数量，不按路径、媒体 ID 或摘要确认选中的文件。 | 验收有旧图、异步媒体扫描、其他来源插图的场景，补可验证的目标图片选择；这是风险，不是本轮已经观测到错图。 |
| P0 完整文案 | `fill_editor` 写入即返回；完整标题/正文回读只在 dryRunBeforeFinalPublish 分支，正式最终点击前没有同等回读门禁。 | 正式路径核对实际输入、长文本、换行、表情、话题与 App 字数限制；不匹配就停止，不静默截断或发布。 |
| P1 最终发布事实 | 当前成功条件包含“编辑页关闭且小红书在前台”，成功提示也可能是“审核中”；没有稳定帖子 ID/链接、审核状态或公开可见核验回传。 | 保留 submitted 语义，补原任务证据与人工核验闭环，不把任务 succeeded 直接映射为公开发布成功。 |
| P1 高量对账与交付 | 用户接口列表只返回最近 100 条，创建接口无远端幂等键/按 ID 单查；本地有 unknown 禁止重发保护。D-078 的完整下载/ACK 协议是候选，不能仅凭本地代码断言生产已部署。 | 补按 ID 查询/幂等协议与保留策略；按真实云端/Agent 版本做不点击最终发布的交付验收，保留断线不重复执行门禁。 |
| P0 上线运行条件 | 新 Worker 是独立入口，当前常规 Compose 没有自动加入；生产 PG 迁移、私有快照共享卷、账号白名单、普通发布用户、回滚和真实双设备验收尚未完成。 | 按前述发布流程逐项演练，先受控单/双设备，再扩大账号范围；不能把隔离 SQLite 测试库或测试案例带上线。 |

#### 本轮验证与限制

- 新增 `backend/tests/test_cloud_phone_publish_acceptance_audit.py` 两项离线验收：10 个账号各一篇，经编辑、审核、批量排期、不同设备/单双开槽位下发、换 Worker 查询、终态及禁止重排期；逐项核对标题/完整正文/图片 bytes/目标设备槽位。另用 HTTP MockTransport 核对普通文案、换行、表情与图片原样入请求，不附加测试文字。模拟不是 10 台真机并发验收，也未运行真实模型生产。
- 后端使用独立 Python 3.12、PID 隔离 SQLite、清空凭据、禁真实发布并用 socket.connect 审计钩子阻止外联。首次合并回归为 135 passed / 1 failed / 9 errors：调度器领导接管等待超时后测试库锁冲突影响后续 fixture。该用例独立复跑 1 passed、调度器整文件 14 passed；最终包括发布、两项新增验收、Hermes 生命周期/图片、调度器、临时 SQLite 迁移及 PG DDL 名称检查的合并回归 **146 passed / 26.09 秒**。首次不稳定记录保留，不以复跑通过证明已消除根因。XML 回执位于 `/tmp/ztqc-cloud-publish-audit-final-20261009.xml`。
- 新测试初轮因编辑 API 必填 comment 未提供而 1 failed / 1 passed，补齐测试输入后 2 passed；Ruff 初轮 fixture 导入名与参数同名触发 F811，改为 usefixtures 后通过。未为测试修改业务验证或保护逻辑。
- 前端 `npm run type-check -- --incremental false` 通过；`npm test -- src/components/workflow/hermes-publish-planner.test.ts` 为 12 passed。Phone Cloud 发布 Python fake/mock 专项 26 passed；`node --test server/automation-center.test.mjs windows-agent/src/automation-center-wiring.test.mjs` 为 26 passed（包含非发布的既有自动化契约用例），均未启动真机任务。没有执行前端生产构建、全仓覆盖率、真实 PG 演练、长时间多设备压力或正式生产验收。
- 本轮文件只有新增验收测试和本任务卡追加；所有已有未提交改动保留。`ruff check`、`git diff --check` 通过，自审核对断网隔离、fixture、数据/内容保留与证据分级；没有独立审查。未改 Web 业务实现、Phone Cloud 代码、设备/媒体、原业务库或线上环境，未部署、提交、推送。下一步应先完成 P0 候选修复及本地回归，真实发布和上线另按用户指定账号、内容、次数与窗口确认，不能承诺自动化永不受掉线、风控或审核影响。

### 2026-10-09 线上运行事实只读审核

- 状态：**线上云端/Web 只读核对完成，Agent 文件级审核待补，不是全账号发布验收通过**。用户要求实际查看线上并判断修改项；本轮只读访问运行容器、PostgreSQL、现有 Nginx 日志及普通发布用户设备清单，没有创建、重试、取消或改动发布任务，没有操作手机、重启服务、部署或改生产配置。只追加本文，保留全部既有工作。共同规范日期/哈希仍为上节记录版本。
- Windows Web 实际运行 core/Hermes API 镜像标签包含 `0.3.43-a9aaaceec458`；两个 API 容器均没有新 `phone_cloud_publish.py`、`hermes_publish_service.py`、`phone_cloud_publish_worker.py` 和 `d5a8c2e7f901` 迁移文件，也未注入本轮候选的发布开关/核验白名单/专用发布认证环境变量。容器清单没有独立云手机发布 Worker；现有 `web-hermes-worker-1` 是内容生产 Worker，不是发布 Worker。生产库 revision 为 `c47f2a6d9b10`，`hermes_publish%` 表为 0 张。因此此前排期成功证明的是本地隔离 Web 对接线上云手机，不能说 Windows 正式 Web 已上线这条新链路。
- 云手机运行容器健康、RestartCount=0，启动时间 `2026-09-21T07:38:22.5279431Z`；镜像 ID 为 `sha256:907e0c65a50b1d066241e55ce475ac772647a531b582ae2894e25e1adc8ed3dd`，容器内 `server/index.mjs` SHA256 为 `1bdfbc3e370fff1c4a07e9c0f30242a348035d3e0227596f2e62eb90f3796e92`。生产事实来自运行容器，不将宿主源码、本地工作树或固定 package 0.1.0 当作运行版本。

#### 对前节交付协议状态的更正

- **`xhs_publish_v1` 已在本次真实任务中使用，不能继续说线上完全没有部署下载/ACK 协议。** 运行中的服务端已支持该协议；Nginx 在北京时间 15:00 分钟内记录目标 Agent 的 97 次领取请求均携带 `xhsPublishDelivery=xhs_publish_v1`，同时携带 `galleryDelivery=gallery_v2`，均为 HTTP 200。
- 原任务 `ef57d2b7-e3d8-4a1f-8965-e5a39771f385` 在 15:00:03 的 payload 请求为 200，15:00:15 的 ACK 为 200，随后产生执行事件，15:00:58 status 回写为 200；发布 job 为 `d3408913-e381-46d7-b6b2-4ef16d2416e9`。下载到 ACK 约 12 秒、受理到完成约 55.5 秒。这是现有任务取证，不是本轮新发或重复发布。
- 终态 `delivery/deliveryAttempts` 为空不能用于否定协议：生产 `task-history-maintenance.mjs:8` 起的 `compactTaskPayload` 会主动删除这两个字段。完整失败分支、重启恢复及 Agent 具体源码哈希仍未验收；旧 Phone Cloud D-078 文档“候选未部署”与这次实际握手冲突，应据新证据补记，不能反向把全部本地候选宣称已发布。

#### 生产账号清单对账

- 截至 UTC `2026-10-09T08:12:24Z` 的只读快照：Windows Web 有 179 个环境，其中 145 个 active、5 个为同步执行环境；140 个 active 非执行环境中，131 个填写稳定小红书 ID，均能在普通发布用户实时清单中找到唯一启用槽位，未找到和重复匹配均为 0。
- 按当前候选适配器的配置就绪条件，这 131 个中 129 个满足设备/自动化/可用条件；「迪迪情报官」对应 118 号 app1 离线；「新能源懂车薯」对应 182 号 app1 忙碌。此为瞬时配置准入，不是实际 App 登录身份、发布权限或全机型成功率验收，也不代表线上已启用这 129 个账号发布。
- 另 9 个 active 非执行环境没有 ID：说车薯、抖音、新能源购车福利中心-小李/小胡/小肖/小龚/小周、小文抖音、新手买车攻略。名单包含非小红书用途，须先确认产品范围，不自动补 ID、推断账号或把它们全算成小红书故障。
- 19 个有 ID 环境的 Web 展示名与云手机配置名不同，其中部分只是负责人后缀/改名；例如「小袁抖音」仍按 ID 对应云手机「小迪买车情报站」，需人工确认用途。ID 相同的名称差异不等于已证明串号，不允许按名字自动改绑。131 个静态映射匹配也不能替代最终发布前实际 App 身份验证。

#### 已确认缺口与修改顺序

| 优先级 | 本轮线上证据 | 要做什么 |
|---|---|---|
| P0 防错账号 | 生产 `server/index.mjs:4116` 的 Agent 载荷不携带预期稳定小红书 ID；今天目标任务 payload 的 `expectedXhsId/xhsAccountId` 均不存在。此前 102 曾出现配置 ID 与实际 App 不一致，已在 10 月 8 日纠正。 | Web、云端、Agent 契约贯穿预期 ID，最终点击前核验实际 App 身份；不匹配/无法核验停止，静态配置与人工白名单不能作为唯一保护。 |
| P0 正式运行条件 | Windows 正式 Web 没有候选模块、发布 Worker 和发布表。 | 本地完成 PG 迁移演练、API/Worker 私有快照共享与权限检查、独立 Worker 生命周期和兼容回滚，再申请上线；不能把隔离 DB/测试政策一起带上线。 |
| P1 证据丢失 | 生产 `sanitizeRunnerLogItem`（5398 起）只保留固定步骤/坐标/计时/错误字段，丢弃 `evidence` 等确认信息；成功任务持久结果没有帖子 ID/链接，`publish_confirmed` 步骤也没有确认依据。 | 对发布证据采用专用安全白名单，保留确认方式、身份与素材/文本核验摘要、截图/帖子标识（取得时）；继续区分 submitted、审核中与公开可见，不能只凭 succeeded。 |
| P1 远端对账 | 生产 GET 列表只取最近 100 条；POST 每次创建新 job，未见客户端幂等键或发布任务按 ID 单查入口。 | 增加按发布身份隔离的幂等键和按 ID 查询；断线未知结果继续禁止自动重发，超过列表窗口不能当任务不存在。 |
| 待 Agent 文件核实 | 本地正式路径依赖相册最前 N 张，完整文案回读仅 dry-run。今天线上日志确有 `publish_gallery_candidates_failed` 的 2 秒 Poco ReadTimeout，随后 `select_publish_image`、写标题/正文、最终点击并成功返回，但证据压缩后不足以核实目标图片/文本。 | 取得当前 Agent 文件/局部日志后确认实现；补正式路径的目标素材和文案回读门槛，并以旧图、延迟扫描、多图顺序、长文本/换行等隔离反例验证。当前不能断言这篇已选错图或文案已截断。 |

- 活跃云手机 Agent 为 `win-bf-202605262318-20260727` / 主机 `BF-202605262318`，不是 Web 主机。心跳新鲜，扫描正常，Node RSS 约 238 MB、主机空闲内存约 19 GB；这些是 Agent 自报健康，不替代 Windows 文件/进程实查。当前未取得该主机的 SSH 登录信息，已向用户询问，不能把云端心跳当成完整 Agent 审核。
- 本轮仅运行只读线上命令和清单对账，未重跑业务测试；上一节 146 项等历史测试不是本轮生产验收。首次 PostgreSQL 查询在 Windows SSH 嵌套 shell 引号处失败，随后改为容器内 asyncpg 只读查询成功；首次设备清单输出被长度截断，丢弃该次对账输入并改为最小字段重新获取后才统计。JSON `state.json` 为旧兼容文件，没有用它冒充当前设备事实；当前统计使用生产 PG 与实时用户 API。
- 本地文档修改前 SHA256 为 `bffa41be75b53d214cef8cc9c61e5979519435709008583998deda3d94bcc6c7`。本轮没有业务代码、生产数据/配置或服务变化；详细 Agent 文件级审核和 P0 修复仍是接续任务，不作全账号无故障承诺。

### 2026-10-09 发布安全补强任务卡

- 状态：S1 本地候选完成，待审阅；跨仓 R2，不授权部署或真实发帖。保留既有脏工作区；规则基线为 2026-09-30 的共同流程。
- 本步范围：Web 传递审核快照中的稳定账号 ID；云端拒绝映射冲突并下发预期 ID；Agent/Python 在自己的个人主页核验 ID、正式点击前完整回读文案、最终按钮最多尝试一次；保留有限且脱敏的确认依据。相册部分选择后异常不得重选。
- 拟动：两仓发布适配器/服务、Phone Cloud `server/index.mjs` 发布局部、Agent `taskXhsPublish` 局部、Python 发布执行器、专项测试和本任务卡/Phone 主文档。不修改投屏、共享 ADB 实现、其他自动化或现有业务库。
- 契约：原 POST 路径/普通用户认证不变，增加 `expectedXhsId`，云端与实际目标配置冲突时 409 且不建任务；新版 Agent 无 ID 时在设备操作前拒绝。证据不存原文、Token 或完整页面文本。Web 成功仍只到 `submitted`，不自动宣称公开可见。
- 兼容顺序：先验证/发布 Agent 执行器与 Agent 传参，再发布云端传参与校验，最后 Web；中间窗口暂停发布任务。旧云端配新 Agent 会因缺 ID 拒绝，不降级为无身份核验。回滚也必须先停新任务，不静默启用旧的不安全路径。
- 验证：隔离 Python 假设备测试、Node 函数/路由测试、Agent 共享代码既有回归、Web 临时 SQLite + HTTP mock。真实设备、PG 演练与生产验收另列，不能用 mock 代替。
- 仍需后续闭环：远端持久幂等和超出最近 100 条的按 ID 对账、实际所选图片身份/顺序证明、PG 迁移/私有快照卷/独立 Worker 部署演练、单机到双机真机验收；上述未全部满足前不批准全账号上线。

#### S1 实现与实际验证

- Web 本轮文件：`backend/app/adapters/phone_cloud_publish.py`、`backend/app/services/hermes_publish_service.py`、两个 `test_cloud_phone_publish*` 测试文件及本文/架构说明。Phone 本轮文件：`server/index.mjs` 发布局部、`server/publish-evidence.mjs`、`server/xhs-publish-safety.test.mjs`、`server/task-history-wiring.test.mjs` 的 VM 依赖、`windows-agent/src/index.mjs` 发布/证据局部、`windows-agent/scripts/xhs_publish_poco.py`、旧自动化测试的点击函数断言、新 `test_xhs_publish_safety.py`、接口文档和主文档。
- 新排期快照增加 `publish_proof_required=true`，不改变内容版本比较/旧排期兼容观察；有效证据必须包含账号、标题和正文 SHA256 与审核快照匹配、账号及文本核验严格 true、最终点击已尝试和有限确认枚举。冲突/缺失进入 `unknown` 且不重发。尝试表保留图片快照和脱敏的 `remote_publish_proof`；旧结果无证明时仍只表示手机提交，不表示公开可见。
- 最终点击 helper 不复用会吞点击异常并继续找下一元素的通用点击函数；必须证明按钮启用，最多尝试一次。部分选图后一旦异常直接停止；尚未选图时可以在原有有界读取预算内等相册。当前**没有证明相册首 N 张就是任务配图**，证据中的 `imageSelectionVerified=false` 保持如实，禁止据此直接全量上线。
- 实测：Web 发布/工作流 123/123（Python 3.12 临时 venv、临时 SQLite、HTTP mock）；独立 SQLite 迁移 2/2；Python 安全专项 13/13 和既有自动化 115/115；Node 跨层专项 9/9、最终当前工作区全量回归 758/758、根 `npm run check` 通过。没有调用真实发布、手机、外部模型或生产 DB。SQLite/DDL 与 mock 不能替代实际 PG/手机验收。
- 初轮回归暴露旧载荷对象、旧点击函数、VM 外部依赖断言不匹配，更新契约测试后重跑通过；另新增缺少证明、账号摘要冲突以及新旧排期兼容反例。Node 750→758 包含并行查名候选增加的用例，不将其全部算作本轮新增。
- 两仓 HEAD 未变化：Web `a9aaaceec4581ece53985db0903aea18e776afb4`，Phone `6811aef632eeaaacd6d6ce1effc4afa64bf6d363`；未提交、未推送、未发布。修改前副本与测试日志在 `/tmp/ztqc-publish-safety-20261009/`，是本轮局部对比证据，不是生产回滚包。
- 自审发现 `server/index.mjs` 和 Agent 入口同期有查名区域的并行修改，未覆盖，发现后停止进一步编辑这两个共享文件。发布不能直接复制整份脏工作区；需在协作结束后从实测生产基线精确合入本轮发布差异。Web `diff --check` 通过；Phone 全仓另有既有 `docs/.ppt-v3/build-workshop-deck.mjs` 两处尾空白，本轮不修，发布范围检查单独执行。

#### 后续上线阻断项

| 顺序 | 验收任务 | 通过标准 |
|---|---|---|
| 1 | 配图身份与顺序 | 从任务摘要到实际选中图片有可核验对应，覆盖旧图混入、索引延迟、多图顺序；不能仅按相册首 N 张或仅按数量断言正确 |
| 2 | 持久幂等与按 ID 单查 | 同用户相同键相同请求只建一次、不同内容冲突；进程重启及超过最近 100 条仍可对账；用户间隔离，不因断线未知自动重发 |
| 3 | PG/部署演练 | 从生产 revision 的隔离副本升级到候选；API 与独立 Worker 共享私有持久快照、非公开 uploads；租约/重启/权限/旧数据兼容通过。不得复制本地 DB、测试政策或凭据覆盖生产 |
| 4 | 真实 Agent 基线及灰度 | 核对实际文件 hash、机型/单双开；明确授权一次正常审核内容，单机→双机验证，原帖只读对账，禁止重复发同一内容。未取得公开证据保持 submitted |
| 5 | 发布与回滚 | 清点进行中任务、保持下发关闭、按已审版本顺序激活，记录不可变包/hash/回执/回滚点；不得重启其他服务或改变 D-075；线上验证后才扩大账号白名单 |

结论：本轮安全基础候选可审阅，**尚不是全账号自动发布上线完成**；以上阻断项仍未验证，不承诺所有账号/机型无故障。

### 2026-10-10 本地人工验收运行环境

- 用户要求本地启动生产、审核、发布链路并设置简单管理员登录。仍使用 `/private/tmp/ztqc-web-manual-20261009/manual.db`，不迁移原 dev.db 或生产数据库。仅将该副本的 local102 用户（ID 14）改名为 admin、设置用户指定的本地密码及 admin/xhs_ops 角色；密码不记录在本文。账号归属和历史记录保留，修改前字段写入本地 0600 私有备份。
- 启动脚本 `/private/tmp/ztqc_web_full_local_20261010.py`；API 8000、前端 3000、生图 Worker、后处理 Worker、Hermes Worker、发布 Worker 均运行。API 不执行 lifespan，禁止定时循环/预热；队列使用新的 `local-manual-20261010:` 前缀，Hermes 使用新的输出目录，不重放旧报告。启动前/后均无 queued/running AI/Hermes 任务，旧发布单仍为 submitted。
- **真实发布下发仍关闭**，发布 Worker 仅待命。已向用户确认仅 102 账号、最多一篇、用户亲自生成/审核/排期的范围，尚未收到确认；没有创建或重试真实手机任务。上一节云端/Agent 安全候选仍未部署，本轮启动不代表远端已具备候选的身份/文案证明。
- 不再沿用要求添加测试字样的 a05-test-neutral 案例，也没有放行已过期的 9 月销售政策。单独本地 `editorial-cases-20261010.json` 提供 a05-editorial 普通选车观察内容，仅限参考图可见外观和到店观察问题，禁止未经核实的价格/补贴/参数/试驾结论；不声称销售政策已更新，不改历史内容或已发布快照。
- 本轮实际验证：前端同源登录、用户角色、Hermes bootstrap/reference-types、AI 模型列表、发布记录均 HTTP 200；bootstrap 仅分配原 102 环境。数据库/Redis/本地存储 readiness 正常，创作页面 HTTP 200，Hermes 新心跳已写入。生成只读自检全部通过：运行依赖、OCR、模型目录、鉴权、素材和 A05 图片；`model_calls=0`、`image_tasks_submitted=0`。未做本轮真实生成、人工审核、手机发布或生产验收。
- 仓内仅追加本节，业务源码及其他既有改动保留；本地配置与临时运行脚本不作为上线产物，未部署、提交或推送。

#### 本地 C11 案例缺失修复

- 用户手动 run 13 选择零跑C11，Worker 在构建配置时出现 `cannot uniquely match vehicle model`，未进入模型或生图调用。此前 bootstrap 合并车型库与生产政策，但本地 cases 仅含 A05；这是本地环境准备不足与 API 准入不一致，不是上游生成故障。run 13 原失败记录保留，未自动重试。
- 本地普通选车案例补齐现有图片库的 A05/C10/C11/C16，沿用无销售报价、不得虚构配置或试驾经历的内容边界，不扩充或伪造有效营销政策。当前所选 policy_news 不能据此视为获得了最新销售政策。API 和 Worker 仍共用同一临时 cases 文件；其他没有案例的车型不再混入可生产选项。
- 源码最小改动：`hermes_policy_service.py` 提供与 Worker 同样归一化/唯一性规则的车型清单；用户 bootstrap 仅展示该清单；`hermes_workflow_service.py` 在入队前拒绝缺失/歧义车型、错误或跨车型 case_id。单篇、批量及重新生成共享此校验，缺失配置返回中文 HTTP 400，不创建注定失败的任务。未改变生成重试、审核或发布开关。
- 新增 `backend/tests/test_hermes_production_models.py` 11 项，覆盖空配置/重复归一化/下拉与提交一致性、批量原子拒绝、显式错误案例、C11 API 入队到实际 Worker 配置构建。定向合并发布/工作流/图片与生命周期回归最终 **150 passed / 13.24 秒**，使用独立 PID SQLite、清空配置凭据并禁止 socket.connect 外联。最初新增测试错误读取接口刻意隐藏的 policy_snapshot，修正为检查落库快照后通过；没有为测试放宽业务接口。
- 本地真实只读验证：bootstrap 和 Worker 心跳均显示相同四款车型；不存在车型 HTTP 400 且无任务入库。C10/C11/C16 分别完整生成依赖自检通过，A05 沿用本日已执行自检；每次 `model_calls=0`、`image_tasks_submitted=0`。C11 图库 5 张、母文/母图来源可读；自检不是实际产图或真实发布成功。Ruff、定向 diff-check 通过；仅重启本地 API 加载改动，其他既有源码/数据保留，未上线或提交。

#### 本地 run 14 长时间卡在配图提交的修复

- 状态：本地候选已加载、待用户重新创作验收；R2，未部署、未提交、未调用付费生成或真实发布。共同流程已重读，修订日期 2026-09-30，SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。已有脏工作区保留，本轮仅处理参考图来源、确定性拒绝和对应回归。
- 根因：run 14 的文案约 25.8 秒、配图规划约 9.5 秒完成；提交生图使用本地旧图库的 `/car-models/零跑汽车/零跑C11/斜前.webp`，被拼成 localhost 绝对地址。该地址 404，且不符合现有参考图来源校验，接口返回 HTTP 422，没有创建 AI 图片任务。提交层错误地将 422 当网络未知反复等 1200 秒，外层再恢复两轮。不是上游模型已生成十几分钟。
- **更正上一节自检证据边界**：旧自检只统计图库记录，并未验证各车型原图字节可读，因此旧自检通过不能证明 C11 原图可用。此次从线上公开车型图库只读取得 C10/C11/C16 对应 OSS 地址，完整读取并用 Pillow 校验 15 张图片，然后仅更新隔离 `manual.db` 的原有 15 行；修改前行备份为该临时目录下 `car-images-before-repair-20261010.json`，0600。没有修改生产图库或导入整库。
- 本轮源码：`ops/xhs_hermes/run_daily_8x5.py` 保留内部 `/uploads/` 相对引用，生成前以最多 3 并发、15 秒请求预算、32 字节读取验证图片头；拒绝旧相对地址、外部私网地址与重定向，不放宽 API 的远程参考图白名单。明确的非瞬态 4xx 返回 `rejected/submission_rejected`，内外两层均不自动重试；仅 HTTP 400 的既有容量提示保留等待。容量、429 和网络未知继续使用同一个幂等键，已受理任务继续查询而不新建。
- `ops/xhs_hermes/web_worker.py` 不恢复明确拒绝的图片，并将生成前图库失败映射为固定中文提示；`backend/app/services/hermes_workflow_service.py` 保存固定错误码与中文失败原因，不回传上游原始鉴权内容。测试为新增 `ops/xhs_hermes/tests/test_image_submission_rejections.py` 和扩充 `backend/tests/test_hermes_workflows.py`。
- 本地处置：先冻结该隔离父 Worker，终止 run 14 的子进程并停止父进程，防止第三轮继续；通过原 Worker 完成接口提交原有部分交付，保留标题、正文、配图方案，将 run 14 落为 failed。原 checkpoint/candidate/log 保留原始事故证据，不清空或重放。AI 最大任务 ID 前后均为 311，未自动重新生成。仅重新启动本地 API 和 Hermes Worker，其他服务、共享 Redis、手机和生产环境未重启或变更。
- 本轮实际验证：`ops/xhs_hermes/tests` **787 passed / 0.87 秒**；后端工作流、车型准入及发布专项四文件 **135 passed / 13.63 秒**，独立 PID SQLite 且禁止 socket.connect，1 条既有 passlib crypt 弃用告警。覆盖 422/权限等永久拒绝、拒绝文案脱敏、内外重试退出、容量/429/断线幂等、内部上传路径、路径穿越、不可读图、外部私网与跳转保护；新外层测试最初断言报告字段误写为 endpoint，改为实际的 path 后重跑通过。
- 当前运行只读验收：C11 自检通过且零模型调用；A05 的 10 张、C10/C11/C16 各 5 张引用通过实际字节探测与 `GenerateImageRequest` 校验；登录后 GET run 14 能看到终态、原文案与安全失败原因，创作页 HTTP 200，发布仍关闭。未做本轮真实成图、OCR 成图验收或手机发布，不将此写成整个生产链路已验收。
- 检查与自审：定向 diff-check 通过；Worker、新测试及后端变更 Ruff 通过；runner 全量 Ruff 仍有 HEAD 已存在的 4 条 F401，未顺带改无关导入，忽略该既有规则后检查通过。本轮自审收紧容量提示仅适用于 HTTP 400，并补绝对上传地址穿越反例。回滚本轮候选应仅撤销上述局部改动并恢复那 15 行备份，不使用整库覆盖，不删除新增业务数据。

#### 2026-10-10 102 账号发布单 2 的单次人工授权补发

- 用户发现 11:07 排期未执行；只读确认 publish job 2 / post 26 / run 15 为已审核、scheduled、远端 ID 为空、attempt 为 0。本地完整运行脚本明确设置 `PHONE_CLOUD_PUBLISH_ENABLED=false`，Worker 仍存活但 tick 直接返回，故未下发，不是时区或审核问题。用户随后明确“允许”仅补发此条一次；不扩大为全局开关、其他帖子或后续排期授权。
- 仓外一次性脚本 `/tmp/ztqc_publish_job2_once_20261010.py` 限定 job 2、post 26、用户 14、102 对应环境及固定稳定账号 ID；核对审核快照、未有尝试/远端任务、未超过既有 30 分钟迟到预算、最新唯一设备槽位及一张私有配图，同标题远端记录存在即停止。只 CAS 领取这一单，沿用正式 dispatch 的权限/版本/白名单检查和原 create 方法，不调用全局 tick，不放宽证据要求，不修改排期时间、审核内容或发布开关。
- 北京时间 11:14:17.712 远端受理，唯一任务 `f2de9809-d70f-4fd9-98c5-72ad56a87045`，app1 / 102；11:14:21.569 领取，11:15:04.695 返回 succeeded，runner ok=true / exitCode=0。原始日志包含选图、写标题、写正文、`click_final_publish`、`publish_confirmed`；远端任务保存的标题/正文与本地审核快照一致。只创建 1 个远端任务和 1 条尝试，未重试或重发，结束后设备 busy=false / available=true。
- 证据限制：线上旧执行器/压缩后的结果没有 `publishEvidence`，未取得公开帖子 ID/链接或独立可见性验证。新本地快照要求完整身份/文案证明，因此 11:15:09.687 正确进入 unknown / `publish_evidence_conflict`；这不是已证明手机发布失败，不能据此重发，也不能将 succeeded 宣称为公开可见。保留原任务与审核内容，等待人工核验；不手工伪造 proof 或将状态改成 submitted/published。
- 本轮为用户明确授权的 R3 单篇真实操作；未改仓内业务源码、部署、重启服务、控制其他设备或运行新业务测试。观察记录为隔离目录下 `job2-publish-observation-20261010.json`（0600）；前面的离线测试结果不是本轮真实发帖/公开可见性证明。全局发布仍关闭，已排期的其他内容不会因此自动下发。

#### 2026-10-10 按云手机状态回写，不再要求 Web 本地证明

- 状态：本地候选已加载，原发布单已对账；未部署、未提交或推送。用户明确撤销本地新增的账号、标题、正文核验证据要求，并要求“直接对接好云手机发布状态，不用重新发布”。本节取代上述历史记录中的 Web 证明终态门槛，不追改当时的观测事实。共同规范修订日期/哈希仍为 2026-09-30 / `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。
- 范围：`hermes_publish_service.py` 去掉新快照的证明开关与成功回写前的 SHA256/布尔证明校验；旧开关兼容忽略，有限脱敏证明仍可留作审计，不参与成功判定。`HermesPublishPlanner.tsx` 将兼容状态 submitted 显示为“云手机发布成功”，failed 显示为“发布失败”；对应后端/前端回归与架构说明同步。保留既有工作区全部其他改动，不修改 Phone Cloud 仓库、生产配置、审核内容或发布开关。
- 状态映射：云手机 succeeded → submitted（显示云手机发布成功），failed/expired → failed（保留失败/超时错误码），cancelled → cancelled；queued/running/stalled 继续沿用现有映射与等待预算。断线、任务不在最近列表或未知状态继续保留原任务，不自动重发。成功表示云手机执行成功，不代表平台审核通过或公开可见，也不要求用户另交证据才能显示成功。
- 兼容与安全：发布前审核版本锁、稳定账号绑定、已提交内容锁、私有配图快照均保留；没有数据库结构迁移。轮询新增内部可选 `job_id` 以只对账指定原单；最近一天因旧证明门槛进入 unknown 的原单可重新查询，不能新建任务来确认结果。全局发布仍关闭。
- 实际原单对账：仅查询云手机原任务 `f2de9809-d70f-4fd9-98c5-72ad56a87045`，再次取得 succeeded；通过正式轮询逻辑只更新隔离 manual.db 中 job 2 / post 26 / 原 attempt 的状态为 submitted，清除旧证据错误，消息为“云手机返回发布成功”。远端 ID、attempt ID 与次数均不变，仍为 1 次；job 1 未改，新增发布 0 次。脚本以请求方法/路径白名单禁止创建和取消，仅允许鉴权与 GET 原任务列表；未调用 tick/dispatch。私有回执 `job2-cloud-status-reconciliation-20261010.json` 和一次性脚本 `/tmp/ztqc_reconcile_job2_cloud_status_20261010.py` 保留，不含凭据或正文。
- 本轮验证：Python 3.12、临时 PID SQLite、清空凭据且禁止 socket.connect 的四文件回归 **136 passed / 18.98 秒**；覆盖新旧快照无证明成功、错误证明不覆盖状态、失败/过期/取消映射、断线不重发、指定原单对账不触碰其他单。初次新增对账测试没有模拟同设备的 30 秒等待，修正测试时钟后全通过，未放宽调度保护。前端类型检查通过；发布/工作流/API 定向 **51 passed**，全量最终 **138 passed**。全量首轮 AI 输入框的滚动时序测试有一次失败，单文件 26 项及随后全量重跑均通过，未顺带修改生图页；该既有时序波动如实保留。前端构建在 `/tmp/ztqc-cloud-status-build-20261010.3yh7S8` 隔离副本完成，34 页面生成成功，未覆盖运行中的 `.next`。Ruff 与范围 diff-check 通过；不将 mock/构建宣称为全账号、PG 或真机全链路验收。
- 本地加载仅重启隔离 API 与仍处于关闭状态的发布 Worker；未重启前端、生图/Hermes Worker、共享 Redis、Docker 或线上服务。自审确认本轮无发布 POST、无自动重试、新状态与尝试/帖子镜像一致；回滚代码应使用本轮文件前副本局部撤回，不回滚数据库或删除既有发布记录。后续生产上线仍需另行审核和授权。
- 加载后通过 3000 同源登录和 GET 发布记录/发布页面均 HTTP 200；job 2 返回 submitted、“云手机返回发布成功”、`can_cancel=false`，下发开关仍 false。SQLite 只读复核 job、attempt 和 post.publish_status 均为 submitted，尝试数 1，原远端 ID 未变。没有执行新的发布来验证界面。

### 2026-10-10 自主上传图文接入发布计划

- 任务/状态：S1 本地候选；用户要求排期不只接收 AI 生产内容，也允许自行上传图文、选择账号发布。本轮仅 Web 开发与隔离验证，R2；不改 Phone Cloud、不部署、不真实发帖、不新建分支或提交。共同规范仍为 2026-09-30 / SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。工作仓为 `/Users/yyx/ztqc/web`，原分支 `codex/v0.3.29-workbench-fix` / HEAD `a9aaaceec4581ece53985db0903aea18e776afb4`；保留所有既有脏工作区修改，不混入聊天 worktree。
- 用户流程：发布计划 → 上传图文 → 选择授权账号、填写标题/正文、按序上传图片 → 保存草稿 → 人工确认/审核 → 原发布排期。支持拖入、多图移位/删除、首张封面；上传和审核本身都不创建发布任务。图片数量遵循 `PHONE_CLOUD_PUBLISH_MAX_IMAGES`（当前默认 5，上限 9），每张不超过 3,000,000 字节，静态 PNG/JPEG/WebP；后端实际解码并限制 2000 万像素，不信任扩展名/MIME。标题 80 字、正文 1000 字，另验证云手机 UTF-16 长度，不静默截断。
- 存储/兼容：新增 `POST /api/v1/hermes-workflows/upload-post`，multipart 字段 `metadata`（request_id UUID、environment_id、title、content）和重复 `files`。沿用存储适配器落盘/对象存储，沿用 Hermes run/post 表，以 `source=user_upload` 与有序 `source_detail.image_urls` 标记；不新增表/迁移。上传稿可在发布候选恢复，默认不混入 AI 创作历史；既有 AI 单图的内容版本哈希不变。上传稿不触发生成/重生，完整详情逐张展示，明确仅做图片完整性校验、未做 AI 内容审核。
- 权限/一致性：普通用户只可选自己当前有效分配账号；管理员可选其他有效负责人账号，草稿归属于账号负责人。账号缺稳定 ID、无有效负责人或已删除时拒绝。审核、编辑、取消及发布沿用现有权限/版本锁；上传图序纳入审核版本，排期冻结全部图片顺序，账号仍锁定审核目标。客户端 HTTP 环境用 getRandomValues 生成 UUID；同用户同请求键及相同图文只建一份，变更内容返回冲突；未知保存结果只允许相同请求核查/重试，不自动重放发布。
- 本轮文件：新 `hermes_upload_service.py`、`test_hermes_upload.py`、`HermesUploadComposer.tsx`、上传 CSS/组件测试；局部调整 Hermes schema、用户/管理员 bootstrap、工作流与发布服务、多图详情、发布计划/API 及对应回归；同步 CHANGELOG、ARCHITECTURE 和本文。没有修改自动发布状态映射、远端接口或既有 AI 生图页。
- 已发现并修复：模拟存储失败时，SQLite 对无物理外层 BEGIN 的 SAVEPOINT 释放会留下占位 run；改用普通事务 flush 预约唯一键，失败 rollback，并清理本次已成功保存且取得 URL 的文件。同键竞争失败会 rollback 后查询原稿；补首次/中途保存失败、同键并发、真实解除负责人关系反例。不删除用户原文件或历史业务数据；存储适配器在未返回 URL 前内部产生的残片仍属于适配器运维清理边界。
- 验证边界：Python 3.12，PID 独立 SQLite、临时本地文件目录、FakePhone，禁止 socket.connect；前端 Vitest mock 不调用真实上传/审核/发布。首轮后端全量出现主节点接管测试 SQLite 锁冲突及连带 teardown 错误；专项重跑又发现测试启动配置禁用了该测试预期开启的主节点状态，纠正隔离启动配置后 981 项全量通过，未改主节点业务源码。随后针对存储回滚与并发补测并修复，本轮最终结果另列下方。前端 148 项、类型检查通过；覆盖率报告仅包含其配置范围，不能宣称 UI 全量覆盖率 94%。
- 本地加载：只重新加载隔离 API（lifespan off、实际发布 false），未重启 AI/后处理/Hermes/发布 Worker、共享 Redis、Docker 或生产服务。OpenAPI 已包含上传接口，浏览器刷新后原 2 篇与 102 授权账号正常加载，旧 Request aborted 消失。没有通过运行中的 manual.db 创建、审核或排期测试稿，更没有真实发布；完整写入到发布回写链路仅在隔离 FakePhone 测试中验证。旧 Worker 尚需后续受控加载候选，多图真实 Agent/PG/Windows/手机验收仍未执行，不能据此批准全账号上线。
- 回滚/接续：局部撤销本轮上传入口与映射即可，不整库回滚；保留已保存的 user_upload 草稿，回滚旧版将不显示其多图，不允许拿旧单图 Worker 执行新多图排期。部署前须沿用已有发布阻断清单，并确保 API/发布 Worker 同版、原 AI 排期兼容及多图数量/顺序真机验证，再申请发布授权。

#### 本轮最终验证与未通过项

- 最终源码专项：`tests/test_hermes_upload.py tests/test_cloud_phone_publish.py tests/test_hermes_workflows.py` **143 passed / 23.13 秒**，包含 20 项上传测试；前端 `npm run test:coverage` **148 passed / 15 文件**，`npm run type-check` 通过。最终生产构建在 `/tmp/ztqc-upload-build-20261010.GCo1kQ` 副本完成 **34 页面**，未覆盖运行中的 `.next`；Ruff、`git diff --check`、密钥扫描及 development 版本检查通过。
- 不宣称最终后端全量通过：最后一次全量在 `test_two_coordinators_run_one_child_and_take_over_after_shutdown` 等待接管超时，随后释放租约/fixture 清理出现 SQLite 锁冲突；为避免继续产生连带失败，停止该测试进程，结果 **611 passed、1 failed、7 errors、interrupted**。该文件未在本轮修改；此前相同代码全量曾 981 项通过、总分支口径 70.42%，只能作为中间快照的结果，不能代替最终源码全量绿灯。偶发原因和 PostgreSQL 对应行为仍待专门调查，不能仅凭 SQLite 认定线上存在同类故障。
- 证据：`/tmp/ztqc-upload-final-targeted.log`（最终专项）、`/tmp/ztqc-upload-final-full.log`（全量失败/中断）、`/tmp/ztqc-upload-full-recheck.log`（中间全量通过）、`/tmp/ztqc-upload-build-final.log`（最终构建）。全量启动为空环境、`Settings(_env_file=None)`、独立 PID 数据库，存储/参考快照为测试值且外网连接禁止；不是生产 DB 或真实手机验收。本次验收结论仅为功能候选可本地体验，**尚不能提交为已通过全量回归的上线版本**。

### 2026-10-11 生产发布配置接入准备

状态：**待专用发布身份确认，未应用线上配置**。用户要求接入发布配置；沿用已经部署的 0.4.0 / `6ad44254ccc0` 镜像，不重新打包脏工作区。此前 10 月 10 日的局部验收失败记录保留；10 月 11 日正式冻结候选的全量测试、PG 演练与代码部署结果见 `RELEASE_PREPARATION_20261010.md`，本节不把历史失败或历史通过混作本轮配置验收。

- 范围与边界：仅 Windows Web 的 Hermes API 配置及独立 `phone-cloud-publish-worker`；全局 `PHONE_CLOUD_PUBLISH_ENABLED=false`，浏览器新会话也保持关闭。只准备 102 / app1 对应稳定账号的 Web 白名单，不放开其他账号；不动 Phone Cloud 服务、Agent、ADB、媒体、FRP、其他容器或定时任务，不迁移、恢复或覆盖数据库。共同流程仍为 2026-09-30 / `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。
- 本轮只读连接：既有专用普通账号 `web-publish-102-test` 可以登录、读取设备和原任务；102 唯一解析到原 app1，available=true / busy=false，已有远端任务3条，新增0条。检查只允许鉴权 POST、设备 GET、任务列表 GET，不允许创建、取消或控制设备。它此前用于本地验收，已询问用户线上沿用还是另建专用账号；**尚未把真实发布密码复制到线上**，没有复用短信管理员身份。
- 已完成基础准备：Windows 新建 `D:\ztqc-private\web\phone-cloud-publish` 及空 `snapshots`，关闭 ACL 继承，仅当前 Windows 用户、SYSTEM、Administrators 访问；目录在公开 uploads 之外。私有目录保存未应用的 Compose 候选和占位连接参数；运行脚本在 `C:\projects\web\runtime\maintenance\ztqc-configure-phone-publish.ps1`，不含实际凭据。私有 `publisher.env` 包含现有运行配置，不能公开、提交 Git 或复制到公开素材目录。
- 候选结构：API 对私有快照读写，新发布 Worker 只读同一快照及现有 uploads；Worker 使用当前 core backend 不可变镜像，512MiB / 0.5CPU / 64PID、有界容器日志、DB 租约健康检查，不暴露宿主端口。API/Worker 使用独立最小配置，不将整个本地测试 env（含其他模型密钥）复制到生产。实际应用只重建 Hermes API 并启动新 Worker，不重建数据库或生成 Worker。
- 本轮实际验证：PowerShell 语法通过；Docker Compose 5.1.1 合并校验通过，逐项确认除 Hermes API 和新增 Worker 外所有服务配置不变、API 原有环境字段不变。14:46 北京时间的反例验证确认配置指纹漂移与占位密码均拒绝执行，线上 override SHA256、所有运行容器 ID/镜像/启动时间均未改变；私有快照0文件、应用回执不存在、新增发布0次。占位密码 Apply 的退出失败是预期防护结果，不算成功接入。
- 当前生产事实：API 的发布地址/凭据仍未配置，实际下发 false、发布单0条；线上没有与 102 名称或已核验稳定账号 ID 匹配的创作账号，不能照搬隔离库的假环境 ID。11 个车型案例政策均截止 2026-09-30，未修改期限或虚构10月价格。连接接入后还需完成正确账号登记/管理员归属，以及真实资料或明确的无销售政策内容配置，才可执行用户要求的真实生产、审核和发布。
- 应用/回退准备：脚本持有部署锁，核对现有配置指纹、固定镜像和无活动 Hermes/发布任务；应用前保留原 override，验证 API/Worker 健康、只读连通和其他容器不变后才写 `receipt.json`。失败仅停止新增 Worker、恢复 API 配置，保留数据库与快照；若出现新发布记录则停止自动回退，不能删除或重放任务。**这些实际应用、Worker 心跳及回退运行验证尚未执行**，不宣称已接通或已完成真机发布。
- 接续注意：新发布 Worker 尚未纳入正式组件版本回执/后续升级协调与私有目录备份流程，接入应用后必须记录其镜像、配置指纹和私有回执路径；后续正式升级不能遗漏该组件，不能用全库恢复或镜像回退抹去新增发布记录。没有新增每日备份。

本轮仓内仅追加本节；既有 release 准备文档修改、删除和未跟踪资料全部保留，没有业务源码变更、提交、推送或改标签。临时脚本仅为本次有界配置运维材料，不代表仓内正式发布工具已增加此能力。

#### 后续授权与实际应用回执（15:05~15:13 北京时间）

用户随后明确要求继续推进；按此前推荐的最小方案沿用 `web-publish-102-test` 普通专用身份，只接入已核验的 102，不另建账号、不扩大白名单。本节更新前一节“未应用”的阶段状态：**连接配置已应用且验证通过，实际发布下发仍关闭**，不是完整生产、审核、发帖验收。

- 实际切换：15:05:07 重建 Hermes API，15:05:14 启动独立发布 Worker，15:05:26 写入应用回执。两者均沿用已冻结的 0.4.0 镜像，没有业务代码热补丁、数据库迁移或本地数据库复制。此前其他9个容器的 ID、镜像与启动时间逐项检查不变；核心生图与生成 Worker、数据库、Redis、MinIO、前端、旁路前端均未重启。
- 配置：仅从本地私有文件选择4个发布连接字段，经过 SSH 写到 Windows ACL 保护的私有目录；未复制整个测试环境、未使用短信管理员、未输出密码。API/新 Worker 的实际运行配置均为发布凭据已配置、精确 HTTP 来源已配置、白名单仅一个稳定账号、`PHONE_CLOUD_PUBLISH_ENABLED=false`、`AUTH_BROWSER_SESSIONS_ENABLED=false`。本机传输用的临时凭据 JSON 已删除，不删除原专用账号配置。
- 连通与租约：API 与发布 Worker 分别真实鉴权并读取设备/原任务，均唯一解析到 102 / app1；远端任务仍3条，线上发布单与尝试仍0条。租约属于新增 Worker，心跳持续刷新；3次相隔12秒的容器健康采样均 healthy、重启0、OOM=false。短窗口不是长时间负载或真机发帖稳定性验收。
- 私有卷：API 写入一个无业务内容的唯一探针，Worker 读取校验相同 SHA256；Worker 写入以只读文件系统错误被拒绝。API 随后只删除本轮探针，快照目录恢复0文件。两组件实际快照路径均为 `/private-publish-snapshots`，在公开 uploads 之外。没有冻结、修改或发布用户配图。
- 接口与版本：正式 `Assert-ReleaseState.ps1` 通过，core/Hermes 应用身份仍为原 0.4.0。5项顺序只读冒烟通过：前端同源管理员 bootstrap、普通及管理发布记录均 HTTP200、下发false/总数0，core `/version` 与 `/health/ready` HTTP200；公网发布页 HTTP200。角色接口使用仅5分钟且不输出的临时令牌，不冒充新一轮真实密码登录。没有调用生成、审核、排期、取消、创建远端任务或设备控制。
- 首次追加验证的脚本失败如实保留：PowerShell 5 将 `@(ConvertFrom-Json)` 的多容器结果包成嵌套数组，导致两个 false 的 OOM 数组被当作 true；Docker 原生逐容器输出证实两者 healthy / restarts0 / OOMfalse。只修正临时验收脚本为直接解析并断言恰好2个独立容器对象，随后重跑全部卷、连通、版本和3次健康检查通过，没有为通过验证修改应用或健康门槛。
- 配置指纹：原 override SHA256 `cc1777089bf4235ab98350158ff20abdd77c7c472d16231d93d1487cefacd544`，应用后 `cf5b908a796d7530d663f87a409f33fe49ee4eadc289931677c01339b18f0010`；API 镜像ID `sha256:f22849c9aabd1437d7048713127e1631377222da042843aca557dfb34bae4b87`，发布 Worker 镜像ID `sha256:752179d5c94e4caa26654412c7391c0d12278a15419aede2e50231a186d4cd50`。没有修改历史标签或 core/Hermes 原组件回执。
- 材料：私有应用回执 `D:\ztqc-private\web\phone-cloud-publish\receipt.json`，原 override 同目录 `override.before.yml`；新增独立组件索引 `C:\projects\web\.release\phone-cloud-publish\current.json` 明确记录 `formalUpgradeAutomationIncludesPublisher=false`。验证记录 `C:\projects\web\runtime\maintenance\phone-publish-connection-verification-20261011.json`，本机脱敏副本 `/tmp/ztqc-publish-applied-{receipt,verification}.json`。后续升级必须协调发布 Worker，不能假设现有 core/Hermes 发布脚本已自动覆盖它。未新增每日备份、未实际演练配置回退。

**真实发布尚余阻断**：扩大只读账号搜索后，102、零跑情报员及已核验稳定账号 ID 均无线上记录；admin 的正式 bootstrap 仍返回0个创作账号。当前工作流通过 `XHSEnvironment` / `UserXHSEnvironment` 获取账号，来源仍是云登，不能仅因 Phone Cloud 可找到102就宣称已经分配给管理员，也不能用隔离库的假环境ID替代。需要完善云手机独立账号登记/绑定，保留真实云登身份；否则伪造 shop_id 还会在下一次云登同步时被停用。另11个车型销售案例仍过期，须有有效资料或明确配置普通选车内容，不虚构新政策。这两项未解决前不启用下发、不自动生产或发布，原远端3条任务不重发。

本轮仓内仍仅追加文档，已有改动全部保留；未提交、推送或改标签。本节只证明生产连接层和私有卷运行正常，不代表完整工作台真实发帖链路已完成。

### 2026-10-11 102 登记与沿用政策候选

- 用户明确要求登记102给管理员并直接沿用现有政策。实施基线为 `/Users/yyx/ztqc/web` / `codex/v0.3.29-workbench-fix` / `f0de5af1caeb5cbcd910d51d96b91342e790885e`；生产仍为冻结的0.4.0。共同流程重新读取，2026-09-30 / SHA256 `0a06c335eb36a017fc84bfdd4b067dedee27041e88ad746963f02f1f9a532e2b`。本地R2兼容修改，生产登记/部署属R3；已提出将本组冻结为0.4.1提交部署的确认，未获确认前不更改生产业务代码。
- 允许范围：`xhs_environment.py`、`xhs_service.py`、`xhs_schedule_service.py`、新 `phone_cloud_account_registry.py` 和显式登记CLI，Hermes管理创建请求/路由/服务、生成Worker及两个新测试文件；架构、CHANGELOG与本任务记录同步。没有数据库DDL迁移，没有修改Phone Cloud/Agent/ADB/媒体或原政策文件；其余既有删除和未跟踪资料保留，不一并暂存。
- 身份设计：`phone-cloud:<稳定小红书ID>`保留真实来源，工作台复用原账号归属表；已存在真实云登账号则复用，重复身份、停用记录或他人归属均拒绝自动处理。只允许活跃管理员操作、活跃接收用户，多角色判断显式异步加载。登记CLI先验证白名单和唯一在线设备/槽位，不调用发布创建接口。云登同步不误停用云手机账号，浏览器列表/采集调度排除该来源，直接启动/停止浏览器拒绝。
- 政策设计：仅管理员手动任务的显式 `use_existing_policy` 生成审计标记，Worker校验来源/操作者后增加 `--no-policy-sync --allow-expired-policy`；没有全局放宽、没有改政策期限。追加历史有效期指令，不把9月政策冒充10月权益；生成后仍需人工审核，不保证模型一定遵循。普通用户、定时任务、未确认的手动任务仍走原检查；重新生成不是自动继承此一次授权。
- 初轮发现并修复：新建User的角色集合未加载导致同步权限判断触发MissingGreenlet；改为显式异步refresh再判断，并增加多角色管理员/停用用户反例，不以旧单角色字段绕过权限。
- 实际验证：定向初轮修复后32项通过；新增CLI/多角色测试后专项21项通过。独立Python3.12、隔离PID SQLite、无真实环境文件/外网连接的第一次全量 **1037 passed / 3 skipped / 31 warnings，覆盖70.26%，163.76秒**；此后增加停止浏览器保护与策略权限refresh，最终源码全量正在重跑，前述不能替代最终结果。生成器全量 **787 passed / 0.86秒**，Ruff、diff-check、development版本门禁与发布契约通过；生产release门禁尚未运行，候选仍dirty/未打标签。
- PostgreSQL16临时库独立演练：本机127.0.0.1:56441、独立数据目录与测试库；两次并发登记+重复登记最终1个账号/1条归属，SQL来源过滤正确，多角色管理员可操作。没有连接生产库或Phone Cloud，临时实例随后正常停止；不把SQLite测试等同于生产PG验收。
- 待部署顺序：冻结明确白名单提交/新标签，通过正式发布门禁后协调core、Hermes API/生成Worker和独立发布Worker版本；保留私有连接、白名单和快照挂载，初始下发仍false。当前独立发布Worker尚未纳入正式自动升级，须单独核验镜像与私有env版本身份，不能只升级API。部署验证兼容保护后，方可用显式CLI登记102给admin并重复执行核对幂等；本地数据库不复制上去，远端原3条任务不重发。
- 回滚边界：未登记前可回到原应用/配置；登记后若回旧版，必须先阻止旧云登同步误停用云手机身份，不删除账号或整库恢复。若已经新增生产/发布记录，保留原任务和内容；未知结果查询原任务，不自动重试。当前未提交、推送、部署、登记或生成/发布新任务，不宣称已完成用户要求的真实闭环。

最终本地源码验证：全量后端 **1038 passed / 3 skipped / 31 warnings，分支合并口径覆盖71.10%，156.24秒**，通过70%门槛；包含CLI白名单拒绝、唯一设备验证、重复登记、未知用户无写入及来源隔离测试。Hermes生成器 **787 passed**，前端 `npm run type-check` 通过。临时PG演练、静态检查及版本/发布契约结果仍如上；没有执行发布门禁、Git提交/标签、生产登记或付费生成。最终日志 `/tmp/ztqc-041-final-full.log` 和 `/tmp/ztqc-041-hermes.log`；PG脚本 `/tmp/ztqc-041-registry-pg.py` 仅用假用户和隔离数据库。

完整变更文件Ruff补查：除 `xhs_service.py` 外全部通过；该旧文件有2条基线问题（未用csv导入F401、既有变量名l触发E741），用 `git show HEAD:... | ruff check --stdin-filename ... -` 确认原HEAD同样失败。本轮未顺带修整旧代码或降低项目规则；仅单独排除这两个已证实的基线项复查后通过。秘密扫描、最终diff-check通过。不能把完整文件原始Ruff结果描述为全绿。

#### 用户确认后冻结0.4.1（2026-10-11）

用户回复“继续吧”，确认本组0.4.1提交与Windows部署、102登记给admin；不推送远端，不扩大账号/发布次数。版本五处统一至0.4.1，沿用原分支，不创建新业务分支、不移动历史标签。本轮自审核对权限、来源过滤、同步误停用、角色异步加载、政策单任务授权与CLI不创建发布任务的调用链；非独立双人审查。

冻结前重新运行全量：后端 **1038 passed / 3 skipped / 31 warnings，71.08%，157.09秒**；前端 **189 passed / 19文件**，指定范围语句/行93.86%、分支83.66%、函数75.92%；版本管理 **16 passed**。Alembic单头仍 `e61010a0b001`，发布契约与秘密扫描通过。原代码范围未增加新业务修改，仅版本默认值更新。

生产预检确认core/Hermes仍0.4.0，独立发布Worker健康，无运行中Hermes任务/发布记录；override指纹仍 `cf5b908a796d7530d663f87a409f33fe49ee4eadc289931677c01339b18f0010`。当前私有配置/回执/容器与挂载基线已保存在ACL保护的 `D:\ztqc-private\web\phone-cloud-publish\release-041-before`，无凭据外传。C可用约13.55GiB，低于数据库大小+8GiB门槛约14.04GiB；未绕过门禁，已单独申请清理无引用临时包/构建缓存，获准前不删除。当前尚未部署或登记。

协调发布准备：core走正式入口，Hermes走现有组件脚本；新的独立发布Worker临时受控升级脚本先验证两份正式回执、来源镜像、0发布记录与关闭开关，只改它的固定镜像及私有env三项版本身份，配置差异校验禁止影响其他服务。脚本Windows PowerShell语法检查通过，计划/应用/健康/回退尚未执行。升级记录追加独立组件索引，不能冒充正式自动升级已覆盖该组件。没有每日备份或本地DB上传。
