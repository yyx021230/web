# 验证码中台 API 文档

更新时间：2026-06-15

公网地址：

```text
http://47.98.127.132
```

所有正式接口都在 `/api/v1/*` 下，统一使用 Bearer Token：

```http
Authorization: Bearer <API_TOKEN>
Content-Type: application/json
```

Token 类型：

- `BUSINESS_API_TOKEN`：业务系统调用，创建接码订单、等待验证码、下发扫码任务。
- `ADMIN_API_TOKEN`：管理后台调用，查看设备、绑定 SIM、维护账号、维护脚本、查看执行轨迹。
- `DEVICE_API_TOKEN`：Android App 调用，上报心跳、短信、领取任务、回传任务状态和轨迹。

## 1. 推荐业务流程

### 1.1 接收短信验证码

重要：现在接码订单有手机确认握手，不要创建订单后立刻去第三方平台发送验证码。

推荐流程：

```text
1. 业务端调用 POST /api/v1/activations 创建订单。
2. 订单初始状态为 arming，表示等待手机确认监听窗口。
3. 手机 APK 通过 WebSocket 收到 activation_available 后，调用 activation-windows 拉取窗口。
4. 服务端把订单从 arming 改为 waiting。
5. 业务端确认 status=waiting 后，再去第三方平台发送验证码。
6. 手机收到短信并上报后，订单变为 received，业务端读取 code。
```

状态说明：

| 状态 | 含义 |
| --- | --- |
| `arming` | 订单已创建，等待目标手机确认监听窗口 |
| `waiting` | 手机已确认监听，可以发送验证码 |
| `received` | 已收到并匹配验证码 |
| `expired` | 订单过期 |
| `ambiguous` | 短信/SIM/手机号映射不明确 |
| `cancelled` | 已取消，当前没有开放取消接口 |

### 1.2 小红书二维码扫码

推荐流程：

```text
1. 业务端选择一台设备和一个小红书账号。
2. 调用 POST /api/v1/devices/<deviceId>/commands 创建 xhs_qr_from_gallery 任务。
3. 任务初始状态 queued。
4. 手机通过 WebSocket 通知或 HTTP 兜底轮询领取任务，任务变为 running。
5. 手机执行脚本，持续追加执行轨迹。
6. 最终任务变为 succeeded/failed/cancelled。
7. 失败时查询 GET /api/v1/device-commands/<commandId>/events 查看步骤、截图、包名和 UI 摘要。
```

## 2. 健康检查

```http
GET /healthz
```

无需认证。

返回：

```json
{
  "ok": true,
  "publicBaseUrl": "http://47.98.127.132",
  "at": "2026-06-15T10:17:03.333Z"
}
```

## 3. 接码订单

### 3.1 创建接码订单

```http
POST /api/v1/activations
Authorization: Bearer <BUSINESS_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "phoneNumber": "16680433836",
  "platform": "小红书",
  "ttlSeconds": 300,
  "clientRequestId": "xhs-login-20260615-001",
  "purpose": "login"
}
```

字段：

- `phoneNumber`：要接收验证码的手机号，必须已在某台设备的 SIM 上绑定。
- `platform`：平台名。`小红书`、`xhs` 会归一成 `小红书`。
- `ttlSeconds`：订单有效期，默认 300 秒，范围 30-900 秒。
- `clientRequestId`：业务方幂等 ID，建议必传；重复请求会返回同一个订单。
- `purpose`：用途，默认 `login`。

成功返回：

```json
{
  "ok": true,
  "activation": {
    "activationId": "fc9a8c1f-e90c-4690-b1ed-771e794361af",
    "status": "arming",
    "phoneNumber": "16680433836",
    "platform": "小红书",
    "clientRequestId": "xhs-login-20260615-001",
    "purpose": "login",
    "code": "",
    "sender": "",
    "body": "",
    "deviceId": "",
    "deviceName": "",
    "smsEventId": "",
    "createdAt": "2026-06-15T10:00:00.000Z",
    "updatedAt": "2026-06-15T10:00:00.000Z",
    "expiresAt": "2026-06-15T10:05:00.000Z",
    "completedAt": null,
    "secondsLeft": 300
  }
}
```

