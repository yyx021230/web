const ONLINE_WINDOW_MS = 130_000;
const DEGRADED_WINDOW_MS = 10 * 60_000;
const QR_IMAGE_MAX_DATA_URL_LENGTH = 1_300_000;
const QR_IMAGE_MAX_SIDE = 1200;
const ACTIVE_COMMAND_STATUSES = new Set(["queued", "running"]);
const ATTENTION_COMMAND_STATUSES = new Set(["failed"]);
const APP_RELEASE_HISTORY = [
  {
    versionName: "0.2.9",
    versionCode: 17,
    date: "2026-06-12",
    title: "Android 10 SIM 兼容修复",
    tag: "Patch",
    notes: [
      "修复 Android 10 / MIUI 设备启动时读取 SIM 信息闪退的问题。",
      "SIM 兜底识别在 Android 11 以下改走 getPhoneCount，避免调用系统不存在的方法。",
      "保留 0.2.8 的通知验证码硬窗口逻辑。"
    ]
  },
  {
    versionName: "0.2.8",
    versionCode: 16,
    date: "2026-06-12",
    title: "验证码通知硬窗口",
    tag: "SMS",
    notes: [
      "通知验证码兜底只处理点击开始等待验证码之后新弹出的短信通知。",
      "旧通知只做清理，不参与验证码匹配，避免误吃历史验证码。",
      "继续以 SMS_RECEIVED 为主，通知监听作为实时补充。"
    ]
  },
  {
    versionName: "0.2.7",
    versionCode: 15,
    date: "2026-06-12",
    title: "通知监听兜底",
    tag: "SMS",
    notes: [
      "加入 NotificationListenerService，用于捕捉部分机型不触发短信广播时的验证码通知。",
      "接码窗口同步到手机端，按手机号和开始时间过滤。"
    ]
  },
  {
    versionName: "0.2.6",
    versionCode: 14,
    date: "2026-06-11",
    title: "通用自动化执行底座",
    tag: "Engine",
    notes: [
      "升级脚本 DSL v2，引入步骤超时、断言、失败截图和执行轨迹。",
      "扫码脚本改为显式重启小红书、选择双开入口、逐步断言页面状态。",
      "适配小米双开选择器和 vivo 双开入口。"
    ]
  }
];

const state = {
  token: localStorage.getItem("smsCenterToken") || "",
  devices: [],
  windowsAgents: [],
  events: [],
  activations: [],
  commands: [],
  commandEvents: {},
  activeTraceCommandId: "",
  workflowScripts: [],
  selectedWorkflowScriptId: "",
  selectedDeviceId: localStorage.getItem("smsSelectedDeviceId") || "",
  query: "",
  statusFilter: "all",
  brandFilter: "",
  androidFilter: "",
  workbenchTab: localStorage.getItem("smsWorkbenchTab") || "tasks",
  navItem: localStorage.getItem("smsNavItem") || "devices",
  queueQuery: "",
  queueStatus: "",
  queueType: "",
  accountQuery: "",
  auditQuery: "",
  auditStatus: "",
  globalWorkflowDeviceId: localStorage.getItem("smsGlobalWorkflowDeviceId") || "",
  globalWorkflowScripts: [],
  globalWorkflowScriptId: "",
  appRelease: null,
  appReleaseError: "",
  isSendingQrCommand: false,
  activationStatusPollers: new Map(),
  mockMode: false,
  stream: null
};

const els = {
  authPanel: document.getElementById("authPanel"),
  workspace: document.getElementById("workspace"),
  tokenInput: document.getElementById("tokenInput"),
  saveTokenButton: document.getElementById("saveTokenButton"),
  logoutButton: document.getElementById("logoutButton"),
  pages: document.querySelectorAll("[data-page]"),
  streamStatus: document.getElementById("streamStatus"),
  onlineCount: document.getElementById("onlineCount"),
  offlineCount: document.getElementById("offlineCount"),
  moduleTitle: document.getElementById("moduleTitle"),
  inventorySummary: document.getElementById("inventorySummary"),
  refreshButton: document.getElementById("refreshButton"),
  searchInput: document.getElementById("searchInput"),
  statusSelect: document.getElementById("statusSelect"),
  brandSelect: document.getElementById("brandSelect"),
  androidSelect: document.getElementById("androidSelect"),
  clearFiltersButton: document.getElementById("clearFiltersButton"),
  devicesList: document.getElementById("devicesList"),
  windowsSummary: document.getElementById("windowsSummary"),
  windowsRefreshButton: document.getElementById("windowsRefreshButton"),
  windowsAgentList: document.getElementById("windowsAgentList"),
  filterButtons: document.querySelectorAll("[data-status-filter]"),
  sideNavLinks: document.querySelectorAll("[data-nav-item]"),
  backToInventoryButton: document.getElementById("backToInventoryButton"),
  detailEmpty: document.getElementById("detailEmpty"),
  detailPanel: document.getElementById("detailPanel"),
  workbenchTabs: document.querySelectorAll("[data-workbench-tab]"),
  workbenchSections: document.querySelectorAll("[data-workbench-section]"),
  selectedStatus: document.getElementById("selectedStatus"),
  selectedDeviceThumb: document.getElementById("selectedDeviceThumb"),
  selectedDeviceName: document.getElementById("selectedDeviceName"),
  selectedDeviceMeta: document.getElementById("selectedDeviceMeta"),
  selectedBattery: document.getElementById("selectedBattery"),
  selectedSimCount: document.getElementById("selectedSimCount"),
  selectedLastSeen: document.getElementById("selectedLastSeen"),
  selectedLatestTask: document.getElementById("selectedLatestTask"),
  simList: document.getElementById("simList"),
  xhsAccountList: document.getElementById("xhsAccountList"),
  requestPhoneInput: document.getElementById("requestPhoneInput"),
  requestPlatformInput: document.getElementById("requestPlatformInput"),
  createRequestButton: document.getElementById("createRequestButton"),
  requestHint: document.getElementById("requestHint"),
  requestInlineList: document.getElementById("requestInlineList"),
  xhsAccountSelect: document.getElementById("xhsAccountSelect"),
  qrImageInput: document.getElementById("qrImageInput"),
  qrFilePreview: document.getElementById("qrFilePreview"),
  selectedXhsSummary: document.getElementById("selectedXhsSummary"),
  scanReadinessList: document.getElementById("scanReadinessList"),
  sendQrCommandButton: document.getElementById("sendQrCommandButton"),
  openScanButton: document.getElementById("openScanButton"),
  manageXhsAccountsButton: document.getElementById("manageXhsAccountsButton"),
  commandHint: document.getElementById("commandHint"),
  commandsList: document.getElementById("commandsList"),
  workflowScriptSelect: document.getElementById("workflowScriptSelect"),
  workflowScriptMeta: document.getElementById("workflowScriptMeta"),
  workflowScriptEditor: document.getElementById("workflowScriptEditor"),
  validateWorkflowButton: document.getElementById("validateWorkflowButton"),
  saveWorkflowDraftButton: document.getElementById("saveWorkflowDraftButton"),
  publishWorkflowButton: document.getElementById("publishWorkflowButton"),
  testWorkflowButton: document.getElementById("testWorkflowButton"),
  rollbackWorkflowButton: document.getElementById("rollbackWorkflowButton"),
  workflowHint: document.getElementById("workflowHint"),
  requestsList: document.getElementById("requestsList"),
  requestCount: document.getElementById("requestCount"),
  eventsList: document.getElementById("eventsList"),
  eventCount: document.getElementById("eventCount"),
  recordsCommandsList: document.getElementById("recordsCommandsList"),
  recordCommandCount: document.getElementById("recordCommandCount"),
  queueSummary: document.getElementById("queueSummary"),
  queueRefreshButton: document.getElementById("queueRefreshButton"),
  queueSearchInput: document.getElementById("queueSearchInput"),
  queueStatusSelect: document.getElementById("queueStatusSelect"),
  queueTypeSelect: document.getElementById("queueTypeSelect"),
  queueList: document.getElementById("queueList"),
  accountsSummary: document.getElementById("accountsSummary"),
  accountsRefreshButton: document.getElementById("accountsRefreshButton"),
  accountSearchInput: document.getElementById("accountSearchInput"),
  globalSimCount: document.getElementById("globalSimCount"),
  globalXhsCount: document.getElementById("globalXhsCount"),
  globalSimList: document.getElementById("globalSimList"),
  globalXhsList: document.getElementById("globalXhsList"),
  globalWorkflowSummary: document.getElementById("globalWorkflowSummary"),
  globalWorkflowRefreshButton: document.getElementById("globalWorkflowRefreshButton"),
  globalWorkflowDeviceSelect: document.getElementById("globalWorkflowDeviceSelect"),
  globalWorkflowScriptSelect: document.getElementById("globalWorkflowScriptSelect"),
  globalWorkflowScriptList: document.getElementById("globalWorkflowScriptList"),
  globalWorkflowTitle: document.getElementById("globalWorkflowTitle"),
  globalWorkflowMeta: document.getElementById("globalWorkflowMeta"),
  globalWorkflowEditor: document.getElementById("globalWorkflowEditor"),
  globalWorkflowQrInput: document.getElementById("globalWorkflowQrInput"),
  globalValidateWorkflowButton: document.getElementById("globalValidateWorkflowButton"),
  globalSaveWorkflowDraftButton: document.getElementById("globalSaveWorkflowDraftButton"),
  globalPublishWorkflowButton: document.getElementById("globalPublishWorkflowButton"),
  globalTestWorkflowButton: document.getElementById("globalTestWorkflowButton"),
  globalRollbackWorkflowButton: document.getElementById("globalRollbackWorkflowButton"),
  globalWorkflowHint: document.getElementById("globalWorkflowHint"),
  auditSummary: document.getElementById("auditSummary"),
  auditRefreshButton: document.getElementById("auditRefreshButton"),
  auditSearchInput: document.getElementById("auditSearchInput"),
  auditStatusSelect: document.getElementById("auditStatusSelect"),
  globalRequestCount: document.getElementById("globalRequestCount"),
  globalEventCount: document.getElementById("globalEventCount"),
  globalRequestsList: document.getElementById("globalRequestsList"),
  globalEventsList: document.getElementById("globalEventsList"),
  releaseSummary: document.getElementById("releaseSummary"),
  releaseRefreshButton: document.getElementById("releaseRefreshButton"),
  releaseDownloadButton: document.getElementById("releaseDownloadButton"),
  releaseDashboard: document.getElementById("releaseDashboard"),
  settingsRefreshButton: document.getElementById("settingsRefreshButton"),
  settingsTokenStatus: document.getElementById("settingsTokenStatus"),
  settingsTokenInput: document.getElementById("settingsTokenInput"),
  settingsSaveTokenButton: document.getElementById("settingsSaveTokenButton"),
  settingsLogoutButton: document.getElementById("settingsLogoutButton"),
  settingsRuntimeList: document.getElementById("settingsRuntimeList"),
  traceOverlay: document.getElementById("traceOverlay"),
  traceTitle: document.getElementById("traceTitle"),
  traceMeta: document.getElementById("traceMeta"),
  traceCloseButton: document.getElementById("traceCloseButton"),
  traceRefreshButton: document.getElementById("traceRefreshButton"),
  traceList: document.getElementById("traceList")
};

els.tokenInput.value = state.token;
if (els.settingsTokenInput) els.settingsTokenInput.value = state.token;

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function timeLabel(value) {
  if (!value) return "未知";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function shortTime(value) {
  if (!value) return "-";
  const diff = Date.now() - new Date(value).getTime();
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  return timeLabel(value);
}

function secondsLeft(expiresAt) {
  return Math.max(0, Math.floor((new Date(expiresAt).getTime() - Date.now()) / 1000));
}

function isOnline(device) {
  return Date.now() - new Date(device.lastSeenAt).getTime() <= ONLINE_WINDOW_MS;
}

function devicePresence(device) {
  const age = Date.now() - new Date(device.lastSeenAt).getTime();
  if (age <= ONLINE_WINDOW_MS) {
    return { key: "online", label: "在线", signal: "Online", hint: "心跳正常" };
  }
  if (age <= DEGRADED_WINDOW_MS) {
    return { key: "idle", label: "省电延迟", signal: "Delayed", hint: "手机可能熄屏省电，命令会排队等待下一次轮询" };
  }
  return { key: "offline", label: "离线", signal: "Offline", hint: "超过 10 分钟未收到心跳" };
}

function isReachable(device) {
  return devicePresence(device).key !== "offline";
}

function normalizeSearch(value) {
  return String(value || "").trim().toLowerCase();
}

function devicePhones(device) {
  return (device.sims || []).map((sim) => sim.phoneNumber).filter(Boolean);
}

function selectedDevice() {
  return state.devices.find((device) => device.deviceId === state.selectedDeviceId) || null;
}

function deviceById(deviceId) {
  return state.devices.find((device) => device.deviceId === deviceId) || null;
}

function deviceLabel(deviceId) {
  const device = deviceById(deviceId);
  return device ? (device.deviceName || device.deviceId) : deviceId || "未知设备";
}

function selectFirstDeviceIfNeeded() {
  if (selectedDevice() || !state.devices.length) return;
  state.selectedDeviceId = sortDevices(state.devices)[0].deviceId;
  localStorage.setItem("smsSelectedDeviceId", state.selectedDeviceId);
}

function latestCommandForDevice(deviceId) {
  return state.commands
    .filter((command) => command.deviceId === deviceId)
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())[0] || null;
}

function hasActiveCommand(deviceId) {
  return state.commands.some((command) => command.deviceId === deviceId && ACTIVE_COMMAND_STATUSES.has(command.status));
}

function hasAttention(device) {
  const presence = devicePresence(device);
  const latest = latestCommandForDevice(device.deviceId);
  return presence.key !== "online" || ATTENTION_COMMAND_STATUSES.has(latest?.status);
}

