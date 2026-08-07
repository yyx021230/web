# 手机云控平台实施方案

> 快速开工入口见 [PHONE_CLOUD_QUICK_START.md](./PHONE_CLOUD_QUICK_START.md)。

## 0. 执行摘要

本方案要建设的是一套“阿里云平台 + Windows 管理器 + Android 手机 Agent”的手机云控系统。用户通过阿里云网站使用手机资源；Windows 主机负责用 USB ADB 管理真实手机；手机 Agent 负责短信接收和小红书二维码扫码。

第一版不追求大而全，只完成两个可运营闭环：

- 短信验证码接收。
- 小红书二维码扫码确认登录。

第一轮验收以两台真实手机为准：

- 平台能看到 Windows 管理器和两台手机。
- Windows 能通过 ADB 安装、授权、启动手机 Agent。
- 两台手机都能收短信并把验证码回传到网页。
- 两台手机都能执行小红书二维码扫码任务。
- 失败时有任务轨迹、截图和明确错误原因。

当前仓库已有 `sms-code-center`，里面已经具备短信订单、短信事件、设备心跳、手机任务、小红书扫码脚本和 Android APK。第一版应优先复用这些能力，新开发重点是 Windows 管理器和正式平台化。

## 0.1 阅读路径

- 只想看最终方案：读 `1-4`。
- 想看系统怎么开发：读 `14`、`16`、`22-24`、`26`。
- 想部署到阿里云：读 `18`、`20.5`。
- 想安装 Windows 管理器：读 `19`、`25`。
- 想用两台手机测试：读 `10`、`15`、`17`、`27`、`28`。
- 想评估风险：读 `12`。

## 0.2 目录

- `1-4`：目标、架构、三端职责、V1 业务范围。
- `5-8`：系统模块、数据模型、Windows 管理器、手机 Agent。
- `9-13`：部署、两台手机验收、开发阶段、风险、完成标准。
- `14-17`：接口契约、联调手册、第一轮任务拆分、验收清单。
- `18-21`：阿里云上线、Windows 运维、MVP 排期、开工确认项。
- `22-25`：当前仓库复用策略、目录结构、开发顺序、实测命令。
- `26-28`：MVP 开发任务看板、端到端测试矩阵、上线判定。

## 0.3 关键决策

- 用户入口只放在阿里云网站，Windows 主机不暴露公网端口。
- Windows 管理器主动连接阿里云，使用 HTTPS/WSS。
- 手机 Agent 主动连接阿里云，使用 HTTPS/WSS。
- 第一版只支持短信接收和小红书二维码扫码。
- 第一版只用两台手机验收，不先做 100 台并发压测。
- 第一版复用现有 Android APK，不重新写手机端。
- 第一版在现有 `sms-code-center` 基础上增强，不做大迁移。
- 第一版新增 `phone-windows-agent` 作为 Windows ADB 管理器。
- 同一台手机同一时间只执行一个业务任务。
- ADB 命令必须白名单化，不开放任意 shell。

## 1. 目标

建设一套可落地的手机云控平台：

- 阿里云服务器承载网站、API、数据库、任务队列和文件存储。
- Windows 主机作为本地管理器，通过 USB ADB 管理真实手机。
- 手机安装 Agent APK，用于短信接收和小红书二维码扫码。
- 用户通过网页使用手机资源，不需要接触 Windows 主机。
- 第一阶段只支持两个业务能力：
  - 短信验证码接收。
  - 小红书二维码扫码确认登录。

当前可先用两台手机完成闭环测试，确认稳定后再扩展到 10 台、30 台、100 台。

## 2. 总体架构

```text
用户浏览器
  -> HTTPS
阿里云平台
  - Web 网站
  - API 服务
  - Postgres 数据库
  - 任务队列
  - 截图/日志文件存储
  <- HTTPS/WSS ->
Windows 管理器
  - ADB 设备扫描
  - APK 安装/升级
  - 权限授权
  - Agent 启动/保活
  - 设备诊断
  <- USB ADB ->
手机 Agent
  - 短信监听
  - 设备心跳
  - 小红书扫码
  - 轨迹/截图/日志回传
```

关键原则：

- Windows 主机不暴露公网端口。
- Windows 管理器主动连接阿里云平台。
- 手机 Agent 也主动连接阿里云平台。
- 用户只访问阿里云网站。
- 同一台手机同一时间只执行一个业务任务。
- 批量任务必须限流，避免 ADB 和 USB 集体卡死。

### 2.1 通信路径和公网访问方式

用户要“在哪里都能访问”，公网入口只需要放在阿里云：

```text
用户浏览器
  -> https://phone.example.com
阿里云平台
  <- HTTPS/WSS 长连接
Windows 管理器
  <- USB ADB
手机
```

Windows 不需要公网 IP，也不需要路由器端口映射。Windows 只要能访问互联网，就可以主动连到阿里云。任务下发采用两种方式：

- 首选：Windows 管理器和阿里云保持 WSS 长连接，平台有新任务时立即推送。
- 兜底：Windows 管理器每 2 秒 HTTP 轮询一次 `tasks/next`，长连接断开也能继续工作。

这种设计的好处：

- 用户只访问阿里云域名，不接触 Windows 主机。
- Windows 放在办公室、家里、机房都可以。
- Windows 所在网络不需要开放入站端口。
- 安全组只需要开放阿里云的 `80/443`，数据库和 Windows 都不暴露公网。
- 后续多台 Windows 管理器时，只要每台用独立 token 主动连接同一个平台即可。

第一版不建议使用内网穿透直接暴露 Windows，因为 Windows 上有 ADB 和手机控制能力，暴露公网后的安全风险过高。

## 3. 三端职责

### 3.1 阿里云平台

平台是用户入口和任务总控。

核心能力：

- 用户登录和权限控制。
- 设备池管理：手机状态、SIM、手机号、小红书账号。
- Windows 管理器管理：在线状态、版本、连接手机数。
- 短信接收订单：创建、等待、匹配、返回验证码。
- 小红书扫码任务：创建、排队、执行、结果展示。
- 任务队列：排队、执行中、成功、失败、超时。
- 执行轨迹：步骤日志、截图、当前包名、UI 摘要。
- 审计日志：用户操作、设备操作、任务结果。
- APK 版本管理：上传、发布、Windows 一键安装到手机。

### 3.2 Windows 管理器

Windows 主机负责所有和 USB ADB 有关的本地管理能力。

核心能力：

- 定时执行 `adb devices -l`，发现手机。
- 读取设备信息：序列号、型号、系统版本、电量、前台应用。
- 给手机安装或升级 Agent APK。
- 给 Agent 授权运行所需权限。
- 启动 Agent App 和前台服务。
- 采集诊断信息：截图、logcat、dumpsys、当前前台页面。
- 上报 Windows 自身心跳：主机名、IP、Agent 版本、ADB 状态。
- 接收平台下发的 ADB 运维任务。

Windows 管理器建议做成 Windows Service：