如果同一个 `phoneNumber + platform` 已有 `arming/waiting` 订单：

```json
{
  "error": "active_activation_exists",
  "activation": {
    "activationId": "已有订单 ID",
    "status": "arming"
  }
}
```

### 3.2 查询订单状态

```http
GET /api/v1/activations/<activationId>/status
Authorization: Bearer <BUSINESS_API_TOKEN>
```

返回：

```json
{
  "activation": {
    "activationId": "fc9a8c1f-e90c-4690-b1ed-771e794361af",
    "status": "waiting",
    "phoneNumber": "16680433836",
    "platform": "小红书",
    "code": "",
    "secondsLeft": 240
  }
}
```

业务端应等 `status=waiting` 后再发送验证码。

### 3.3 等待订单变化

```http
GET /api/v1/activations/<activationId>/wait?timeout=30
Authorization: Bearer <BUSINESS_API_TOKEN>
```

返回同 `activation` 对象。收到验证码时：

```json
{
  "activation": {
    "activationId": "fc9a8c1f-e90c-4690-b1ed-771e794361af",
    "status": "received",
    "phoneNumber": "16680433836",
    "platform": "小红书",
    "code": "135790",
    "sender": "小红书",
    "body": "【小红书】验证码 135790，5 分钟内有效。",
    "deviceId": "10AF2J03F7009RL",
    "deviceName": "redmi-M2010J19SC",
    "smsEventId": "5bb9bd00-93b0-448a-b4ed-53e57fcc5b85",
    "completedAt": "2026-06-15T10:00:18.500Z"
  }
}
```

### 3.4 查看最近订单

```http
GET /api/v1/activations
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
```

返回：

```json
{
  "activations": []
}
```

### 3.5 调试获取最新验证码

只建议人工排查使用，自动登录请优先用 activation。

```http
GET /api/v1/latest-code?phoneNumber=16680433836&platform=小红书&after=2026-06-15T10:00:00.000Z
Authorization: Bearer <BUSINESS_API_TOKEN>
```

注意：`after` 必填，防止取到旧码。

返回：

```json
{
  "status": "found",
  "id": "sms-event-id",
  "phoneNumber": "16680433836",
  "platform": "小红书",
  "code": "135790",
  "receivedAt": "2026-06-15T10:00:18.000Z"
}
```

未找到：

```json
{
  "status": "not_found",
  "phoneNumber": "16680433836",
  "platform": "小红书"
}
```

## 4. 二维码扫码任务

### 4.1 下发扫码任务

```http
POST /api/v1/devices/<deviceId>/commands
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "type": "xhs_qr_from_gallery",
  "payload": {
    "qrImageDataUrl": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQ...",
    "fileName": "xhs-login-qr.jpeg",
    "strategy": "server_workflow_script",
    "autoConfirmLogin": true,
    "xhsAccount": "懂车大师冬",
    "xhsAppSlot": "app1"
  }
}
```

字段：

- `type`：`xhs_qr_from_gallery` 表示保存二维码到相册，让小红书从相册识别。
- `qrImageDataUrl`：二维码图片 data URL，支持 `png/jpg/jpeg`，大小限制约 1.5MB。
- `fileName`：保存到手机相册的文件名。
- `strategy`：建议传 `server_workflow_script`。
- `autoConfirmLogin`：是否自动点击“确认登录”，默认 `true`。
- `xhsAccount`：可选，传后台维护的小红书账号名；服务端可据此解析 app 槽位。
- `xhsAppSlot`：可选，`app1` 或 `app2`。
- `phoneNumber`：扫码任务不需要传手机号。手机号和小红书账号是两条独立关系。
- `workflowScript`：一般不要传，由服务端下发该设备当前发布脚本。

成功：

