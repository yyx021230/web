# XHS Report Token Worker

这个小服务只恢复小红书报表所需的 token 获取 API，不依赖主 Web、Postgres、Redis 或前端。

Windows 后端当前调用：

```text
GET http://47.98.127.132/xhs-worker/api/v1/xhs/internal/report-token?account_id=10113684
Header: X-XHS-Worker-Token: <内部 token>
```

服务返回：

```json
{
  "code": 0,
  "data": {
    "account_id": "10113684",
    "token": "..."
  },
  "message": "报表 token 获取成功"
}
```

## 数据文件

默认读取 `tokens.ndjson`，一行一个账号：

```json
{"account_id":"10113684","account_name":"示例账号","token":"replace-with-real-token","token_status":"成功"}
```

可以直接使用现有 `xhs_report_tokens.ndjson` 导出文件，服务只依赖 `account_id` 和 `token` 两个字段。

## 本地启动

```bash
cd /opt/xhs-report-token-worker
XHS_REPORT_TOKENS_FILE=/opt/xhs-report-token-worker/tokens.ndjson \
XHS_REPORT_WORKER_INTERNAL_TOKEN='<和 Windows 后端一致的内部 token>' \
HOST=127.0.0.1 \
PORT=8791 \
python3 server.py
```

健康检查：

```bash
curl http://127.0.0.1:8791/health
```

接口测试：

```bash
curl -H 'X-XHS-Worker-Token: <内部 token>' \
  'http://127.0.0.1:8791/api/v1/xhs/internal/report-token?account_id=10113684'
```

## systemd

`/etc/systemd/system/xhs-report-token-worker.service`：

```ini
[Unit]
Description=XHS report token worker
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/xhs-report-token-worker
Environment=HOST=127.0.0.1
Environment=PORT=8791
Environment=XHS_REPORT_TOKENS_FILE=/opt/xhs-report-token-worker/tokens.ndjson
Environment=XHS_REPORT_WORKER_INTERNAL_TOKEN=<和 Windows 后端一致的内部 token>
ExecStart=/usr/bin/python3 /opt/xhs-report-token-worker/server.py
Restart=always
RestartSec=3
User=xhsworker
Group=xhsworker

[Install]
WantedBy=multi-user.target
```

## Nginx

把 `/xhs-worker/` 反代到本地 8791：

```nginx
location /xhs-worker/ {
    proxy_pass http://127.0.0.1:8791/xhs-worker/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

改完后：

```bash
nginx -t
systemctl reload nginx
systemctl enable --now xhs-report-token-worker
```

## 安全说明

- 不建议开放旧的 `/ztcar-api/carshow/market/xhs/token` 无鉴权路径。
- 默认只开放带 `X-XHS-Worker-Token` 的 worker 路径。
- `tokens.ndjson` 需要设置为 `600` 权限，并且不要提交到仓库。
