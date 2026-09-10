# Windows 宿主机上的 Hermes Worker

这是 Linux Docker 容器方案，不是宣称 Swift 或整个 Hermes 批处理器能在 Windows
原生 Python 中运行。Windows 已有 Docker Linux 引擎，不需要 Mac 长期开机。

## 边界

- Web API 保存任务、归属、逐篇结果、审核和修改记录；Worker 只认领 Web 队列。
- 保留母文复刻、独立图片母版、当前政策、产品资料、近 15 篇避重、并发和恢复逻辑。
- Mac 默认 Apple Vision；容器用 RapidOCR 3.9.2 + ONNX Runtime 1.29.0，CPU 推理。
  模型随镜像附带并校验 SHA-256，不运行时下载模型，不调用付费 OCR。
- 默认最多 2 个文案/规划并发、5 个图片接口并发，容器 2 CPU / 1536 MiB。
  此上限是待服务器实测验收的资源设置，不是 40 篇性能承诺。
- 不新增定时任务、不打开自动发布。发布计划界面继续仅提示开发中。
- OCR 原始文字、置信度保留；不根据政策猜测或改写识别出的金额/配置名。

## 构建

在有 Python 3.11 的开发环境执行 `prepare_context.py`，指定现有 Hermes
源码目录和全新输出目录。脚本验证 Hermes 提交号，复制已锁定依赖，只打包明确列出的
运营代码与资料。不打包 `.env`、本地历史会话、成图或密钥。

```sh
python ops/xhs_hermes/docker/prepare_context.py \
  --hermes-repo /path/to/hermes-agent --output /path/to/new-build-context
docker build -t ztqc/hermes-worker:<verified-release> /path/to/new-build-context
docker run --rm --network none --memory 1536m --cpus 2 \
  ztqc/hermes-worker:<verified-release> preflight
```

构建输出含源码及依赖散列清单。传输压缩包后先验证 SHA-256，再解压构建。
依赖锁由该 Hermes 提交的 `uv.lock` 经 `uv export --frozen --no-default-groups --no-dev
--no-emit-project` 导出，再与 `requirements-ocr.in` 按 Linux x86_64 / Python 3.11
合并编译并生成 hashes。正常打包不会重新解析依赖；升级必须重跑验收并更新锁。
`preflight` 不连接 Web、模型或生图接口，不认领任务。必须另做 Linux 成图 OCR
回放、Hermes 插件导入、资源和端到端验收，不能把 preflight 成功当成生产验收。

## 部署（验收后才执行）

1. 先按项目生产发布门禁备份、隔离回迁测试，发布匹配的 Web API/前端/数据库迁移。
   不从脏工作目录整包覆盖线上现有业务。
2. 将 `worker.env.example` 复制为私密的 `worker.env` 并填既有素材库、模型中转凭证；
   内部 Worker 令牌由现有根目录 `.env` 传入，不写入镜像。
3. 以现有 `web` Compose 项目加载主配置及 `ops/xhs_hermes/docker/compose.hermes.yml`。
   所有相对路径按主 Compose 文件所在的项目根目录解析。
4. 在启动 API 前用同样的命名卷运行一次 `seed`（可用 `run --rm --no-deps`），
   让 API 的只读政策卷和 Worker 的政策卷一致。不会覆盖用户已更新的政策。
5. **显式启用 `hermes` profile 才启动 Worker**。先单任务验收，再允许正常排队生产；
   本配置不会新建任何每日计划。

卷分别保存 config、state、outputs、Hermes home。新镜像只刷新 home 中的发布所有的
插件代码、config.yaml、SOUL.md，不覆盖其余会话/状态；政策数据仅初始化缺失文件。
逐篇回传成功不依赖整个批次完成。API 断线保留报告，恢复后重传；已有 task_id 继续轮询。

健康检查依据最近成功 API 请求，不只是进程存在。Docker 的 unhealthy 本身不会自动
重启服务；接口持续不可用应告警并诊断，不能靠不断重启重复生成。停止 Worker 会先
结束当前任务，最多等待 Compose 的 45 分钟宽限；不得用强制删除数据卷回收进程。

## 验收状态

本目录是兼容实现，不表示线上已经切换。实际测试结果记录于
`docs/hermes-workflow-v2/Windows容器兼容验收-2026-09-08.md`。