```json
{
  "ok": true,
  "command": {
    "commandId": "9e9f3ee6-e537-4d4b-becf-3a302dbc4c8e",
    "deviceId": "10AF2J03F7009RL",
    "type": "xhs_qr_from_gallery",
    "status": "queued",
    "payload": {
      "fileName": "xhs-login-qr.jpeg",
      "strategy": "server_workflow_script",
      "xhsAccount": "懂车大师冬",
      "xhsAppSlot": "app1",
      "qrImageDataUrl": "[image-data]"
    },
    "result": {},
    "createdAt": "2026-06-15T10:30:00.000Z",
    "updatedAt": "2026-06-15T10:30:00.000Z",
    "pickedAt": null,
    "completedAt": null
  }
}
```

任务状态：

| 状态 | 含义 |
| --- | --- |
| `queued` | 已入队，等待手机领取 |
| `running` | 手机已领取，正在执行 |
| `succeeded` | 手机端报告完成 |
| `failed` | 手机端报告失败 |
| `cancelled` | 已取消 |

### 4.2 唤醒/打开扫码测试任务

```http
POST /api/v1/devices/<deviceId>/commands
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "type": "open_xhs_scan",
  "payload": {}
}
```

### 4.3 查看设备任务

```http
GET /api/v1/devices/<deviceId>/commands
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
```

返回最近 30 条：

```json
{
  "commands": []
}
```

### 4.4 查看全局任务

```http
GET /api/v1/commands?limit=180
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
```

参数：

- `limit`：默认 120，最大 300。

返回：

```json
{
  "commands": [
    {
      "commandId": "9e9f3ee6-e537-4d4b-becf-3a302dbc4c8e",
      "deviceId": "10AF2J03F7009RL",
      "type": "xhs_qr_from_gallery",
      "status": "running",
      "payload": {
        "fileName": "xhs-login-qr.jpeg",
        "qrImageDataUrl": "[image-data]"
      },
      "result": {
        "message": "等待断言通过：点击扫码页相册入口"
      },
      "createdAt": "2026-06-15T10:30:00.000Z",
      "updatedAt": "2026-06-15T10:31:00.000Z"
    }
  ]
}
```

## 5. 任务执行轨迹

### 5.1 查询轨迹

```http
GET /api/v1/device-commands/<commandId>/events
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
```

返回：

```json
{
  "events": [
    {
      "eventId": "uuid",
      "commandId": "uuid",
      "deviceId": "10AF2J03F7009RL",
      "stepIndex": 3,
      "stepId": "launch-xhs",
      "phase": "assert",
      "level": "warn",
      "message": "等待断言通过：重启主应用小红书",
      "packageName": "com.miui.home",
      "uiSnapshot": "当前界面摘要...",
      "screenshot": {
        "mimeType": "image/jpeg",
        "data": "base64..."
      },
      "detail": {
        "expectedPackages": ["com.xingin.xhs"]
      },
      "createdAt": "2026-06-15T10:31:00.000Z"
    }
  ]
}
```

### 5.2 APK 追加轨迹

```http
POST /api/v1/device-commands/<commandId>/events
Authorization: Bearer <DEVICE_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "deviceId": "10AF2J03F7009RL",
  "stepIndex": 3,
  "stepId": "launch-xhs",
  "phase": "assert",
  "level": "warn",
  "message": "等待断言通过：重启主应用小红书",
  "packageName": "com.miui.home",
  "uiSnapshot": "当前界面摘要...",
  "screenshot": {
    "mimeType": "image/jpeg",
    "data": "base64..."
  },
  "detail": {
    "expectedPackages": ["com.xingin.xhs"]
  }
}
```

`level` 可选：`debug`、`info`、`warn`、`error`。

### 5.3 APK 回传任务状态

```http
POST /api/v1/device-commands/<commandId>/status
Authorization: Bearer <DEVICE_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "status": "failed",
  "result": {
    "error": "步骤断言失败",
    "stepId": "launch-xhs",
    "packageName": "com.miui.home"
  }
}
```

`status` 可选：`running`、`succeeded`、`failed`、`cancelled`。

## 6. 扫码脚本管理

