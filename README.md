# AI Creative Studio

AI 创意工作台，集成异步生图、内容资源库、工作流、小红书运营与投流看板。

独立模板库和在线编辑器已下线；图库、提示词库、AI 图片保存不受影响。历史数据保留，详见 [模块下线说明](docs/EDITOR_TEMPLATE_RETIREMENT.md)。

## 功能特性

- **AI 生图**：Seedream、GPT Image 2/2.5 等模型，异步任务与图片后处理。
- **内容工作台**：Dify 与 Hermes 工作流。
- **资源与数据**：提示词、文案、图库、车型库，以及小红书运营和投流看板。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 15 + React 18 + TypeScript + Tailwind CSS + CSS Modules |
| 后端 | FastAPI + Python 3.11+ + SQLAlchemy 2.0 + Pydantic v2 |
| 数据与队列 | PostgreSQL + Redis |
| 存储 | MinIO / S3 / 本地存储 |

## 快速开始

### 环境要求
- Node.js 20.19+
- Python 3.11+
- Docker & Docker Compose (可选)

### 使用 Docker Compose
```bash
# 本地开发容器使用独立项目名、端口和数据卷
cp .env.development.example .env.development
docker compose --env-file .env.development \
  -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# 查看日志
docker compose --env-file .env.development \
  -f docker-compose.yml -f docker-compose.dev.yml logs -f
```

### 手动启动

#### 后端
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 配置环境变量
cp .env.example .env

# 运行数据库迁移
alembic upgrade head

# 终端 1：启动 API 服务
uvicorn app.main:app --reload --port 8000

# 终端 2：启动生图队列 Worker（异步生图必需）
python -m app.scripts.ai_worker

# 终端 3：启动去水印 Worker（异步后处理必需）
python -m app.scripts.ai_postprocess_worker
```

只启动 FastAPI 时，提交接口仍会正常返回任务 ID，但任务会一直停留在“排队中”；本地调试生图必须同时保持上述三个后端进程运行。

#### 前端
```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

访问 http://localhost:3000

## 项目结构
```
web/
├── frontend/          # Next.js 前端
│   ├── src/
│   │   ├── app/       # 页面路由
│   │   ├── components/  # UI 组件
│   │   ├── services/  # API 服务
│   │   ├── lib/       # 通用工具
│   │   └── types/     # TypeScript 类型
│   └── CLAUDE.md      # AI 编码规则
├── backend/           # FastAPI 后端
│   ├── app/
│   │   ├── api/       # API 路由
│   │   ├── services/  # 业务逻辑
│   │   ├── models/    # 数据模型
│   │   ├── schemas/   # Pydantic 验证
│   │   ├── adapters/  # 外部服务适配器
│   │   └── core/      # 核心工具
│   └── CLAUDE.md      # AI 编码规则
└── docs/              # 项目文档
    ├── ARCHITECTURE.md  # 当前架构
    ├── DESIGN_SYSTEM.md # 当前界面约定
    └── DATA_ISOLATION.md # 数据隔离与共享设计规范
```

## API 文档

启动后端后访问: http://localhost:8000/docs

版本与健康检查：

- `GET /version`：版本号、Git commit、构建时间和运行环境。
- `GET /health`：进程存活检查。
- `GET /health/ready`：数据库、Redis 和存储就绪检查。

## Windows 部署

项目根目录自带 `deploy-to-windows.sh`，正式发布会完成：
- 编译 Linux 版 `backend/bin/xiaohongshu-mcp`
- 检查干净工作区和语义化版本标签
- 生成可追溯发布包和版本镜像
- 发布前备份数据库与上传文件
- 执行数据库迁移、健康验证和失败自动回滚

执行：
```bash
cd /Users/yyx/ztqc/web
./deploy-to-windows.sh
```

完整准备、灰度、备份和回滚流程见 [发布手册](docs/V0.3_RELEASE_RUNBOOK.md)。生产密钥只能放在 Windows 的 `.env` 文件或 CI Secret 中。

日常分支、提交、版本标签和自动门禁统一按 [版本管理与发布规范](docs/RELEASE_VERSION_STANDARD.md) 执行。提交保存代码、打版本标签、生产部署是三个独立步骤；数据库和运行素材不随代码覆盖。

## Dify 集成

支持对接 Dify 的以下接口:
- `POST /v1/workflows/run` — 运行工作流
- `POST /v1/chat-messages` — 聊天模式
- `POST /v1/completion-messages` — 补全模式
- `POST /v1/files/upload` — 上传文件
- `POST /v1/workflows/tasks/{id}/stop` — 停止任务
- `GET /v1/workflows/logs` — 运行日志

## 开发参考

当前模块关系、生图任务链路及模型扩展方式见 [系统架构](docs/ARCHITECTURE.md)；页面布局和色彩约定见 [界面设计约定](docs/DESIGN_SYSTEM.md)。
