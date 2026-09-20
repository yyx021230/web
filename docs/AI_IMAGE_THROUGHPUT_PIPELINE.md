# AI 生图吞吐改造

## 目标

将前台实时生图、Hermes 批量生图和去水印从同一个执行槽中拆开，避免批量任务或去水印故障占满全部生图容量。

## 运行结构

- `ai-worker`：30 个生成槽，其中 `interactive=18`、`batch=12`。前台任务只能进入实时车道；管理员调用的 Hermes 请求显式进入批量车道。
- `ai-postprocess-worker`：12 个独立去水印槽。生成完成后任务进入 `postprocessing`，生成 worker 立即释放模型入口。
- Redis 队列使用 FIFO。实时、批量、去水印分别使用独立 pending 键，处理中任务均有持久 membership 防重。
- `AITask` 是恢复真相源。中间原图 URL 只保存在内部参数中，去水印成功前不通过任务接口返回。
- 提供商按剩余容量、延迟、失败率、优先级动态选择；默认入口只获得轻微偏好，不再独占请求。连续 3 次失败后熔断 300 秒，之后只放一个探测任务。

## 关键配置

```ini
AI_TASK_WORKER_CONCURRENCY=30
AI_TASK_INTERACTIVE_CONCURRENCY=18
AI_TASK_BATCH_CONCURRENCY=12
AI_TASK_WORKER_MIN_INTERVAL_SECONDS=1
AI_POSTPROCESS_WORKER_CONCURRENCY=12
REMOVE_AI_WATERMARKS_MAX_CONCURRENT=12
AI_PROVIDER_CIRCUIT_BREAKER_SECONDS=300
```

## 发布要求

1. 使用完整发布脚本，让 `backend`、`ai-worker`、`ai-postprocess-worker` 和 `frontend` 使用同一不可变镜像版本。
2. 切换前必须确认数据库中不存在 `queued`、`processing`、`postprocessing` 任务，并确认三个 Redis 队列均为空。
3. 发布后确认 `ai-postprocess-worker` 为 `running`，再提交一条测试任务验证状态按 `queued -> processing -> postprocessing -> completed` 流转。
4. 需要执行 `alembic upgrade head`，本版本新增生图历史隐藏字段迁移 `c47f2a6d9b10`；旧任务默认归入 `interactive` 车道。

## 回滚

旧版本不认识 `postprocessing`，因此只有在全部生图与去水印任务结束后才能回滚。发布脚本的队列门禁会阻止带活动任务的切换。