脚本按单台设备管理，当前支持 `app1` 和 `app2` 两份脚本。保存草稿不会影响正式任务；发布后，新创建的 `xhs_qr_from_gallery` 任务才会使用新脚本。

### 6.1 查看设备脚本

```http
GET /api/v1/devices/<deviceId>/workflow-scripts
Authorization: Bearer <ADMIN_API_TOKEN>
```

返回：

```json
{
  "scripts": [
    {
      "scriptId": "6e3f8b7f-c1a4-4b6e-94f1-d5b04c70d3a8",
      "deviceId": "10AF2J03F7009RL",
      "name": "小红书扫码默认脚本 app1",
      "platform": "小红书",
      "appSlot": "app1",
      "commandType": "xhs_qr_from_gallery",
      "draftScript": {},
      "publishedScript": {},
      "publishedVersion": 1,
      "enabled": true,
      "hasDraftChanges": false
    }
  ],
  "supportedActions": [
    "home",
    "openSelfFromLauncher",
    "launchApp",
    "tap",
    "tapExactText",
    "tapByResourceId",
    "tapBottomTextCenter",
    "tapTopRightIcon",
    "tapFirstGalleryImage"
  ]
}
```

### 6.2 保存草稿

```http
PUT /api/v1/workflow-scripts/<scriptId>/draft
Authorization: Bearer <ADMIN_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "script": {
    "version": "xhs-qr-login-v15",
    "engineVersion": 2,
    "timeoutMs": 180000,
    "description": "打开小红书后从相册识别二维码并确认电脑端登录",
    "steps": [
      {
        "id": "launch-xhs",
        "action": "launchApp",
        "params": {
          "platform": "xhs",
          "appSlot": "app1",
          "restart": true
        },
        "timeoutMs": 25000,
        "assert": {
          "anyPackage": [
            "com.xingin.xhs",
            "com.miui.securitycore",
            "com.android.intentresolver",
            "android"
          ]
        },
        "description": "重启主应用小红书"
      }
    ]
  }
}
```

### 6.3 发布脚本

```http
POST /api/v1/workflow-scripts/<scriptId>/publish
Authorization: Bearer <ADMIN_API_TOKEN>
```

### 6.4 草稿下发测试

```http
POST /api/v1/workflow-scripts/<scriptId>/test
Authorization: Bearer <ADMIN_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "payload": {
    "qrImageDataUrl": "data:image/jpeg;base64,...",
    "fileName": "xhs-login-qr.jpg",
    "xhsAccount": "懂车大师冬"
  }
}
```

### 6.5 回滚上一版

```http
POST /api/v1/workflow-scripts/<scriptId>/rollback
Authorization: Bearer <ADMIN_API_TOKEN>
```

## 7. 设备、SIM 和账号管理

### 7.1 查看设备列表

```http
GET /api/v1/devices
Authorization: Bearer <ADMIN_API_TOKEN 或 BUSINESS_API_TOKEN>
```

返回：

```json
{
  "devices": [
    {
      "deviceId": "10AF2J03F7009RL",
      "deviceName": "redmi-M2010J19SC",
      "model": "M2010J19SC",
      "androidVersion": "12",
      "appVersion": "0.3.11",
      "batteryLevel": 86,
      "lastSeenAt": "2026-06-15T10:17:03.333Z",
      "liveConnected": true,
      "liveConnectionCount": 1,
      "liveStatus": {
        "connected": true,
        "connecting": false,
        "reconnectAttempt": 0,
        "watchdogTimeoutMs": 90000,
        "lastOpenAt": 1781518620000,
        "lastMessageAt": 1781518680000,
        "lastReconnectAt": 0,
        "msSinceLastMessage": 12000,
        "watchdogReconnectCount": 0,
        "lastDisconnectReason": "",
        "lastFailure": "",
        "lastReconnectReason": ""
      },
      "sims": [
        {
          "subscriptionId": 1,
          "slotIndex": 0,
          "carrierName": "中国移动",
          "phoneNumber": "16680433836",
          "label": "卡1",
          "xhsAccount": "",
          "xhsAppSlot": "app1",
          "enabled": true,
          "lastSeenAt": "2026-06-15T10:17:03.333Z"
        }
      ],
      "xhsAccounts": [
        {
          "appSlot": "app1",
          "accountName": "懂车大师冬",
          "label": "主号",
          "enabled": true,
          "updatedAt": "2026-06-15T10:17:03.333Z"
        }
      ],
      "xhsTargets": [
        {
          "label": "小红书",
          "packageName": "com.xingin.xhs",
          "activityName": "com.xingin.xhs.index.v2.IndexActivityV2",
          "appSlot": "app1"
        }
      ]
    }
  ]
}
```

