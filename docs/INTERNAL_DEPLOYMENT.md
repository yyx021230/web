# 内网部署指南（无域名 / 无 HTTPS）

## 1. 前提条件
- 一台可被内网访问的 Linux 服务器（建议 4C8G+）
- 已安装 Docker 与 Docker Compose
- 开放端口：`3000`（前端）、`8000`（后端，可选仅内网）

## 2. 配置文件准备
1. 准备根目录生产变量和后端业务变量：
```bash
cp .env.production.example .env
cp backend/.env.internal.example backend/.env.internal
```
2. 编辑 `.env` 与 `backend/.env.internal`：
- `.env`：数据库、MinIO、版本、资源限制和生产确认
- `DATABASE_URL`
- `JWT_SECRET_KEY`（必须替换）
- `CORS_ORIGINS`（改为你的内网 IP，例如 `http://10.0.0.12:3000`）
- AI API keys（按需）

## 3. 启动服务
```bash
docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.internal.yml up -d --build
```

## 4. 执行数据库迁移
```bash
bash scripts/migrate_internal.sh
```

## 5. 访问地址
- 前端：`http://<服务器IP>:3000`
- 后端文档：`http://<服务器IP>:8000/docs`
- 上传资源：`http://<服务器IP>:8000/uploads/...`

## 6. 冒烟测试清单
1. 登录成功
2. 提示词库增删改查正常
3. 批量导入（无图行被拦截）正常
4. AI 生图正常
5. 管理员页面可访问且权限隔离正常

## 7. 持久化与备份
- 数据目录：
- PostgreSQL: Docker volume `pgdata`
- Redis: Docker volume `redisdata`
- 上传文件: `.env` 的 `UPLOADS_HOST_PATH`
- 执行备份：
```bash
bash scripts/backup_internal.sh
```

## 8. 升级与回滚
### 升级
```bash
git pull
docker compose --env-file .env \
  -f docker-compose.yml -f docker-compose.internal.yml up -d --build
bash scripts/migrate_internal.sh
```

### 回滚（代码版本）
正式环境不要直接 `git pull` 回滚，按 [v0.3.0 发布手册](./V0.3_RELEASE_RUNBOOK.md) 使用版本包和对应备份恢复。