- 开机自启。
- 崩溃自动重启。
- 本地保留日志。
- 网络断开后自动重连。
- ADB server 异常时自动重启 ADB server。

### 3.3 手机 Agent

手机 Agent 是安装在每台 Android 手机上的 APK。

核心能力：

- 设备心跳。
- WebSocket 长连接。
- 短信广播接收。
- 通知监听兜底接码。
- SIM 信息读取。
- 接收任务并执行。
- 小红书扫码自动化。
- 回传任务状态、错误、截图和 UI 摘要。

现有 `sms-code-center/android/SmsRelay` 已经具备大量基础能力：

- 短信上报。
- 设备心跳。
- WebSocket。
- 接码订单窗口。
- 小红书二维码扫码任务。
- 无障碍执行轨迹。

因此第一版应优先复用并整理现有 APK，不建议重新从零开发手机端。

## 4. 第一阶段业务范围

### 4.1 短信接收

用户流程：

```text
1. 用户进入网页，选择一个手机号或一台手机。
2. 用户创建短信接收订单。
3. 平台找到绑定该手机号的手机。
4. 手机 Agent 确认进入监听窗口。
5. 平台显示“可以发送验证码”。
6. 用户在第三方平台触发验证码。
7. 手机收到短信并上传。
8. 平台按手机号、平台、时间窗口匹配订单。
9. 页面实时显示验证码。
```

重要规则：

- 订单创建后不要立刻触发验证码，必须等手机确认监听。
- 旧短信不能匹配新订单。
- 同一手机号同一平台同一时间只允许一个等待订单。
- 双卡设备优先按 `subscriptionId` 精确匹配。
- 无法确认手机号时标记为异常，不自动返回验证码。

### 4.2 小红书二维码扫码

用户流程：

```text
1. 用户上传小红书登录二维码。
2. 用户选择手机或小红书账号。
3. 平台创建扫码任务。
4. 手机 Agent 领取任务。
5. 手机保存二维码到相册。
6. 手机打开小红书。
7. 手机进入扫码页并选择相册二维码。
8. 手机点击确认登录。
9. 平台展示成功或失败轨迹。
```

第一版限制：

- 只支持小红书。
- 优先支持已安装小红书的手机。
- 一台手机一次只执行一个扫码任务。
- 失败必须回传步骤、截图、当前包名和 UI 摘要。

## 5. 系统模块

### 5.1 Web 管理后台

页面建议：

- 登录页。
- 总览页：在线手机、可用手机号、执行中任务、异常设备。
- 设备池：设备列表、状态、Windows 管理器、手机号、小红书账号。
- 设备详情：SIM、权限、最近任务、截图、诊断、日志。
- 短信接收：创建订单、等待状态、验证码结果。
- 小红书扫码：上传二维码、选择手机、查看结果。
- 任务队列：全部任务、执行轨迹、失败原因。
- Windows 管理器：在线状态、连接设备、ADB 健康状态。
- APK 版本：上传 APK、发布版本、批量安装。
- 审计日志：用户操作和设备操作记录。

### 5.2 API 服务

API 按角色分三类：

- 用户 API：网页登录后调用。
- Windows Agent API：Windows 管理器调用。
- 手机 Agent API：Android APK 调用。

鉴权方式：

- 用户：账号密码登录，后续可加 JWT。
- Windows 管理器：独立 `AGENT_TOKEN` 或每台 Windows 独立密钥。
- 手机 Agent：`DEVICE_TOKEN`，后续可升级为设备绑定密钥。

### 5.3 任务系统

任务类型：

- `sms_receive`：短信接收订单。
- `xhs_qr_scan`：小红书二维码扫码。
- `adb_install_apk`：安装或升级 APK。
- `adb_grant_permissions`：授权。
- `adb_start_agent`：启动手机 Agent。
- `adb_screenshot`：采集截图。
- `adb_logcat`：采集日志。

状态：

- `queued`：排队中。
- `running`：执行中。
- `succeeded`：成功。
- `failed`：失败。
- `cancelled`：取消。
- `timeout`：超时。

执行规则：

- 同设备串行。
- 跨设备并发。
- Windows 管理器断线时任务保持排队。
- 手机 Agent 断线时业务任务失败或等待重试。
- 所有失败都写入 `task_events`。

## 6. 数据模型

核心表：

- `users`
  - 用户账号、角色、状态。
- `windows_agents`
  - Windows 主机、版本、在线状态、最近心跳、ADB 状态。
- `devices`
  - 手机设备、ADB 序列号、Android ID、型号、系统版本、电量、状态。
- `device_sims`
  - SIM 槽位、手机号、运营商、是否启用。
- `xhs_accounts`
  - 小红书账号、所属手机、App 槽位、备注。
- `sms_orders`
  - 接码订单、手机号、平台、状态、验证码、过期时间。
- `sms_events`
  - 短信事件、发送方、正文、验证码、匹配订单。
- `device_tasks`
  - 任务主表、任务类型、目标设备、状态、载荷、结果。
- `task_events`
  - 任务步骤、日志、截图、错误、UI 摘要。
- `artifacts`
  - 截图、日志、上传二维码、APK 文件。
- `audit_logs`
  - 操作审计。

## 7. Windows 管理器实施细节

### 7.1 环境准备

Windows 主机需要：

- Windows 10/11 64 位。
- ADB Platform Tools。
- 手机厂商 USB 驱动。
- 稳定供电 USB Hub。
- 关闭系统睡眠。
- 关闭 USB 省电。
- 手机逐台开启 USB 调试并确认授权。

### 7.1.1 USB 和 Hub 原则

两台手机测试时，一台普通稳定 Windows 主机加一个独立供电 Hub 就够，不需要上来就买很夸张的配置。

Hub 需要具备的性质：

- 独立供电，不依赖电脑 USB 口给所有手机供电。
- 单口供电稳定，至少能长期维持手机不掉线。
- 数据传输稳定，不只是充电 Hub。
- 每个口最好有独立开关，方便单台手机断电恢复。
- 线材短而稳定，优先 0.5-1 米。
- 避免廉价多层级级联，尤其是一个 Hub 后面再挂多个 Hub。

Hub 可以接 Hub，但不建议作为常态扩容方式。原因是 ADB 对连接稳定性敏感，深层级 Hub 级联后容易出现：

- 某台手机偶发 `offline`。
- ADB 扫描变慢。
- 多台同时截图或安装 APK 时卡住。
- 供电波动导致手机反复断连。

可接受的方式：

- 2-8 台：一个独立供电 USB Hub。
- 10-20 台：两个独立供电 Hub，分别接到电脑不同 USB 控制器或不同主板接口。
- 30 台以上：优先增加 Windows 主机，而不是继续堆 Hub。

USB 2.0 和 USB 3.0 都可以用于本项目。短信接收和二维码扫码的数据量很小，真正重要的是稳定性，不是带宽。实际建议：