### 7.2 绑定 SIM 手机号

```http
PUT /api/v1/devices/<deviceId>/sims/<subscriptionId>
Authorization: Bearer <ADMIN_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "phoneNumber": "16680433836",
  "label": "卡1",
  "enabled": true
}
```

说明：SIM 只负责接收短信验证码，和小红书账号没有必然关系。

### 7.3 绑定本机小红书账号

```http
PUT /api/v1/devices/<deviceId>/xhs-accounts/<appSlot>
Authorization: Bearer <ADMIN_API_TOKEN>
Content-Type: application/json
```

`appSlot`：`app1` 或 `app2`。

请求：

```json
{
  "accountName": "懂车大师冬",
  "label": "主号",
  "enabled": true
}
```

说明：

- `app1`：普通小红书。
- `app2`：系统双开/分身小红书。
- 如果只配置 `app1`，就按单开处理；如果 `app1/app2` 都配置了账号，就按双开处理。

## 8. 短信事件

### 8.1 查看短信事件

```http
GET /api/v1/sms-events
Authorization: Bearer <ADMIN_API_TOKEN 或 BUSINESS_API_TOKEN>
```

返回：

```json
{
  "events": [],
  "retentionMinutes": 30
}
```

### 8.2 APK 上报短信

```http
POST /api/v1/sms-events
Authorization: Bearer <DEVICE_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "deviceId": "10AF2J03F7009RL",
  "subscriptionId": 1,
  "slotIndex": 0,
  "sender": "小红书",
  "body": "【小红书】验证码 135790，5 分钟内有效，请勿泄露。",
  "platform": "小红书",
  "receivedAt": "2026-06-15T10:00:18.000Z",
  "eventFingerprint": "device-message-unique-id"
}
```

服务端会重新从短信正文解析验证码，不依赖客户端传入的 `code`。

返回：

```json
{
  "ok": true,
  "event": {
    "id": "sms-event-id",
    "eventFingerprint": "device-message-unique-id",
    "deviceId": "10AF2J03F7009RL",
    "subscriptionId": 1,
    "slotIndex": 0,
    "phoneNumber": "16680433836",
    "sender": "小红书",
    "platform": "小红书",
    "code": "135790",
    "body": "【小红书】验证码 135790，5 分钟内有效，请勿泄露。",
    "status": "matched",
    "matchedActivationId": "activation-id",
    "receivedAt": "2026-06-15T10:00:18.000Z",
    "createdAt": "2026-06-15T10:00:18.500Z",
    "expiresAt": "2026-06-15T10:30:18.000Z"
  }
}
```

## 9. Android 设备专用接口

### 9.1 设备心跳

```http
POST /api/v1/devices/heartbeat
Authorization: Bearer <DEVICE_API_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "deviceId": "10AF2J03F7009RL",
  "deviceName": "redmi-M2010J19SC",
  "phoneNumber": "",
  "phoneNumbers": ["16680433836"],
  "model": "M2010J19SC",
  "androidVersion": "12",
  "appVersion": "0.3.11",
  "batteryLevel": 86,
  "sims": [
    {
      "slotIndex": 0,
      "subscriptionId": 1,
      "carrierName": "中国移动",
      "enabled": true
    }
  ],
  "xhsTargets": [
    {
      "label": "小红书",
      "packageName": "com.xingin.xhs",
      "activityName": "com.xingin.xhs.index.v2.IndexActivityV2",
      "appSlot": "app1"
    }
  ],
  "liveStatus": {
    "connected": true,
    "connecting": false,
    "reconnectAttempt": 0,
    "watchdogTimeoutMs": 90000,
    "lastOpenAt": 1781518620000,
    "lastMessageAt": 1781518680000,
    "lastReconnectAt": 0,
    "msSinceLastMessage": 12000,
    "watchdogReconnectCount": 0,
    "lastDisconnectReason": "",
    "lastFailure": "",
    "lastReconnectReason": ""
  }
}
```