function deviceBrandKey(device) {
  const text = `${device.deviceName || ""} ${device.model || ""}`.toLowerCase();
  if (text.includes("vivo")) return "vivo";
  if (text.includes("oppo")) return "oppo";
  if (text.includes("xiaomi") || text.includes("redmi") || text.includes("小米")) return "xiaomi";
  if (text.includes("samsung") || text.includes("三星")) return "samsung";
  return "";
}

function androidMajor(device) {
  return String(device.androidVersion || "").match(/\d+/)?.[0] || "";
}

function mergeCommands(commands = []) {
  const byId = new Map(state.commands.map((command) => [command.commandId, command]));
  for (const command of commands) byId.set(command.commandId, command);
  state.commands = [...byId.values()]
    .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    .slice(0, 300);
}

function commandResultText(command) {
  return command?.result?.message || command?.result?.action || command?.result?.error || command?.payload?.fileName || "等待手机执行";
}

function moduleCopy(navItem = state.navItem) {
  const online = state.devices.filter((device) => devicePresence(device).key === "online").length;
  const idle = state.devices.filter((device) => devicePresence(device).key === "idle").length;
  const offline = state.devices.filter((device) => devicePresence(device).key === "offline").length;
  const reachable = online + idle;
  const running = state.commands.filter((item) => ACTIVE_COMMAND_STATUSES.has(item.status)).length;
  const copy = {
    devices: {
      title: "设备库存",
      summary: `共 ${state.devices.length} 台设备，可达 ${reachable} 台（在线 ${online}，省电延迟 ${idle}），离线 ${offline} 台${running ? `，执行中 ${running} 个任务` : ""}`,
      status: state.mockMode ? "Mock 预览" : "设备墙"
    },
    windows: {
      title: "Windows 管理器",
      summary: `共 ${state.windowsAgents.length} 台 Windows 管理器，负责 USB ADB、APK 安装、授权和 Agent 保活。`,
      status: "ADB 控制面"
    },
    queue: {
      title: "执行队列",
      summary: `全局查看所有手机的接码、扫码、唤醒任务。当前有 ${running} 个任务执行中。`,
      status: "全局任务视角"
    },
    accounts: {
      title: "号码与账号",
      summary: "全局维护手机号、SIM、平台账号和 app1/app2 映射。",
      status: "账号池视角"
    },
    scripts: {
      title: "脚本模板库",
      summary: "这里是全局脚本模板和版本入口，可按设备维护 app1/app2 脚本。",
      status: "脚本库视角"
    },
    audit: {
      title: "短信与审计",
      summary: `全量短信、订单和失败任务的审计入口。当前已载入 ${state.events.length} 条短信、${state.activations.length} 个订单。`,
      status: "审计视角"
    },
    alerts: {
      title: "App 版本维护",
      summary: "管理手机端 APK 最新版本、更新内容、下载安装和设备覆盖情况。",
      status: "Release 控制台"
    },
    settings: {
      title: "系统设置",
      summary: "管理 API Key、设备 Token、保活策略和部署配置；右上角仍可快速切换 API Key。",
      status: "系统设置"
    }
  };
  return copy[navItem] || copy.devices;
}

function selectedWorkflowScript() {
  return state.workflowScripts.find((script) => script.scriptId === state.selectedWorkflowScriptId) || state.workflowScripts[0] || null;
}

function buildMockData() {
  const now = Date.now();
  const iso = (offsetMs) => new Date(now + offsetMs).toISOString();
  const devices = [
    {
      deviceId: "38fc9d2a",
      deviceName: "vivo-Y37-formal",
      model: "vivo Y37",
      androidVersion: "14",
      appVersion: "0.5.0",
      batteryLevel: 86,
      lastSeenAt: iso(-22_000),
      sims: [
        { slotIndex: 0, subscriptionId: 1, carrierName: "中国电信", phoneNumber: "19067125562", label: "电信主卡", xhsAccount: "小红书账号 A", xhsAppSlot: "app1" },
        { slotIndex: 1, subscriptionId: 2, carrierName: "中国联通", phoneNumber: "18569413909", label: "联通副卡", xhsAccount: "小红书账号 B", xhsAppSlot: "app2" }
      ]
    },
    {
      deviceId: "6a7b8c1e",
      deviceName: "OPPO Reno8",
      model: "OPPO Reno8",
      androidVersion: "13",
      appVersion: "0.5.0",
      batteryLevel: 62,
      lastSeenAt: iso(-41_000),
      sims: [
        { slotIndex: 0, subscriptionId: 11, carrierName: "中国移动", phoneNumber: "13800138000", label: "测试移动", xhsAccount: "小红书账号 C", xhsAppSlot: "app1" },
        { slotIndex: 1, subscriptionId: 12, carrierName: "中国电信", phoneNumber: "19876543210", label: "测试电信", xhsAccount: "小红书账号 D", xhsAppSlot: "app2" }
      ]
    },
    {
      deviceId: "9d4e6f7b",
      deviceName: "小米 12 Pro",
      model: "Xiaomi 12 Pro",
      androidVersion: "13",
      appVersion: "0.4.8",
      batteryLevel: 74,
      lastSeenAt: iso(-65_000),
      sims: [
        { slotIndex: 0, subscriptionId: 21, carrierName: "中国联通", phoneNumber: "16600001111", label: "联通验证", xhsAccount: "小红书账号 E", xhsAppSlot: "app1" }
      ]
    },
    {
      deviceId: "4c9d1a2b",
      deviceName: "Redmi Note 12",
      model: "Redmi Note 12",
      androidVersion: "12",
      appVersion: "0.4.5",
      batteryLevel: null,
      lastSeenAt: iso(-7_200_000),
      sims: [
        { slotIndex: 0, subscriptionId: 31, carrierName: "中国电信", phoneNumber: "14725836900", label: "离线备用", xhsAccount: "备用账号", xhsAppSlot: "app1" }
      ]
    },
    {
      deviceId: "a1b2c3d4",
      deviceName: "vivo X90",
      model: "vivo X90",
      androidVersion: "14",
      appVersion: "0.5.0",
      batteryLevel: 91,
      lastSeenAt: iso(-50_000),
      sims: [
        { slotIndex: 0, subscriptionId: 41, carrierName: "中国移动", phoneNumber: "13911112222", label: "移动主卡", xhsAccount: "小红书账号 F", xhsAppSlot: "app1" },
        { slotIndex: 1, subscriptionId: 42, carrierName: "中国联通", phoneNumber: "13933334444", label: "联通副卡", xhsAccount: "小红书账号 G", xhsAppSlot: "app2" }
      ]
    },
    {
      deviceId: "e5f6a7b8",
      deviceName: "三星 Galaxy A54",
      model: "Samsung Galaxy A54",
      androidVersion: "13",
      appVersion: "0.4.5",
      batteryLevel: null,
      lastSeenAt: iso(-86_400_000),
      sims: [
        { slotIndex: 0, subscriptionId: 51, carrierName: "中国电信", phoneNumber: "17000000000", label: "离线卡", xhsAccount: "旧账号", xhsAppSlot: "app1" }
      ]
    }
  ];
  const activations = [
    { activationId: "mock-act-1", phoneNumber: "19067125562", platform: "小红书", status: "received", code: "123456", createdAt: iso(-300_000), updatedAt: iso(-250_000), completedAt: iso(-250_000), expiresAt: iso(120_000), deviceId: "38fc9d2a" },
    { activationId: "mock-act-2", phoneNumber: "18569413909", platform: "小红书", status: "waiting", code: "", createdAt: iso(-40_000), updatedAt: iso(-40_000), expiresAt: iso(260_000), deviceId: "38fc9d2a" },
    { activationId: "mock-act-3", phoneNumber: "13800138000", platform: "抖音", status: "expired", code: "", createdAt: iso(-900_000), updatedAt: iso(-600_000), expiresAt: iso(-600_000), deviceId: "6a7b8c1e" }
  ];
  const events = [
    { id: "mock-sms-1", deviceId: "38fc9d2a", phoneNumber: "19067125562", platform: "小红书", sender: "小红书", code: "123456", receivedAt: iso(-250_000), body: "【小红书】验证码 123456，5 分钟内有效，请勿泄露。" },
    { id: "mock-sms-2", deviceId: "38fc9d2a", phoneNumber: "18569413909", platform: "招商银行", sender: "招商银行", code: "", receivedAt: iso(-600_000), body: "【招商银行】账户动账提醒，此条不应被识别为验证码。" },
    { id: "mock-sms-3", deviceId: "6a7b8c1e", phoneNumber: "13800138000", platform: "小红书", sender: "小红书", code: "654321", receivedAt: iso(-120_000), body: "【小红书】您的验证码为 654321，请勿转发。" }
  ];
  const commands = [
    { commandId: "mock-cmd-1", deviceId: "38fc9d2a", type: "xhs_qr_from_gallery", status: "succeeded", createdAt: iso(-330_000), result: { message: "相册二维码扫码完成" } },
    { commandId: "mock-cmd-2", deviceId: "38fc9d2a", type: "open_xhs_scan", status: "succeeded", createdAt: iso(-420_000), result: { message: "设备已唤醒" } },
    { commandId: "mock-cmd-3", deviceId: "6a7b8c1e", type: "xhs_qr_from_gallery", status: "running", createdAt: iso(-35_000), result: { message: "正在等待手机领取" } },
    { commandId: "mock-cmd-4", deviceId: "9d4e6f7b", type: "open_xhs_scan", status: "failed", createdAt: iso(-680_000), result: { error: "无障碍服务未开启" } }
  ];
  const workflowScripts = [
    { scriptId: "mock-script-app1", appSlot: "app1", name: "小红书 app1 扫码", publishedVersion: 3, hasDraftChanges: false, publishedAt: iso(-3_600_000), draftScript: { version: "1.3.0", description: "Mock app1 gallery QR workflow", steps: [{ action: "tapLauncherIcon", text: "小红书", delayMs: 2000 }, { action: "tapBottomTextCenter", text: "我", delayMs: 2000 }, { action: "tapTopRightIcon", text: "扫一扫", delayMs: 2000 }, { action: "tapTextCenter", text: "相册", delayMs: 2000 }, { action: "tapFirstGalleryImage", delayMs: 10000 }, { action: "tapTextCenter", text: "确认登录", delayMs: 1000 }] } },
    { scriptId: "mock-script-app2", appSlot: "app2", name: "小红书 app2 扫码", publishedVersion: 2, hasDraftChanges: true, publishedAt: iso(-7_200_000), draftScript: { version: "1.2.0", description: "Mock app2 gallery QR workflow", steps: [{ action: "tapLauncherIcon", text: "Ⅱ·小红书", delayMs: 2000 }] } }
  ];
  return { devices, activations, events, commands, workflowScripts };
}

function loadMockData(reason = "Mock Data") {
  const mock = buildMockData();
  state.mockMode = true;
  state.devices = mock.devices;
  state.activations = mock.activations;
  state.events = mock.events;
  state.commands = mock.commands;
  state.workflowScripts = mock.workflowScripts;
  state.appRelease = {
    ...APP_RELEASE_HISTORY[0],
    mandatory: false,
    publishedAt: new Date().toISOString(),
    sizeBytes: 69_568,
    sha256: "mock-release-sha256"
  };
  state.appReleaseError = "";
  state.selectedDeviceId = state.selectedDeviceId && state.devices.some((item) => item.deviceId === state.selectedDeviceId)
    ? state.selectedDeviceId
    : state.devices[0].deviceId;
  state.selectedWorkflowScriptId = state.workflowScripts[0]?.scriptId || "";
  localStorage.setItem("smsSelectedDeviceId", state.selectedDeviceId);
  els.streamStatus.textContent = reason;
  render();
}

function isEditingSimMapping() {
  const active = document.activeElement;
  return !!active && els.simList.contains(active);
}

function isEditingXhsAccounts() {
  const active = document.activeElement;
  return !!active && els.xhsAccountList.contains(active);
}

function isEditingGlobalAccounts() {
  const active = document.activeElement;
  return !!active && (els.globalSimList?.contains(active) || els.globalXhsList?.contains(active));
}

function setSelectOptionsPreservingValue(select, html, fallbackValue = "") {
  if (!select) return;
  const previous = select.value;
  if (select.dataset.optionsSignature !== html) {
    select.innerHTML = html;
    select.dataset.optionsSignature = html;
  }
  const hasPrevious = [...select.options].some((option) => option.value === previous);
  const hasCurrent = [...select.options].some((option) => option.value === select.value);
  const nextValue = hasPrevious ? previous : (hasCurrent ? select.value : fallbackValue);
  if (nextValue && select.value !== nextValue) select.value = nextValue;
}

function selectedXhsScanTarget() {
  const option = els.xhsAccountSelect?.selectedOptions?.[0];
  if (!option || !option.value) return null;
  return {
    appSlot: option.dataset.appSlot || option.value,
    accountName: option.dataset.accountName || option.textContent.trim(),
    label: option.dataset.label || "",
    displayText: option.textContent.trim()
  };
}