- 只做 ADB 控制、短信、截图、扫码：USB 2.0 足够。
- 批量安装 APK、频繁拉截图或 logcat：USB 3.0 更快。
- 无论 USB 2.0 还是 3.0，都要关闭 Windows 的 USB 选择性暂停。

主板背后的 USB 口不等于每个口都是独立控制器。很多接口共享同一个 USB 控制器和带宽。扩容时不要只看“有几个孔”，要看稳定连接数。第一版两台手机不用纠结；到 10 台以上再按实际掉线率决定是否增加独立 PCIe USB 控制卡。

### 7.2 ADB 白名单

Windows 管理器只能执行白名单命令，不开放任意 shell。

第一版白名单：

- `adb devices -l`
- `adb -s <serial> get-state`
- `adb -s <serial> shell getprop`
- `adb -s <serial> shell dumpsys battery`
- `adb -s <serial> install -r <apk>`
- `adb -s <serial> shell pm grant <package> <permission>`
- `adb -s <serial> shell am start <component>`
- `adb -s <serial> shell input keyevent`
- `adb -s <serial> exec-out screencap -p`
- `adb -s <serial> logcat -d`

禁止第一版开放：

- 任意 `adb shell` 输入。
- 删除数据。
- 恢复出厂。
- 卸载系统应用。
- 刷机。

### 7.3 Windows 管理器 API

Windows -> 平台：

- `POST /api/agent/heartbeat`
- `POST /api/agent/devices/sync`
- `POST /api/agent/tasks/:id/events`
- `POST /api/agent/tasks/:id/status`
- `POST /api/agent/artifacts`

平台 -> Windows：

- `WSS /api/agent/live`
- `GET /api/agent/tasks/next`

WebSocket 优先，HTTP 轮询兜底。

## 8. 手机 Agent 实施细节

手机 Agent 权限：

- `RECEIVE_SMS`
- `READ_SMS`
- `READ_PHONE_STATE`
- `READ_PHONE_NUMBERS`
- `POST_NOTIFICATIONS`
- `FOREGROUND_SERVICE`
- `WAKE_LOCK`
- `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`
- 无障碍服务：用于小红书扫码。
- 通知监听服务：用于短信通知兜底。

手机 Agent API：

- `POST /api/device/heartbeat`
- `POST /api/device/sms-events`
- `GET /api/device/:deviceId/activation-windows`
- `GET /api/device/:deviceId/tasks/next`
- `POST /api/device/tasks/:taskId/events`
- `POST /api/device/tasks/:taskId/status`
- `WSS /api/device/:deviceId/live`

## 9. 部署方案

### 9.1 阿里云服务器

建议配置：

- 2 核 4G 可启动测试。
- 4 核 8G 更适合正式早期使用。
- 系统：Ubuntu 22.04/24.04。
- 数据库：Postgres。
- 反代：Nginx。
- HTTPS：Let's Encrypt 或阿里云证书。
- 文件：本地磁盘起步，后续接 OSS。

部署服务：

- Web/API 服务。
- Postgres。
- Nginx。
- 后台任务进程。
- 日志轮转。
- 备份脚本。

### 9.2 Windows 主机

建议第一阶段：

- 一台 Windows 主机。
- 两台测试手机。
- 一个稳定 USB Hub。
- 安装 Windows 管理器。
- Windows 管理器连接阿里云。

扩容阶段：

- 10 台以内：一台 Windows 主机即可。
- 30 台以内：仍可一台，重点看 Hub 稳定性。
- 100 台：建议 3-4 台 Windows 主机，每台 25-35 台更稳。

### 9.3 Windows 硬件配置建议

这套系统的瓶颈通常不是 CPU，而是 USB 稳定性、供电、手机自身响应速度和任务调度。

两台手机开发测试：

- CPU：普通 i5/R5 或以上。
- 内存：16GB。
- 磁盘：256GB SSD。
- 网络：普通千兆网口或稳定 Wi-Fi。
- USB：一个独立供电 Hub。

10 台以内：

- CPU：i5/R5 级别即可。
- 内存：16-32GB。
- 磁盘：512GB SSD。
- 网络：千兆有线更稳。
- USB：1-2 个独立供电 Hub。

30 台左右：

- CPU：i7/R7 更舒服，但不是硬性要求。
- 内存：32GB。
- 磁盘：1TB SSD。
- 网络：千兆有线。
- USB：多个独立供电 Hub，最好分散到不同 USB 控制器。

100 台不建议硬塞到一台机器。更可实施的方式是：

- 3-4 台 Windows 管理器。
- 每台 25-35 台手机。
- 每台独立供电 Hub。
- 阿里云平台统一调度。

这样比“单台超高配置电脑 + 很多 Hub”更稳，坏一台 Windows 也不会影响全部手机。

## 10. 两台手机验收计划

### 10.1 基础接入

验收项：

- Windows ADB 能识别两台手机。
- 平台显示 Windows 管理器在线。
- 平台显示两台手机 ADB 在线。
- 手机 Agent 安装成功。
- 手机 Agent 在线。
- 手机型号、系统版本、电量可见。

### 10.2 短信接收

验收项：

- 手机 1 绑定手机号后可接收验证码。
- 手机 2 绑定手机号后可接收验证码。
- 平台订单进入 `waiting` 后再发送验证码。
- 验证码能在网页显示。
- 旧短信不会误匹配。
- 手机断网/离线时订单能超时。

### 10.3 小红书扫码

验收项：

- 手机 1 能完成小红书二维码扫码。
- 手机 2 能完成小红书二维码扫码。
- 任务执行轨迹完整。
- 失败时能看到失败步骤和截图。
- 手机锁屏或熄屏时能唤醒，不能唤醒时有明确失败原因。

### 10.4 稳定性

验收项：

- Windows 管理器重启后自动恢复。
- 手机拔插后状态自动更新。
- 手机 Agent 重启后自动恢复。
- 网络断开恢复后不会产生重复任务。
- 两台手机同时执行不同任务时互不影响。

## 11. 开发阶段

### 阶段 0：现状确认

- 确认现有 `sms-code-center` 服务可启动。
- 确认现有 Android APK 可编译。
- 确认两台手机 ADB 可连接。
- 确认小红书安装和登录状态。

### 阶段 1：平台基础

- 整理服务端模块。
- 建立正式配置文件。
- 增加用户登录。
- 建立设备、Windows 管理器、任务、审计模型。
- 管理页能查看设备和任务。

### 阶段 2：Windows 管理器

- 实现 ADB 扫描。
- 实现 Windows 心跳。
- 实现设备同步。
- 实现 APK 安装。
- 实现权限授权。
- 实现启动 Agent。
- 实现截图和 logcat 诊断。

### 阶段 3：短信接收

- 完成手机号绑定。
- 完成短信订单。
- 完成手机监听确认。
- 完成短信匹配。
- 完成网页实时展示验证码。

### 阶段 4：小红书扫码

- 完成二维码上传。
- 完成扫码任务创建。
- 完成手机执行扫码。
- 完成结果和失败轨迹展示。

