# Backend AI Coding Rules

## 项目信息
- 项目: AI Creative Studio (AI创意工作台)
- 技术栈: FastAPI + Python 3.11+ + SQLAlchemy 2.0 + Pydantic v2 + PostgreSQL + Redis
- 目录: /Users/yyx/ztqc/web/backend

## 核心规则

### 1. 严格遵循的约定
- **必须使用 Python 3.11+**，使用类型注解
- **异步优先**：所有 IO 操作使用 async/await
- **文件命名**: snake_case.py
- **类命名**: PascalCase
- **函数/变量命名**: snake_case
- **常量命名**: UPPER_SNAKE_CASE

### 2. 项目结构规范
```
app/
├── main.py              # FastAPI 入口
├── config.py            # 配置管理 (使用 pydantic-settings)
├── api/                 # API 路由层
│   └── v1/             # API 版本控制
├── services/            # 业务逻辑层
├── models/              # SQLAlchemy 数据模型
├── schemas/             # Pydantic 请求/响应模型
├── adapters/            # 外部服务适配器
├── core/                # 核心工具（认证、中间件）
└── db/                  # 数据库连接和迁移
```

### 3. API 规范
- **路由必须加版本前缀**: `/api/v1/...`
- **响应格式统一**:
```python
class ApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: T | None = None
```
- **错误处理**: 使用 HTTPException，统一错误格式
- **分页**: 使用 `skip` + `limit` 参数
- **所有接口必须有文档字符串**

### 4. 数据库规范
- 使用 SQLAlchemy 2.0 异步模式 (`async_session`)
- 模型继承自 `Base`
- 所有表必须有 `created_at` 和 `updated_at` 字段
- 使用 Alembic 管理迁移

#### 模型模板
```python
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, func
from app.db.base import Base

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    # ... 其他字段
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

### 5. Pydantic Schema 规范
- **请求 Schema**: 放在 `schemas/` 目录，命名 `xxx_create.py`, `xxx_update.py`
- **响应 Schema**: 与请求分开，命名 `xxx_response.py`
- 所有字段必须有类型注解和描述

```python
from pydantic import BaseModel, Field

class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="模板名称")
    description: str | None = Field(None, max_length=1000, description="描述")
```

### 6. Dify 服务规范
- DifyClient 封装在 `services/dify/dify_client.py`
- 基于 Dify Service API 规范实现:
  - `POST /v1/workflows/run` — 运行工作流
  - `POST /v1/chat-messages` — 聊天
  - `POST /v1/completion-messages` — 补全
  - `POST /v1/files/upload` — 上传文件
  - `POST /v1/workflows/tasks/{id}/stop` — 停止任务
  - `GET /v1/workflows/logs` — 运行日志
- SSE 流式响应使用 `async_generator` 处理

### 7. AI 模型适配器规范
- 基类在 `adapters/ai_model/base.py`
- 新模型必须实现 `AIModelAdapter` 接口
- 注册到 `adapters/ai_model/registry.py`

```python
class AIModelAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...
    
    @abstractmethod
    async def generate_image(self, params: GenerateParams) -> GenerateResult: ...
    
    @abstractmethod
    async def cancel_task(self, task_id: str) -> None: ...
```

### 8. 安全规范
- 禁止硬编码密钥，使用环境变量或 .env 文件
- 密码必须使用 bcrypt 哈希
- JWT token 过期时间可配置
- 所有用户输入必须经过 Pydantic 验证

### 9. 禁止事项
- 禁止在路由层写业务逻辑（放在 services 层）
- 禁止使用同步数据库操作
- 禁止硬编码 SQL（使用 SQLAlchemy ORM）
- 禁止跳过输入验证
- 禁止在响应中包含敏感信息（密码、token）
- 禁止使用全局变量存储状态