function updateScanPanel() {
  const device = selectedDevice();
  const target = selectedXhsScanTarget();
  const file = els.qrImageInput?.files?.[0] || null;
  const presence = device ? devicePresence(device) : { key: "offline", label: "未选设备" };
  const hasAccounts = !!target;
  const hasFile = !!file;
  const canSend = !!device && hasAccounts && hasFile;

  if (els.qrFilePreview) {
    els.qrFilePreview.innerHTML = hasFile
      ? `<strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(formatBytes(file.size))} · 已就绪</span>`
      : `<strong>未选择二维码</strong><span>选择图片后才能下发扫码任务</span>`;
    els.qrFilePreview.classList.toggle("is-ready", hasFile);
  }

  if (els.selectedXhsSummary) {
    els.selectedXhsSummary.innerHTML = hasAccounts
      ? `
        <span>扫码将使用</span>
        <strong>${escapeHtml(target.accountName || "未命名账号")}</strong>
        <small>${escapeHtml(target.label || (target.appSlot === "app2" ? "Ⅱ·小红书" : "小红书"))} · ${escapeHtml(target.appSlot)}</small>
      `
      : `
        <span>还不能下发扫码</span>
        <strong>请先维护小红书账号</strong>
        <small>至少填写一个启用账号，才能选择 app1/app2</small>
      `;
    els.selectedXhsSummary.classList.toggle("is-empty", !hasAccounts);
  }

  if (els.scanReadinessList) {
    const checks = [
      { ok: hasAccounts, label: hasAccounts ? "账号已选择" : "缺少小红书账号" },
      { ok: hasFile, label: hasFile ? "二维码已选择" : "等待二维码图片" },
      { ok: presence.key === "online", label: presence.key === "online" ? "设备在线" : `设备${presence.label}` }
    ];
    els.scanReadinessList.innerHTML = checks.map((item) => `
      <span class="${item.ok ? "is-ok" : "is-warn"}">${escapeHtml(item.label)}</span>
    `).join("");
  }

  if (els.sendQrCommandButton) {
    els.sendQrCommandButton.disabled = state.isSendingQrCommand || !canSend;
    if (state.isSendingQrCommand) {
      els.sendQrCommandButton.textContent = "下发中...";
      return;
    }
    if (!hasAccounts) els.sendQrCommandButton.textContent = "先维护账号";
    else if (!hasFile) els.sendQrCommandButton.textContent = "先选择二维码";
    else els.sendQrCommandButton.textContent = "上传二维码并扫码";
  }
}

function statusText(status) {
  return {
    arming: "准备中",
    waiting: "等待中",
    received: "已收到",
    expired: "已过期",
    ambiguous: "需人工确认",
    cancelled: "已取消"
  }[status] || status;
}

function activationTimeHint(item) {
  if (item.status === "arming") return `等待手机确认 · ${secondsLeft(item.expiresAt)}s 后过期`;
  if (item.status === "waiting") return `手机已就绪 · ${secondsLeft(item.expiresAt)}s 后过期`;
  return timeLabel(item.completedAt || item.updatedAt);
}

function upsertActivation(item) {
  if (!item?.activationId) return;
  state.activations = [item, ...state.activations.filter((old) => old.activationId !== item.activationId)];
}

function stopActivationStatusPoll(activationId) {
  const timer = state.activationStatusPollers.get(activationId);
  if (timer) clearTimeout(timer);
  state.activationStatusPollers.delete(activationId);
}

function isActivationOpen(item) {
  return item && ["arming", "waiting"].includes(item.status);
}

function updateActivationHint(item) {
  if (!item || !els.requestHint) return;
  if (item.status === "received") {
    els.requestHint.textContent = `已收到验证码${item.code ? `：${item.code}` : ""}。`;
  } else if (item.status === "waiting") {
    els.requestHint.textContent = "手机已确认监听，可以去对应平台点击发送验证码。";
  } else if (item.status === "arming") {
    els.requestHint.textContent = "已通知手机进入监听状态，等这里变成“等待中/手机已就绪”后再去平台发送验证码。";
  } else {
    els.requestHint.textContent = `订单状态已更新：${statusText(item.status)}。`;
  }
}

function startActivationStatusPoll(activationId) {
  if (!activationId || state.activationStatusPollers.has(activationId)) return;
  let attempts = 0;
  const tick = async () => {
    attempts += 1;
    try {
      const payload = await api(`/api/v1/activations/${encodeURIComponent(activationId)}/status`);
      if (payload.activation) {
        upsertActivation(payload.activation);
        updateActivationHint(payload.activation);
        render();
        if (!isActivationOpen(payload.activation)) {
          stopActivationStatusPoll(activationId);
          return;
        }
      }
    } catch (error) {
      if (attempts >= 2 && els.requestHint) els.requestHint.textContent = error.message;
    }
    if (attempts >= 180) {
      stopActivationStatusPoll(activationId);
      return;
    }
    const current = state.activations.find((item) => item.activationId === activationId);
    state.activationStatusPollers.set(activationId, setTimeout(tick, current?.status === "waiting" ? 2000 : 1000));
  };
  state.activationStatusPollers.set(activationId, setTimeout(tick, 1000));
}

function syncActivationStatusPollers() {
  state.activations
    .filter(isActivationOpen)
    .forEach((item) => startActivationStatusPoll(item.activationId));
}

function commandStatusText(status) {
  return {
    queued: "等待手机领取",
    running: "执行中",
    succeeded: "已完成",
    failed: "失败",
    cancelled: "已取消"
  }[status] || status;
}

function commandTypeText(type) {
  return {
    xhs_qr_from_gallery: "相册二维码扫码",
    open_xhs_scan: "唤醒设备测试"
  }[type] || type;
}

