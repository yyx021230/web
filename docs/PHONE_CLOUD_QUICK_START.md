# 手机云控平台开工清单

这是一页式开工清单。完整方案见 [PHONE_CLOUD_IMPLEMENTATION_PLAN.md](./PHONE_CLOUD_IMPLEMENTATION_PLAN.md)。

## 1. 第一版目标

用阿里云平台 + Windows 管理器 + 两台 Android 手机，先跑通两个业务闭环：

- 短信验证码接收。
- 小红书二维码扫码确认登录。

第一版不做：

- 其他 App。
- 多租户计费。
- 100 台并发压测。
- 任意 ADB shell。
- 手机实时投屏。

## 2. 当前代码策略

优先复用现有项目：

- 服务端和网页：`sms-code-center/`
- 手机 Agent：`sms-code-center/android/SmsRelay/`
- 新增 Windows 管理器：`phone-windows-agent/`

第一轮不大迁移、不重写 Android APK。先把两台真实手机跑通。

## 3. 开工前要准备

阿里云：

- ECS 公网 IP。
- 域名可后补；没有域名时先用 IP 测试。
- 安全组开放 `80`、`443`、必要时临时开放测试端口。
- 用户只访问阿里云；Windows 管理器主动连阿里云，不开放公网端口。

Windows：

- 安装 ADB Platform Tools。
- 安装手机 USB 驱动。
- 关闭睡眠和 USB 省电。
- 插入两台手机。
- 两台手机开启 USB 调试并点允许授权。
- 两台手机测试不需要高配电脑，重点是稳定独立供电 Hub 和稳定线材。
- 不建议多层 Hub 级联；扩容到 30 台以上优先增加 Windows 主机。

手机：

- 两台手机都能被 `adb devices -l` 识别为 `device`。
- 两台手机都插入可接短信 SIM。
- 两台手机都安装小红书。
- 两台手机允许安装/启动手机 Agent。

## 4. 开发顺序

### 第一步：平台识别 Windows 和手机

交付：

- `windows_agents` 表。
- Windows 心跳 API。
- Windows 设备同步 API。
- 管理页显示 Windows 管理器和两台 ADB 手机。

验收：

- Windows 管理器启动后，网页显示在线。
- 两台手机插入后，网页显示两台 ADB 在线。
- 拔掉手机 1 后，网页显示手机 1 离线，手机 2 不受影响。

### 第二步：Windows 安装和启动手机 Agent

交付：

- `adb_install_apk` 任务。
- `adb_grant_permissions` 任务。
- `adb_start_agent` 任务。
- 手机 Agent 心跳状态。

验收：

- 网页可以对手机 1 一键安装/授权/启动 Agent。
- 网页可以对手机 2 一键安装/授权/启动 Agent。
- 两台手机都显示 Agent 在线。

### 第三步：短信接收

交付：

- 手机号绑定。
- 短信订单。
- 手机监听确认。
- 短信上报和订单匹配。
- 网页显示验证码。

验收：

- 手机 1 收码成功。
- 手机 2 收码成功。
- 旧短信不误匹配。
- 订单超时状态正确。

### 第四步：小红书二维码扫码

交付：

- 二维码上传。
- 小红书扫码任务。
- 手机执行扫码。
- 任务轨迹、截图、失败原因。

验收：

- 手机 1 小红书扫码成功。
- 手机 2 小红书扫码成功。
- 失败时能看到卡在哪一步。

### 第五步：稳定性

验收：

- Windows 重启后自动恢复。
- 阿里云服务重启后自动恢复。
- 手机拔插后自动恢复。
- 两台手机同时执行任务互不影响。
- 连续运行 24 小时无服务崩溃。

## 5. 第一轮手工命令

Windows 上先确认：

```powershell
adb version
adb devices -l
adb -s <serial> shell getprop ro.product.model
adb -s <serial> shell getprop ro.build.version.release
adb -s <serial> shell dumpsys battery
```

安装手机 Agent：

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

## 6. 开发验收口径

第一版只有全部满足才算完成：

- 用户可以访问阿里云平台。
- Windows 管理器在线。
- 两台手机 ADB 在线。
- 两台手机 Agent 在线。
- 两台手机都能接短信验证码。
- 两台手机都能完成小红书二维码扫码。
- 失败任务都有轨迹和截图。
- Windows 和服务重启后能恢复。