返回：

```json
{
  "ok": true,
  "device": {}
}
```

### 9.2 手机领取接码窗口

```http
GET /api/v1/devices/<deviceId>/activation-windows
Authorization: Bearer <DEVICE_API_TOKEN>
```

作用：APK 收到 `activation_available` 后立即调用。服务端会把匹配该设备 SIM 的订单从 `arming` 改为 `waiting`。

返回：

```json
{
  "windows": [
    {
      "activationId": "activation-id",
      "status": "waiting",
      "phoneNumber": "16680433836",
      "platform": "小红书",
      "purpose": "login",
      "expiresAt": "2026-06-15T10:05:00.000Z",
      "secondsLeft": 280,
      "subscriptionId": 1,
      "slotIndex": 0
    }
  ]
}
```

### 9.3 手机领取任务

```http
GET /api/v1/devices/<deviceId>/commands/next
Authorization: Bearer <DEVICE_API_TOKEN>
```

无任务：

```json
{
  "command": null
}
```

有任务时服务端会把最早的 `queued` 改成 `running` 并返回完整 payload。

## 10. WebSocket 长连接

```http
GET /api/v1/devices/<deviceId>/live
Authorization: Bearer <DEVICE_API_TOKEN>
Upgrade: websocket
```

说明：

- 只允许 `device` token。
- `deviceId` 必须和 APK 自身设备 ID 一致。
- WebSocket 只传“通知信号”，不传二维码图片、完整脚本、截图、短信正文。
- 任务领取、状态上报、轨迹上报仍走 HTTP。
- APK `0.3.11+` 有本地 watchdog：超过 90 秒未收到服务端文本消息，会主动重建 WebSocket，并通过 heartbeat 上报 `liveStatus.lastReconnectReason=watchdog_timeout`。

服务端下行：

```json
{
  "type": "hello",
  "serverTime": "2026-06-15T10:17:03.333Z"
}
```

```json
{
  "type": "ping",
  "serverTime": "2026-06-15T10:17:33.333Z"
}
```

```json
{
  "type": "command_available",
  "commandId": "command-id",
  "commandType": "xhs_qr_from_gallery",
  "createdAt": "2026-06-15T10:17:03.333Z"
}
```

```json
{
  "type": "activation_available",
  "activationId": "activation-id",
  "phoneNumber": "16680433836",
  "platform": "小红书",
  "createdAt": "2026-06-15T10:17:03.333Z"
}
```

客户端可回：

```json
{
  "type": "pong",
  "clientTime": 1781518680000
}
```

## 11. App 更新

### 11.1 获取最新版本

```http
GET /api/v1/app-release/latest
Authorization: Bearer <ADMIN_API_TOKEN 或 DEVICE_API_TOKEN>
```

返回：

```json
{
  "ok": true,
  "release": {
    "versionCode": 29,
    "versionName": "0.3.11",
    "minSupportedVersionCode": 0,
    "mandatory": false,
    "releaseNotes": "长连接自检重连：APK 会记录最近一次服务端 hello/ping/任务通知时间，超过 90 秒无消息会主动重建 WebSocket，并在心跳中上报 watchdog_timeout、最近断开原因和重连次数，便于定位省电/弱网导致的长连接假在线。",
    "publishedAt": "2026-06-15T18:05:00+08:00",
    "sizeBytes": 1415187,
    "sha256": "8ad1486a989c0ff351fa4c1d9aca0d430e8cb7b4f59c486d6b74ff3158cc85b7",
    "downloadUrl": "http://47.98.127.132/api/v1/app-release/latest/download"
  }
}
```

