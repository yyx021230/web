# AI Creative Studio

AI 创意工作台 — 基于 Fabric.js 的在线设计编辑器，集成 AI 生图和 Dify 工作流。

## 功能特性

- 🎨 **在线编辑器** — 基于 Fabric.js 的强大图形编辑能力
- 🤖 **AI 生图** — 支持 Seedream 等多种 AI 图像生成模型
- 🔄 **Dify 工作流** — 可添加和管理 Dify 工作流，支持阻塞和流式运行
- 📋 **模板管理** — 丰富的模板库，快速开始设计
- 📁 **素材管理** — 上传图片素材，支持分类和搜索

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 14 + TypeScript + Tailwind CSS + shadcn/ui + Zustand + Fabric.js |
| 后端 | FastAPI + Python 3.11+ + SQLAlchemy 2.0 + Pydantic v2 |
| 数据库 | PostgreSQL + Redis |
| 存储 | MinIO / S3 / 本地存储 |

## 快速开始

### 环境要求
- Node.js 18+
- Python 3.11+
- Docker & Docker Compose (可选)

### 使用 Docker Compose
```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
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

# 启动服务
uvicorn app.main:app --reload --port 8000
```

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
│   │   ├── stores/    # Zustand 状态管理
│   │   ├── services/  # API 服务
│   │   ├── lib/       # 工具库 (fabric, dify, ai)
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
    ├── DESIGN_SYSTEM.md # 设计规范
    └── DATA_ISOLATION.md # 数据隔离与共享设计规范
```

## API 文档

启动后端后访问: http://localhost:8000/docs

## Dify 集成

支持对接 Dify 的以下接口:
- `POST /v1/workflows/run` — 运行工作流
- `POST /v1/chat-messages` — 聊天模式
- `POST /v1/completion-messages` — 补全模式
- `POST /v1/files/upload` — 上传文件
- `POST /v1/workflows/tasks/{id}/stop` — 停止任务
- `GET /v1/workflows/logs` — 运行日志

## AI 生图模型扩展

新增 AI 模型只需:
1. 继承 `AIModelAdapter` 基类
2. 实现 `generate_image`, `cancel_task`, `get_task_status` 方法
3. 注册到 `model_registry`

```python
from app.adapters.ai_model.base import AIModelAdapter
from app.adapters.ai_model.registry import model_registry

class MyModelAdapter(AIModelAdapter):
    # 实现...

model_registry.register(MyModelAdapter())
```
