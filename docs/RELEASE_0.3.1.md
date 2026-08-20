# v0.3.1 发布候选

发布日期：2026-08-17

## 版本范围

- AI 生图终态参数瘦身、去水印处理、任务恢复与管理员任务证据。
- 数据库调度 Leader、任务影子记录和报表增量刷新。
- 创作者中心作为账号帖子主数据来源，主页同步负责补齐帖子 ID 和内容字段。
- 小红书账号 ID 配置、同步历史、失败账号重跑和任务进度。
- 主页帖子、创作者中心互动和帖子详情最多 5 路云登并发。
- 同一云登环境严格串行，Redis 跨进程租约失效时降级为单路同步。
- 前端 AI 滚动策略、看板查询和后台同步配置修复。

## 账号帖子主次链路

1. 创作者中心导出是唯一的新增帖子入口。新记录只先写入标题、发布时间和互动指标；已有记录只刷新互动指标。
2. 主页帖子同步不得创建帖子，只按帖子 ID 或“标题 + 发布时间”匹配创作者中心主记录，并补齐帖子 ID、访问令牌、链接、封面和账号信息。
3. 主页出现但创作者中心尚未建档的帖子只计入 `deferred_homepage_notes`，等待下一次创作者中心同步，不写入 `xhs_account_notes`。
4. 未同步策略仅处理已经补齐帖子 ID 的记录，补正文、图片和详情字段；创作者中心指标存在时，不使用主页或详情接口覆盖互动指标。

## 数据库迁移

- `8b9c0d1e2f3a`：为云登环境增加小红书账号 ID。
- `9c0d1e2f3a4b`：增加创作者中心主数据字段和原始同步行表。
- 生产升级路径：`4d5e6f7a8b9c -> 9c0d1e2f3a4b`。

## 上线默认值

```dotenv
XHS_YUNDENG_SYNC_CONCURRENCY=5
XHS_YUNDENG_LEASE_SECONDS=1800
XHS_YUNDENG_ACQUIRE_TIMEOUT_SECONDS=3600
XHS_YUNDENG_START_STAGGER_SECONDS=2
XHS_YUNDENG_DISTRIBUTED_COORDINATOR_ENABLED=true
AI_IMAGE_SHADOW_ENABLED=false
AI_IMAGE_RECONCILIATION_ENABLED=false
XHS_HOMEPAGE_SYNC_SHADOW_ENABLED=false
XHS_ENGAGEMENT_DETAIL_SYNC_SHADOW_ENABLED=false
XHS_REPORT_REFRESH_SHADOW_ENABLED=false
DIFY_TASK_SHADOW_ENABLED=false
SCHEDULER_LEADER_ENABLED=true
```

## 强制上线顺序

1. 等待 AI、Dify、小红书同步、报表和发布任务全部排空。
2. 分批压缩终态 AI 任务参数，并在维护窗口回收 `ai_tasks` 空间。
3. 生成 PostgreSQL 与 uploads 完整备份，并在隔离数据库恢复验证。
4. 在备份副本演练迁移到 `9c0d1e2f3a4b`。
5. 预构建 `0.3.1` 镜像后再停止旧应用容器。
6. 发布后验证版本、登录、权限、生图、图片访问、看板、同步和调度 Leader。
7. 先用 2 个测试环境验证并行，再扩大到 5 个；同一环境不得重叠执行。

## 回滚门槛

出现数据挂载变化、迁移版本异常、核心接口 `500`、AI 队列不能恢复、图片大量裂开、
数据库 IO 持续异常或定时任务重复触发时，停止灰度并按发布前备份回滚。