function authHeaders(extra = {}) {
  return {
    ...extra,
    authorization: `Bearer ${state.token}`
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: authHeaders(options.headers || {})
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `HTTP ${response.status}`);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function setAuthenticated(authenticated) {
  els.authPanel.classList.toggle("is-hidden", authenticated);
  els.workspace.classList.toggle("is-hidden", !authenticated);
}

function sortDevices(devices) {
  const presenceRank = {
    online: 0,
    idle: 1,
    offline: 2
  };
  return [...devices].sort((a, b) => {
    const rankDiff = (presenceRank[devicePresence(a).key] ?? 3) - (presenceRank[devicePresence(b).key] ?? 3);
    if (rankDiff) return rankDiff;
    const nameDiff = String(a.deviceName || "").localeCompare(String(b.deviceName || ""), "zh-Hans-CN", {
      numeric: true,
      sensitivity: "base"
    });
    if (nameDiff) return nameDiff;
    return String(a.deviceId || "").localeCompare(String(b.deviceId || ""));
  });
}

function filteredDevices() {
  const query = normalizeSearch(state.query);
  let devices = sortDevices(state.devices);
  if (state.statusFilter === "online") {
    devices = devices.filter((device) => devicePresence(device).key === "online");
  }
  if (state.statusFilter === "idle") {
    devices = devices.filter((device) => devicePresence(device).key === "idle");
  }
  if (state.statusFilter === "offline") {
    devices = devices.filter((device) => devicePresence(device).key === "offline");
  }
  if (state.statusFilter === "running") {
    devices = devices.filter((device) => hasActiveCommand(device.deviceId));
  }
  if (state.statusFilter === "attention") {
    devices = devices.filter(hasAttention);
  }
  if (state.brandFilter) {
    devices = devices.filter((device) => deviceBrandKey(device) === state.brandFilter);
  }
  if (state.androidFilter) {
    devices = devices.filter((device) => androidMajor(device) === state.androidFilter);
  }
  if (!query) return devices;
  return devices.filter((device) => {
    const haystack = [
      device.deviceName,
      device.deviceId,
      device.model,
      device.androidVersion,
      ...devicePhones(device),
      ...(device.xhsAccounts || []).map((account) => `${account.accountName} ${account.label} ${account.appSlot}`),
      ...(device.sims || []).map((sim) => `${sim.carrierName} ${sim.label} ${sim.subscriptionId}`)
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderDeviceList() {
  const online = state.devices.filter(isReachable).length;
  const offline = Math.max(0, state.devices.length - online);
  els.onlineCount.textContent = online;
  els.offlineCount.textContent = offline;
  const copy = moduleCopy("devices");
  els.filterButtons.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.statusFilter === state.statusFilter);
  });
  if (els.statusSelect) els.statusSelect.value = state.statusFilter;
  if (els.brandSelect) els.brandSelect.value = state.brandFilter;
  if (els.androidSelect) els.androidSelect.value = state.androidFilter;

  const devices = filteredDevices();
  if (els.moduleTitle) els.moduleTitle.textContent = copy.title;
  if (els.inventorySummary) {
    const suffix = devices.length === state.devices.length ? "" : `，当前显示 ${devices.length} 台`;
    els.inventorySummary.textContent = `${copy.summary}${suffix}`;
  }
  els.devicesList.innerHTML = devices.length
    ? devices.map((device) => {
      const presence = devicePresence(device);
      const phones = devicePhones(device);
      const xhsAccounts = (device.xhsAccounts || []).filter((account) => account.enabled !== false);
      const selected = device.deviceId === state.selectedDeviceId;
      const lastCommand = latestCommandForDevice(device.deviceId);
      const taskText = lastCommand ? `${commandTypeText(lastCommand.type)} · ${commandStatusText(lastCommand.status)}` : "点开查看任务";
      const battery = device.batteryLevel == null ? "-" : `${device.batteryLevel}%`;
      const primaryPhone = phones[0] || "未绑定手机号";
      const deviceInitial = (device.deviceName || device.model || "D").slice(0, 1).toUpperCase();
      return `
        <button class="device-card ${selected ? "is-selected" : ""} is-${presence.key}" data-device-id="${escapeHtml(device.deviceId)}" title="${escapeHtml(presence.hint)}" type="button">
          <div class="device-thumb" aria-hidden="true">
            <span>${escapeHtml(deviceInitial)}</span>
          </div>
          <div class="device-main">
            <div class="device-title-line">
              <strong>${escapeHtml(device.deviceName || device.deviceId)}</strong>
              <span class="device-signal is-${presence.key}">${escapeHtml(presence.signal)}</span>
            </div>
            <small>${escapeHtml(device.model || "未知型号")} · Android ${escapeHtml(device.androidVersion || "-")} · ${escapeHtml(device.appVersion || "App -")}</small>
            <div class="device-meta-grid">
              <span><b>Battery</b>${escapeHtml(battery)}</span>
              <span><b>SIM</b>${(device.sims || []).length}</span>
              <span><b>Seen</b>${escapeHtml(shortTime(device.lastSeenAt))}</span>
            </div>
            <div class="phone-chips">
              ${phones.length ? phones.slice(0, 2).map((phone, index) => `<i>SIM ${index + 1} · ${escapeHtml(phone)}</i>`).join("") : `<i>${escapeHtml(primaryPhone)}</i>`}
            </div>
            <div class="xhs-chips">
              ${xhsAccounts.length ? xhsAccounts.slice(0, 2).map((account) => `<i>${escapeHtml(account.appSlot)} · ${escapeHtml(account.accountName || account.label || "未填小红书账号")}</i>`).join("") : `<i>未填小红书账号</i>`}
            </div>
            <div class="device-task-line">
              <span>Latest task</span>
              <b>${escapeHtml(taskText)}</b>
            </div>
          </div>
        </button>
      `;
    }).join("")
    : `<div class="empty-box">没有匹配的手机。可以点“重置筛选”，或确认 App 已启动并且 API Key 正确。</div>`;
}

function openDevicePage(deviceId, workbenchTab = state.workbenchTab) {
  state.navItem = "deviceWorkbench";
  state.selectedDeviceId = deviceId || state.selectedDeviceId;
  state.workbenchTab = workbenchTab || "tasks";
  localStorage.setItem("smsNavItem", state.navItem);
  localStorage.setItem("smsSelectedDeviceId", state.selectedDeviceId);
  localStorage.setItem("smsWorkbenchTab", state.workbenchTab);
  Promise.all([loadSelectedCommands(), loadSelectedWorkflowScripts()]).then(render).catch(showError);
}

function openInventoryPage() {
  state.navItem = "devices";
  localStorage.setItem("smsNavItem", state.navItem);
  render();
}

function renderPageVisibility() {
  const knownPage = [...els.pages].some((page) => page.dataset.page === state.navItem);
  if (!knownPage) state.navItem = "devices";
  if (state.navItem === "deviceWorkbench" && state.devices.length && !selectedDevice()) {
    state.navItem = "devices";
    localStorage.setItem("smsNavItem", state.navItem);
  }
  els.pages.forEach((page) => {
    page.classList.toggle("is-hidden", page.dataset.page !== state.navItem);
  });
}

function isWindowsAgentOnline(agent) {
  if (!agent?.lastSeenAt) return false;
  return Date.now() - new Date(agent.lastSeenAt).getTime() <= ONLINE_WINDOW_MS;
}

function windowsAgentDevices(agent) {
  return Array.isArray(agent?.devices) ? agent.devices : [];
}

function windowsTaskTypeText(type = "") {
  const labels = {
    adb_install_apk: "安装 APK",
    adb_grant_permissions: "授权权限",
    adb_start_agent: "启动 Agent",
    adb_collect_diagnostics: "采集诊断",
    adb_restart_server: "重启 ADB"
  };
  return labels[type] || type || "未知任务";
}

function renderWindowsPage() {
  if (!els.windowsAgentList) return;
  const agents = state.windowsAgents || [];
  const online = agents.filter(isWindowsAgentOnline).length;
  const adbDevices = agents.reduce((sum, agent) => sum + windowsAgentDevices(agent).filter((device) => device.state === "device").length, 0);
  els.windowsSummary.textContent = `共 ${agents.length} 台管理器，在线 ${online} 台，ADB 可控手机 ${adbDevices} 台`;
  els.windowsAgentList.innerHTML = agents.length
    ? agents.map((agent) => {
      const onlineState = isWindowsAgentOnline(agent);
      const devices = windowsAgentDevices(agent);
      const queued = Number(agent.taskCounts?.queued || 0);
      const running = Number(agent.taskCounts?.running || 0);
      return `
        <article class="windows-agent-card ${onlineState ? "is-online" : "is-offline"}">
          <header>
            <div>
              <span class="eyebrow">Windows Agent</span>
              <h3>${escapeHtml(agent.agentName || agent.agentId)}</h3>
              <p>${escapeHtml(agent.agentId)} · ${escapeHtml(agent.hostname || "未知主机")} · ${escapeHtml(agent.version || "版本未知")}</p>
            </div>
            <em data-status="${onlineState ? "online" : "offline"}">${onlineState ? "在线" : "离线"}</em>
          </header>
          <div class="windows-metrics">
            <span><b>${devices.length}</b>ADB 设备</span>
            <span><b>${devices.filter((device) => device.state === "device").length}</b>可控制</span>
            <span><b>${running}</b>执行中</span>
            <span><b>${queued}</b>排队</span>
          </div>
          <div class="windows-agent-meta">
            <span>ADB：${escapeHtml(agent.adbVersion || "未上报")}</span>
            <span>最近心跳：${escapeHtml(shortTime(agent.lastSeenAt))}</span>
            <span>并发：${escapeHtml(agent.maxConcurrentAdbTasks || 1)}</span>
          </div>
          <div class="adb-device-table">
            ${devices.length ? devices.map((device) => `
              <div class="adb-device-row" data-agent-id="${escapeHtml(agent.agentId)}" data-adb-serial="${escapeHtml(device.adbSerial)}" data-device-id="${escapeHtml(device.deviceId || "")}">
                <div>
                  <strong>${escapeHtml(device.deviceName || device.model || device.adbSerial)}</strong>
                  <span>${escapeHtml(device.adbSerial)} · ${escapeHtml(device.model || "未知型号")} · Android ${escapeHtml(device.androidVersion || "-")}</span>
                </div>
                <em data-state="${escapeHtml(device.state)}">${escapeHtml(device.state)}</em>
                <div class="adb-actions">
                  <button class="ghost" data-action="windows-task" data-task-type="adb_install_apk" type="button">${escapeHtml(windowsTaskTypeText("adb_install_apk"))}</button>
                  <button class="ghost" data-action="windows-task" data-task-type="adb_grant_permissions" type="button">${escapeHtml(windowsTaskTypeText("adb_grant_permissions"))}</button>
                  <button class="ghost" data-action="windows-task" data-task-type="adb_start_agent" type="button">${escapeHtml(windowsTaskTypeText("adb_start_agent"))}</button>
                </div>
              </div>
            `).join("") : `<div class="empty-box">这台 Windows 还没有同步 ADB 手机。请确认 Windows 管理器已启动并能执行 adb devices。</div>`}
          </div>
        </article>
      `;
    }).join("")
    : `<div class="empty-box">还没有 Windows 管理器上线。先在 Windows 上配置并启动 phone-windows-agent。</div>`;
}

function filteredCommands() {
  const query = normalizeSearch(state.queueQuery);
  return state.commands.filter((command) => {
    if (state.queueStatus && command.status !== state.queueStatus) return false;
    if (state.queueType && command.type !== state.queueType) return false;
    if (!query) return true;
    const haystack = [
      command.commandId,
      command.deviceId,
      deviceLabel(command.deviceId),
      command.type,
      command.status,
      commandResultText(command)
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });
}

function renderQueuePage() {
  if (!els.queueList) return;
  const commands = filteredCommands();
  const active = state.commands.filter((command) => ACTIVE_COMMAND_STATUSES.has(command.status)).length;
  els.queueSummary.textContent = `最近 ${state.commands.length} 个任务，执行中 ${active} 个，当前显示 ${commands.length} 个`;
  els.queueStatusSelect.value = state.queueStatus;
  els.queueTypeSelect.value = state.queueType;
  els.queueList.innerHTML = commands.length
    ? commands.map((command) => `
      <article class="data-row queue-row" data-action="open-device" data-device-id="${escapeHtml(command.deviceId)}">
        <div>
          <strong>${escapeHtml(deviceLabel(command.deviceId))}</strong>
          <span>${escapeHtml(command.deviceId)}</span>
        </div>
        <div>
          <b>${escapeHtml(commandTypeText(command.type))}</b>
          <span>${timeLabel(command.createdAt)} · 更新 ${shortTime(command.updatedAt)}</span>
        </div>
        <em data-status="${escapeHtml(command.status)}">${escapeHtml(commandStatusText(command.status))}</em>
        <small>${escapeHtml(commandResultText(command))}</small>
        <button class="ghost trace-button" data-action="open-trace" data-command-id="${escapeHtml(command.commandId)}" type="button">轨迹</button>
      </article>
    `).join("")
    : `<div class="empty-box">没有匹配的任务。</div>`;
}

function renderCommandTrace() {
  if (!els.traceOverlay || !state.activeTraceCommandId) return;
  const command = state.commands.find((item) => item.commandId === state.activeTraceCommandId);
  const events = state.commandEvents[state.activeTraceCommandId] || [];
  els.traceTitle.textContent = command ? `${commandTypeText(command.type)} · ${commandStatusText(command.status)}` : "任务执行轨迹";
  els.traceMeta.textContent = command
    ? `${deviceLabel(command.deviceId)} · ${command.commandId} · ${timeLabel(command.createdAt)}`
    : state.activeTraceCommandId;
  els.traceList.innerHTML = events.length
    ? events.map((event) => `
      <article class="trace-event" data-level="${escapeHtml(event.level || "info")}">
        <header>
          <strong>${escapeHtml(event.phase || "log")} · ${event.stepIndex ?? "-"}</strong>
          <span>${escapeHtml(event.stepId || "")}</span>
          <time>${escapeHtml(shortTime(event.createdAt))}</time>
        </header>
        <p>${escapeHtml(event.message || "")}</p>
        ${event.packageName ? `<small>包名：${escapeHtml(event.packageName)}</small>` : ""}
        ${event.uiSnapshot ? `<pre>${escapeHtml(event.uiSnapshot)}</pre>` : ""}
        ${event.screenshot?.dataUrl ? `<img src="${event.screenshot.dataUrl}" alt="失败截图" />` : ""}
      </article>
    `).join("")
    : `<div class="empty-box">这条任务还没有执行轨迹。</div>`;
}

async function openCommandTrace(commandId) {
  if (!commandId) return;
  state.activeTraceCommandId = commandId;
  if (els.traceOverlay) els.traceOverlay.classList.add("is-open");
  renderCommandTrace();
  const payload = await api(`/api/v1/device-commands/${encodeURIComponent(commandId)}/events`);
  state.commandEvents[commandId] = payload.events || [];
  renderCommandTrace();
}

function accountMatches(text, query) {
  return !query || String(text || "").toLowerCase().includes(query);
}

function renderAccountsPage() {
  if (!els.globalSimList) return;
  if (isEditingGlobalAccounts()) return;
  const query = normalizeSearch(state.accountQuery);
  const simRows = [];
  const xhsRows = [];
  for (const device of state.devices) {
    for (const sim of device.sims || []) {
      const haystack = `${device.deviceName} ${device.deviceId} ${device.model} ${sim.phoneNumber} ${sim.label} ${sim.carrierName} ${sim.subscriptionId}`;
      if (accountMatches(haystack, query)) simRows.push({ device, sim });
    }
    for (const account of device.xhsAccounts || []) {
      const haystack = `${device.deviceName} ${device.deviceId} ${device.model} ${account.accountName} ${account.label} ${account.appSlot}`;
      if (accountMatches(haystack, query)) xhsRows.push({ device, account });
    }
  }
  els.accountsSummary.textContent = `共 ${state.devices.length} 台设备，当前显示 ${simRows.length} 个 SIM、${xhsRows.length} 个小红书槽位`;
  els.globalSimCount.textContent = String(simRows.length);
  els.globalXhsCount.textContent = String(xhsRows.length);
  els.globalSimList.innerHTML = simRows.length
    ? simRows.map(({ device, sim }) => `
      <div class="global-editor-row" data-device-id="${escapeHtml(device.deviceId)}" data-subscription-id="${escapeHtml(sim.subscriptionId)}">
        <button class="row-device-link" data-action="open-device" data-device-id="${escapeHtml(device.deviceId)}" type="button">
          <strong>${escapeHtml(device.deviceName || device.deviceId)}</strong>
          <span>SIM ${escapeHtml((sim.slotIndex ?? 0) + 1)} · ${escapeHtml(sim.carrierName || "未知运营商")}</span>
        </button>
        <input data-role="phone" placeholder="手机号" value="${escapeHtml(sim.phoneNumber || "")}" />
        <input data-role="label" placeholder="备注" value="${escapeHtml(sim.label || "")}" />
        <button data-action="bind-sim" class="ghost" type="button">保存</button>
      </div>
    `).join("")
    : `<div class="empty-box">没有匹配的 SIM。</div>`;
  els.globalXhsList.innerHTML = xhsRows.length
    ? xhsRows.map(({ device, account }) => `
      <div class="global-editor-row" data-device-id="${escapeHtml(device.deviceId)}" data-app-slot="${escapeHtml(account.appSlot)}">
        <button class="row-device-link" data-action="open-device" data-device-id="${escapeHtml(device.deviceId)}" type="button">
          <strong>${escapeHtml(device.deviceName || device.deviceId)}</strong>
          <span>${escapeHtml(account.appSlot)} · ${escapeHtml(account.appSlot === "app2" ? "Ⅱ·小红书" : "小红书")}</span>
        </button>
        <input data-role="xhs-account-name" placeholder="小红书号 / 账号备注" value="${escapeHtml(account.accountName || "")}" />
        <input data-role="xhs-label" placeholder="备注" value="${escapeHtml(account.label || "")}" />
        <button data-action="save-xhs-account" class="ghost" type="button">保存</button>
      </div>
    `).join("")
    : `<div class="empty-box">没有匹配的小红书账号。</div>`;
}

function selectedGlobalWorkflowScript() {
  return state.globalWorkflowScripts.find((script) => script.scriptId === state.globalWorkflowScriptId) || state.globalWorkflowScripts[0] || null;
}

function renderGlobalWorkflowPage() {
  if (!els.globalWorkflowDeviceSelect) return;
  if (!state.globalWorkflowDeviceId && state.devices.length) {
    state.globalWorkflowDeviceId = state.selectedDeviceId || state.devices[0].deviceId;
  }
  els.globalWorkflowDeviceSelect.innerHTML = state.devices.length
    ? state.devices.map((device) => `<option value="${escapeHtml(device.deviceId)}">${escapeHtml(device.deviceName || device.deviceId)} · ${escapeHtml(device.model || "未知型号")}</option>`).join("")
    : `<option value="">暂无设备</option>`;
  els.globalWorkflowDeviceSelect.value = state.globalWorkflowDeviceId;

  const script = selectedGlobalWorkflowScript();
  els.globalWorkflowScriptSelect.innerHTML = state.globalWorkflowScripts.length
    ? state.globalWorkflowScripts.map((item) => `<option value="${escapeHtml(item.scriptId)}">${escapeHtml(item.appSlot)} · ${escapeHtml(item.name)}</option>`).join("")
    : `<option value="">请先选择设备</option>`;
  if (script) els.globalWorkflowScriptSelect.value = script.scriptId;
  els.globalWorkflowScriptList.innerHTML = state.globalWorkflowScripts.length
    ? state.globalWorkflowScripts.map((item) => `
      <button class="script-list-item ${item.scriptId === script?.scriptId ? "is-active" : ""}" data-script-id="${escapeHtml(item.scriptId)}" type="button">
        <strong>${escapeHtml(item.appSlot)} · ${escapeHtml(item.name)}</strong>
        <span>发布版 v${escapeHtml(item.publishedVersion || 0)} · ${item.hasDraftChanges ? "草稿有改动" : "已同步"}</span>
      </button>
    `).join("")
    : `<div class="empty-box">选择设备后加载脚本。</div>`;

  const disabled = !script;
  [els.globalWorkflowEditor, els.globalValidateWorkflowButton, els.globalSaveWorkflowDraftButton, els.globalPublishWorkflowButton, els.globalTestWorkflowButton, els.globalRollbackWorkflowButton].forEach((item) => {
    item.disabled = disabled;
  });
  els.globalWorkflowSummary.textContent = state.globalWorkflowDeviceId
    ? `${deviceLabel(state.globalWorkflowDeviceId)} 的 app1/app2 扫码脚本`
    : "选择设备后加载脚本";
  els.globalWorkflowTitle.textContent = script ? `${script.appSlot} · ${script.name}` : "扫码脚本";
  els.globalWorkflowMeta.textContent = script
    ? `发布版 v${script.publishedVersion || 0} · ${script.hasDraftChanges ? "草稿有改动" : "草稿与发布一致"} · ${script.publishedAt ? timeLabel(script.publishedAt) : "未发布"}`
    : "未加载脚本";
  if (!script) {
    els.globalWorkflowEditor.value = "";
    return;
  }
  if (document.activeElement !== els.globalWorkflowEditor) {
    els.globalWorkflowEditor.value = JSON.stringify(script.draftScript || {}, null, 2);
  }
}

function renderAuditPage() {
  if (!els.globalRequestsList) return;
  const query = normalizeSearch(state.auditQuery);
  const orders = state.activations.filter((item) => {
    if (state.auditStatus && item.status !== state.auditStatus) return false;
    if (!query) return true;
    const haystack = `${item.phoneNumber} ${item.platform} ${item.status} ${item.deviceId} ${item.deviceName} ${item.sender} ${item.body}`;
    return haystack.toLowerCase().includes(query);
  });
  const events = state.events.filter((item) => {
    if (!query) return true;
    const haystack = `${item.phoneNumber} ${item.platform} ${item.sender} ${item.deviceId} ${deviceLabel(item.deviceId)} ${item.body} ${item.code}`;
    return haystack.toLowerCase().includes(query);
  });
  els.auditSummary.textContent = `共 ${state.activations.length} 个订单、${state.events.length} 条短信，当前显示 ${orders.length} 个订单、${events.length} 条短信`;
  els.auditStatusSelect.value = state.auditStatus;
  els.globalRequestCount.textContent = String(orders.length);
  els.globalEventCount.textContent = String(events.length);
  els.globalRequestsList.innerHTML = orders.length
    ? orders.slice(0, 80).map((item) => `
      <article class="order-row" data-status="${escapeHtml(item.status)}">
        <div>
          <strong>${escapeHtml(item.platform)}</strong>
          <span>${escapeHtml(item.phoneNumber)} · ${escapeHtml(item.deviceName || item.deviceId || "未匹配设备")}</span>
        </div>
        <div>
          <b>${escapeHtml(statusText(item.status))}</b>
          <small>${escapeHtml(activationTimeHint(item))}</small>
        </div>
        <code>${escapeHtml(item.code || "等待")}</code>
      </article>
    `).join("")
    : `<div class="empty-box">没有匹配的订单。</div>`;
  els.globalEventsList.innerHTML = events.length
    ? events.slice(0, 100).map((item) => `
      <article class="sms-row">
        <div>
          <strong>${escapeHtml(item.platform || item.sender)}</strong>
          <span>${escapeHtml(item.phoneNumber || "未匹配手机号")} · ${escapeHtml(deviceLabel(item.deviceId))} · ${timeLabel(item.receivedAt)}</span>
        </div>
        <p>${escapeHtml(item.body || "")}</p>
        <code>${escapeHtml(item.code || "无验证码")}</code>
      </article>
    `).join("")
    : `<div class="empty-box">没有匹配的短信。</div>`;
}

function buildAlerts() {
  const alerts = [];
  const now = Date.now();
  for (const device of state.devices) {
    const presence = devicePresence(device);
    if (presence.key === "offline") alerts.push({ level: "high", title: "设备离线", detail: `${device.deviceName || device.deviceId} 超过 10 分钟未心跳`, deviceId: device.deviceId });
    if (presence.key === "idle") alerts.push({ level: "medium", title: "省电延迟", detail: `${device.deviceName || device.deviceId} 可能熄屏省电，任务会排队等待`, deviceId: device.deviceId });
    if (!devicePhones(device).length) alerts.push({ level: "medium", title: "未绑定手机号", detail: `${device.deviceName || device.deviceId} 没有可用于接码的手机号`, deviceId: device.deviceId, tab: "sims" });
    const hasXhs = (device.xhsAccounts || []).some((account) => account.enabled !== false && (account.accountName || account.label));
    if (!hasXhs) alerts.push({ level: "medium", title: "未绑定小红书账号", detail: `${device.deviceName || device.deviceId} 没有可用于扫码的账号`, deviceId: device.deviceId, tab: "sims" });
  }
  for (const command of state.commands) {
    const age = now - new Date(command.createdAt).getTime();
    if (ACTIVE_COMMAND_STATUSES.has(command.status) && age > 120_000) {
      alerts.push({ level: "high", title: "任务可能卡住", detail: `${deviceLabel(command.deviceId)} · ${commandTypeText(command.type)} 已等待 ${Math.floor(age / 60_000)} 分钟`, deviceId: command.deviceId, tab: "records" });
    }
    if (command.status === "failed") {
      alerts.push({ level: "high", title: "任务失败", detail: `${deviceLabel(command.deviceId)} · ${commandTypeText(command.type)} · ${commandResultText(command)}`, deviceId: command.deviceId, tab: "records" });
    }
  }
  return alerts;
}

function versionParts(versionName = "") {
  return String(versionName).split(".").map((part) => Number.parseInt(part, 10) || 0);
}

function compareVersionName(left = "", right = "") {
  const a = versionParts(left);
  const b = versionParts(right);
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index++) {
    const diff = (a[index] || 0) - (b[index] || 0);
    if (diff) return diff;
  }
  return 0;
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (!size) return "-";
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function releaseNotes(release) {
  if (!release?.releaseNotes) return APP_RELEASE_HISTORY[0].notes;
  return String(release.releaseNotes)
    .split(/\n+|；|;/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function deviceVersionState(device, latestVersion) {
  if (!device.appVersion) return { key: "unknown", label: "未知版本" };
  const diff = compareVersionName(device.appVersion, latestVersion);
  if (diff < 0) return { key: "behind", label: "待升级" };
  if (diff > 0) return { key: "ahead", label: "高于发布版" };
  return { key: "current", label: "已是最新" };
}

function renderReleasePage() {
  if (!els.releaseDashboard) return;
  const fallback = APP_RELEASE_HISTORY[0];
  const latest = state.appRelease || fallback;
  const latestVersion = latest.versionName || fallback.versionName;
  const latestCode = latest.versionCode || fallback.versionCode;
  const notes = releaseNotes(latest);
  const coverage = state.devices.reduce((acc, device) => {
    const item = deviceVersionState(device, latestVersion);
    acc[item.key] = (acc[item.key] || 0) + 1;
    return acc;
  }, { current: 0, behind: 0, ahead: 0, unknown: 0 });
  const affected = coverage.behind + coverage.unknown;
  els.releaseSummary.textContent = state.appReleaseError
    ? `最新版本信息读取失败：${state.appReleaseError}`
    : `当前发布版 ${latestVersion}，${coverage.current} 台已覆盖，${affected} 台需要关注`;
  els.releaseDashboard.innerHTML = `
    <section class="release-hero panel-card">
      <div>
        <span class="eyebrow">Latest Android Package</span>
        <h3>v${escapeHtml(latestVersion)} <small>build ${escapeHtml(latestCode)}</small></h3>
        <p>${escapeHtml(latest.title || fallback.title || "手机端 APK 最新发布")}</p>
      </div>
      <div class="release-actions">
        <span class="release-badge">${latest.mandatory ? "强制更新" : "可选更新"}</span>
        <button class="ghost" data-action="download-release" type="button">下载 APK</button>
      </div>
    </section>

    <section class="release-stat-grid">
      <div class="metric-card"><span>已是最新</span><strong>${coverage.current}</strong></div>
      <div class="metric-card"><span>待升级</span><strong>${coverage.behind}</strong></div>
      <div class="metric-card"><span>未知版本</span><strong>${coverage.unknown}</strong></div>
      <div class="metric-card"><span>包体大小</span><strong>${escapeHtml(formatBytes(latest.sizeBytes || latest.size))}</strong></div>
    </section>

    <section class="split-grid release-grid">
      <article class="panel-card">
        <div class="section-head">
          <div>
            <span class="eyebrow">Release Notes</span>
            <h3>本次更新内容</h3>
          </div>
          <small>${escapeHtml(latest.publishedAt ? timeLabel(latest.publishedAt) : fallback.date)}</small>
        </div>
        <ol class="release-notes">
          ${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}
        </ol>
        <div class="release-fingerprint">
          <span>SHA256</span>
          <code>${escapeHtml(latest.sha256 || "未生成")}</code>
        </div>
      </article>

      <article class="panel-card">
        <div class="section-head">
          <div>
            <span class="eyebrow">Install Coverage</span>
            <h3>设备安装覆盖</h3>
          </div>
          <strong>${state.devices.length}</strong>
        </div>
        <div class="release-device-list">
          ${state.devices.length ? sortDevices(state.devices).map((device) => {
            const item = deviceVersionState(device, latestVersion);
            return `
              <button class="release-device-row" data-action="open-device" data-device-id="${escapeHtml(device.deviceId)}" type="button">
                <div>
                  <strong>${escapeHtml(device.deviceName || device.deviceId)}</strong>
                  <span>${escapeHtml(device.model || "未知型号")} · Android ${escapeHtml(device.androidVersion || "-")}</span>
                </div>
                <em data-version-state="${escapeHtml(item.key)}">${escapeHtml(device.appVersion || "-")} · ${escapeHtml(item.label)}</em>
              </button>
            `;
          }).join("") : `<div class="empty-box">还没有设备上报，安装 APK 并配置 token 后会出现在这里。</div>`}
        </div>
      </article>
    </section>

    <section class="panel-card release-history-card">
      <div class="section-head">
        <div>
          <span class="eyebrow">Changelog</span>
          <h3>版本更新记录</h3>
        </div>
        <small>按 APK 版本归档</small>
      </div>
      <div class="release-timeline">
        ${APP_RELEASE_HISTORY.map((item, index) => `
          <article class="release-timeline-item ${index === 0 ? "is-current" : ""}">
            <div class="release-dot"></div>
            <header>
              <strong>v${escapeHtml(item.versionName)}</strong>
              <span>${escapeHtml(item.tag)} · build ${escapeHtml(item.versionCode)} · ${escapeHtml(item.date)}</span>
            </header>
            <h4>${escapeHtml(item.title)}</h4>
            <ul>${item.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

async function downloadLatestRelease() {
  const button = els.releaseDownloadButton;
  if (button) {
    button.disabled = true;
    button.textContent = "下载中";
  }
  try {
    const url = state.appRelease?.downloadUrl || "/api/v1/app-release/latest/download";
    const response = await fetch(url, { headers: authHeaders() });
    if (!response.ok) throw new Error(`下载失败 HTTP ${response.status}`);
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = `sms-relay-${state.appRelease?.versionName || "latest"}.apk`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 2000);
  } catch (error) {
    state.appReleaseError = error.message;
    renderReleasePage();
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = "下载最新 APK";
    }
  }
}

function renderSettingsPage() {
  if (!els.settingsRuntimeList) return;
  els.settingsTokenStatus.textContent = state.token ? "已保存" : "未保存";
  if (document.activeElement !== els.settingsTokenInput) els.settingsTokenInput.value = state.token;
  const active = state.commands.filter((command) => ACTIVE_COMMAND_STATUSES.has(command.status)).length;
  els.settingsRuntimeList.innerHTML = `
    <div><span>设备总数</span><strong>${state.devices.length}</strong></div>
    <div><span>任务缓存</span><strong>${state.commands.length}</strong></div>
    <div><span>执行中</span><strong>${active}</strong></div>
    <div><span>接码订单</span><strong>${state.activations.length}</strong></div>
    <div><span>短信记录</span><strong>${state.events.length}</strong></div>
  `;
}

function renderDeviceWorkbench() {
  const device = selectedDevice();
  const isWorkbenchPage = state.navItem === "deviceWorkbench";
  if (els.detailEmpty) els.detailEmpty.classList.toggle("is-hidden", !!device || !isWorkbenchPage);
  if (els.detailPanel) els.detailPanel.classList.toggle("is-hidden", !device || !isWorkbenchPage);
  if (!device) return;

  const presence = devicePresence(device);
  if (els.selectedDeviceThumb) {
    els.selectedDeviceThumb.textContent = (device.deviceName || device.model || "D").slice(0, 1).toUpperCase();
  }
  els.selectedStatus.textContent = presence.label;
  els.selectedStatus.className = `status-pill is-${presence.key}`;
  els.selectedDeviceName.textContent = device.deviceName || device.deviceId;
  els.selectedDeviceMeta.textContent = `${device.model || "未知型号"} · Android ${device.androidVersion || "-"} · App ${device.appVersion || "-"}`;
  els.selectedBattery.textContent = device.batteryLevel == null ? "-" : `${device.batteryLevel}%`;
  els.selectedSimCount.textContent = String((device.sims || []).length);
  els.selectedLastSeen.textContent = shortTime(device.lastSeenAt);
  const latestCommand = latestCommandForDevice(device.deviceId);
  if (els.selectedLatestTask) {
    els.selectedLatestTask.textContent = latestCommand ? commandStatusText(latestCommand.status) : "暂无";
  }

  if (!isEditingSimMapping()) {
    els.simList.innerHTML = (device.sims || []).length
      ? device.sims.map((sim) => `
        <div class="sim-editor" data-device-id="${escapeHtml(device.deviceId)}" data-subscription-id="${escapeHtml(sim.subscriptionId)}">
          <div class="sim-badge">
            <strong>SIM ${escapeHtml((sim.slotIndex ?? 0) + 1)}</strong>
            <span>${escapeHtml(sim.carrierName || "未知运营商")}</span>
            <small>subscriptionId=${escapeHtml(sim.subscriptionId)}</small>
          </div>
          <input data-role="phone" placeholder="这个 SIM 的手机号" value="${escapeHtml(sim.phoneNumber || "")}" />
          <input data-role="label" placeholder="备注，例如 电信主卡" value="${escapeHtml(sim.label || "")}" />
          <button data-action="bind-sim" class="ghost" type="button">保存</button>
        </div>
      `).join("")
      : `<div class="empty-box">这台手机还没有上报 SIM 信息。确认 App 已授予 READ_PHONE_STATE 权限。</div>`;

    if (!isEditingXhsAccounts()) {
      const accounts = device.xhsAccounts || [];
      els.xhsAccountList.innerHTML = accounts.length
        ? accounts.map((account) => `
          <div class="xhs-account-editor" data-device-id="${escapeHtml(device.deviceId)}" data-app-slot="${escapeHtml(account.appSlot)}">
            <div class="xhs-slot-badge">
              <strong>${escapeHtml(account.appSlot)}</strong>
              <span>${escapeHtml(account.appSlot === "app2" ? "Ⅱ·小红书" : "小红书")}</span>
            </div>
            <input data-role="xhs-account-name" placeholder="小红书号 / 账号备注" value="${escapeHtml(account.accountName || "")}" />
            <input data-role="xhs-label" placeholder="备注，例如 主号、客户A、备用号" value="${escapeHtml(account.label || "")}" />
            <button data-action="save-xhs-account" class="ghost" type="button">保存</button>
          </div>
        `).join("")
        : `<div class="empty-box">这台手机还没有小红书账号槽位。</div>`;
    }
  }

  const phoneOptions = (device.sims || [])
    .filter((sim) => sim.phoneNumber)
    .map((sim) => `<option value="${escapeHtml(sim.phoneNumber)}">${escapeHtml(sim.phoneNumber)} · ${escapeHtml(sim.label || sim.carrierName || "SIM")}</option>`);
  setSelectOptionsPreservingValue(
    els.requestPhoneInput,
    phoneOptions.length ? phoneOptions.join("") : `<option value="">请先给 SIM 绑定手机号</option>`
  );
  els.createRequestButton.disabled = !phoneOptions.length;

  const xhsOptions = (device.xhsAccounts || [])
    .filter((account) => account.enabled !== false && account.accountName)
    .map((account) => {
      const name = account.accountName;
      const slotLabel = account.label || (account.appSlot === "app2" ? "Ⅱ·小红书" : "小红书");
      return `<option value="${escapeHtml(account.appSlot)}" data-account-name="${escapeHtml(name)}" data-label="${escapeHtml(slotLabel)}" data-app-slot="${escapeHtml(account.appSlot)}">${escapeHtml(name)} · ${escapeHtml(slotLabel)} · ${escapeHtml(account.appSlot)}</option>`;
    });
  setSelectOptionsPreservingValue(
    els.xhsAccountSelect,
    xhsOptions.length ? xhsOptions.join("") : `<option value="">请先填写本机小红书账号</option>`
  );
  updateScanPanel();

  const phones = new Set(devicePhones(device));
  const deviceActivations = state.activations.filter((item) => phones.has(item.phoneNumber) || item.deviceId === device.deviceId);
  const deviceEvents = state.events.filter((item) => item.deviceId === device.deviceId || phones.has(item.phoneNumber));
  const deviceCommands = state.commands.filter((item) => item.deviceId === device.deviceId);
  els.requestCount.textContent = String(deviceActivations.length);
  els.eventCount.textContent = String(deviceEvents.length);
  if (els.recordCommandCount) els.recordCommandCount.textContent = String(deviceCommands.length);

  const activationRows = deviceActivations.length
    ? deviceActivations.map((item) => `
      <article class="order-row" data-status="${escapeHtml(item.status)}">
        <div>
          <strong>${escapeHtml(item.platform)}</strong>
          <span>${escapeHtml(item.phoneNumber)}</span>
        </div>
        <div>
          <b>${escapeHtml(statusText(item.status))}</b>
          <small>${escapeHtml(activationTimeHint(item))}</small>
        </div>
        <code>${escapeHtml(item.code || "等待")}</code>
      </article>
    `)
    : [];

  els.requestInlineList.innerHTML = activationRows.length
    ? activationRows.slice(0, 3).join("")
    : `<div class="empty-box">还没有接码订单。</div>`;
  els.requestsList.innerHTML = activationRows.length
    ? activationRows.slice(0, 10).join("")
    : `<div class="empty-box">这台手机还没有接码订单。</div>`;

  els.eventsList.innerHTML = deviceEvents.length
    ? deviceEvents.slice(0, 12).map((item) => `
      <article class="sms-row">
        <div>
          <strong>${escapeHtml(item.platform || item.sender)}</strong>
          <span>${escapeHtml(item.phoneNumber || "未匹配手机号")} · ${timeLabel(item.receivedAt)}</span>
        </div>
        <p>${escapeHtml(item.body || "")}</p>
        <code>${escapeHtml(item.code || "无验证码")}</code>
      </article>
    `).join("")
    : `<div class="empty-box">这台手机暂无短信记录。</div>`;

  els.commandsList.innerHTML = deviceCommands.length
    ? deviceCommands.slice(0, 8).map((item) => `
      <article class="command-row" data-status="${escapeHtml(item.status)}">
        <div>
          <strong>${escapeHtml(commandTypeText(item.type))}</strong>
          <span>${timeLabel(item.createdAt)}</span>
        </div>
        <b>${escapeHtml(commandStatusText(item.status))}</b>
        <small>${escapeHtml(item.result?.message || item.result?.action || item.result?.error || "等待手机执行")}</small>
        <button class="ghost trace-button" data-action="open-trace" data-command-id="${escapeHtml(item.commandId)}" type="button">查看轨迹</button>
      </article>
    `).join("")
    : `<div class="empty-box">还没有下发过扫码任务。</div>`;

  if (els.recordsCommandsList) {
    els.recordsCommandsList.innerHTML = deviceCommands.length
      ? deviceCommands.slice(0, 18).map((item) => `
        <article class="command-row" data-status="${escapeHtml(item.status)}">
          <div>
            <strong>${escapeHtml(commandTypeText(item.type))}</strong>
            <span>${timeLabel(item.createdAt)} · 更新 ${timeLabel(item.updatedAt || item.createdAt)}</span>
          </div>
          <b>${escapeHtml(commandStatusText(item.status))}</b>
          <small>${escapeHtml(item.result?.message || item.result?.action || item.result?.error || "等待手机执行")}</small>
          <button class="ghost trace-button" data-action="open-trace" data-command-id="${escapeHtml(item.commandId)}" type="button">查看轨迹</button>
        </article>
      `).join("")
      : `<div class="empty-box">这台手机还没有任务记录。</div>`;
  }

  renderWorkflowEditor();
}

function renderWorkflowEditor() {
  const script = selectedWorkflowScript();
  const workflowOptions = state.workflowScripts.length
    ? state.workflowScripts.map((item) => `
      <option value="${escapeHtml(item.scriptId)}" ${item.scriptId === script?.scriptId ? "selected" : ""}>
        ${escapeHtml(item.appSlot)} · ${escapeHtml(item.name)}
      </option>
    `).join("")
    : `<option value="">暂无脚本</option>`;
  setSelectOptionsPreservingValue(els.workflowScriptSelect, workflowOptions, script?.scriptId || "");
  const disabled = !script;
  [
    els.workflowScriptEditor,
    els.validateWorkflowButton,
    els.saveWorkflowDraftButton,
    els.publishWorkflowButton,
    els.testWorkflowButton,
    els.rollbackWorkflowButton
  ].forEach((item) => {
    item.disabled = disabled;
  });
  if (!script) {
    els.workflowScriptMeta.textContent = "暂无脚本";
    els.workflowScriptEditor.value = "";
    return;
  }
  if (document.activeElement !== els.workflowScriptEditor) {
    els.workflowScriptEditor.value = JSON.stringify(script.draftScript || {}, null, 2);
  }
  els.workflowScriptMeta.textContent = `发布版 v${script.publishedVersion || 0} · ${script.hasDraftChanges ? "草稿有改动" : "草稿与发布一致"} · ${script.publishedAt ? timeLabel(script.publishedAt) : "未发布"}`;
}

function renderWorkbenchTabs() {
  const allowedTabs = new Set(["tasks", "sims", "script", "records"]);
  if (!allowedTabs.has(state.workbenchTab)) state.workbenchTab = "tasks";
  if (state.navItem === "deviceWorkbench") {
    els.workbenchTabs.forEach((button) => {
      button.classList.toggle("is-active", button.dataset.workbenchTab === state.workbenchTab);
    });
    els.workbenchSections.forEach((section) => {
      section.classList.toggle("is-hidden", section.dataset.workbenchSection !== state.workbenchTab);
    });
    return;
  }
  els.workbenchTabs.forEach((button) => {
    button.classList.toggle("is-active", button.dataset.workbenchTab === state.workbenchTab);
  });
  els.workbenchSections.forEach((section) => {
    section.classList.toggle("is-hidden", section.dataset.workbenchSection !== state.workbenchTab);
  });
}

function renderSideNav() {
  els.sideNavLinks.forEach((link) => {
    const activeItem = state.navItem === "deviceWorkbench" ? "devices" : state.navItem;
    link.classList.toggle("is-active", link.dataset.navItem === activeItem);
  });
}

function render() {
  setAuthenticated(!!state.token);
  renderPageVisibility();
  renderDeviceList();
  renderDeviceWorkbench();
  renderWorkbenchTabs();
  renderQueuePage();
  renderAccountsPage();
  renderGlobalWorkflowPage();
  renderAuditPage();
  renderReleasePage();
  renderSettingsPage();
  renderSideNav();
}

async function loadAll() {
  if (!state.token) {
    render();
    return;
  }
  let devicesPayload;
  let eventsPayload;
  let activationsPayload;
  let commandsPayload;
  let releasePayload;
  try {
    [devicesPayload, eventsPayload, activationsPayload, commandsPayload, releasePayload] = await Promise.all([
      api("/api/v1/devices"),
      api("/api/v1/sms-events"),
      api("/api/v1/activations"),
      api("/api/v1/commands?limit=180"),
      api("/api/v1/app-release/latest").catch((error) => {
        state.appReleaseError = error.message;
        return { release: null };
      })
    ]);
  } catch (error) {
    if (error.status === 404 || location.port === "8799") {
      loadMockData("Mock 预览");
      return;
    }
    throw error;
  }
  state.devices = devicesPayload.devices || [];
  state.mockMode = false;
  state.events = eventsPayload.events || [];
  state.activations = activationsPayload.activations || [];
  state.commands = commandsPayload.commands || [];
  state.appRelease = releasePayload.release || null;
  syncActivationStatusPollers();
  if (state.appRelease) state.appReleaseError = "";
  if (state.navItem === "deviceWorkbench" && state.selectedDeviceId && !selectedDevice()) {
    state.navItem = "devices";
    localStorage.setItem("smsNavItem", state.navItem);
  }
  if (!selectedDevice() && state.devices.length && !(state.navItem === "deviceWorkbench" && !state.selectedDeviceId)) {
    state.selectedDeviceId = sortDevices(state.devices)[0].deviceId;
    localStorage.setItem("smsSelectedDeviceId", state.selectedDeviceId);
  }
  await loadSelectedCommands();
  await loadSelectedWorkflowScripts();
  if (state.navItem === "scripts") {
    await loadGlobalWorkflowScriptsForDevice(state.globalWorkflowDeviceId || state.selectedDeviceId || state.devices[0]?.deviceId || "");
  }
  els.streamStatus.textContent = "已连接";
  render();
}

async function loadSelectedCommands() {
  if (!state.selectedDeviceId) {
    return;
  }
  if (state.mockMode) return;
  const payload = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}/commands`);
  mergeCommands(payload.commands || []);
}

async function loadSelectedWorkflowScripts() {
  if (!state.selectedDeviceId) {
    state.workflowScripts = [];
    state.selectedWorkflowScriptId = "";
    return;
  }
  if (state.mockMode) return;
  const payload = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}/workflow-scripts`);
  state.workflowScripts = payload.scripts || [];
  if (!selectedWorkflowScript()) {
    state.selectedWorkflowScriptId = state.workflowScripts[0]?.scriptId || "";
  }
}

async function loadGlobalWorkflowScriptsForDevice(deviceId = state.globalWorkflowDeviceId) {
  if (!deviceId) {
    state.globalWorkflowScripts = [];
    state.globalWorkflowScriptId = "";
    return;
  }
  state.globalWorkflowDeviceId = deviceId;
  localStorage.setItem("smsGlobalWorkflowDeviceId", state.globalWorkflowDeviceId);
  if (state.mockMode) {
    state.globalWorkflowScripts = state.workflowScripts.map((script) => ({ ...script, deviceId }));
  } else {
    const payload = await api(`/api/v1/devices/${encodeURIComponent(deviceId)}/workflow-scripts`);
    state.globalWorkflowScripts = payload.scripts || [];
  }
  if (!selectedGlobalWorkflowScript()) {
    state.globalWorkflowScriptId = state.globalWorkflowScripts[0]?.scriptId || "";
  }
}

function connectStream() {
  if (state.mockMode) {
    els.streamStatus.textContent = "Mock 预览";
    return;
  }
  if (state.stream) state.stream.close();
  state.stream = new EventSource("/api/v1/stream");
  state.stream.addEventListener("open", () => {
    els.streamStatus.textContent = "实时在线";
  });
  state.stream.addEventListener("error", () => {
    els.streamStatus.textContent = "重连中";
  });
  state.stream.addEventListener("sms", (event) => {
    const item = JSON.parse(event.data);
    state.events = [item, ...state.events.filter((old) => old.id !== item.id)];
    render();
  });
  state.stream.addEventListener("device", (event) => {
    const item = JSON.parse(event.data);
    state.devices = [item, ...state.devices.filter((old) => old.deviceId !== item.deviceId)];
    if (!state.selectedDeviceId) state.selectedDeviceId = item.deviceId;
    render();
  });
  state.stream.addEventListener("activation", (event) => {
    const item = JSON.parse(event.data);
    upsertActivation(item);
    if (!isActivationOpen(item)) stopActivationStatusPoll(item.activationId);
    render();
  });
  state.stream.addEventListener("command", (event) => {
    const item = JSON.parse(event.data);
    state.commands = [item, ...state.commands.filter((old) => old.commandId !== item.commandId)];
    render();
  });
}

function showError(error) {
  if (error.status === 401) {
    els.streamStatus.textContent = "API Key 错误";
    state.token = "";
    localStorage.removeItem("smsCenterToken");
    els.tokenInput.value = "";
    if (els.settingsTokenInput) els.settingsTokenInput.value = "";
    render();
    return;
  }
  els.streamStatus.textContent = "连接失败";
  els.devicesList.innerHTML = `<div class="empty-box">${escapeHtml(error.message)}</div>`;
}

els.saveTokenButton.addEventListener("click", async () => {
  state.token = els.tokenInput.value.trim();
  localStorage.setItem("smsCenterToken", state.token);
  if (els.settingsTokenInput) els.settingsTokenInput.value = state.token;
  try {
    await loadAll();
    connectStream();
  } catch (error) {
    showError(error);
  }
});

els.logoutButton.addEventListener("click", () => {
  state.token = "";
  localStorage.removeItem("smsCenterToken");
  els.tokenInput.value = "";
  if (els.settingsTokenInput) els.settingsTokenInput.value = "";
  render();
});

els.refreshButton.addEventListener("click", () => {
  loadAll().catch(showError);
});

els.searchInput.addEventListener("input", () => {
  state.query = els.searchInput.value;
  render();
});

els.statusSelect?.addEventListener("change", () => {
  state.statusFilter = els.statusSelect.value || "all";
  render();
});

els.brandSelect?.addEventListener("change", () => {
  state.brandFilter = els.brandSelect.value || "";
  render();
});

els.androidSelect?.addEventListener("change", () => {
  state.androidFilter = els.androidSelect.value || "";
  render();
});

els.clearFiltersButton?.addEventListener("click", () => {
  state.query = "";
  state.statusFilter = "all";
  state.brandFilter = "";
  state.androidFilter = "";
  els.searchInput.value = "";
  render();
});

els.queueSearchInput?.addEventListener("input", () => {
  state.queueQuery = els.queueSearchInput.value;
  renderQueuePage();
});

els.queueStatusSelect?.addEventListener("change", () => {
  state.queueStatus = els.queueStatusSelect.value;
  renderQueuePage();
});

els.queueTypeSelect?.addEventListener("change", () => {
  state.queueType = els.queueTypeSelect.value;
  renderQueuePage();
});

els.queueRefreshButton?.addEventListener("click", () => loadAll().catch(showError));

els.queueList?.addEventListener("click", (event) => {
  const traceTarget = event.target.closest("[data-action='open-trace']");
  if (traceTarget) {
    event.stopPropagation();
    openCommandTrace(traceTarget.dataset.commandId).catch(showError);
    return;
  }
  const target = event.target.closest("[data-action='open-device']");
  if (!target) return;
  openDevicePage(target.dataset.deviceId, "records");
});

els.commandsList?.addEventListener("click", (event) => {
  const traceTarget = event.target.closest("[data-action='open-trace']");
  if (!traceTarget) return;
  openCommandTrace(traceTarget.dataset.commandId).catch(showError);
});

els.recordsCommandsList?.addEventListener("click", (event) => {
  const traceTarget = event.target.closest("[data-action='open-trace']");
  if (!traceTarget) return;
  openCommandTrace(traceTarget.dataset.commandId).catch(showError);
});

els.traceCloseButton?.addEventListener("click", () => {
  state.activeTraceCommandId = "";
  els.traceOverlay?.classList.remove("is-open");
});

els.traceOverlay?.addEventListener("click", (event) => {
  if (event.target !== els.traceOverlay) return;
  state.activeTraceCommandId = "";
  els.traceOverlay.classList.remove("is-open");
});

els.traceRefreshButton?.addEventListener("click", () => {
  if (!state.activeTraceCommandId) return;
  openCommandTrace(state.activeTraceCommandId).catch(showError);
});

els.accountSearchInput?.addEventListener("input", () => {
  state.accountQuery = els.accountSearchInput.value;
  renderAccountsPage();
});

els.accountsRefreshButton?.addEventListener("click", () => loadAll().catch(showError));

els.globalSimList?.addEventListener("click", async (event) => {
  const openTarget = event.target.closest("[data-action='open-device']");
  if (openTarget) return openDevicePage(openTarget.dataset.deviceId, "sims");
  const button = event.target.closest("[data-action='bind-sim']");
  if (!button) return;
  const row = button.closest(".global-editor-row");
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await saveSimRow(row);
    button.textContent = "已保存";
    await loadAll();
  } catch (error) {
    els.accountsSummary.textContent = error.message;
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = "保存";
    }
  }
});

els.globalXhsList?.addEventListener("click", async (event) => {
  const openTarget = event.target.closest("[data-action='open-device']");
  if (openTarget) return openDevicePage(openTarget.dataset.deviceId, "sims");
  const button = event.target.closest("[data-action='save-xhs-account']");
  if (!button) return;
  const row = button.closest(".global-editor-row");
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await saveXhsAccountRow(row);
    button.textContent = "已保存";
    await loadAll();
  } catch (error) {
    els.accountsSummary.textContent = error.message;
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = "保存";
    }
  }
});