### 11.2 下载最新 APK

```http
GET /api/v1/app-release/latest/download
Authorization: Bearer <ADMIN_API_TOKEN 或 DEVICE_API_TOKEN>
```

返回 APK 文件：

```http
Content-Type: application/vnd.android.package-archive
Content-Disposition: attachment; filename="sms-relay-latest.apk"
```

## 12. SSE 实时流

```http
GET /api/v1/stream
Authorization: Bearer <BUSINESS_API_TOKEN 或 ADMIN_API_TOKEN>
```

事件类型：

| 事件 | 含义 |
| --- | --- |
| `device` | 设备心跳、长连接状态变化 |
| `command` | 任务创建、领取、完成、失败 |
| `activation` | 接码订单创建、手机确认、收到验证码、过期 |
| `sms` | 收到短信事件 |

示例：

```text
event: command
data: {"commandId":"...","status":"running"}
```

## 13. 兼容调试接口

这些接口是旧调试页兼容接口，新业务不建议使用：

```http
GET /api/events
GET /api/devices
GET /api/code-requests
```

## 14. 匹配规则和注意事项

- 双卡并发靠 Android 上报的 `subscriptionId` 精确匹配。
- 服务端用 `deviceId + subscriptionId` 找到绑定手机号。
- 接码订单同一 `phoneNumber + platform` 同时只允许一个 `arming/waiting` 订单。
- 业务端必须等 `activation.status=waiting` 后再触发第三方平台发送验证码。
- 短信只匹配 `receivedAt >= activation.createdAt - 5s` 的记录。
- `clientRequestId` 用于业务幂等。
- `eventFingerprint` 用于短信去重。
- 如果短信缺少 `subscriptionId`，且设备绑定了多个启用手机号，会标记为 `ambiguous`，不会自动完成订单。
- 手机号和小红书账号是独立关系：接码只看手机号，扫码只看小红书账号/app 槽位。
- 长连接只保证 APK 进程存活时更快收到通知；如果系统杀死 APK，仍需要前台服务、省电白名单、自启动、最近任务锁定或后续厂商 Push。

## 15. curl 示例

### 15.1 创建验证码订单

```bash
curl -s \
  -H "Authorization: Bearer $BUSINESS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "phoneNumber": "16680433836",
    "platform": "小红书",
    "ttlSeconds": 300,
    "clientRequestId": "xhs-login-demo-001"
  }' \
  http://47.98.127.132/api/v1/activations
```

### 15.2 轮询到手机就绪

```bash
curl -s \
  -H "Authorization: Bearer $BUSINESS_API_TOKEN" \
  "http://47.98.127.132/api/v1/activations/<activationId>/status"
```

确认返回 `status=waiting` 后，再去第三方平台发送验证码。

### 15.3 等待验证码

```bash
curl -s \
  -H "Authorization: Bearer $BUSINESS_API_TOKEN" \
  "http://47.98.127.132/api/v1/activations/<activationId>/wait?timeout=60"
```

### 15.4 下发二维码扫码任务

```bash
IMG_DATA="$(base64 -i ./xhs-login-qr.jpeg | tr -d '\n')"

curl -s \
  -H "Authorization: Bearer $BUSINESS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": \"xhs_qr_from_gallery\",
    \"payload\": {
      \"qrImageDataUrl\": \"data:image/jpeg;base64,$IMG_DATA\",
      \"fileName\": \"xhs-login-qr.jpeg\",
      \"strategy\": \"server_workflow_script\",
      \"autoConfirmLogin\": true,
      \"xhsAccount\": \"懂车大师冬\",
      \"xhsAppSlot\": \"app1\"
    }
  }" \
  http://47.98.127.132/api/v1/devices/<deviceId>/commands
```

### 15.5 查看任务轨迹

```bash
curl -s \
  -H "Authorization: Bearer $BUSINESS_API_TOKEN" \
  "http://47.98.127.132/api/v1/device-commands/<commandId>/events"
```
