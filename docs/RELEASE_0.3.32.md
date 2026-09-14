# v0.3.32 首页图片详情与跨页去重修复

更新日期：2026-09-14

本版本只替换主前端与 Hermes 前端。首页详情图片改为独立的等比适配舞台，横图、竖图和超宽图均完整居中显示；无限滚动按标准化图片地址跨页去重，数据库记录 ID 不同或签名参数不同也不会重复展示。

发布使用 `deploy-prompt-homepage-to-windows.sh`。候选镜像在切换前完成构建，切换阶段只重建两个前端容器；核心后端、AI 生图 Worker、Hermes API、Hermes Worker、PostgreSQL、Redis 和 MinIO 的容器 ID、镜像与启动时间必须保持不变。