### 阶段 5：两台手机联调

- 跑完整测试清单。
- 修复机型兼容问题。
- 固化操作手册。

### 阶段 6：小规模扩容

- 扩到 5-10 台。
- 加任务限流。
- 加异常告警。
- 优化设备分组。

## 12. 风险和对策

- USB 不稳定：使用独立供电 Hub，短线，关闭 Windows USB 省电。
- ADB 卡死：Windows 管理器监控 ADB server，必要时自动重启。
- 手机省电杀后台：开启前台服务、忽略电池优化、开机自启。
- 无障碍服务被关闭：平台检测状态，提示人工开启。
- 小红书页面变化：脚本可版本化，失败时保留截图和 UI 摘要。
- 短信广播被系统限制：短信广播为主，通知监听兜底。
- 任务重复执行：任务状态机和幂等 ID 控制。
- 用户误操作：审计日志、任务确认、危险操作禁用。

## 13. 第一版完成标准

第一版完成必须满足：

- 阿里云平台可通过 HTTPS 访问。
- Windows 管理器在线并能上报两台手机。
- 两台手机 Agent 在线。
- 网页能创建短信接收订单并拿到验证码。
- 网页能上传小红书二维码并让手机完成扫码。
- 失败时有截图和错误轨迹。
- Windows 重启、手机拔插后系统能恢复。

达到以上标准后，再进入 10 台以上扩容阶段。

## 14. 第一版接口契约

本节用于指导第一轮开发。字段命名先统一为 camelCase，数据库字段可以继续使用 snake_case。

### 14.1 Windows 管理器注册和心跳

Windows 管理器启动后，先向平台注册或刷新自身信息。

```http
POST /api/v1/windows-agents/heartbeat
Authorization: Bearer <AGENT_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "agentId": "win-office-001",
  "agentName": "办公室一号管理器",
  "hostname": "WIN-ADB-01",
  "osVersion": "Windows 11 Pro",
  "agentVersion": "0.1.0",
  "adbVersion": "Android Debug Bridge version 1.0.41",
  "adbServerStatus": "running",
  "localIp": "192.168.10.20",
  "deviceCount": 2,
  "startedAt": "2026-06-21T10:00:00.000Z"
}
```

返回：

```json
{
  "ok": true,
  "serverTime": "2026-06-21T10:00:03.000Z",
  "agent": {
    "agentId": "win-office-001",
    "status": "online"
  }
}
```

### 14.2 Windows 管理器同步 ADB 设备

Windows 管理器定时扫描本机 ADB，并把全量结果同步给平台。

```http
POST /api/v1/windows-agents/:agentId/devices/sync
Authorization: Bearer <AGENT_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "scannedAt": "2026-06-21T10:01:00.000Z",
  "devices": [
    {
      "adbSerial": "10AF3K0G7Y00AJA",
      "adbState": "device",
      "transportId": "1",
      "model": "M2010J19SC",
      "product": "fog",
      "androidVersion": "12",
      "androidId": "abc123",
      "batteryLevel": 86,
      "foregroundPackage": "com.ztqc.smsrelay",
      "agentInstalled": true,
      "agentVersion": "0.3.15"
    }
  ]
}
```

`adbState` 取值：

- `device`：已授权可用。
- `unauthorized`：手机未确认 USB 调试授权。
- `offline`：ADB 看到设备但不可用。
- `missing`：平台已知设备本次扫描缺失，由服务端计算。

### 14.3 Windows 管理器领取运维任务

WebSocket 优先，HTTP 轮询兜底。

```http
GET /api/v1/windows-agents/:agentId/tasks/next
Authorization: Bearer <AGENT_TOKEN>
```

返回：

```json
{
  "task": {
    "taskId": "task-uuid",
    "type": "adb_install_apk",
    "target": {
      "adbSerial": "10AF3K0G7Y00AJA",
      "deviceId": "device-uuid"
    },
    "payload": {
      "apkUrl": "https://example.com/releases/phone-agent.apk",
      "packageName": "com.ztqc.smsrelay"
    },
    "timeoutSeconds": 180
  }
}
```

第一版 Windows 运维任务类型：

- `adb_install_apk`
- `adb_grant_permissions`
- `adb_start_agent`
- `adb_screenshot`
- `adb_logcat`
- `adb_restart_adb_server`
- `adb_wake_device`

### 14.4 手机 Agent 心跳

手机 Agent 上报设备和业务状态。

```http
POST /api/v1/devices/heartbeat
Authorization: Bearer <DEVICE_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "deviceId": "android-id",
  "adbSerial": "10AF3K0G7Y00AJA",
  "deviceName": "redmi-01",
  "model": "M2010J19SC",
  "androidVersion": "12",
  "appVersion": "0.3.15",
  "batteryLevel": 86,
  "agentStatus": {
    "foregroundService": true,
    "webSocketConnected": true,
    "accessibilityEnabled": true,
    "notificationListenerEnabled": true
  },
  "sims": [
    {
      "subscriptionId": 1,
      "slotIndex": 0,
      "carrierName": "中国移动",
      "phoneNumber": "13800138000"
    }
  ]
}
```

### 14.5 短信接收订单

创建订单：

```http
POST /api/v1/sms-orders
Authorization: Bearer <USER_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "phoneNumber": "13800138000",
  "platform": "小红书",
  "purpose": "login",
  "ttlSeconds": 300,
  "clientRequestId": "xhs-login-20260621-001"
}
```

订单状态：

- `arming`：平台已创建，等待目标手机确认监听窗口。
- `waiting`：手机已确认监听，可以发送验证码。
- `received`：已收到验证码。
- `expired`：超时。
- `ambiguous`：手机号/SIM/短信归属不明确。
- `cancelled`：已取消。

查询订单：

```http
GET /api/v1/sms-orders/:orderId
Authorization: Bearer <USER_TOKEN>
```

手机上传短信：

```http
POST /api/v1/devices/sms-events
Authorization: Bearer <DEVICE_TOKEN>
Content-Type: application/json
```

### 14.6 小红书二维码扫码任务

创建扫码任务：

```http
POST /api/v1/xhs/qr-scan-tasks
Authorization: Bearer <USER_TOKEN>
Content-Type: application/json
```

请求：

```json
{
  "deviceId": "device-uuid",
  "xhsAccountId": "xhs-account-uuid",
  "qrImageDataUrl": "data:image/png;base64,...",
  "autoConfirmLogin": true,
  "clientRequestId": "xhs-qr-20260621-001"
}
```

任务状态：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `timeout`

任务事件：

```http
POST /api/v1/device-tasks/:taskId/events
Authorization: Bearer <DEVICE_TOKEN>
Content-Type: application/json
```

事件字段：

```json
{
  "stepIndex": 4,
  "stepId": "open-album",
  "phase": "action",
  "level": "info",
  "message": "点击扫码页相册入口",
  "packageName": "com.xingin.xhs",
  "uiSnapshot": "当前页面文本摘要",
  "screenshot": {
    "mimeType": "image/jpeg",
    "data": "base64..."
  }
}
```

