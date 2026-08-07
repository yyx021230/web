# 小红书发布模块实测报告（2026-05-05）

## 测试目标
- 覆盖发布主链路更多场景，重点验证：
  - 输入校验是否前置拦截
  - `publish-now` 是否还会 500
  - 定时任务是否到点触发
  - 待发布修改内容/时间后是否按新值执行

## 代码修复点
1. `/backend/app/schemas/xhs.py`
- `PublishRequest` 增加校验：标题/正文/图片必填与长度限制。
- `PostUpdateRequest` 增加标题/正文编辑校验。
- `tags` 改为 `Field(default_factory=list)`。

2. `/backend/app/api/v1/xhs.py`
- `/xhs/publish`：新增 `RuntimeError` 和通用异常兜底，返回业务失败而非 500。
- `/xhs/posts/{id}/publish-now`：新增 `RuntimeError` 和通用异常兜底，返回 `code=1` 与帖子当前状态。

3. `/backend/tests/test_xhs_flow.py`
- 新增发布请求校验用例。
- 新增接口异常兜底用例（publish / publish-now）。

## 自动化单测
- 命令：`backend/.venv/bin/pytest backend/tests/test_xhs_flow.py -q`
- 结果：`31 passed`

## 真实接口回归（本地运行）
- 运行时间：2026-05-05
- 后端：`http://127.0.0.1:8000`
- 认证：测试管理员 `codex_admin`
- 图片：复用本地已上传图片路径

### 第一轮（旧进程）
- 结果：18 条中 14 通过，4 失败
- 失败点：标题/正文/图片校验未拦截
- 原因：后端进程未重启，仍在跑旧代码

### 第二轮（重启后）
- 结果：11 条中 11 通过

#### 关键场景通过明细
1. 标题为空 -> 422（参数验证失败，标题不能为空）
2. 标题超20字 -> 422（标题不能超过20字）
3. 正文为空 -> 422（正文不能为空）
4. 图片为空 -> 422（请至少上传1张图片）
5. 定时创建 -> 成功（status=scheduled）
6. `publish-now` -> 返回 200（不再 500）
7. 定时任务编辑（内容+时间）-> 保存成功
8. 到点前检查 -> 仍为 `scheduled`
9. 到点后检查 -> 状态已变化（本轮为 `success`）

## 证据摘要
- 服务日志中未出现 `/xhs/posts/{id}/publish-now` 的 500。
- 定时任务日志出现：`定时发布执行完成: 1 条`。
- 到点触发场景最终状态从 `scheduled` 变为 `success`，符合预期。

## 结论
当前发布模块在“输入校验、立即发布异常兜底、定时到点触发、修改后按新值发布”四个核心风险点上，已通过本轮实测。
