# 验证码中控台

自有实名手机号的私有验证码中台。正式链路采用 activation 订单模式：业务端先创建取码订单，Android 收到短信后按 `deviceId + subscriptionId` 精确归属到 SIM 和手机号，再完成对应订单。

## 本地启动

需要 Postgres。最简单方式：

```bash
cd /Users/yyx/ztqc/web/sms-code-center
cp .env.example .env
docker compose up -d --build
```

如果服务器 Docker Hub 拉取不稳定，可以在 `.env` 里把 `NODE_IMAGE`、`POSTGRES_IMAGE` 改成服务器已有镜像或国内镜像。

本地开发也可以直接跑 Node，但要先提供 `DATABASE_URL`：

```bash
DATABASE_URL='postgres://sms:sms@127.0.0.1:5432/sms_code_center' npm start
```

管理页：

```text
http://127.0.0.1:8787
```

本地开发默认启用 `dev-admin-token`、`dev-business-token`、`dev-device-token`。Docker 镜像内 `NODE_ENV=production`，不会启用开发 Token，必须使用 `.env` 中配置的真实 Token。

## 核心 API

完整对外 API 文档见 [API.md](./API.md)。

设备心跳：

```http
POST /api/v1/devices/heartbeat
Authorization: Bearer <DEVICE_API_TOKEN>
```

短信上报：

```http
POST /api/v1/sms-events
Authorization: Bearer <DEVICE_API_TOKEN>
```

创建 activation：

```http
POST /api/v1/activations
Authorization: Bearer <BUSINESS_API_TOKEN>
Content-Type: application/json
```

```json
{
  "phoneNumber": "13800138000",
  "platform": "小红书",
  "ttlSeconds": 300,
  "clientRequestId": "xhs-login-unique-id"
}
```

轮询状态：

```http
GET /api/v1/activations/<activationId>/status
Authorization: Bearer <BUSINESS_API_TOKEN>
```

长轮询等待：

```http
GET /api/v1/activations/<activationId>/wait?timeout=60
Authorization: Bearer <BUSINESS_API_TOKEN>
```

调试接口：

```http
GET /api/v1/latest-code?phoneNumber=13800138000&platform=xhs&after=2026-06-09T00:00:00.000Z
Authorization: Bearer <BUSINESS_API_TOKEN>
```

`latest-code` 必须传 `after`，只建议人工排查使用，自动化登录默认使用 activation。

## Android 调试

USB 调试连接后：

```bash
cd /Users/yyx/ztqc/web/sms-code-center/android/SmsRelay
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell pm grant com.ztqc.smsrelay android.permission.RECEIVE_SMS
adb shell pm grant com.ztqc.smsrelay android.permission.READ_SMS
adb shell pm grant com.ztqc.smsrelay android.permission.READ_PHONE_STATE
adb shell pm grant com.ztqc.smsrelay android.permission.POST_NOTIFICATIONS
adb shell am start -n com.ztqc.smsrelay/.MainActivity
```

App 默认服务地址是 `http://47.98.127.132`，Token 默认是开发用 `dev-device-token`。正式部署后请在 App 内改成真实 `DEVICE_API_TOKEN`。

## 部署要点

1. 在服务器创建独立部署用户，不建议长期使用 root 运维。
2. 在服务器目录创建 `.env`，填入随机强密码和三类 API Token。
3. 使用 `docker compose up -d --build` 启动 `sms-api` 和 `postgres`。
4. Nginx 反代到 `127.0.0.1:8787`，参考 `nginx.sms-code-center.conf.example`。
5. HTTPS 证书覆盖 IP 后，再把 Android 服务地址切到 `https://47.98.127.132`。

## 匹配规则

- 双卡并发靠 Android 短信广播里的 `subscriptionId` 精确匹配。
- `phoneNumber + platform` 同时只能有一个 waiting activation；同一个 `clientRequestId` 会幂等复用。
- 短信只匹配 `receivedAt >= activation.createdAt - 5s` 的订单，避免拿旧码。
- 缺失 `subscriptionId` 时，只有设备仅绑定一个启用手机号才自动匹配；多卡设备会标记 `ambiguous`。
- `eventFingerprint` 用于去重，避免 multipart 或重试重复完成订单。
- 短信明文默认保留 30 分钟，审计只保留脱敏手机号和状态信息。