## 15. 两台手机联调手册

### 15.1 Windows 主机准备

1. 安装 Android Platform Tools。
2. 安装对应手机厂商 USB 驱动。
3. 关闭 Windows 睡眠。
4. 关闭 USB 选择性暂停。
5. 使用独立供电 USB Hub。
6. 插入两台手机。
7. 两台手机开启开发者选项和 USB 调试。
8. 两台手机都点击“允许 USB 调试”。

确认命令：

```powershell
adb devices -l
```

期望：

```text
List of devices attached
<serial-1> device ...
<serial-2> device ...
```

如果出现 `unauthorized`，先在手机上重新确认授权。

### 15.2 手机准备

两台手机都需要：

- 插入可收短信的 SIM。
- 安装小红书。
- 安装手机 Agent APK。
- 授权短信权限。
- 授权通知权限。
- 开启通知监听服务。
- 开启无障碍服务。
- 允许忽略电池优化。
- 小红书账号保持可用状态。

### 15.3 第一轮测试顺序

按这个顺序测，能最快定位问题：

1. Windows ADB 识别两台手机。
2. Windows 管理器上报阿里云在线。
3. 平台显示两台手机 ADB 在线。
4. Windows 给两台手机安装 Agent。
5. Windows 启动两台手机 Agent。
6. 平台显示两台手机 Agent 在线。
7. 绑定手机 1 的手机号。
8. 给手机 1 创建短信订单。
9. 手机 1 收短信，平台显示验证码。
10. 绑定手机 2 的手机号。
11. 给手机 2 创建短信订单。
12. 手机 2 收短信，平台显示验证码。
13. 上传小红书二维码给手机 1 扫码。
14. 上传小红书二维码给手机 2 扫码。
15. 查看成功任务和失败任务轨迹。

### 15.4 必须保留的测试证据

每轮测试都记录：

- Windows 管理器日志。
- 平台任务 ID。
- 手机设备 ID。
- 短信订单 ID。
- 二维码扫码任务 ID。
- 失败截图。
- 失败 UI 摘要。
- ADB 设备列表截图或文本。

## 16. 第一轮开发任务拆分

### 16.1 最小可用版本

目标：两台手机完成短信接收和小红书扫码。

必须完成：

- 平台服务可启动。
- 管理页可访问。
- Windows 管理器可启动。
- Windows 管理器可同步 ADB 设备。
- 手机 Agent 可安装和心跳。
- 平台可创建短信订单。
- 手机可上传短信。
- 平台可展示验证码。
- 平台可创建小红书二维码扫码任务。
- 手机可执行扫码任务并回传结果。

### 16.2 开发优先级

第一优先级：

- Windows 管理器设备同步。
- 手机 Agent 安装/启动链路。
- 短信订单链路。
- 小红书扫码链路。
- 任务事件和失败截图。

第二优先级：

- 用户权限。
- APK 版本管理。
- 审计日志。
- 设备分组。
- 任务重试。

第三优先级：

- 多 Windows 管理器。
- 多用户隔离。
- 费用/计量。
- 告警系统。
- OSS 文件存储。

### 16.3 不在第一版做

- 支持其他 App。
- 任意 ADB shell。
- 复杂计费系统。
- 手机远程实时投屏。
- 批量 100 台并发压测。
- 自动注册小红书账号。

## 17. 开发完成验收清单

开发完成前逐条检查：

- 阿里云平台 HTTPS 可访问。
- 用户能登录。
- Windows 管理器在线。
- Windows 管理器能看到两台 ADB 手机。
- 平台能看到两台手机。
- 手机 Agent 在线。
- 两台手机 SIM 和手机号绑定正确。
- 手机 1 短信接收成功。
- 手机 2 短信接收成功。
- 手机 1 小红书扫码成功。
- 手机 2 小红书扫码成功。
- 失败任务有轨迹和截图。
- Windows 管理器重启后自动恢复。
- 手机拔插后状态自动恢复。
- 网络短断后不会重复执行同一任务。
- 操作日志可追溯。

## 18. 阿里云上线清单

### 18.1 服务器准备

第一阶段两台手机测试建议：

- ECS：2 核 4G 起步。
- 系统：Ubuntu 22.04 LTS 或 Ubuntu 24.04 LTS。
- 磁盘：40G 起步，建议 80G。
- 带宽：3-5 Mbps 起步。
- 安全组开放：
  - `80/tcp`：证书申请和 HTTP 跳转。
  - `443/tcp`：网站、API、WebSocket。
  - `22/tcp`：SSH，仅限固定 IP 更好。
- 不开放数据库端口到公网。
- 不开放 Windows 管理器端口到公网。

正式早期建议：

- ECS：4 核 8G。
- 磁盘：100G 以上。
- 数据库可以先同机 Postgres，后续迁移到阿里云 RDS。
- 截图和日志先本地存储，后续迁移到 OSS。

### 18.2 域名和 HTTPS

建议准备一个独立域名：

```text
phone.example.com
```

Nginx 统一反代：

- `/` -> Web 管理后台。
- `/api/` -> API 服务。
- `/ws/` -> WebSocket。
- `/uploads/` -> 截图、日志、二维码文件。

HTTPS 证书：

- 测试期可用 Let's Encrypt。
- 正式可用阿里云证书。
- 手机 Agent 和 Windows 管理器都只连接 HTTPS/WSS。

### 18.3 环境变量

平台服务至少需要：

```text
NODE_ENV=production
PORT=8787
PUBLIC_BASE_URL=https://phone.example.com
DATABASE_URL=postgres://...
JWT_SECRET=...
ADMIN_BOOTSTRAP_PASSWORD=...
WINDOWS_AGENT_TOKEN=...
DEVICE_AGENT_TOKEN=...
UPLOAD_DIR=/opt/phone-cloud/uploads
APK_RELEASE_DIR=/opt/phone-cloud/releases
```

密钥要求：

- `JWT_SECRET` 至少 32 字符随机字符串。
- `WINDOWS_AGENT_TOKEN` 和 `DEVICE_AGENT_TOKEN` 分开。
- 后续多 Windows 管理器时，每台 Windows 独立 token。

### 18.4 服务进程

第一阶段推荐：

- Postgres：Docker 或系统服务。
- 平台 API：systemd 管理 Node 进程。
- Nginx：系统服务。
- 日志：journald + 文件日志。

systemd 目标：

- 开机自启。
- 崩溃自动重启。
- 环境变量独立文件管理。
- 日志可通过 `journalctl` 查询。

### 18.5 备份

每天备份：

- Postgres 数据库。
- 上传文件目录。
- APK 发布目录。
- `.env` 配置单独安全保存。

保留策略：

- 本机保留最近 7 天。
- 远端保留最近 30 天。
- 重要版本上线前手动备份一次。

