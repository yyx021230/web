# v0.3.28 首页随机排序热修

更新日期：2026-09-14

## 问题

- `v0.3.27` 安装 1000 条外部素材后，首页“全部”查询携带随机种子时返回 500。
- PostgreSQL 报错为 `NumericValueOutOfRangeError: integer out of range`。
- 根因是随机排序表达式以 32 位 `prompt_examples.id` 参与大系数乘法；素材数量增加后，计算结果超过 PostgreSQL `INTEGER` 范围。

## 修复

- 排序前将提示词 ID 显式转换为 `BIGINT`，保留原有稳定随机、跨页不重复的排序语义。
- 增加最大允许随机种子 `2147483646` 的接口回归测试。
- 后端、前端和 Python 包版本统一为 `0.3.28`。

## 发布

- 不新增数据库迁移，不重复安装素材包。
- 必须沿用唯一发布入口 `WIN_PASS=... ./deploy-to-windows.sh`。

## Post-deploy frontend correction

- Production's module override pinned the core `frontend` service to `ztqc/frontend:0.3.25`, so the first cutover upgraded the API and worker while leaving the public UI stale.
- Core release lifecycle commands now use the base Compose file explicitly, preventing module overrides from replacing the immutable release image.
- Release-state verification now checks the frontend image tag, version, commit, and source fingerprint in addition to the backend and worker.
- The production override no longer pins the core frontend release, and FRP port `18080` targets the main frontend on local port `3000`.
- 发布后验证“全部/外部/内部”三类提示词接口、首页图片和主要功能页面。