els.auditSearchInput?.addEventListener("input", () => {
  state.auditQuery = els.auditSearchInput.value;
  renderAuditPage();
});

els.auditStatusSelect?.addEventListener("change", () => {
  state.auditStatus = els.auditStatusSelect.value;
  renderAuditPage();
});

els.auditRefreshButton?.addEventListener("click", () => loadAll().catch(showError));
els.releaseRefreshButton?.addEventListener("click", () => loadAll().catch(showError));
els.releaseDownloadButton?.addEventListener("click", () => downloadLatestRelease());

els.releaseDashboard?.addEventListener("click", (event) => {
  const downloadTarget = event.target.closest("[data-action='download-release']");
  if (downloadTarget) {
    return downloadLatestRelease();
  }
  const target = event.target.closest("[data-action='open-device']");
  if (!target) return;
  openDevicePage(target.dataset.deviceId, target.dataset.tab || "records");
});

els.settingsRefreshButton?.addEventListener("click", () => loadAll().catch(showError));

els.settingsSaveTokenButton?.addEventListener("click", async () => {
  state.token = els.settingsTokenInput.value.trim();
  localStorage.setItem("smsCenterToken", state.token);
  els.tokenInput.value = state.token;
  try {
    await loadAll();
    connectStream();
  } catch (error) {
    showError(error);
  }
});