## 19. Windows 管理器安装和运维方案

### 19.1 安装目录

建议安装到：

```text
C:\ztqc-phone-agent
```

目录结构：

```text
C:\ztqc-phone-agent
  agent.exe 或 node dist\index.js
  config.json
  platform-tools\
  logs\
  cache\
  apk\
```

### 19.2 配置文件

`config.json`：

```json
{
  "agentId": "win-office-001",
  "agentName": "办公室一号管理器",
  "serverBaseUrl": "https://phone.example.com",
  "agentToken": "replace-with-token",
  "adbPath": "C:\\ztqc-phone-agent\\platform-tools\\adb.exe",
  "scanIntervalSeconds": 10,
  "heartbeatIntervalSeconds": 15,
  "taskPollIntervalSeconds": 2,
  "maxConcurrentAdbTasks": 4,
  "deviceTaskConcurrency": 1
}
```

并发建议：

- 两台手机测试：`maxConcurrentAdbTasks=2`。
- 10 台手机：`maxConcurrentAdbTasks=4`。
- 30 台手机：`maxConcurrentAdbTasks=8`。
- 安装 APK、截图、logcat 这类重任务不要全设备同时跑。

### 19.3 Windows Service

Windows 管理器最终应注册为服务：

- 服务名：`ZtqcPhoneWindowsAgent`
- 开机自启。
- 失败后 30 秒重启。
- 本地日志轮转。

第一阶段开发期也可以先用命令行运行，便于观察日志。

### 19.4 ADB 异常恢复

Windows 管理器需要内置这些恢复动作：

- ADB 连续扫描失败 3 次，执行 `adb kill-server` 和 `adb start-server`。
- 某设备连续 `offline`，标记设备异常，不强行继续任务。
- 某设备 `unauthorized`，平台提示“请在手机上确认 USB 调试授权”。
- 任务超时后停止等待，回传失败和最后一次诊断。
- Windows 网络断开后，任务不丢失，恢复连接后重新同步状态。

### 19.5 本地日志

Windows 本地至少记录：

- Agent 启动/停止。
- 连接平台成功/失败。
- ADB 扫描结果。
- 每个任务的命令、耗时、退出码。
- stderr 摘要。
- 上传失败重试。

日志脱敏：

- 不记录完整 token。
- 短信正文默认不写 Windows 本地日志。
- 上传二维码不写原始 base64。

## 20. MVP 开发排期

### 20.1 第 1 个里程碑：本地两台手机可见

目标：

- Windows 管理器能扫描两台手机。
- 阿里云平台能看到 Windows 管理器和两台手机。
- 设备状态能实时更新。

交付：

- Windows 管理器基础进程。
- `windows_agents` 和 `devices` 数据模型。
- 管理页设备列表。
- ADB 状态同步 API。

验收：

- 拔掉手机 1，网页显示手机 1 离线。
- 插回手机 1，网页恢复在线。
- 手机 2 不受影响。

### 20.2 第 2 个里程碑：APK 安装和保活

目标：

- 平台可以让 Windows 给手机安装 Agent APK。
- 平台可以让 Windows 启动 Agent。
- 手机 Agent 能向平台心跳。

交付：

- APK 发布目录。
- Windows `adb_install_apk` 任务。
- Windows `adb_start_agent` 任务。
- 手机 Agent 心跳 API。
- 设备详情页显示 Agent 在线状态。

验收：

- 两台手机都能一键安装 Agent。
- 两台手机都能一键启动 Agent。
- 平台显示两台手机 Agent 在线。

### 20.3 第 3 个里程碑：短信接收闭环

目标：

- 用户可创建短信订单。
- 手机可上报短信。
- 平台可匹配并显示验证码。

交付：

- 手机号绑定页面。
- 短信订单 API。
- 短信事件 API。
- 订单状态页面。
- WebSocket 或轮询刷新。

验收：

- 手机 1 收码成功。
- 手机 2 收码成功。
- 旧短信不误匹配。
- 订单超时正常。

### 20.4 第 4 个里程碑：小红书扫码闭环

目标：

- 用户上传二维码。
- 手机执行小红书扫码。
- 平台展示执行结果和失败轨迹。

交付：

- 二维码上传。
- 小红书扫码任务 API。
- 手机任务领取。
- 执行事件和截图上传。
- 任务详情页。

验收：

- 手机 1 扫码成功。
- 手机 2 扫码成功。
- 失败时能看到截图和步骤。

### 20.5 第 5 个里程碑：稳定性和上线

目标：

- 两台手机连续使用稳定。
- 阿里云 HTTPS 部署完成。
- Windows 管理器开机自启。

交付：

- systemd 部署。
- Nginx HTTPS。
- Windows Service。
- 备份脚本。
- 操作手册。

验收：

- Windows 重启后自动恢复。
- 阿里云服务重启后恢复。
- 手机拔插后恢复。
- 网络短断后恢复。

## 21. 开工前确认项

开发前需要确认：

- 阿里云服务器公网 IP。
- 是否已有域名；没有域名则先用 IP + HTTP 测试，再补 HTTPS。
- Windows 主机是否已准备。
- 两台手机品牌、Android 版本、小红书是否已安装。
- 两台手机 SIM 是否能收短信。
- 是否允许先复用现有 `sms-code-center` 的 Android APK。
- 小红书扫码目标是“登录确认”还是还包括其他扫码动作。

默认决策：

- 默认复用现有 Android APK。
- 默认 Windows 管理器不暴露公网。
- 默认阿里云平台作为唯一用户入口。
- 默认第一版只支持管理员用户，不先做多租户计费。
- 默认两台手机先跑通，再扩容。

## 22. 当前仓库复用与改造策略

当前仓库已经有一个可运行雏形：`sms-code-center`。第一版不建议推倒重写，应在它的基础上做正式化和扩展。

### 22.1 可直接复用的服务端能力

位置：

```text
sms-code-center/server.mjs
```

已有能力：

- `devices`：设备心跳和设备列表。
- `device_sims`：SIM 和手机号绑定。
- `device_xhs_accounts`：手机上的小红书账号槽位。
- `activations`：短信接收订单。
- `sms_events`：短信上报和匹配。
- `device_commands`：手机任务队列。
- `device_command_events`：任务执行轨迹。
- `workflow_scripts`：小红书扫码脚本。
- `/api/v1/stream`：管理页 SSE 实时更新。
- `/api/v1/devices/:deviceId/live`：手机 WebSocket 长连接。

改造方向：

- 保留短信订单状态机。
- 保留短信匹配规则。
- 保留小红书扫码任务类型 `xhs_qr_from_gallery`。
- 保留任务轨迹和截图回传设计。
- 新增 `windows_agents` 表。
- 新增 Windows 运维任务类型。
- 新增 Windows 管理器 API。
- 把单文件服务逐步拆成模块，但第一轮可以先保持单文件，避免过早重构影响测试速度。

### 22.2 可直接复用的手机 Agent 能力

位置：

