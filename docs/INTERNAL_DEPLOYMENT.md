# 内网部署指南（无域名 / 无 HTTPS）

## 1. 前提条件
- 一台可被内网访问的 Linux 服务器（建议 4C8G+）
- 已安装 Docker 与 Docker Compose
- 开放端口：`3000`（前端）、`8000`（后端，可选仅内网）

## 2. 配置文件准备
1. 复制后端环境模板：
```bash
cp backend/.env.internal.example backend/.env.internal
```
2. 编辑 `backend/.env.internal`：
- `DATABASE_URL`
- `JWT_SECRET_KEY`（必须替换）
- `CORS_ORIGINS`（改为你的内网 IP，例如 `http://10.0.0.12:3000`）
- AI API keys（按需）

## 3. 启动服务
```bash
docker compose -f docker-compose.internal.yml up -d --build
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
  - PostgreSQL: `./data/postgres`
  - Redis: `./data/redis`
  - 上传文件: `./data/uploads`
- 执行备份：
```bash
bash scripts/backup_internal.sh
```

## 8. 升级与回滚
### 升级
```bash
git pull
docker compose -f docker-compose.internal.yml up -d --build
bash scripts/migrate_internal.sh
```

### 回滚（代码版本）
1. 回退到旧版本代码（或旧镜像 tag）
2. 重新 `up -d --build`
3. 若涉及不可逆迁移，先恢复数据库备份再启动