els.settingsLogoutButton?.addEventListener("click", () => {
  state.token = "";
  localStorage.removeItem("smsCenterToken");
  els.tokenInput.value = "";
  els.settingsTokenInput.value = "";
  render();
});

els.filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    state.statusFilter = button.dataset.statusFilter || "all";
    render();
  });
});

els.sideNavLinks.forEach((link) => {
  link.addEventListener("click", async (event) => {
    event.preventDefault();
    state.navItem = link.dataset.navItem || "devices";
    localStorage.setItem("smsNavItem", state.navItem);
    els.streamStatus.textContent = moduleCopy().status;
    if (state.navItem === "scripts" && !state.globalWorkflowScripts.length) {
      await loadGlobalWorkflowScriptsForDevice(state.globalWorkflowDeviceId || state.selectedDeviceId || state.devices[0]?.deviceId || "").catch(showError);
    }

    render();
    const target = document.querySelector(link.getAttribute("href"));
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

document.querySelector(".add-device-button")?.addEventListener("click", () => {
  state.navItem = "settings";
  localStorage.setItem("smsNavItem", state.navItem);
  els.streamStatus.textContent = "安装 APK 后自动上线";
  render();
});

els.workbenchTabs.forEach((button) => {
  button.addEventListener("click", () => {
    state.workbenchTab = button.dataset.workbenchTab || "tasks";
    localStorage.setItem("smsWorkbenchTab", state.workbenchTab);
    renderWorkbenchTabs();
  });
});

els.backToInventoryButton?.addEventListener("click", openInventoryPage);

els.detailEmpty?.addEventListener("click", (event) => {
  if (!event.target.closest("[data-action='back-to-inventory']")) return;
  openInventoryPage();
});

els.globalWorkflowDeviceSelect?.addEventListener("change", async () => {
  await loadGlobalWorkflowScriptsForDevice(els.globalWorkflowDeviceSelect.value).catch(showError);
  render();
});

els.globalWorkflowRefreshButton?.addEventListener("click", async () => {
  await loadGlobalWorkflowScriptsForDevice(state.globalWorkflowDeviceId || state.devices[0]?.deviceId || "").catch(showError);
  render();
});

els.globalWorkflowScriptSelect?.addEventListener("change", () => {
  state.globalWorkflowScriptId = els.globalWorkflowScriptSelect.value;
  renderGlobalWorkflowPage();
});

els.globalWorkflowScriptList?.addEventListener("click", (event) => {
  const item = event.target.closest("[data-script-id]");
  if (!item) return;
  state.globalWorkflowScriptId = item.dataset.scriptId;
  renderGlobalWorkflowPage();
});

els.globalValidateWorkflowButton?.addEventListener("click", () => {
  try {
    const validation = validateWorkflowScript(parseGlobalWorkflowEditor());
    els.globalWorkflowHint.textContent = workflowValidationText(validation);
  } catch (error) {
    els.globalWorkflowHint.textContent = error.message;
  }
});

els.globalSaveWorkflowDraftButton?.addEventListener("click", async () => {
  els.globalSaveWorkflowDraftButton.disabled = true;
  try {
    const payload = await saveGlobalWorkflowDraft();
    els.globalWorkflowHint.textContent = `草稿已保存。${workflowValidationText(payload.validation || { ok: true, errors: [], warnings: [] })}`;
    render();
  } catch (error) {
    els.globalWorkflowHint.textContent = error.message;
  } finally {
    els.globalSaveWorkflowDraftButton.disabled = false;
  }
});

els.globalPublishWorkflowButton?.addEventListener("click", async () => {
  const script = selectedGlobalWorkflowScript();
  if (!script) return;
  els.globalPublishWorkflowButton.disabled = true;
  try {
    await saveGlobalWorkflowDraft();
    const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/publish`, { method: "POST" });
    state.globalWorkflowScripts = [payload.script, ...state.globalWorkflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
      .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
    state.globalWorkflowScriptId = payload.script.scriptId;
    els.globalWorkflowHint.textContent = `已发布 v${payload.script.publishedVersion}。`;
    render();
  } catch (error) {
    els.globalWorkflowHint.textContent = error.message;
  } finally {
    els.globalPublishWorkflowButton.disabled = false;
  }
});

els.globalRollbackWorkflowButton?.addEventListener("click", async () => {
  const script = selectedGlobalWorkflowScript();
  if (!script) return;
  els.globalRollbackWorkflowButton.disabled = true;
  try {
    const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/rollback`, { method: "POST" });
    state.globalWorkflowScripts = [payload.script, ...state.globalWorkflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
      .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
    state.globalWorkflowScriptId = payload.script.scriptId;
    els.globalWorkflowHint.textContent = `已回滚并发布为 v${payload.script.publishedVersion}。`;
    render();
  } catch (error) {
    els.globalWorkflowHint.textContent = error.message;
  } finally {
    els.globalRollbackWorkflowButton.disabled = false;
  }
});

els.globalTestWorkflowButton?.addEventListener("click", async () => {
  const script = selectedGlobalWorkflowScript();
  const file = els.globalWorkflowQrInput.files?.[0];
  if (!script) return;
  if (!file) {
    els.globalWorkflowHint.textContent = "请先选择一张二维码图片，再下发测试。";
    return;
  }
  els.globalTestWorkflowButton.disabled = true;
  try {
    await saveGlobalWorkflowDraft();
    const image = await compressQrImage(file);
    const xhsAccount = xhsAccountForDeviceSlot(script.deviceId || state.globalWorkflowDeviceId, script.appSlot || "app1");
    const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/test`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        payload: {
          qrImageDataUrl: image.dataUrl,
          fileName: image.fileName,
          xhsAccount: xhsAccount.accountName || xhsAccount.label || "",
          xhsAppSlot: script.appSlot || xhsAccount.appSlot || "app1"
        }
      })
    });
    if (payload.command) mergeCommands([payload.command]);
    els.globalWorkflowHint.textContent = "测试任务已下发，使用当前草稿脚本。";
    render();
  } catch (error) {
    els.globalWorkflowHint.textContent = error.message;
  } finally {
    els.globalTestWorkflowButton.disabled = false;
  }
});

els.devicesList.addEventListener("click", (event) => {
  const card = event.target.closest(".device-card");
  if (!card) return;
  openDevicePage(card.dataset.deviceId, "tasks");
});

els.simList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action='bind-sim']");
  if (!button) return;
  const row = button.closest(".sim-editor");
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await saveSimRow(row);
    button.textContent = "已保存";
    await loadAll();
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = "保存";
    }
  }
});

els.xhsAccountList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action='save-xhs-account']");
  if (!button) return;
  const row = button.closest(".xhs-account-editor");
  button.disabled = true;
  button.textContent = "保存中";
  try {
    await saveXhsAccountRow(row);
    els.commandHint.textContent = "小红书账号已保存。后续扫码任务会按这里选择 app1/app2。";
    button.textContent = "已保存";
    await loadAll();
  } catch (error) {
    els.commandHint.textContent = error.message;
  } finally {
    if (button.isConnected) {
      button.disabled = false;
      button.textContent = "保存";
    }
  }
});

function simRowPayload(row) {
  return {
    phoneNumber: row.querySelector("[data-role='phone']").value.trim(),
    label: row.querySelector("[data-role='label']").value.trim(),
    enabled: true
  };
}

async function saveSimRow(row) {
  await api(`/api/v1/devices/${encodeURIComponent(row.dataset.deviceId)}/sims/${encodeURIComponent(row.dataset.subscriptionId)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(simRowPayload(row))
  });
}

function xhsAccountRowPayload(row) {
  return {
    accountName: row.querySelector("[data-role='xhs-account-name']").value.trim(),
    label: row.querySelector("[data-role='xhs-label']").value.trim(),
    enabled: true
  };
}

async function saveXhsAccountRow(row) {
  await api(`/api/v1/devices/${encodeURIComponent(row.dataset.deviceId)}/xhs-accounts/${encodeURIComponent(row.dataset.appSlot)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(xhsAccountRowPayload(row))
  });
}

els.createRequestButton.addEventListener("click", async () => {
  const phoneNumber = els.requestPhoneInput.value;
  if (!phoneNumber) return;
  els.createRequestButton.disabled = true;
  els.createRequestButton.textContent = "等待中...";
  try {
    const payload = await api("/api/v1/activations", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        phoneNumber,
        platform: els.requestPlatformInput.value,
        ttlSeconds: 300,
        clientRequestId: `ui-${phoneNumber}-${els.requestPlatformInput.value}-${Date.now()}`
      })
    });
    if (payload.activation) {
      upsertActivation(payload.activation);
      updateActivationHint(payload.activation);
      startActivationStatusPoll(payload.activation.activationId);
    }
  } catch (error) {
    if (error.payload?.activation) {
      upsertActivation(error.payload.activation);
      updateActivationHint(error.payload.activation);
      startActivationStatusPoll(error.payload.activation.activationId);
    } else {
      els.requestHint.textContent = error.message;
    }
  } finally {
    els.createRequestButton.disabled = false;
    els.createRequestButton.textContent = "开始等待验证码";
    render();
  }
});

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result));
    reader.addEventListener("error", () => reject(reader.error || new Error("读取二维码图片失败")));
    reader.readAsDataURL(file);
  });
}

function loadImageFromDataUrl(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener("load", () => resolve(image));
    image.addEventListener("error", () => reject(new Error("二维码图片无法解析")));
    image.src = dataUrl;
  });
}

async function compressQrImage(file) {
  const originalDataUrl = await readFileAsDataUrl(file);
  const image = await loadImageFromDataUrl(originalDataUrl);
  const scale = Math.min(1, QR_IMAGE_MAX_SIDE / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
  const context = canvas.getContext("2d", { alpha: false });
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);

  for (const quality of [0.9, 0.82, 0.74, 0.66, 0.58, 0.5]) {
    const dataUrl = canvas.toDataURL("image/jpeg", quality);
    if (dataUrl.length <= QR_IMAGE_MAX_DATA_URL_LENGTH) {
      return {
        dataUrl,
        fileName: file.name.replace(/\.[^.]+$/, "") + ".jpg",
        originalBytes: file.size,
        outputBytes: Math.ceil(dataUrl.length * 0.75),
        width: canvas.width,
        height: canvas.height
      };
    }
  }

  throw new Error("图片压缩后仍然过大，请裁剪二维码区域后再上传。");
}

const SUPPORTED_WORKFLOW_ACTIONS = new Set([
  "launchApp",
  "forceStopApp",
  "tap",
  "wait",
  "assert",
  "back",
  "home",
  "sleep",
  "tapExactText",
  "tapLauncherIcon",
  "tapText",
  "tapTextCenter",
  "waitTapTextCenter",
  "tapByResourceId",
  "tapMiuiXspaceApp",
  "tapBottomTextCenter",
  "tapTopRightIcon",
  "tapFirstGalleryImage",
  "waitText",
  "tapPointWhenText"
]);

function parseWorkflowEditor() {
  try {
    return JSON.parse(els.workflowScriptEditor.value);
  } catch (error) {
    throw new Error(`脚本 JSON 格式错误：${error.message}`);
  }
}

function parseGlobalWorkflowEditor() {
  try {
    return JSON.parse(els.globalWorkflowEditor.value);
  } catch (error) {
    throw new Error(`脚本 JSON 格式错误：${error.message}`);
  }
}

function validateWorkflowScript(script) {
  const errors = [];
  const warnings = [];
  if (!script || typeof script !== "object" || Array.isArray(script)) {
    errors.push("脚本必须是 JSON object");
  } else {
    if (!String(script.version || "").trim()) errors.push("缺少 version");
    if (!String(script.description || "").trim()) errors.push("缺少 description");
    if (!Array.isArray(script.steps) || !script.steps.length) {
      errors.push("缺少 steps[]");
    } else {
      script.steps.forEach((step, index) => {
        const action = step?.action || "";
        if (!SUPPORTED_WORKFLOW_ACTIONS.has(action)) errors.push(`steps[${index}].action 不支持：${action || "空"}`);
        if (action === "tapPointWhenText") warnings.push(`steps[${index}] 使用固定坐标，不推荐`);
        for (const field of ["delayMs", "postDelayMs", "retryIntervalMs"]) {
          if (step?.[field] != null) {
            const delay = Number(step[field]);
            if (!Number.isFinite(delay) || delay < 0 || delay > 60_000) errors.push(`steps[${index}].${field} 必须是 0-60000`);
          }
        }
        for (const field of ["timeoutMs", "waitTimeoutMs"]) {
          if (step?.[field] != null) {
            const timeout = Number(step[field]);
            if (!Number.isFinite(timeout) || timeout < 1000 || timeout > 180_000) errors.push(`steps[${index}].${field} 必须是 1000-180000`);
          }
        }
      });
    }
  }
  return { ok: errors.length === 0, errors, warnings };
}

function workflowValidationText(validation) {
  if (validation.ok && !validation.warnings.length) return "校验通过，没有发现问题。";
  const parts = [];
  if (validation.errors.length) parts.push(`错误：${validation.errors.join("；")}`);
  if (validation.warnings.length) parts.push(`警告：${validation.warnings.join("；")}`);
  return parts.join(" ");
}

function currentSimConfigForPhone(phoneNumber) {
  const device = selectedDevice();
  const saved = (device?.sims || []).find((item) => item.phoneNumber === phoneNumber) || {};
  const rows = [...els.simList.querySelectorAll(".sim-editor")];
  const row = rows.find((item) => item.querySelector("[data-role='phone']").value.trim() === phoneNumber);
  return row ? { ...saved, ...simRowPayload(row) } : saved;
}

function currentXhsAccountConfig(appSlot) {
  const device = selectedDevice();
  const normalizedSlot = appSlot === "app2" ? "app2" : "app1";
  const saved = (device?.xhsAccounts || []).find((item) => item.appSlot === normalizedSlot) || { appSlot: normalizedSlot };
  const row = els.xhsAccountList?.querySelector(`.xhs-account-editor[data-app-slot="${CSS.escape(normalizedSlot)}"]`);
  return row ? { ...saved, ...xhsAccountRowPayload(row), appSlot: normalizedSlot } : saved;
}

function xhsAccountForDeviceSlot(deviceId, appSlot) {
  const device = deviceById(deviceId);
  const normalizedSlot = appSlot === "app2" ? "app2" : "app1";
  return (device?.xhsAccounts || []).find((item) => item.appSlot === normalizedSlot) || { appSlot: normalizedSlot };
}

async function createDeviceCommand(type, payload = {}) {
  if (!state.selectedDeviceId) throw new Error("请先选择一台手机");
  const response = await api(`/api/v1/devices/${encodeURIComponent(state.selectedDeviceId)}/commands`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ type, payload })
  });
  if (response.command) {
    state.commands = [response.command, ...state.commands.filter((old) => old.commandId !== response.command.commandId)];
  }
  return response.command;
}

async function saveWorkflowDraft() {
  const script = selectedWorkflowScript();
  if (!script) throw new Error("请先选择脚本");
  const draft = parseWorkflowEditor();
  const validation = validateWorkflowScript(draft);
  if (!validation.ok) throw new Error(workflowValidationText(validation));
  const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/draft`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ script: draft })
  });
  state.workflowScripts = [payload.script, ...state.workflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
    .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
  state.selectedWorkflowScriptId = payload.script.scriptId;
  return payload;
}

async function saveGlobalWorkflowDraft() {
  const script = selectedGlobalWorkflowScript();
  if (!script) throw new Error("请先选择脚本");
  const draft = parseGlobalWorkflowEditor();
  const validation = validateWorkflowScript(draft);
  if (!validation.ok) throw new Error(workflowValidationText(validation));
  const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/draft`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ script: draft })
  });
  state.globalWorkflowScripts = [payload.script, ...state.globalWorkflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
    .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
  state.globalWorkflowScriptId = payload.script.scriptId;
  if (payload.script.deviceId === state.selectedDeviceId) {
    state.workflowScripts = [payload.script, ...state.workflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
      .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
  }
  return payload;
}

els.workflowScriptSelect.addEventListener("change", () => {
  state.selectedWorkflowScriptId = els.workflowScriptSelect.value;
  renderWorkflowEditor();
});

els.validateWorkflowButton.addEventListener("click", () => {
  try {
    const validation = validateWorkflowScript(parseWorkflowEditor());
    els.workflowHint.textContent = workflowValidationText(validation);
  } catch (error) {
    els.workflowHint.textContent = error.message;
  }
});

els.saveWorkflowDraftButton.addEventListener("click", async () => {
  els.saveWorkflowDraftButton.disabled = true;
  try {
    const payload = await saveWorkflowDraft();
    els.workflowHint.textContent = `草稿已保存。${workflowValidationText(payload.validation || { ok: true, errors: [], warnings: [] })}`;
    render();
  } catch (error) {
    els.workflowHint.textContent = error.message;
  } finally {
    els.saveWorkflowDraftButton.disabled = false;
  }
});

els.publishWorkflowButton.addEventListener("click", async () => {
  const script = selectedWorkflowScript();
  if (!script) return;
  els.publishWorkflowButton.disabled = true;
  try {
    await saveWorkflowDraft();
    const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/publish`, { method: "POST" });
    state.workflowScripts = [payload.script, ...state.workflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
      .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
    state.selectedWorkflowScriptId = payload.script.scriptId;
    els.workflowHint.textContent = `已发布 v${payload.script.publishedVersion}。新扫码任务会使用这个脚本。`;
    render();
  } catch (error) {
    els.workflowHint.textContent = error.message;
  } finally {
    els.publishWorkflowButton.disabled = false;
  }
});

els.rollbackWorkflowButton.addEventListener("click", async () => {
  const script = selectedWorkflowScript();
  if (!script) return;
  els.rollbackWorkflowButton.disabled = true;
  try {
    const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/rollback`, { method: "POST" });
    state.workflowScripts = [payload.script, ...state.workflowScripts.filter((item) => item.scriptId !== payload.script.scriptId)]
      .sort((a, b) => a.appSlot.localeCompare(b.appSlot));
    state.selectedWorkflowScriptId = payload.script.scriptId;
    els.workflowHint.textContent = `已回滚并发布为 v${payload.script.publishedVersion}。`;
    render();
  } catch (error) {
    els.workflowHint.textContent = error.message;
  } finally {
    els.rollbackWorkflowButton.disabled = false;
  }
});

els.testWorkflowButton.addEventListener("click", async () => {
  const script = selectedWorkflowScript();
  const file = els.qrImageInput.files?.[0];
  if (!script) return;
  if (!file) {
    els.workflowHint.textContent = "请先在 Remote Scan 里选择一张二维码图片，再下发测试。";
    return;
  }
  els.testWorkflowButton.disabled = true;
  try {
    await saveWorkflowDraft();
    const image = await compressQrImage(file);
    const xhsAccount = currentXhsAccountConfig(script.appSlot || "app1");
    const payload = await api(`/api/v1/workflow-scripts/${encodeURIComponent(script.scriptId)}/test`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        payload: {
          qrImageDataUrl: image.dataUrl,
          fileName: image.fileName,
          xhsAccount: xhsAccount.accountName || "",
          xhsAppSlot: script.appSlot || xhsAccount.appSlot || "app1"
        }
      })
    });
    if (payload.command) state.commands = [payload.command, ...state.commands.filter((item) => item.commandId !== payload.command.commandId)];
    els.workflowHint.textContent = "测试任务已下发，使用当前草稿脚本，不影响发布版。";
    render();
  } catch (error) {
    els.workflowHint.textContent = error.message;
  } finally {
    els.testWorkflowButton.disabled = false;
  }
});

els.qrImageInput.addEventListener("change", () => {
  updateScanPanel();
  const file = els.qrImageInput.files?.[0];
  if (file) {
    els.commandHint.textContent = `已选择 ${file.name}，确认账号后可以下发扫码任务。`;
  }
});

els.xhsAccountSelect.addEventListener("change", () => {
  updateScanPanel();
  const target = selectedXhsScanTarget();
  if (target) {
    els.commandHint.textContent = `已选择 ${target.accountName || target.displayText}，扫码会走 ${target.appSlot}。`;
  }
});

els.manageXhsAccountsButton.addEventListener("click", () => {
  state.workbenchTab = "sims";
  localStorage.setItem("smsWorkbenchTab", state.workbenchTab);
  render();
});

els.openScanButton.addEventListener("click", async () => {
  els.openScanButton.disabled = true;
  els.commandHint.textContent = "唤醒任务已进入设备队列。在线设备通常 2-5 秒响应；熄屏省电时会等下一次轮询。";
  try {
    await createDeviceCommand("open_xhs_scan");
    render();
  } catch (error) {
    els.commandHint.textContent = error.message;
  } finally {
    els.openScanButton.disabled = false;
  }
});

els.sendQrCommandButton.addEventListener("click", async () => {
  const file = els.qrImageInput.files?.[0];
  if (!file) {
    els.commandHint.textContent = "请先选择一张二维码图片。";
    updateScanPanel();
    return;
  }
  const target = selectedXhsScanTarget();
  if (!target?.accountName) {
    els.commandHint.textContent = "请先在“SIM / 账号”里填写本机小红书账号。";
    updateScanPanel();
    return;
  }
  state.isSendingQrCommand = true;
  updateScanPanel();
  els.commandHint.textContent = `正在压缩二维码截图，并下发给 ${target.accountName} · ${target.appSlot}。`;
  try {
    const image = await compressQrImage(file);
    await createDeviceCommand("xhs_qr_from_gallery", {
      qrImageDataUrl: image.dataUrl,
      fileName: image.fileName,
      strategy: "server_workflow_script",
      autoConfirmLogin: true,
      xhsAccount: target.accountName,
      xhsAppSlot: target.appSlot
    });
    els.commandHint.textContent = `任务已下发给 ${target.accountName} · ${target.appSlot}。图片已压缩为 ${image.width}x${image.height}，手机会相册识别二维码并点击确认登录。`;
    render();
  } catch (error) {
    els.commandHint.textContent = error.message;
  } finally {
    state.isSendingQrCommand = false;
    updateScanPanel();
  }
});

setInterval(render, 1000);
render();
loadAll().then(connectStream).catch(showError);