```text
sms-code-center/android/SmsRelay/app/src/main/java/com/ztqc/smsrelay
```

已有关键类：

- `RelayForegroundService`：前台服务、心跳、任务轮询。
- `DeviceLiveClient`：WebSocket 长连接。
- `RelayClient`：手机端 API 客户端。
- `SmsReceiver`：短信广播接收。
- `SmsNotificationListenerService`：短信通知兜底。
- `SimInfoReader`：SIM 信息读取。
- `DeviceCommandExecutor`：任务执行入口。
- `ScanAccessibilityService`：小红书扫码无障碍流程。
- `XhsAppDiscovery`：小红书主应用/双开入口发现。
- `AppUpdater`：APK 更新能力。

改造方向：

- 保留包名 `com.ztqc.smsrelay`，避免第一版重新处理权限和安装兼容。
- 保留短信接收逻辑。
- 保留小红书扫码自动化逻辑。
- 增加上报 `adbSerial` 字段，方便平台把 ADB 设备和手机 Agent 设备合并。
- 增加权限状态上报：短信权限、通知监听、无障碍、电池优化。
- 增加更清晰的失败原因枚举。

### 22.3 需要新增的 Windows 管理器

建议新增目录：

```text
phone-windows-agent/
```

职责：

- 本地运行在 Windows 主机。
- 管理 `adb.exe`。
- 扫描 USB 手机。
- 同步 ADB 设备到平台。
- 安装/升级手机 Agent APK。
- 授权运行时权限。
- 启动手机 Agent。
- 采集截图和 logcat。
- 后续打包成 Windows Service。

第一版语言选择：

- 推荐 Node.js + TypeScript，和当前 `sms-code-center` 技术栈接近，开发快。
- 后续如果要降低部署依赖，再考虑 Go 打包成单文件 exe。

### 22.4 管理页复用策略

位置：

```text
sms-code-center/public/index.html
sms-code-center/public/app.js
sms-code-center/public/styles.css
```

已有能力：

- 设备库存页。
- 设备详情页。
- SIM/小红书账号维护。
- 短信订单列表。
- 短信事件列表。
- 二维码扫码任务。
- 任务轨迹查看。
- APK 版本展示。

改造方向：

- 增加 Windows 管理器页面。
- 增加 ADB 在线状态和 Agent 在线状态区分。
- 增加一键安装 APK、一键授权、一键启动 Agent。
- 增加两台手机联调页面或检查清单。
- 先保留原生 HTML/JS，后续再考虑迁移到 React。

## 23. 建议代码目录结构

第一轮为了快，建议保留 `sms-code-center` 为主项目目录，并新增 Windows 管理器目录。

```text
sms-code-center/
  server.mjs
  public/
    index.html
    app.js
    styles.css
    releases/
  android/
    SmsRelay/
  docs/
  package.json

phone-windows-agent/
  package.json
  src/
    index.ts
    config.ts
    logger.ts
    apiClient.ts
    adb/
      adbClient.ts
      parsers.ts
      tasks.ts
    services/
      heartbeatService.ts
      deviceScanService.ts
      taskRunnerService.ts
    types.ts
  config.example.json
  README.md
```

后续正式化后可以再演进成：

```text
phone-cloud/
  server/
  web/
  android-agent/
  windows-agent/
  deploy/
```

但第一轮不建议一开始就大迁移，先把真实两台手机跑通更重要。

## 24. 第一轮具体开发顺序

### 24.1 服务端先补 Windows 管理器模型

在 `sms-code-center/server.mjs` 增加：

- `windows_agents` 表。
- `windows_agent_events` 表。
- Windows 心跳接口。
- Windows 设备同步接口。
- Windows 任务领取接口。
- Windows 任务状态回传接口。

第一轮不改已有短信和扫码 API，只增加 Windows 管理层。

### 24.2 Windows 管理器先做只读扫描

先实现：

- 读取配置。
- 调用 `adb devices -l`。
- 解析设备列表。
- 对 `device` 状态设备读取 `getprop` 和电量。
- 上报平台。
- 本地打印日志。

不急着做安装 APK，先让网页看到两台 ADB 手机。

### 24.3 再做 APK 安装和启动

确认设备同步稳定后，再实现：

- 下载平台 APK。
- `adb install -r`。
- `pm grant` 授权。
- `am start` 启动 Agent。
- 回传任务执行步骤。

### 24.4 最后打通业务闭环

顺序：

1. 手机 Agent 在线。
2. 短信接收成功。
3. 小红书扫码成功。
4. 失败轨迹可读。

这个顺序能最快区分问题在 ADB、Agent、平台还是小红书脚本。

## 25. 两台手机首次实测命令清单

在 Windows 上先人工确认：

```powershell
adb version
adb devices -l
adb -s <serial> shell getprop ro.product.model
adb -s <serial> shell getprop ro.build.version.release
adb -s <serial> shell dumpsys battery
adb -s <serial> shell dumpsys window | findstr mCurrentFocus
```

安装 Agent：

```powershell
adb -s <serial> install -r phone-agent.apk
```

授权：

```powershell
adb -s <serial> shell pm grant com.ztqc.smsrelay android.permission.RECEIVE_SMS
adb -s <serial> shell pm grant com.ztqc.smsrelay android.permission.READ_SMS
adb -s <serial> shell pm grant com.ztqc.smsrelay android.permission.READ_PHONE_STATE
adb -s <serial> shell pm grant com.ztqc.smsrelay android.permission.POST_NOTIFICATIONS
```

启动：

```powershell
adb -s <serial> shell am start -n com.ztqc.smsrelay/.MainActivity
```

注意：

- 无障碍服务和通知监听通常不能完全靠 ADB 普通权限授权，需要人工打开或通过特定厂商设置引导。
- 如果手机弹出 USB 调试授权，必须人工点允许。
- Android 13+ 的通知权限需要确认授权状态。

## 26. MVP 开发任务看板

本节把第一版拆成可以直接开发的任务卡。每张任务卡都必须有代码、可运行验证和验收证据。

### 26.1 服务端任务

#### S1. Windows 管理器数据模型

交付：

- `windows_agents` 表。
- `windows_agent_events` 表。
- `devices` 增加 `windows_agent_id`、`adb_serial`、`adb_state`、`adb_updated_at`。

验收：

- 服务启动后自动迁移或初始化表结构。
- 能保存一台 Windows 管理器心跳。
- 能把一台 ADB 手机关联到 Windows 管理器。

#### S2. Windows 管理器 API

交付：

- `POST /api/v1/windows-agents/heartbeat`
- `POST /api/v1/windows-agents/:agentId/devices/sync`
- `GET /api/v1/windows-agents/:agentId/tasks/next`
- `POST /api/v1/windows-agents/:agentId/tasks/:taskId/status`
- `POST /api/v1/windows-agents/:agentId/tasks/:taskId/events`

验收：

- 使用 curl 可以注册 Windows 管理器。
- 使用 curl 可以同步两台测试设备。
- 同步后管理页能看到设备归属。

#### S3. 运维任务队列

交付：

- 支持 Windows 执行的任务类型：
  - `adb_install_apk`
  - `adb_grant_permissions`
  - `adb_start_agent`
  - `adb_screenshot`
  - `adb_logcat`
- 任务写入统一任务表。
- 任务事件写入统一轨迹表。

验收：

- 平台能创建安装 APK 任务。
- Windows 管理器能领取任务。
- 执行结果能回写成功或失败。

#### S4. 设备状态合并

交付：

- 设备详情同时展示：
  - ADB 在线状态。
  - 手机 Agent 在线状态。
  - 所属 Windows 管理器。
  - 最近 ADB 更新时间。
  - 最近 Agent 心跳时间。

验收：

- 手机只插 USB 但 Agent 未启动时，显示 ADB 在线、Agent 离线。
- Agent 启动后，显示 ADB 在线、Agent 在线。
- 手机拔线后，ADB 状态变离线。

### 26.2 Windows 管理器任务

#### W1. 基础项目和配置

交付：

- `phone-windows-agent/package.json`
- `config.example.json`
- 配置读取。
- 日志输出。
- 平台 API 客户端。

验收：

- 在 Windows 命令行能启动。
- 配置错误时给出清晰提示。
- Token 不在日志中明文输出。

#### W2. ADB 扫描

交付：

- 调用 `adb devices -l`。
- 解析 `adbState`、`adbSerial`、`model`、`product`、`transportId`。
- 对可用设备读取系统版本、电量。
- 定时同步平台。

验收：

- 两台手机连接时平台显示两台。
- 拔掉一台时平台状态更新。
- `unauthorized` 时能在平台显示授权异常。

#### W3. ADB 任务执行器

交付：

- 单设备串行锁。
- 全局并发限制。
- 超时控制。
- stdout/stderr 摘要。
- 任务状态和事件回传。

验收：

- 同一台手机不会同时执行两个任务。
- 任务超时会失败并回传原因。
- ADB 命令失败时能看到退出码和 stderr 摘要。

#### W4. APK 安装和启动

交付：

- 下载 APK。
- `adb install -r`。
- `pm grant`。
- `am start`。
- 权限结果检测。

验收：

- 两台手机都能由平台触发安装。
- 两台手机都能由平台触发启动。
- 手机 Agent 启动后平台显示在线。

### 26.3 手机 Agent 任务

#### A1. 心跳增强

交付：

- 心跳增加 `adbSerial`。
- 心跳增加权限状态。
- 心跳增加无障碍/通知监听状态。

验收：

- 设备详情能看到权限缺失项。
- 未开无障碍时能明确提示。

#### A2. 短信接收稳定化

交付：

- 保留现有短信广播。
- 保留通知监听兜底。
- 增强短信事件去重。
- 增强订单监听窗口状态。

验收：

- 手机 1 收码成功。
- 手机 2 收码成功。
- 重复短信不上报成多个有效验证码。

#### A3. 小红书扫码稳定化

交付：

- 保留 `xhs_qr_from_gallery`。
- 增强每步失败截图。
- 增强当前包名和 UI 摘要回传。
- 保留脚本版本号。

验收：

- 手机 1 扫码成功。
- 手机 2 扫码成功。
- 失败时能判断卡在哪一步。

### 26.4 Web 管理页任务

#### P1. Windows 管理器页面

交付：

- 管理器列表。
- 管理器详情。
- 已连接设备数。
- 最近心跳。
- ADB 健康状态。

验收：

- Windows 管理器启动后页面显示在线。
- Windows 管理器停止后页面显示离线。

#### P2. 设备详情增强

交付：

- 展示 ADB 状态。
- 展示 Agent 状态。
- 展示权限检查。
- 展示操作按钮：安装 APK、授权、启动 Agent、截图、日志。

验收：

- 对两台手机分别执行操作。
- 操作结果进入任务轨迹。

#### P3. 两个业务入口

交付：

- 短信接收页面。
- 小红书扫码页面。
- 任务详情页。
- 失败轨迹弹窗或侧栏。

验收：

- 用户能在页面完成收码。
- 用户能在页面上传二维码并完成扫码。

## 27. 端到端测试矩阵

### 27.1 基础状态测试

| 场景 | 期望 |
| --- | --- |
| Windows 管理器启动 | 平台显示管理器在线 |
| Windows 管理器停止 | 平台在超时后显示离线 |
| 两台手机插入 | 平台显示两台 ADB 在线 |
| 拔掉手机 1 | 手机 1 离线，手机 2 不受影响 |
| 手机 USB 未授权 | 平台显示 `unauthorized` |
| 手机 Agent 未启动 | ADB 在线，Agent 离线 |
| 手机 Agent 启动 | ADB 在线，Agent 在线 |

### 27.2 短信测试

| 场景 | 期望 |
| --- | --- |
| 手机 1 创建短信订单 | 订单进入 `arming` |
| 手机 1 确认监听 | 订单进入 `waiting` |
| 手机 1 收到验证码 | 订单进入 `received` |
| 手机 2 收到验证码 | 不会匹配手机 1 的订单 |
| 旧短信到达 | 不匹配新订单 |
| 未绑定手机号收到短信 | 标记未匹配或异常 |
| 订单超时 | 状态变 `expired` |

### 27.3 小红书扫码测试

| 场景 | 期望 |
| --- | --- |
| 上传合法二维码 | 创建扫码任务成功 |
| 上传过大图片 | 前端或后端拒绝 |
| 手机 1 执行扫码 | 成功或回传明确失败步骤 |
| 手机 2 执行扫码 | 成功或回传明确失败步骤 |
| 小红书未安装 | 任务失败并提示未安装 |
| 无障碍未开启 | 任务失败并提示开启无障碍 |
| 二维码过期 | 任务失败并保留截图 |

### 27.4 稳定性测试

| 场景 | 期望 |
| --- | --- |
| Windows 重启 | 管理器自动恢复上线 |
| 阿里云服务重启 | Windows 和手机自动重连 |
| 手机拔插 | 状态自动恢复 |
| 网络短断 | 不重复执行已完成任务 |
| ADB server 卡死 | Windows 管理器尝试恢复 |
| 同一手机连续下发两个任务 | 串行执行 |
| 两台手机同时执行任务 | 互不影响 |

## 28. 第一版上线判定

只有以下全部满足，才算第一版可以交付试用：

- 用户可以通过阿里云网站登录。
- Windows 管理器可以稳定在线。
- 两台手机 ADB 状态准确。
- 两台手机 Agent 状态准确。
- 手机 1 短信接收成功。
- 手机 2 短信接收成功。
- 手机 1 小红书扫码成功。
- 手机 2 小红书扫码成功。
- 所有失败都有任务轨迹。
- 至少连续运行 24 小时无服务崩溃。
- Windows 重启后自动恢复。
- 阿里云服务重启后自动恢复。
