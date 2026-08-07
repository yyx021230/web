import crypto from "node:crypto";
import http from "node:http";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { WebSocketServer, WebSocket } from "ws";

const { Pool } = pg;
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(__dirname, "public");
const appReleaseDir = process.env.APK_RELEASE_DIR || path.join(publicDir, "releases");
const appReleaseMetaPath = process.env.APK_RELEASE_META || path.join(appReleaseDir, "latest.json");

const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || "0.0.0.0";
const DATABASE_URL = process.env.DATABASE_URL;
const PUBLIC_BASE_URL = process.env.PUBLIC_BASE_URL || "https://47.98.127.132";
const RETENTION_MINUTES = Number(process.env.SMS_RETENTION_MINUTES || 30);
const DEFAULT_TTL_SECONDS = Number(process.env.DEFAULT_ACTIVATION_TTL_SECONDS || 300);
const MAX_WAIT_SECONDS = Number(process.env.MAX_WAIT_SECONDS || 60);
const COMMAND_RUNNING_TIMEOUT_SECONDS = Number(process.env.COMMAND_RUNNING_TIMEOUT_SECONDS || 150);
const DEV_TOKENS_ENABLED = process.env.ALLOW_DEV_TOKENS === "true" || process.env.NODE_ENV !== "production";
const SUPPORTED_WORKFLOW_ACTIONS = new Set([
  "launchApp",
  "forceStopApp",
  "tap",
  "wait",
  "assert",
  "back",
  "home",
  "openSelfFromLauncher",
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

const TOKENS = {
  admin: new Set([process.env.ADMIN_API_TOKEN, process.env.SMS_RELAY_TOKEN, DEV_TOKENS_ENABLED ? "dev-admin-token" : "", DEV_TOKENS_ENABLED ? "dev-local-token" : ""].filter(Boolean)),
  business: new Set([process.env.BUSINESS_API_TOKEN, process.env.SMS_RELAY_TOKEN, DEV_TOKENS_ENABLED ? "dev-business-token" : "", DEV_TOKENS_ENABLED ? "dev-local-token" : ""].filter(Boolean)),
  device: new Set([process.env.DEVICE_API_TOKEN, process.env.SMS_RELAY_TOKEN, DEV_TOKENS_ENABLED ? "dev-device-token" : "", DEV_TOKENS_ENABLED ? "dev-local-token" : ""].filter(Boolean)),
  windows_agent: new Set([process.env.WINDOWS_AGENT_TOKEN, process.env.SMS_RELAY_TOKEN, DEV_TOKENS_ENABLED ? "dev-windows-token" : "", DEV_TOKENS_ENABLED ? "dev-local-token" : ""].filter(Boolean))
};

if (!DATABASE_URL) {
  console.warn("DATABASE_URL is not set; using local development Postgres URL.");
}

const pool = new Pool({
  connectionString: DATABASE_URL || "postgres://sms:sms@127.0.0.1:5432/sms_code_center"
});

const sseClients = new Set();
const deviceLiveConnections = new Map();
const deviceLiveServer = new WebSocketServer({ noServer: true });

await migrate();
await expireStaleCommands().catch((error) => console.error("expireStaleCommands", error));
setInterval(() => expireActivations().catch((error) => console.error("expireActivations", error)), 15_000).unref();
setInterval(() => expireStaleCommands().catch((error) => console.error("expireStaleCommands", error)), 15_000).unref();
setInterval(() => purgeOldSms().catch((error) => console.error("purgeOldSms", error)), 60_000).unref();

function nowIso() {
  return new Date().toISOString();
}

function normalizePhone(value = "") {
  return String(value).replace(/[^\d+]/g, "");
}

function normalizePlatform(value = "") {
  const text = String(value || "").trim();
  if (!text) return "未知平台";
  if (/xhs|redbook|xiaohongshu/i.test(text)) return "小红书";
  return text;
}

function maskPhone(phone = "") {
  const normalized = normalizePhone(phone);
  if (normalized.length <= 7) return normalized ? "***" : "";
  return `${normalized.slice(0, 3)}****${normalized.slice(-4)}`;
}

function extractCode(body = "") {
  const normalized = String(body).replace(/\s+/g, " ");
  const patterns = [
    /(?:验证码|校验码|动态码|验证代码|确认码|短信码|code|Code|CODE)[^\dA-Za-z]{0,18}([A-Za-z0-9]{4,8})/,
    /([A-Za-z0-9]{4,8})(?:\s*为|是|，|。|\.|,)?[^，。,.]{0,24}(?:验证码|校验码|动态码|验证代码|确认码|短信码)/
  ];
  for (const pattern of patterns) {
    const match = normalized.match(pattern);
    if (match?.[1]) return match[1];
  }
  return "";
}

function detectPlatform(body = "", sender = "") {
  const text = `${sender} ${body}`;
  const candidates = ["小红书", "抖音", "微信", "支付宝", "淘宝", "京东", "美团", "拼多多", "快手", "微博", "百度", "腾讯", "阿里云", "懂车帝"];
  return candidates.find((name) => text.includes(name)) || sender || "未知平台";
}

function hashToken(token) {
  return crypto.createHash("sha256").update(String(token)).digest("hex");
}

function extractToken(req) {
  const auth = req.headers.authorization || "";
  if (auth.startsWith("Bearer ")) return auth.slice(7);
  return req.headers["x-sms-token"] || req.headers["x-api-key"] || "";
}

async function authContext(req, allowedRoles = []) {
  const token = String(extractToken(req) || "");
  if (!token) return null;
  const envRoles = Object.entries(TOKENS)
    .filter(([, tokens]) => tokens.has(token))
    .map(([role]) => role);
  if (envRoles.includes("admin")) return { role: "admin", name: "env-admin" };
  if (allowedRoles.some((role) => envRoles.includes(role))) return { role: allowedRoles.find((role) => envRoles.includes(role)), name: "env-token" };

  const row = await one(
    `select id, name, role from api_keys where key_hash = $1 and revoked_at is null and (expires_at is null or expires_at > now())`,
    [hashToken(token)]
  );
  if (!row) return null;
  if (row.role === "admin" || allowedRoles.includes(row.role)) return row;
  return null;
}

async function requireAuth(req, res, roles) {
  const context = await authContext(req, roles);
  if (!context) {
    json(res, 401, { error: "unauthorized" });
    return null;
  }
  return context;
}

async function query(sql, params = []) {
  return pool.query(sql, params);
}

async function one(sql, params = []) {
  const result = await query(sql, params);
  return result.rows[0] || null;
}

async function migrate() {
  await query(`create extension if not exists pgcrypto`);
  await query(`
    create table if not exists api_keys (
      id uuid primary key default gen_random_uuid(),
      name text not null,
      role text not null check (role in ('admin', 'device', 'business', 'windows_agent')),
      key_hash text not null unique,
      created_at timestamptz not null default now(),
      revoked_at timestamptz,
      expires_at timestamptz
    )
  `);
  await query(`alter table api_keys drop constraint if exists api_keys_role_check`);
  await query(`alter table api_keys add constraint api_keys_role_check check (role in ('admin', 'device', 'business', 'windows_agent'))`);
  await query(`
    create table if not exists devices (
      device_id text primary key,
      device_name text not null,
      model text,
      android_version text,
      app_version text,
      battery_level integer,
      windows_agent_id text,
      adb_serial text,
      adb_state text,
      adb_model text,
      adb_product text,
      adb_transport_id text,
      adb_last_seen_at timestamptz,
      raw jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      last_seen_at timestamptz not null default now()
    )
  `);
  await query(`alter table devices add column if not exists windows_agent_id text`);
  await query(`alter table devices add column if not exists adb_serial text`);
  await query(`alter table devices add column if not exists adb_state text`);
  await query(`alter table devices add column if not exists adb_model text`);
  await query(`alter table devices add column if not exists adb_product text`);
  await query(`alter table devices add column if not exists adb_transport_id text`);
  await query(`alter table devices add column if not exists adb_last_seen_at timestamptz`);
  await query(`create index if not exists idx_devices_windows_agent on devices(windows_agent_id)`);
  await query(`create index if not exists idx_devices_adb_serial on devices(adb_serial)`);
  await query(`
    create table if not exists windows_agents (
      agent_id text primary key,
      agent_name text not null,
      hostname text,
      version text,
      platform text,
      arch text,
      ip text,
      adb_version text,
      max_concurrent_adb_tasks integer not null default 1,
      device_task_concurrency integer not null default 1,
      status text not null default 'online',
      raw jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      last_seen_at timestamptz not null default now()
    )
  `);
  await query(`
    create table if not exists windows_agent_devices (
      agent_id text not null references windows_agents(agent_id) on delete cascade,
      adb_serial text not null,
      device_id text,
      state text not null default 'unknown',
      model text,
      product text,
      device_name text,
      transport_id text,
      battery_level integer,
      android_version text,
      raw jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      last_seen_at timestamptz not null default now(),
      primary key (agent_id, adb_serial)
    )
  `);
  await query(`create index if not exists idx_windows_agent_devices_device on windows_agent_devices(device_id)`);
  await query(`
    create table if not exists windows_agent_tasks (
      id uuid primary key default gen_random_uuid(),
      agent_id text not null references windows_agents(agent_id) on delete cascade,
      adb_serial text,
      device_id text,
      type text not null,
      status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')) default 'queued',
      payload jsonb not null default '{}'::jsonb,
      result jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      picked_at timestamptz,
      completed_at timestamptz
    )
  `);
  await query(`create index if not exists idx_windows_agent_tasks_next on windows_agent_tasks(agent_id, status, created_at)`);
  await query(`
    create table if not exists windows_agent_task_events (
      id bigserial primary key,
      task_id uuid not null references windows_agent_tasks(id) on delete cascade,
      agent_id text,
      adb_serial text,
      phase text not null default 'log',
      level text not null default 'info',
      message text not null default '',
      detail jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now()
    )
  `);
  await query(`create index if not exists idx_windows_agent_task_events_task on windows_agent_task_events(task_id, created_at, id)`);
  await query(`
    create table if not exists device_sims (
      device_id text not null references devices(device_id) on delete cascade,
      subscription_id integer not null,
      slot_index integer,
      carrier_name text,
      phone_number text,
      label text,
      xhs_account text,
      xhs_app_slot text not null default 'app1',
      enabled boolean not null default true,
      last_seen_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      primary key (device_id, subscription_id)
    )
  `);
  await query(`create index if not exists idx_device_sims_phone on device_sims(phone_number)`);
  await query(`alter table device_sims add column if not exists xhs_account text`);
  await query(`alter table device_sims add column if not exists xhs_app_slot text not null default 'app1'`);
  await query(`
    create table if not exists device_xhs_accounts (
      device_id text not null references devices(device_id) on delete cascade,
      app_slot text not null,
      account_name text,
      label text,
      enabled boolean not null default true,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      primary key (device_id, app_slot)
    )
  `);
  await query(`
    insert into device_xhs_accounts(device_id, app_slot, account_name, label, enabled)
    select distinct on (device_id, xhs_app_slot)
      device_id,
      xhs_app_slot,
      nullif(xhs_account, ''),
      case when xhs_app_slot = 'app2' then 'Ⅱ·小红书' else '小红书' end,
      true
    from device_sims
    where xhs_app_slot in ('app1', 'app2')
      and nullif(xhs_account, '') is not null
    on conflict(device_id, app_slot) do nothing
  `);
  await query(`
    create table if not exists activations (
      id uuid primary key default gen_random_uuid(),
      phone_number text not null,
      platform text not null,
      status text not null check (status in ('arming', 'waiting', 'received', 'expired', 'ambiguous', 'cancelled')) default 'arming',
      client_request_id text,
      purpose text not null default 'login',
      code text,
      sms_event_id uuid,
      device_id text,
      device_name text,
      sender text,
      body text,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      expires_at timestamptz not null,
      completed_at timestamptz
    )
  `);
  await query(`alter table activations alter column status set default 'arming'`);
  await query(`alter table activations drop constraint if exists activations_status_check`);
  await query(`alter table activations add constraint activations_status_check check (status in ('arming', 'waiting', 'received', 'expired', 'ambiguous', 'cancelled'))`);
  await query(`create index if not exists idx_activations_waiting on activations(phone_number, platform, status, created_at)`);
  await query(`create unique index if not exists idx_activations_client_request on activations(client_request_id) where client_request_id is not null`);
  await query(`
    create table if not exists sms_events (
      id uuid primary key default gen_random_uuid(),
      event_fingerprint text not null unique,
      device_id text not null references devices(device_id) on delete cascade,
      subscription_id integer,
      slot_index integer,
      phone_number text,
      sender text not null,
      platform text not null,
      code text,
      body text not null,
      status text not null check (status in ('received', 'matched', 'ambiguous', 'duplicate')) default 'received',
      matched_activation_id uuid references activations(id),
      received_at timestamptz not null,
      created_at timestamptz not null default now()
    )
  `);
  await query(`create index if not exists idx_sms_events_lookup on sms_events(phone_number, platform, received_at desc)`);
  await query(`
    create table if not exists device_commands (
      id uuid primary key default gen_random_uuid(),
      device_id text not null references devices(device_id) on delete cascade,
      type text not null,
      status text not null check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')) default 'queued',
      payload jsonb not null default '{}'::jsonb,
      result jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      picked_at timestamptz,
      completed_at timestamptz
    )
  `);
  await query(`create index if not exists idx_device_commands_next on device_commands(device_id, status, created_at)`);
  await query(`
    create table if not exists device_command_events (
      id bigserial primary key,
      command_id uuid not null references device_commands(id) on delete cascade,
      device_id text,
      step_index integer,
      step_id text,
      phase text not null default 'log',
      level text not null default 'info',
      message text not null default '',
      package_name text,
      ui_snapshot text,
      screenshot jsonb,
      detail jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now()
    )
  `);
  await query(`create index if not exists idx_device_command_events_command on device_command_events(command_id, created_at, id)`);
  await query(`
    create table if not exists workflow_scripts (
      id uuid primary key default gen_random_uuid(),
      device_id text not null references devices(device_id) on delete cascade,
      platform text not null default '小红书',
      app_slot text not null default 'app1',
      command_type text not null default 'xhs_qr_from_gallery',
      name text not null,
      draft_script jsonb not null,
      published_script jsonb,
      published_version integer not null default 0,
      enabled boolean not null default true,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      published_at timestamptz,
      unique(device_id, platform, app_slot, command_type)
    )
  `);
  await query(`
    create table if not exists workflow_script_versions (
      id uuid primary key default gen_random_uuid(),
      workflow_script_id uuid not null references workflow_scripts(id) on delete cascade,
      version integer not null,
      script jsonb not null,
      created_at timestamptz not null default now()
    )
  `);
  await query(`create index if not exists idx_workflow_scripts_lookup on workflow_scripts(device_id, platform, app_slot, command_type, enabled)`);
  await query(`create index if not exists idx_workflow_script_versions_latest on workflow_script_versions(workflow_script_id, version desc)`);
  await query(`
    create table if not exists audit_logs (
      id bigserial primary key,
      action text not null,
      actor_role text,
      actor_name text,
      phone_mask text,
      device_id text,
      activation_id uuid,
      detail jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now()
    )
  `);
  const devices = await query(`select device_id from devices`);
  for (const device of devices.rows) await ensureWorkflowScriptsForDevice(device.device_id);
  await upgradeDefaultWorkflowScripts();
}

async function upgradeDefaultWorkflowScripts() {
  for (const appSlot of ["app1", "app2"]) {
    const script = xhsQrLoginWorkflowScript(appSlot);
    await query(
      `update workflow_scripts
       set draft_script = $1,
           published_script = $1,
           published_version = greatest(published_version + 1, 2),
           published_at = now(),
           updated_at = now()
       where platform = '小红书'
         and command_type = 'xhs_qr_from_gallery'
         and app_slot = $2
         and name = $3
         and (
           published_script is null
          or published_script->>'version' in ('xhs-qr-login-v1', 'xhs-qr-login-v2', 'xhs-qr-login-v3', 'xhs-qr-login-v4', 'xhs-qr-login-v5', 'xhs-qr-login-v6', 'xhs-qr-login-v7', 'xhs-qr-login-v8', 'xhs-qr-login-v9', 'xhs-qr-login-v10', 'xhs-qr-login-v11', 'xhs-qr-login-v12', 'xhs-qr-login-v13', 'xhs-qr-login-v14')
          or draft_script->>'version' in ('xhs-qr-login-v1', 'xhs-qr-login-v2', 'xhs-qr-login-v3', 'xhs-qr-login-v4', 'xhs-qr-login-v5', 'xhs-qr-login-v6', 'xhs-qr-login-v7', 'xhs-qr-login-v8', 'xhs-qr-login-v9', 'xhs-qr-login-v10', 'xhs-qr-login-v11', 'xhs-qr-login-v12', 'xhs-qr-login-v13', 'xhs-qr-login-v14')
         )`,
      [script, appSlot, `小红书扫码默认脚本 ${appSlot}`]
    );
  }
}

async function audit(action, ctx = {}, detail = {}) {
  await query(
    `insert into audit_logs(action, actor_role, actor_name, phone_mask, device_id, activation_id, detail)
     values ($1,$2,$3,$4,$5,$6,$7)`,
    [action, ctx.role || null, ctx.name || null, detail.phoneNumber ? maskPhone(detail.phoneNumber) : null, detail.deviceId || null, detail.activationId || null, detail]
  );
}

async function expireActivations() {
  const result = await query(
    `update activations set status = 'expired', updated_at = now()
     where status in ('arming', 'waiting') and expires_at <= now()
     returning *`
  );
  for (const row of result.rows) broadcast("activation", publicActivation(row));
}

async function purgeOldSms() {
  await query(`delete from sms_events where created_at < now() - ($1::int * interval '1 minute')`, [RETENTION_MINUTES]);
}

async function expireStaleCommands() {
  const result = await query(
    `update device_commands
     set status = 'failed',
         result = jsonb_build_object(
           'message', '任务执行超时：手机超过 ' || $1::text || ' 秒未回传进度，已由服务器标记失败',
           'serverTimeout', true,
           'timeoutSeconds', $1::int,
           'lastResult', result,
           'timedOutAt', now()
         ),
         updated_at = now(),
         completed_at = now()
     where status = 'running'
       and coalesce(updated_at, picked_at, created_at) < now() - ($1::int * interval '1 second')
     returning *`,
    [COMMAND_RUNNING_TIMEOUT_SECONDS]
  );
  for (const row of result.rows) {
    await audit("device_command_timeout", { role: "system", name: "command-watchdog" }, { deviceId: row.device_id, activationId: row.id, type: row.type });
    broadcast("command", commandSummary(row));
  }
}

function publicActivation(row) {
  if (!row) return null;
  return {
    activationId: row.id,
    status: row.status,
    phoneNumber: row.phone_number,
    platform: row.platform,
    clientRequestId: row.client_request_id,
    purpose: row.purpose,
    code: row.code || "",
    sender: row.sender || "",
    body: row.body || "",
    deviceId: row.device_id || "",
    deviceName: row.device_name || "",
    smsEventId: row.sms_event_id || "",
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    expiresAt: row.expires_at,
    completedAt: row.completed_at,
    secondsLeft: Math.max(0, Math.floor((new Date(row.expires_at).getTime() - Date.now()) / 1000))
  };
}

function publicSmsEvent(row) {
  return {
    id: row.id,
    eventFingerprint: row.event_fingerprint,
    deviceId: row.device_id,
    subscriptionId: row.subscription_id,
    slotIndex: row.slot_index,
    phoneNumber: row.phone_number || "",
    sender: row.sender,
    platform: row.platform,
    code: row.code || "",
    body: row.body,
    status: row.status,
    matchedActivationId: row.matched_activation_id || "",
    receivedAt: row.received_at,
    createdAt: row.created_at,
    expiresAt: new Date(new Date(row.received_at).getTime() + RETENTION_MINUTES * 60 * 1000).toISOString()
  };
}

function publicDeviceCommand(row, { includePayload = true } = {}) {
  if (!row) return null;
  const payload = row.payload || {};
  const safePayload = includePayload
    ? payload
    : {
        ...payload,
        qrImageDataUrl: payload.qrImageDataUrl ? "[image-data]" : undefined
      };
  return {
    commandId: row.id,
    deviceId: row.device_id,
    type: row.type,
    status: row.status,
    payload: safePayload,
    result: row.result || {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    pickedAt: row.picked_at,
    completedAt: row.completed_at
  };
}

function publicCommandEvent(row) {
  if (!row) return null;
  return {
    eventId: row.id,
    commandId: row.command_id,
    deviceId: row.device_id || "",
    stepIndex: row.step_index,
    stepId: row.step_id || "",
    phase: row.phase,
    level: row.level,
    message: row.message || "",
    packageName: row.package_name || "",
    uiSnapshot: row.ui_snapshot || "",
    screenshot: row.screenshot || null,
    detail: row.detail || {},
    createdAt: row.created_at
  };
}

async function upsertDevice(input = {}) {
  const deviceId = String(input.deviceId || "unknown-device").slice(0, 160);
  const hasDeviceName = typeof input.deviceName === "string" && input.deviceName.trim() !== "";
  const deviceName = String(hasDeviceName ? input.deviceName : deviceId).slice(0, 160);
  const sims = Array.isArray(input.sims) ? input.sims : [];
  const raw = { ...input };
  delete raw.body;
  const device = await one(
    `insert into devices(device_id, device_name, model, android_version, app_version, battery_level, adb_serial, raw, updated_at, last_seen_at)
     values ($1,$2,$3,$4,$5,$6,$7,$8,now(),now())
     on conflict (device_id) do update set
       device_name = case when $9::boolean then excluded.device_name else devices.device_name end,
       model = coalesce(nullif(excluded.model, ''), devices.model),
       android_version = coalesce(nullif(excluded.android_version, ''), devices.android_version),
       app_version = coalesce(nullif(excluded.app_version, ''), devices.app_version),
       battery_level = coalesce(excluded.battery_level, devices.battery_level),
       adb_serial = coalesce(nullif(excluded.adb_serial, ''), devices.adb_serial),
       raw = devices.raw || excluded.raw,
       updated_at = now(),
       last_seen_at = now()
     returning *`,
    [deviceId, deviceName, input.model || "", input.androidVersion || "", input.appVersion || "", input.batteryLevel ?? null, input.adbSerial || "", raw, hasDeviceName]
  );

  for (const sim of sims) {
    const subscriptionId = Number(sim.subscriptionId);
    if (!Number.isFinite(subscriptionId)) continue;
    const phoneNumber = normalizePhone(sim.phoneNumber || sim.number || "");
    await query(
      `insert into device_sims(device_id, subscription_id, slot_index, carrier_name, phone_number, enabled, last_seen_at, updated_at)
       values ($1,$2,$3,$4,$5,$6,now(),now())
       on conflict (device_id, subscription_id) do update set
         slot_index = excluded.slot_index,
         carrier_name = excluded.carrier_name,
         phone_number = coalesce(nullif(device_sims.phone_number, ''), excluded.phone_number),
         enabled = device_sims.enabled and excluded.enabled,
         last_seen_at = now(),
         updated_at = now()`,
      [deviceId, subscriptionId, Number.isFinite(Number(sim.slotIndex)) ? Number(sim.slotIndex) : null, sim.carrierName || "", phoneNumber || null, sim.enabled !== false]
    );
  }
  return device;
}

async function publicDevice(row) {
  const sims = await query(`select * from device_sims where device_id = $1 order by slot_index nulls last, subscription_id`, [row.device_id]);
  const xhsAccounts = await ensureDeviceXhsAccounts(row.device_id);
  const xhsTargets = normalizeXhsTargets(row.raw?.xhsTargets || []);
  return {
    deviceId: row.device_id,
    deviceName: row.device_name,
    model: row.model || "",
    androidVersion: row.android_version || "",
    appVersion: row.app_version || "",
    batteryLevel: row.battery_level,
    lastSeenAt: row.last_seen_at,
    adb: {
      agentId: row.windows_agent_id || "",
      serial: row.adb_serial || "",
      state: row.adb_state || "",
      model: row.adb_model || "",
      product: row.adb_product || "",
      transportId: row.adb_transport_id || "",
      lastSeenAt: row.adb_last_seen_at || null
    },
    liveConnected: liveConnectionCount(row.device_id) > 0,
    liveConnectionCount: liveConnectionCount(row.device_id),
    liveStatus: row.raw?.liveStatus && typeof row.raw.liveStatus === "object" ? row.raw.liveStatus : {},
    sims: sims.rows.map((sim) => ({
      subscriptionId: sim.subscription_id,
      slotIndex: sim.slot_index,
      carrierName: sim.carrier_name || "",
      phoneNumber: sim.phone_number || "",
      label: sim.label || "",
      xhsAccount: sim.xhs_account || "",
      xhsAppSlot: sim.xhs_app_slot || "app1",
      enabled: sim.enabled,
      lastSeenAt: sim.last_seen_at
    })),
    xhsAccounts,
    xhsTargets
  };
}

function normalizeAgentId(value = "") {
  return String(value || "").trim().slice(0, 120);
}

function normalizeAdbSerial(value = "") {
  return String(value || "").trim().slice(0, 160);
}

function publicWindowsAgent(row, devices = [], taskCounts = {}) {
  if (!row) return null;
  return {
    agentId: row.agent_id,
    agentName: row.agent_name,
    hostname: row.hostname || "",
    version: row.version || "",
    platform: row.platform || "",
    arch: row.arch || "",
    ip: row.ip || "",
    adbVersion: row.adb_version || "",
    maxConcurrentAdbTasks: row.max_concurrent_adb_tasks,
    deviceTaskConcurrency: row.device_task_concurrency,
    status: row.status || "online",
    raw: row.raw || {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    lastSeenAt: row.last_seen_at,
    devices: devices.map(publicWindowsAgentDevice),
    taskCounts
  };
}

function publicWindowsAgentDevice(row) {
  if (!row) return null;
  return {
    agentId: row.agent_id,
    adbSerial: row.adb_serial,
    deviceId: row.device_id || "",
    state: row.state || "unknown",
    model: row.model || "",
    product: row.product || "",
    deviceName: row.device_name || "",
    transportId: row.transport_id || "",
    batteryLevel: row.battery_level,
    androidVersion: row.android_version || "",
    raw: row.raw || {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    lastSeenAt: row.last_seen_at
  };
}

function publicWindowsAgentTask(row, { includePayload = true } = {}) {
  if (!row) return null;
  return {
    taskId: row.id,
    agentId: row.agent_id,
    adbSerial: row.adb_serial || "",
    deviceId: row.device_id || "",
    type: row.type,
    status: row.status,
    payload: includePayload ? row.payload || {} : undefined,
    result: row.result || {},
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    pickedAt: row.picked_at,
    completedAt: row.completed_at
  };
}

function publicWindowsAgentTaskEvent(row) {
  if (!row) return null;
  return {
    eventId: row.id,
    taskId: row.task_id,
    agentId: row.agent_id || "",
    adbSerial: row.adb_serial || "",
    phase: row.phase || "log",
    level: row.level || "info",
    message: row.message || "",
    detail: row.detail || {},
    createdAt: row.created_at
  };
}

async function loadWindowsAgent(agentId) {
  const agent = await one(`select * from windows_agents where agent_id = $1`, [agentId]);
  if (!agent) return null;
  const devices = await query(`select * from windows_agent_devices where agent_id = $1 order by last_seen_at desc, adb_serial`, [agentId]);
  const counts = await query(
    `select status, count(*)::int as count
     from windows_agent_tasks
     where agent_id = $1
     group by status`,
    [agentId]
  );
  const taskCounts = Object.fromEntries(counts.rows.map((row) => [row.status, row.count]));
  return publicWindowsAgent(agent, devices.rows, taskCounts);
}

async function upsertWindowsAgent(input = {}, req = null) {
  const agentId = normalizeAgentId(input.agentId);
  if (!agentId) {
    const error = new Error("agentId is required");
    error.statusCode = 400;
    throw error;
  }
  const agentName = String(input.agentName || input.name || agentId).trim().slice(0, 160);
  const raw = { ...input };
  const row = await one(
    `insert into windows_agents(
       agent_id, agent_name, hostname, version, platform, arch, ip, adb_version,
       max_concurrent_adb_tasks, device_task_concurrency, status, raw, updated_at, last_seen_at
     )
     values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'online',$11,now(),now())
     on conflict(agent_id) do update set
       agent_name = coalesce(nullif(excluded.agent_name, ''), windows_agents.agent_name),
       hostname = coalesce(nullif(excluded.hostname, ''), windows_agents.hostname),
       version = coalesce(nullif(excluded.version, ''), windows_agents.version),
       platform = coalesce(nullif(excluded.platform, ''), windows_agents.platform),
       arch = coalesce(nullif(excluded.arch, ''), windows_agents.arch),
       ip = coalesce(nullif(excluded.ip, ''), windows_agents.ip),
       adb_version = coalesce(nullif(excluded.adb_version, ''), windows_agents.adb_version),
       max_concurrent_adb_tasks = excluded.max_concurrent_adb_tasks,
       device_task_concurrency = excluded.device_task_concurrency,
       status = 'online',
       raw = windows_agents.raw || excluded.raw,
       updated_at = now(),
       last_seen_at = now()
     returning *`,
    [
      agentId,
      agentName,
      input.hostname || "",
      input.version || "",
      input.platform || process.platform,
      input.arch || process.arch,
      input.ip || req?.socket?.remoteAddress || "",
      input.adbVersion || "",
      Math.max(1, Number(input.maxConcurrentAdbTasks || 1)),
      Math.max(1, Number(input.deviceTaskConcurrency || 1)),
      raw
    ]
  );
  return row;
}

async function syncWindowsAgentDevices(agentId, devices = []) {
  const seen = [];
  for (const item of Array.isArray(devices) ? devices : []) {
    const adbSerial = normalizeAdbSerial(item.adbSerial || item.serial);
    if (!adbSerial) continue;
    seen.push(adbSerial);
    const state = String(item.state || "unknown").trim().slice(0, 40);
    const deviceId = String(item.deviceId || (state === "device" ? `adb:${adbSerial}` : "")).slice(0, 160);
    const model = String(item.model || "").slice(0, 120);
    const product = String(item.product || "").slice(0, 120);
    const deviceName = String(item.deviceName || model || adbSerial).slice(0, 160);
    const androidVersion = String(item.androidVersion || "").slice(0, 80);
    const transportId = String(item.transportId || "").slice(0, 80);
    const batteryLevel = Number.isFinite(Number(item.batteryLevel)) ? Number(item.batteryLevel) : null;
    const raw = { ...item };
    await query(
      `insert into windows_agent_devices(
         agent_id, adb_serial, device_id, state, model, product, device_name, transport_id,
         battery_level, android_version, raw, updated_at, last_seen_at
       )
       values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,now(),now())
       on conflict(agent_id, adb_serial) do update set
         device_id = coalesce(nullif(excluded.device_id, ''), windows_agent_devices.device_id),
         state = excluded.state,
         model = coalesce(nullif(excluded.model, ''), windows_agent_devices.model),
         product = coalesce(nullif(excluded.product, ''), windows_agent_devices.product),
         device_name = coalesce(nullif(excluded.device_name, ''), windows_agent_devices.device_name),
         transport_id = coalesce(nullif(excluded.transport_id, ''), windows_agent_devices.transport_id),
         battery_level = coalesce(excluded.battery_level, windows_agent_devices.battery_level),
         android_version = coalesce(nullif(excluded.android_version, ''), windows_agent_devices.android_version),
         raw = windows_agent_devices.raw || excluded.raw,
         updated_at = now(),
         last_seen_at = now()`,
      [agentId, adbSerial, deviceId, state, model, product, deviceName, transportId, batteryLevel, androidVersion, raw]
    );
    if (deviceId && state === "device") {
      await query(
        `insert into devices(
           device_id, device_name, model, android_version, battery_level, windows_agent_id,
           adb_serial, adb_state, adb_model, adb_product, adb_transport_id, adb_last_seen_at,
           raw, updated_at, last_seen_at
         )
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,now(),$12,now(),now())
         on conflict(device_id) do update set
           device_name = case when devices.device_name = devices.device_id or devices.device_name like 'adb:%' then excluded.device_name else devices.device_name end,
           model = coalesce(nullif(excluded.model, ''), devices.model),
           android_version = coalesce(nullif(excluded.android_version, ''), devices.android_version),
           battery_level = coalesce(excluded.battery_level, devices.battery_level),
           windows_agent_id = excluded.windows_agent_id,
           adb_serial = excluded.adb_serial,
           adb_state = excluded.adb_state,
           adb_model = excluded.adb_model,
           adb_product = excluded.adb_product,
           adb_transport_id = excluded.adb_transport_id,
           adb_last_seen_at = now(),
           raw = devices.raw || excluded.raw,
           updated_at = now()
         returning *`,
        [deviceId, deviceName, model, androidVersion, batteryLevel, agentId, adbSerial, state, model, product, transportId, { adb: raw }]
      );
      await ensureWorkflowScriptsForDevice(deviceId);
      broadcastDeviceSnapshot(deviceId).catch((error) => console.error("broadcastDeviceSnapshot", error));
    }
  }
  if (seen.length) {
    await query(
      `update windows_agent_devices
       set state = 'missing', updated_at = now()
       where agent_id = $1 and not (adb_serial = any($2::text[]))`,
      [agentId, seen]
    );
  } else {
    await query(`update windows_agent_devices set state = 'missing', updated_at = now() where agent_id = $1`, [agentId]);
  }
  const agent = await loadWindowsAgent(agentId);
  broadcast("windowsAgent", agent);
  return agent;
}

function normalizeXhsTargets(targets) {
  if (!Array.isArray(targets)) return [];
  return targets
    .map((target, index) => ({
      label: String(target?.label || (index === 0 ? "小红书" : "Ⅱ·小红书")).trim(),
      packageName: String(target?.packageName || "").trim(),
      activityName: String(target?.activityName || "").trim(),
      appSlot: target?.appSlot === "app2" ? "app2" : "app1"
    }))
    .filter((target) => target.packageName && target.activityName);
}

function pickXhsLaunchTarget(device, appSlot) {
  const targets = normalizeXhsTargets(device?.raw?.xhsTargets || []);
  if (!targets.length) return null;
  const normalizedSlot = appSlot === "app2" ? "app2" : "app1";
  return targets.find((target) => target.appSlot === normalizedSlot) || targets[0];
}

async function ensureDeviceXhsAccounts(deviceId) {
  for (const appSlot of ["app1", "app2"]) {
    await query(
      `insert into device_xhs_accounts(device_id, app_slot, account_name, label, enabled)
       values ($1,$2,'',$3,true)
       on conflict(device_id, app_slot) do nothing`,
      [deviceId, appSlot, appSlot === "app2" ? "Ⅱ·小红书" : "小红书"]
    );
  }
  const rows = await query(
    `select * from device_xhs_accounts
     where device_id = $1
     order by case app_slot when 'app1' then 1 when 'app2' then 2 else 3 end, app_slot`,
    [deviceId]
  );
  return rows.rows.map((row) => ({
    appSlot: row.app_slot,
    accountName: row.account_name || "",
    label: row.label || "",
    enabled: row.enabled,
    updatedAt: row.updated_at
  }));
}

async function resolveEventPhone(deviceId, subscriptionId) {
  if (Number.isFinite(subscriptionId)) {
    const sim = await one(
      `select phone_number, enabled from device_sims where device_id = $1 and subscription_id = $2`,
      [deviceId, subscriptionId]
    );
    if (sim?.enabled && sim.phone_number) return { phoneNumber: sim.phone_number, ambiguous: false };
    return { phoneNumber: "", ambiguous: true };
  }

  const sims = await query(
    `select phone_number from device_sims where device_id = $1 and enabled = true and phone_number is not null and phone_number <> ''`,
    [deviceId]
  );
  if (sims.rows.length === 1) return { phoneNumber: sims.rows[0].phone_number, ambiguous: false };
  return { phoneNumber: "", ambiguous: sims.rows.length > 1 };
}

async function completeActivationForEvent(event) {
  if (!event.code || !event.phone_number || event.status === "ambiguous") return null;
  const activation = await one(
    `select * from activations
     where status = 'waiting'
       and phone_number = $1
       and platform = $2
       and expires_at > now()
       and $3::timestamptz >= created_at - interval '5 seconds'
     order by created_at asc
     limit 1`,
    [event.phone_number, event.platform, event.received_at]
  );
  if (!activation) return null;
  const updated = await one(
    `update activations set
       status = 'received',
       code = $1,
       sms_event_id = $2,
       device_id = $3,
       device_name = (select device_name from devices where device_id = $3),
       sender = $4,
       body = $5,
       completed_at = now(),
       updated_at = now()
     where id = $6 and status = 'waiting'
     returning *`,
    [event.code, event.id, event.device_id, event.sender, event.body, activation.id]
  );
  if (!updated) return null;
  await query(`update sms_events set status = 'matched', matched_activation_id = $1 where id = $2`, [updated.id, event.id]);
  broadcast("activation", publicActivation(updated));
  return updated;
}

function eventFingerprint(input = {}) {
  if (input.eventFingerprint) return String(input.eventFingerprint).slice(0, 200);
  return crypto
    .createHash("sha256")
    .update([input.deviceId, input.subscriptionId ?? "", input.sender ?? "", input.body ?? "", input.receivedAt ?? ""].join("|"))
    .digest("hex");
}

function commandSummary(command) {
  if (!command) return null;
  return publicDeviceCommand(command, { includePayload: false });
}

function xhsQrLoginWorkflowScript(appSlot = "app1") {
  const xhsEntryText = appSlot === "app2" ? "Ⅱ·小红书" : "小红书";
  return {
    version: "xhs-qr-login-v15",
    engineVersion: 2,
    timeoutMs: 180_000,
    description: "打开小红书后从相册识别二维码并确认电脑端登录",
    steps: [
      {
        id: "return-home",
        action: "home",
        timeoutMs: 5_000,
        description: "回到桌面，准备从统一入口启动"
      },
      {
        id: "open-control-app",
        action: "openSelfFromLauncher",
        timeoutMs: 22_000,
        assert: { package: "com.ztqc.smsrelay" },
        description: "从桌面打开 ZTC 云控作为前台启动入口"
      },
      {
        id: "launch-xhs",
        action: "launchApp",
        params: { platform: "xhs", appSlot, restart: true },
        timeoutMs: 25_000,
        assert: { anyPackage: ["com.xingin.xhs", "com.miui.securitycore", "com.android.intentresolver", "android"] },
        description: `重启${appSlot === "app2" ? "双开" : "主应用"}小红书`
      },
      {
        id: "miui-android-resolver-picker",
        action: "tapByResourceId",
        resourceId: `android.miui:id/${appSlot === "app2" ? "app2" : "app1"}`,
        whenPackage: "android",
        whenText: "请选择要使用的应用",
        optional: true,
        timeoutMs: 8_000,
        assert: { package: "com.xingin.xhs" },
        description: `MIUI 系统选择器出现时选择${appSlot === "app2" ? "右侧双开" : "左侧主应用"}小红书`
      },
      {
        id: "miui-xspace-picker",
        action: "tapByResourceId",
        resourceId: `com.miui.securitycore:id/${appSlot === "app2" ? "app2" : "app1"}`,
        whenPackage: "com.miui.securitycore",
        whenText: "选择要使用的应用",
        optional: true,
        timeoutMs: 8_000,
        assert: { package: "com.xingin.xhs" },
        description: `小米双开选择器出现时选择${appSlot === "app2" ? "右侧双开" : "左侧主应用"}小红书`
      },
      {
        id: "generic-xhs-picker",
        action: "tapExactText",
        selector: { text: xhsEntryText },
        when: { text: "选择要使用的应用" },
        optional: true,
        timeoutMs: 8_000,
        assert: { package: "com.xingin.xhs" },
        description: `双开选择器出现时选择${appSlot === "app2" ? "第二个" : "第一个"}小红书入口`
      },
      {
        id: "open-profile",
        action: "tapBottomTextCenter",
        selector: { text: "我" },
        when: { anyText: ["首页", "发现", "消息"] },
        optional: true,
        postDelayMs: 2_000,
        timeoutMs: 10_000,
        assert: { anyText: ["编辑主页", "小红书号", "扫一扫"] },
        description: "点击底部我的"
      },
      {
        id: "open-scanner",
        action: "tapTopRightIcon",
        selector: { texts: ["扫一扫", "扫码", "扫描"], indexFromRight: 2 },
        when: { anyText: ["编辑主页", "小红书号"] },
        postDelayMs: 2_000,
        timeoutMs: 10_000,
        assert: { anyText: ["扫描二维码", "相册"] },
        description: "点击个人主页右上角扫码图标"
      },
      {
        id: "open-album",
        action: "tapByResourceId",
        selector: { resourceId: "com.xingin.xhs.redscanner:id/llMyPhoto" },
        when: { package: "com.xingin.xhs" },
        postDelayMs: 2_000,
        timeoutMs: 10_000,
        assert: { anyText: ["全部"] },
        description: "点击扫码页相册入口"
      },
      {
        id: "select-qr-image",
        action: "tapFirstGalleryImage",
        timeoutMs: 14_000,
        assert: { anyText: ["登录确认", "确认登录", "即将登录小红书电脑端"] },
        description: "点击图库第一张图片"
      },
      {
        id: "confirm-login",
        action: "tap",
        selector: { text: "确认登录", contentDesc: "确认登录", center: true },
        delayMs: 20_000,
        timeoutMs: 45_000,
        assert: { goneText: "确认登录" },
        finish: true,
        description: "持续等待确认登录出现，出现后点击元素中心"
      }
    ]
  };
}

function validateWorkflowScript(script) {
  const warnings = [];
  const errors = [];
  if (!script || typeof script !== "object" || Array.isArray(script)) {
    return { ok: false, errors: ["script must be an object"], warnings };
  }
  if (!String(script.version || "").trim()) errors.push("version is required");
  if (!String(script.description || "").trim()) errors.push("description is required");
  if (!Array.isArray(script.steps) || script.steps.length === 0) {
    errors.push("steps[] is required");
  } else {
    script.steps.forEach((step, index) => {
      if (!step || typeof step !== "object" || Array.isArray(step)) {
        errors.push(`steps[${index}] must be an object`);
        return;
      }
      const action = String(step.action || "");
      if (!SUPPORTED_WORKFLOW_ACTIONS.has(action)) errors.push(`steps[${index}].action is unsupported: ${action || "(empty)"}`);
      if (action === "tapPointWhenText") warnings.push(`steps[${index}] uses fixed coordinates; prefer dynamic element actions`);
      for (const field of ["delayMs", "postDelayMs", "retryIntervalMs"]) {
        if (step[field] != null) {
          const delay = Number(step[field]);
          if (!Number.isFinite(delay) || delay < 0 || delay > 60_000) errors.push(`steps[${index}].${field} must be 0-60000`);
        }
      }
      if (step.waitTimeoutMs != null) {
        const timeout = Number(step.waitTimeoutMs);
        if (!Number.isFinite(timeout) || timeout < 1000 || timeout > 120_000) errors.push(`steps[${index}].waitTimeoutMs must be 1000-120000`);
      }
      if (step.timeoutMs != null) {
        const timeout = Number(step.timeoutMs);
        if (!Number.isFinite(timeout) || timeout < 1000 || timeout > 180_000) errors.push(`steps[${index}].timeoutMs must be 1000-180000`);
      }
      if (step.selector != null && (typeof step.selector !== "object" || Array.isArray(step.selector))) {
        errors.push(`steps[${index}].selector must be an object`);
      }
      if (step.params != null && (typeof step.params !== "object" || Array.isArray(step.params))) {
        errors.push(`steps[${index}].params must be an object`);
      }
      if (step.when != null && (typeof step.when !== "object" || Array.isArray(step.when))) {
        errors.push(`steps[${index}].when must be an object`);
      }
      if (step.assert != null && (typeof step.assert !== "object" || Array.isArray(step.assert))) {
        errors.push(`steps[${index}].assert must be an object`);
      }
    });
  }
  return { ok: errors.length === 0, errors, warnings };
}

function workflowScriptPayload(row) {
  if (!row) return null;
  const draft = row.draft_script || {};
  const published = row.published_script || null;
  return {
    scriptId: row.id,
    deviceId: row.device_id,
    name: row.name,
    platform: row.platform,
    appSlot: row.app_slot,
    commandType: row.command_type,
    draftScript: draft,
    publishedScript: published,
    publishedVersion: row.published_version,
    enabled: row.enabled,
    hasDraftChanges: JSON.stringify(draft) !== JSON.stringify(published || {}),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    publishedAt: row.published_at
  };
}

async function ensureWorkflowScriptsForDevice(deviceId) {
  const device = await one(`select device_id from devices where device_id = $1`, [deviceId]);
  if (!device) return [];
  for (const appSlot of ["app1", "app2"]) {
    const script = xhsQrLoginWorkflowScript(appSlot);
    await query(
      `insert into workflow_scripts(device_id, platform, app_slot, command_type, name, draft_script, published_script, published_version, enabled, published_at)
       values ($1,$2,$3,$4,$5,$6,$6,1,true,now())
       on conflict(device_id, platform, app_slot, command_type) do nothing`,
      [deviceId, "小红书", appSlot, "xhs_qr_from_gallery", `小红书扫码默认脚本 ${appSlot}`, script]
    );
  }
  const rows = await query(
    `select * from workflow_scripts where device_id = $1 order by platform, command_type, case app_slot when 'app1' then 1 when 'app2' then 2 else 3 end, app_slot`,
    [deviceId]
  );
  return rows.rows;
}

async function findPublishedWorkflowScript(deviceId, appSlot) {
  const normalizedSlot = appSlot === "app2" ? "app2" : "app1";
  await ensureWorkflowScriptsForDevice(deviceId);
  const row = await one(
    `select * from workflow_scripts
     where device_id = $1
       and platform = $2
       and command_type = $3
       and app_slot in ($4, 'default')
       and enabled = true
       and published_script is not null
     order by case when app_slot = $4 then 0 else 1 end
     limit 1`,
    [deviceId, "小红书", "xhs_qr_from_gallery", normalizedSlot]
  );
  return row?.published_script || xhsQrLoginWorkflowScript(normalizedSlot);
}

function attachWorkflowScript(type, payload, workflowScript) {
  if (payload.workflowScript && typeof payload.workflowScript === "object") return payload;
  if (type !== "xhs_qr_from_gallery") return payload;
  const xhsAppSlot = payload.xhsAppSlot === "app2" ? "app2" : "app1";
  const script = JSON.parse(JSON.stringify(workflowScript || xhsQrLoginWorkflowScript(xhsAppSlot)));
  const launchStep = Array.isArray(script.steps) ? script.steps.find((step) => step && step.action === "launchApp") : null;
  if (launchStep) {
    launchStep.params = {
      ...(launchStep.params || {}),
      appSlot: xhsAppSlot,
      xhsAppSlot,
      ...(payload.xhsLaunchTarget ? { xhsLaunchTarget: payload.xhsLaunchTarget } : {})
    };
  }
  return {
    ...payload,
    autoConfirmLogin: payload.autoConfirmLogin !== false,
    xhsAppSlot,
    workflowScript: script
  };
}

async function resolveXhsCommandPayload(deviceId, type, payload) {
  if (type !== "xhs_qr_from_gallery") return payload;
  const requestedAccount = String(payload.xhsAccount || payload.xhsAccountName || "").trim();
  let account = requestedAccount
    ? await one(
      `select * from device_xhs_accounts
       where device_id = $1
         and enabled = true
         and (account_name = $2 or label = $2)
       order by case when account_name = $2 then 0 else 1 end
       limit 1`,
      [deviceId, requestedAccount]
    )
    : null;
  if (!account && payload.xhsAppSlot) {
    const requestedSlot = payload.xhsAppSlot === "app2" ? "app2" : "app1";
    account = await one(
      `select * from device_xhs_accounts where device_id = $1 and app_slot = $2 and enabled = true`,
      [deviceId, requestedSlot]
    );
  }
  if (requestedAccount && !account) {
    const error = new Error(`xhs_account_not_found: ${requestedAccount}`);
    error.statusCode = 400;
    throw error;
  }
  if (!account) {
    account = await one(
      `select * from device_xhs_accounts
       where device_id = $1 and enabled = true
       order by case app_slot when 'app1' then 1 when 'app2' then 2 else 3 end, app_slot
       limit 1`,
      [deviceId]
    );
  }
  const xhsAppSlot = account?.app_slot === "app2" ? "app2" : "app1";
  const device = await one(`select raw from devices where device_id = $1`, [deviceId]);
  const xhsLaunchTarget = pickXhsLaunchTarget(device, xhsAppSlot);
  const resolvedPayload = {
    ...payload,
    xhsAccount: requestedAccount || account?.account_name || account?.label || "",
    xhsAppSlot,
    ...(xhsLaunchTarget ? { xhsLaunchTarget } : {})
  };
  const workflowScript = await findPublishedWorkflowScript(deviceId, resolvedPayload.xhsAppSlot);
  return attachWorkflowScript(type, resolvedPayload, workflowScript);
}

function json(res, status, payload) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(payload));
}

async function readJson(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function readLatestAppRelease() {
  const meta = JSON.parse(await fs.readFile(appReleaseMetaPath, "utf8"));
  const apkFile = path.basename(meta.apkFile || "sms-relay-latest.apk");
  const apkPath = path.join(appReleaseDir, apkFile);
  const [stat, bytes] = await Promise.all([fs.stat(apkPath), fs.readFile(apkPath)]);
  const sha256 = crypto.createHash("sha256").update(bytes).digest("hex");
  return {
    versionCode: Number(meta.versionCode || 0),
    versionName: String(meta.versionName || ""),
    minSupportedVersionCode: Number(meta.minSupportedVersionCode || 0),
    mandatory: Boolean(meta.mandatory),
    releaseNotes: String(meta.releaseNotes || ""),
    publishedAt: meta.publishedAt || null,
    sizeBytes: stat.size,
    sha256,
    apkFile,
    apkPath,
    downloadUrl: `${PUBLIC_BASE_URL.replace(/\/$/, "")}/api/v1/app-release/latest/download`
  };
}

function appReleasePayload(release) {
  return {
    versionCode: release.versionCode,
    versionName: release.versionName,
    minSupportedVersionCode: release.minSupportedVersionCode,
    mandatory: release.mandatory,
    releaseNotes: release.releaseNotes,
    publishedAt: release.publishedAt,
    sizeBytes: release.sizeBytes,
    sha256: release.sha256,
    downloadUrl: release.downloadUrl
  };
}

function broadcast(type, payload) {
  const message = `event: ${type}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const res of sseClients) res.write(message);
}

function liveConnectionCount(deviceId) {
  return deviceLiveConnections.get(deviceId)?.size || 0;
}

function sendLiveMessage(ws, payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  try {
    ws.send(JSON.stringify(payload));
    return true;
  } catch {
    return false;
  }
}

function sendDeviceLiveMessage(deviceId, payload) {
  const connections = deviceLiveConnections.get(deviceId);
  if (!connections || !connections.size) return 0;
  let sent = 0;
  for (const ws of connections) {
    if (sendLiveMessage(ws, payload)) sent++;
  }
  return sent;
}

function notifyDeviceCommandAvailable(command) {
  if (!command) return 0;
  return sendDeviceLiveMessage(command.device_id, {
    type: "command_available",
    commandId: command.id,
    commandType: command.type,
    createdAt: command.created_at || nowIso()
  });
}

async function notifyActivationAvailable(activation) {
  if (!activation?.phone_number) return 0;
  const rows = await query(
    `select distinct device_id
     from device_sims
     where phone_number = $1
       and enabled = true`,
    [activation.phone_number]
  );
  let sent = 0;
  for (const row of rows.rows) {
    sent += sendDeviceLiveMessage(row.device_id, {
      type: "activation_available",
      activationId: activation.id,
      phoneNumber: activation.phone_number,
      platform: activation.platform,
      createdAt: activation.created_at || nowIso()
    });
  }
  return sent;
}

async function broadcastDeviceSnapshot(deviceId) {
  const device = await one(`select * from devices where device_id = $1`, [deviceId]);
  if (!device) return;
  broadcast("device", await publicDevice(device));
}

function addDeviceLiveConnection(deviceId, ws) {
  let connections = deviceLiveConnections.get(deviceId);
  if (!connections) {
    connections = new Set();
    deviceLiveConnections.set(deviceId, connections);
  }
  connections.add(ws);
  ws.deviceId = deviceId;
  ws.isAlive = true;
  sendLiveMessage(ws, { type: "hello", serverTime: nowIso() });
  broadcastDeviceSnapshot(deviceId).catch((error) => console.error("broadcastDeviceSnapshot", error));

  ws.on("pong", () => {
    ws.isAlive = true;
  });
  ws.on("message", (raw) => {
    try {
      const message = JSON.parse(String(raw || "{}"));
      if (message.type === "pong") ws.isAlive = true;
    } catch {
      // Unknown device messages are ignored; HTTP remains the authoritative data channel.
    }
  });
  ws.on("close", () => {
    const current = deviceLiveConnections.get(deviceId);
    if (current) {
      current.delete(ws);
      if (!current.size) deviceLiveConnections.delete(deviceId);
    }
    broadcastDeviceSnapshot(deviceId).catch((error) => console.error("broadcastDeviceSnapshot", error));
  });
}

async function handleDeviceLiveUpgrade(req, socket, head) {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const match = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/live$/);
  if (!match) {
    socket.destroy();
    return;
  }
  const ctx = await authContext(req, ["device"]);
  if (!ctx) {
    socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
    socket.destroy();
    return;
  }
  const deviceId = decodeURIComponent(match[1]);
  deviceLiveServer.handleUpgrade(req, socket, head, (ws) => addDeviceLiveConnection(deviceId, ws));
}

async function serveStatic(req, res) {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const pathname = url.pathname === "/" ? "/index.html" : url.pathname;
  const target = path.normalize(path.join(publicDir, pathname));
  if (!target.startsWith(publicDir)) {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }
  try {
    const content = await fs.readFile(target);
    const ext = path.extname(target);
    const type = ext === ".css" ? "text/css" : ext === ".js" ? "text/javascript" : "text/html";
    res.writeHead(200, { "content-type": `${type}; charset=utf-8` });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end("Not found");
  }
}

async function waitForActivation(id, timeoutSeconds) {
  const deadline = Date.now() + Math.min(Math.max(Number(timeoutSeconds || 30), 1), MAX_WAIT_SECONDS) * 1000;
  while (Date.now() < deadline) {
    await expireActivations();
    const row = await one(`select * from activations where id = $1`, [id]);
    if (!row || !["arming", "waiting"].includes(row.status)) return row;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return one(`select * from activations where id = $1`, [id]);
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);

    if (req.method === "GET" && url.pathname === "/healthz") {
      await query("select 1");
      return json(res, 200, { ok: true, publicBaseUrl: PUBLIC_BASE_URL, at: nowIso() });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/stream") {
      res.writeHead(200, {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive"
      });
      res.write(`event: hello\ndata: ${JSON.stringify({ at: nowIso() })}\n\n`);
      sseClients.add(res);
      req.on("close", () => sseClients.delete(res));
      return;
    }

    if (req.method === "GET" && url.pathname === "/api/v1/windows-agents") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const rows = await query(`select * from windows_agents order by last_seen_at desc`);
      const agents = [];
      for (const row of rows.rows) agents.push(await loadWindowsAgent(row.agent_id));
      return json(res, 200, { agents });
    }

    const windowsAgentMatch = url.pathname.match(/^\/api\/v1\/windows-agents\/([^/]+)$/);
    if (req.method === "GET" && windowsAgentMatch) {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const agent = await loadWindowsAgent(decodeURIComponent(windowsAgentMatch[1]));
      if (!agent) return json(res, 404, { error: "windows_agent_not_found" });
      return json(res, 200, { agent });
    }

    if (req.method === "POST" && url.pathname === "/api/v1/windows-agents/heartbeat") {
      const ctx = await requireAuth(req, res, ["windows_agent"]);
      if (!ctx) return;
      const input = await readJson(req);
      const row = await upsertWindowsAgent(input, req);
      const agent = await loadWindowsAgent(row.agent_id);
      await audit("windows_agent_heartbeat", ctx, { detail: { agentId: row.agent_id } });
      broadcast("windowsAgent", agent);
      return json(res, 200, { ok: true, agent });
    }

    const windowsAgentDevicesSyncMatch = url.pathname.match(/^\/api\/v1\/windows-agents\/([^/]+)\/devices\/sync$/);
    if (req.method === "POST" && windowsAgentDevicesSyncMatch) {
      const ctx = await requireAuth(req, res, ["windows_agent"]);
      if (!ctx) return;
      const agentId = normalizeAgentId(decodeURIComponent(windowsAgentDevicesSyncMatch[1]));
      const input = await readJson(req);
      await upsertWindowsAgent({ ...(input.agent || {}), agentId }, req);
      const agent = await syncWindowsAgentDevices(agentId, input.devices || []);
      await audit("windows_agent_devices_sync", ctx, { detail: { agentId, count: agent.devices.length } });
      return json(res, 200, { ok: true, agent });
    }

    if (req.method === "POST" && url.pathname === "/api/v1/windows-agent-tasks") {
      const ctx = await requireAuth(req, res, ["admin"]);
      if (!ctx) return;
      const input = await readJson(req);
      const agentId = normalizeAgentId(input.agentId);
      if (!agentId) return json(res, 400, { error: "agentId is required" });
      const agent = await one(`select agent_id from windows_agents where agent_id = $1`, [agentId]);
      if (!agent) return json(res, 404, { error: "windows_agent_not_found" });
      const type = String(input.type || "").trim();
      if (!["adb_install_apk", "adb_grant_permissions", "adb_start_agent", "adb_collect_diagnostics", "adb_restart_server"].includes(type)) {
        return json(res, 400, { error: "unsupported_windows_task_type" });
      }
      const task = await one(
        `insert into windows_agent_tasks(agent_id, adb_serial, device_id, type, payload)
         values ($1,$2,$3,$4,$5)
         returning *`,
        [agentId, input.adbSerial || "", input.deviceId || "", type, input.payload || {}]
      );
      await audit("windows_agent_task_create", ctx, { deviceId: input.deviceId || null, detail: { agentId, adbSerial: input.adbSerial || "", type } });
      broadcast("windowsAgentTask", publicWindowsAgentTask(task, { includePayload: false }));
      return json(res, 201, { ok: true, task: publicWindowsAgentTask(task) });
    }

    const windowsAgentTaskListMatch = url.pathname.match(/^\/api\/v1\/windows-agents\/([^/]+)\/tasks$/);
    if (req.method === "GET" && windowsAgentTaskListMatch) {
      const ctx = await requireAuth(req, res, ["admin", "business", "windows_agent"]);
      if (!ctx) return;
      const agentId = normalizeAgentId(decodeURIComponent(windowsAgentTaskListMatch[1]));
      const rows = await query(
        `select * from windows_agent_tasks where agent_id = $1 order by created_at desc limit 80`,
        [agentId]
      );
      return json(res, 200, { tasks: rows.rows.map((row) => publicWindowsAgentTask(row, { includePayload: ctx.role !== "business" })) });
    }

    const windowsAgentTaskNextMatch = url.pathname.match(/^\/api\/v1\/windows-agents\/([^/]+)\/tasks\/next$/);
    if (req.method === "GET" && windowsAgentTaskNextMatch) {
      const ctx = await requireAuth(req, res, ["windows_agent"]);
      if (!ctx) return;
      const agentId = normalizeAgentId(decodeURIComponent(windowsAgentTaskNextMatch[1]));
      await upsertWindowsAgent({ agentId }, req);
      const task = await one(
        `update windows_agent_tasks set status = 'running', picked_at = coalesce(picked_at, now()), updated_at = now()
         where id = (
           select id from windows_agent_tasks
           where agent_id = $1 and status = 'queued'
           order by created_at asc
           limit 1
           for update skip locked
         )
         returning *`,
        [agentId]
      );
      if (!task) return json(res, 200, { task: null });
      broadcast("windowsAgentTask", publicWindowsAgentTask(task, { includePayload: false }));
      return json(res, 200, { task: publicWindowsAgentTask(task) });
    }

    const windowsTaskEventsMatch = url.pathname.match(/^\/api\/v1\/windows-agent-tasks\/([^/]+)\/events$/);
    if (windowsTaskEventsMatch && req.method === "GET") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const rows = await query(
        `select * from windows_agent_task_events where task_id = $1 order by created_at asc, id asc`,
        [windowsTaskEventsMatch[1]]
      );
      return json(res, 200, { events: rows.rows.map(publicWindowsAgentTaskEvent) });
    }

    if (windowsTaskEventsMatch && req.method === "POST") {
      const ctx = await requireAuth(req, res, ["windows_agent"]);
      if (!ctx) return;
      const input = await readJson(req);
      const task = await one(`select * from windows_agent_tasks where id = $1`, [windowsTaskEventsMatch[1]]);
      if (!task) return json(res, 404, { error: "windows_agent_task_not_found" });
      const event = await one(
        `insert into windows_agent_task_events(task_id, agent_id, adb_serial, phase, level, message, detail)
         values ($1,$2,$3,$4,$5,$6,$7)
         returning *`,
        [
          task.id,
          task.agent_id,
          input.adbSerial || task.adb_serial || "",
          input.phase || "log",
          input.level || "info",
          String(input.message || "").slice(0, 2000),
          input.detail || {}
        ]
      );
      await query(`update windows_agent_tasks set updated_at = now() where id = $1`, [task.id]);
      broadcast("windowsAgentTaskEvent", publicWindowsAgentTaskEvent(event));
      return json(res, 201, { ok: true, event: publicWindowsAgentTaskEvent(event) });
    }

    const windowsTaskStatusMatch = url.pathname.match(/^\/api\/v1\/windows-agent-tasks\/([^/]+)\/status$/);
    if (req.method === "POST" && windowsTaskStatusMatch) {
      const ctx = await requireAuth(req, res, ["windows_agent"]);
      if (!ctx) return;
      const input = await readJson(req);
      const status = String(input.status || "").trim();
      if (!["running", "succeeded", "failed", "cancelled"].includes(status)) return json(res, 400, { error: "invalid_status" });
      const task = await one(
        `update windows_agent_tasks set status = $1, result = $2, updated_at = now(),
           completed_at = case when $1 in ('succeeded', 'failed', 'cancelled') then now() else completed_at end
         where id = $3
         returning *`,
        [status, input.result || {}, windowsTaskStatusMatch[1]]
      );
      if (!task) return json(res, 404, { error: "windows_agent_task_not_found" });
      broadcast("windowsAgentTask", publicWindowsAgentTask(task, { includePayload: false }));
      return json(res, 200, { ok: true, task: publicWindowsAgentTask(task) });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/app-release/latest") {
      const ctx = await requireAuth(req, res, ["admin", "device"]);
      if (!ctx) return;
      try {
        const release = await readLatestAppRelease();
        return json(res, 200, { ok: true, release: appReleasePayload(release) });
      } catch (error) {
        if (error.code === "ENOENT") return json(res, 404, { error: "app_release_not_found" });
        throw error;
      }
    }

    if (req.method === "GET" && url.pathname === "/api/v1/app-release/latest/download") {
      const ctx = await requireAuth(req, res, ["admin", "device"]);
      if (!ctx) return;
      try {
        const release = await readLatestAppRelease();
        const bytes = await fs.readFile(release.apkPath);
        res.writeHead(200, {
          "content-type": "application/vnd.android.package-archive",
          "content-length": String(bytes.length),
          "content-disposition": `attachment; filename="${release.apkFile}"`,
          "cache-control": "no-store"
        });
        return res.end(bytes);
      } catch (error) {
        if (error.code === "ENOENT") return json(res, 404, { error: "app_release_not_found" });
        throw error;
      }
    }

    if (req.method === "POST" && url.pathname === "/api/v1/devices/heartbeat") {
      const ctx = await requireAuth(req, res, ["device"]);
      if (!ctx) return;
      const input = await readJson(req);
      const device = await upsertDevice(input);
      const payload = await publicDevice(device);
      await audit("device_heartbeat", ctx, { deviceId: payload.deviceId });
      broadcast("device", payload);
      return json(res, 200, { ok: true, device: payload });
    }

    const activationWindowMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/activation-windows$/);
    if (req.method === "GET" && activationWindowMatch) {
      const ctx = await requireAuth(req, res, ["device"]);
      if (!ctx) return;
      await expireActivations();
      const deviceId = decodeURIComponent(activationWindowMatch[1]);
      const rows = await query(
        `with claimed as (
           update activations a
           set status = 'waiting',
               updated_at = now()
           from device_sims s
           where s.device_id = $1
             and s.enabled = true
             and s.phone_number = a.phone_number
             and a.status = 'arming'
             and a.expires_at > now()
           returning a.*
         )
         select
           a.*,
           s.subscription_id,
           s.slot_index,
           (claimed.id is not null) as just_acknowledged
         from activations a
         join device_sims s on s.phone_number = a.phone_number
         left join claimed on claimed.id = a.id
         where s.device_id = $1
           and s.enabled = true
           and a.status = 'waiting'
           and a.expires_at > now()
         order by a.created_at asc
         limit 10`,
        [deviceId]
      );
      for (const row of rows.rows) {
        if (row.just_acknowledged) broadcast("activation", publicActivation(row));
      }
      return json(res, 200, {
        windows: rows.rows.map((row) => ({
          ...publicActivation(row),
          subscriptionId: row.subscription_id,
          slotIndex: row.slot_index
        }))
      });
    }

    const simMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/sims\/(-?\d+)$/);
    if (req.method === "PUT" && simMatch) {
      const ctx = await requireAuth(req, res, ["admin"]);
      if (!ctx) return;
      const input = await readJson(req);
      const deviceId = decodeURIComponent(simMatch[1]);
      const subscriptionId = Number(simMatch[2]);
      const phoneNumber = normalizePhone(input.phoneNumber || "");
      const row = await one(
        `update device_sims set phone_number = $1, enabled = $2, label = $3, updated_at = now()
         where device_id = $4 and subscription_id = $5
         returning *`,
        [phoneNumber || null, input.enabled !== false, input.label || "", deviceId, subscriptionId]
      );
      if (!row) return json(res, 404, { error: "sim_not_found" });
      await audit("sim_update", ctx, { deviceId, phoneNumber });
      const device = await one(`select * from devices where device_id = $1`, [deviceId]);
      if (device) broadcast("device", await publicDevice(device));
      return json(res, 200, { ok: true, sim: row });
    }

    const xhsAccountMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/xhs-accounts\/([^/]+)$/);
    if (req.method === "PUT" && xhsAccountMatch) {
      const ctx = await requireAuth(req, res, ["admin"]);
      if (!ctx) return;
      const input = await readJson(req);
      const deviceId = decodeURIComponent(xhsAccountMatch[1]);
      const appSlot = decodeURIComponent(xhsAccountMatch[2]) === "app2" ? "app2" : "app1";
      const accountName = String(input.accountName || input.xhsAccount || "").trim();
      const label = String(input.label || (appSlot === "app2" ? "Ⅱ·小红书" : "小红书")).trim();
      const row = await one(
        `insert into device_xhs_accounts(device_id, app_slot, account_name, label, enabled, updated_at)
         values ($1,$2,$3,$4,$5,now())
         on conflict(device_id, app_slot) do update set
           account_name = excluded.account_name,
           label = excluded.label,
           enabled = excluded.enabled,
           updated_at = now()
         returning *`,
        [deviceId, appSlot, accountName, label, input.enabled !== false]
      );
      await audit("xhs_account_update", ctx, { deviceId, detail: { appSlot, accountName } });
      const device = await one(`select * from devices where device_id = $1`, [deviceId]);
      if (device) broadcast("device", await publicDevice(device));
      return json(res, 200, { ok: true, xhsAccount: row });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/devices") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const devices = await query(`select * from devices order by last_seen_at desc`);
      const payload = [];
      for (const device of devices.rows) payload.push(await publicDevice(device));
      return json(res, 200, { devices: payload });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/commands") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      await expireStaleCommands();
      const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || 120), 1), 300);
      const rows = await query(
        `select * from device_commands order by created_at desc limit $1`,
        [limit]
      );
      return json(res, 200, { commands: rows.rows.map(commandSummary) });
    }

    const workflowListMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/workflow-scripts$/);
    if (workflowListMatch && req.method === "GET") {
      const ctx = await requireAuth(req, res, ["admin"]);
      if (!ctx) return;
      const deviceId = decodeURIComponent(workflowListMatch[1]);
      const rows = await ensureWorkflowScriptsForDevice(deviceId);
      return json(res, 200, { scripts: rows.map(workflowScriptPayload), supportedActions: [...SUPPORTED_WORKFLOW_ACTIONS] });
    }

    const workflowActionMatch = url.pathname.match(/^\/api\/v1\/workflow-scripts\/([^/]+)\/(draft|publish|test|rollback)$/);
    if (workflowActionMatch) {
      const ctx = await requireAuth(req, res, ["admin"]);
      if (!ctx) return;
      const scriptId = workflowActionMatch[1];
      const action = workflowActionMatch[2];
      const current = await one(`select * from workflow_scripts where id = $1`, [scriptId]);
      if (!current) return json(res, 404, { error: "workflow_script_not_found" });

      if (action === "draft" && req.method === "PUT") {
        const input = await readJson(req);
        const script = input.script && typeof input.script === "object" ? input.script : null;
        const validation = validateWorkflowScript(script);
        if (!validation.ok) return json(res, 400, { error: "invalid_workflow_script", validation });
        const updated = await one(
          `update workflow_scripts set draft_script = $1, updated_at = now() where id = $2 returning *`,
          [script, scriptId]
        );
        await audit("workflow_script_draft_update", ctx, { deviceId: updated.device_id, detail: { scriptId } });
        return json(res, 200, { ok: true, script: workflowScriptPayload(updated), validation });
      }

      if (action === "publish" && req.method === "POST") {
        const validation = validateWorkflowScript(current.draft_script);
        if (!validation.ok) return json(res, 400, { error: "invalid_workflow_script", validation });
        if (current.published_script) {
          await query(
            `insert into workflow_script_versions(workflow_script_id, version, script) values ($1,$2,$3)`,
            [scriptId, current.published_version, current.published_script]
          );
        }
        const updated = await one(
          `update workflow_scripts
           set published_script = draft_script,
               published_version = published_version + 1,
               published_at = now(),
               updated_at = now()
           where id = $1 returning *`,
          [scriptId]
        );
        await audit("workflow_script_publish", ctx, { deviceId: updated.device_id, detail: { scriptId, version: updated.published_version } });
        return json(res, 200, { ok: true, script: workflowScriptPayload(updated), validation });
      }

      if (action === "rollback" && req.method === "POST") {
        const previous = await one(
          `select * from workflow_script_versions where workflow_script_id = $1 order by created_at desc limit 1`,
          [scriptId]
        );
        if (!previous) return json(res, 404, { error: "workflow_script_version_not_found" });
        if (current.published_script) {
          await query(
            `insert into workflow_script_versions(workflow_script_id, version, script) values ($1,$2,$3)`,
            [scriptId, current.published_version, current.published_script]
          );
        }
        const updated = await one(
          `update workflow_scripts
           set draft_script = $1,
               published_script = $1,
               published_version = published_version + 1,
               published_at = now(),
               updated_at = now()
           where id = $2 returning *`,
          [previous.script, scriptId]
        );
        await audit("workflow_script_rollback", ctx, { deviceId: updated.device_id, detail: { scriptId, rolledBackFromVersion: previous.version } });
        return json(res, 200, { ok: true, script: workflowScriptPayload(updated) });
      }

      if (action === "test" && req.method === "POST") {
        const input = await readJson(req);
        const validation = validateWorkflowScript(current.draft_script);
        if (!validation.ok) return json(res, 400, { error: "invalid_workflow_script", validation });
        const payload = input.payload && typeof input.payload === "object" ? input.payload : {};
        const dataUrl = String(payload.qrImageDataUrl || "");
        if (!/^data:image\/(png|jpeg|jpg);base64,/i.test(dataUrl)) return json(res, 400, { error: "qrImageDataUrl is required" });
        if (dataUrl.length > 1_500_000) return json(res, 413, { error: "qr_image_too_large" });
        const command = await one(
          `insert into device_commands(device_id, type, payload) values ($1,$2,$3) returning *`,
          [
            current.device_id,
            current.command_type,
            {
              ...payload,
              strategy: "server_workflow_script",
              autoConfirmLogin: payload.autoConfirmLogin !== false,
              xhsAppSlot: current.app_slot === "app2" ? "app2" : "app1",
              workflowScript: current.draft_script,
              workflowScriptId: current.id,
              workflowScriptMode: "draft-test"
            }
          ]
        );
        await audit("workflow_script_test", ctx, { deviceId: current.device_id, activationId: command.id, detail: { scriptId } });
        broadcast("command", commandSummary(command));
        notifyDeviceCommandAvailable(command);
        return json(res, 201, { ok: true, command: commandSummary(command), validation });
      }
    }

    const commandListMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/commands$/);
    if (commandListMatch && req.method === "GET") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      await expireStaleCommands();
      const deviceId = decodeURIComponent(commandListMatch[1]);
      const rows = await query(
        `select * from device_commands where device_id = $1 order by created_at desc limit 30`,
        [deviceId]
      );
      return json(res, 200, { commands: rows.rows.map(commandSummary) });
    }

    if (commandListMatch && req.method === "POST") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const deviceId = decodeURIComponent(commandListMatch[1]);
      const input = await readJson(req);
      const device = await one(`select * from devices where device_id = $1`, [deviceId]);
      if (!device) return json(res, 404, { error: "device_not_found" });
      const type = String(input.type || "").trim();
      if (!["open_xhs_scan", "xhs_qr_from_gallery"].includes(type)) return json(res, 400, { error: "unsupported_command_type" });
      let payload = input.payload && typeof input.payload === "object" ? input.payload : {};
      if (type === "xhs_qr_from_gallery") {
        const dataUrl = String(payload.qrImageDataUrl || "");
        if (!/^data:image\/(png|jpeg|jpg);base64,/i.test(dataUrl)) return json(res, 400, { error: "qrImageDataUrl is required" });
        if (dataUrl.length > 1_500_000) return json(res, 413, { error: "qr_image_too_large" });
      }
      payload = await resolveXhsCommandPayload(deviceId, type, payload);
      const command = await one(
        `insert into device_commands(device_id, type, payload) values ($1,$2,$3) returning *`,
        [deviceId, type, payload]
      );
      await audit("device_command_create", ctx, { deviceId, activationId: command.id, type });
      broadcast("command", commandSummary(command));
      notifyDeviceCommandAvailable(command);
      return json(res, 201, { ok: true, command: commandSummary(command) });
    }

    const commandNextMatch = url.pathname.match(/^\/api\/v1\/devices\/([^/]+)\/commands\/next$/);
    if (commandNextMatch && req.method === "GET") {
      const ctx = await requireAuth(req, res, ["device"]);
      if (!ctx) return;
      const deviceId = decodeURIComponent(commandNextMatch[1]);
      const command = await one(
        `update device_commands set status = 'running', picked_at = coalesce(picked_at, now()), updated_at = now()
         where id = (
           select id from device_commands
           where device_id = $1 and status = 'queued'
           order by created_at asc
           limit 1
         )
         returning *`,
        [deviceId]
      );
      if (!command) return json(res, 200, { command: null });
      broadcast("command", commandSummary(command));
      return json(res, 200, { command: publicDeviceCommand(command) });
    }

    const commandEventsMatch = url.pathname.match(/^\/api\/v1\/device-commands\/([^/]+)\/events$/);
    if (commandEventsMatch && req.method === "GET") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const commandId = commandEventsMatch[1];
      const rows = await query(
        `select * from device_command_events where command_id = $1 order by created_at asc, id asc limit 500`,
        [commandId]
      );
      return json(res, 200, { events: rows.rows.map(publicCommandEvent) });
    }

    if (commandEventsMatch && req.method === "POST") {
      const ctx = await requireAuth(req, res, ["device"]);
      if (!ctx) return;
      const input = await readJson(req);
      const commandId = commandEventsMatch[1];
      const command = await one(`select * from device_commands where id = $1`, [commandId]);
      if (!command) return json(res, 404, { error: "command_not_found" });
      const screenshot = input.screenshot && typeof input.screenshot === "object" ? input.screenshot : null;
      const detail = input.detail && typeof input.detail === "object" ? input.detail : {};
      const inserted = await one(
        `insert into device_command_events(command_id, device_id, step_index, step_id, phase, level, message, package_name, ui_snapshot, screenshot, detail)
         values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
         returning *`,
        [
          commandId,
          String(input.deviceId || command.device_id || "").slice(0, 160) || null,
          Number.isInteger(input.stepIndex) ? input.stepIndex : null,
          String(input.stepId || "").slice(0, 160) || null,
          String(input.phase || "log").slice(0, 80),
          ["debug", "info", "warn", "error"].includes(String(input.level || "")) ? String(input.level) : "info",
          String(input.message || "").slice(0, 2000),
          String(input.packageName || "").slice(0, 240) || null,
          String(input.uiSnapshot || "").slice(0, 4000) || null,
          screenshot,
          detail
        ]
      );
      return json(res, 201, { ok: true, event: publicCommandEvent(inserted) });
    }

    const commandStatusMatch = url.pathname.match(/^\/api\/v1\/device-commands\/([^/]+)\/status$/);
    if (commandStatusMatch && req.method === "POST") {
      const ctx = await requireAuth(req, res, ["device"]);
      if (!ctx) return;
      const input = await readJson(req);
      const status = String(input.status || "").trim();
      if (!["running", "succeeded", "failed", "cancelled"].includes(status)) return json(res, 400, { error: "invalid_status" });
      const command = await one(
        `update device_commands set status = $1, result = $2, updated_at = now(),
          completed_at = case when $1 in ('succeeded', 'failed', 'cancelled') then now() else completed_at end
         where id = $3 returning *`,
        [status, input.result && typeof input.result === "object" ? input.result : {}, commandStatusMatch[1]]
      );
      if (!command) return json(res, 404, { error: "command_not_found" });
      broadcast("command", commandSummary(command));
      return json(res, 200, { ok: true, command: commandSummary(command) });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/sms-events") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      const rows = await query(`select * from sms_events order by received_at desc limit 200`);
      return json(res, 200, { events: rows.rows.map(publicSmsEvent), retentionMinutes: RETENTION_MINUTES });
    }

    if (req.method === "POST" && url.pathname === "/api/v1/sms-events") {
      const ctx = await requireAuth(req, res, ["device"]);
      if (!ctx) return;
      const input = await readJson(req);
      const device = await upsertDevice(input);
      const subscriptionId = Number(input.subscriptionId);
      const slotIndex = Number(input.slotIndex);
      const body = String(input.body || "").slice(0, 1600);
      const sender = String(input.sender || "").slice(0, 160);
      const platform = normalizePlatform(input.platform || detectPlatform(body, sender));
      const code = extractCode(body).slice(0, 16);
      const receivedAt = input.receivedAt || nowIso();
      const resolved = await resolveEventPhone(device.device_id, Number.isFinite(subscriptionId) ? subscriptionId : null);
      const fingerprint = eventFingerprint(input);
      let event = await one(`select * from sms_events where event_fingerprint = $1`, [fingerprint]);
      if (!event) {
        event = await one(
          `insert into sms_events(event_fingerprint, device_id, subscription_id, slot_index, phone_number, sender, platform, code, body, status, received_at)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
           returning *`,
          [
            fingerprint,
            device.device_id,
            Number.isFinite(subscriptionId) ? subscriptionId : null,
            Number.isFinite(slotIndex) ? slotIndex : null,
            resolved.phoneNumber || null,
            sender,
            platform,
            code || null,
            body,
            resolved.ambiguous ? "ambiguous" : "received",
            receivedAt
          ]
        );
        const activation = await completeActivationForEvent(event);
        if (activation) event = await one(`select * from sms_events where id = $1`, [event.id]);
        broadcast("sms", publicSmsEvent(event));
        await audit("sms_event", ctx, { deviceId: device.device_id, phoneNumber: event.phone_number || "", activationId: activation?.id || null });
      }
      return json(res, 201, { ok: true, event: publicSmsEvent(event) });
    }

    if (req.method === "POST" && url.pathname === "/api/v1/activations") {
      const ctx = await requireAuth(req, res, ["business"]);
      if (!ctx) return;
      await expireActivations();
      const input = await readJson(req);
      const phoneNumber = normalizePhone(input.phoneNumber || "");
      const platform = normalizePlatform(input.platform || "小红书");
      if (!phoneNumber) return json(res, 400, { error: "phoneNumber is required" });
      if (input.clientRequestId) {
        const existing = await one(`select * from activations where client_request_id = $1`, [String(input.clientRequestId)]);
        if (existing) return json(res, 200, { ok: true, activation: publicActivation(existing) });
      }
      const active = await one(
        `select * from activations where phone_number = $1 and platform = $2 and status in ('arming', 'waiting') and expires_at > now() order by created_at desc limit 1`,
        [phoneNumber, platform]
      );
      if (active) return json(res, 409, { error: "active_activation_exists", activation: publicActivation(active) });
      const ttl = Math.min(Math.max(Number(input.ttlSeconds || DEFAULT_TTL_SECONDS), 30), 900);
      const activation = await one(
        `insert into activations(phone_number, platform, status, client_request_id, purpose, expires_at)
         values ($1,$2,'arming',$3,$4,now() + ($5::int * interval '1 second'))
         returning *`,
        [phoneNumber, platform, input.clientRequestId || null, input.purpose || "login", ttl]
      );
      await audit("activation_create", ctx, { phoneNumber, activationId: activation.id });
      broadcast("activation", publicActivation(activation));
      await notifyActivationAvailable(activation);
      return json(res, 201, { ok: true, activation: publicActivation(activation) });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/activations") {
      const ctx = await requireAuth(req, res, ["admin", "business"]);
      if (!ctx) return;
      await expireActivations();
      const rows = await query(`select * from activations order by created_at desc limit 100`);
      return json(res, 200, { activations: rows.rows.map(publicActivation) });
    }

    const activationStatus = url.pathname.match(/^\/api\/v1\/activations\/([^/]+)\/status$/);
    if (req.method === "GET" && activationStatus) {
      const ctx = await requireAuth(req, res, ["business"]);
      if (!ctx) return;
      await expireActivations();
      const activation = await one(`select * from activations where id = $1`, [activationStatus[1]]);
      if (!activation) return json(res, 404, { error: "activation_not_found" });
      return json(res, 200, { activation: publicActivation(activation) });
    }

    const activationWait = url.pathname.match(/^\/api\/v1\/activations\/([^/]+)\/wait$/);
    if (req.method === "GET" && activationWait) {
      const ctx = await requireAuth(req, res, ["business"]);
      if (!ctx) return;
      const activation = await waitForActivation(activationWait[1], url.searchParams.get("timeout") || 30);
      if (!activation) return json(res, 404, { error: "activation_not_found" });
      return json(res, 200, { activation: publicActivation(activation) });
    }

    if (req.method === "GET" && url.pathname === "/api/v1/latest-code") {
      const ctx = await requireAuth(req, res, ["business"]);
      if (!ctx) return;
      const phoneNumber = normalizePhone(url.searchParams.get("phoneNumber") || url.searchParams.get("phone") || "");
      const platform = normalizePlatform(url.searchParams.get("platform") || "小红书");
      const after = url.searchParams.get("after");
      if (!after) return json(res, 400, { error: "after is required for latest-code" });
      const event = await one(
        `select * from sms_events
         where code is not null and platform = $1 and received_at >= $2 and ($3 = '' or phone_number = $3)
         order by received_at desc
         limit 1`,
        [platform, after, phoneNumber]
      );
      if (!event) return json(res, 200, { status: "not_found", phoneNumber, platform });
      return json(res, 200, { status: "found", ...publicSmsEvent(event) });
    }

    // Compatibility endpoints for the current debug page.
    if (req.method === "GET" && url.pathname === "/api/events") {
      const rows = await query(`select * from sms_events order by received_at desc limit 100`);
      return json(res, 200, { events: rows.rows.map(publicSmsEvent), retentionMinutes: RETENTION_MINUTES });
    }
    if (req.method === "GET" && url.pathname === "/api/devices") {
      const devices = await query(`select * from devices order by last_seen_at desc`);
      const payload = [];
      for (const device of devices.rows) payload.push(await publicDevice(device));
      return json(res, 200, { devices: payload });
    }
    if (req.method === "GET" && url.pathname === "/api/code-requests") {
      const rows = await query(`select * from activations order by created_at desc limit 100`);
      return json(res, 200, { requests: rows.rows.map(publicActivation) });
    }

    return serveStatic(req, res);
  } catch (error) {
    console.error(error);
    json(res, error.statusCode || 500, { error: error.message || "server_error" });
  }
});

server.on("upgrade", (req, socket, head) => {
  handleDeviceLiveUpgrade(req, socket, head).catch((error) => {
    console.error("device live upgrade", error);
    socket.destroy();
  });
});

setInterval(() => {
  for (const [deviceId, connections] of deviceLiveConnections) {
    for (const ws of connections) {
      if (ws.isAlive === false) {
        ws.terminate();
        connections.delete(ws);
        continue;
      }
      ws.isAlive = false;
      sendLiveMessage(ws, { type: "ping", serverTime: nowIso() });
      try {
        ws.ping();
      } catch {
        ws.terminate();
        connections.delete(ws);
      }
    }
    if (!connections.size) {
      deviceLiveConnections.delete(deviceId);
      broadcastDeviceSnapshot(deviceId).catch((error) => console.error("broadcastDeviceSnapshot", error));
    }
  }
}, 30_000).unref();

server.listen(PORT, HOST, () => {
  console.log(`SMS code center listening on http://${HOST}:${PORT}`);
  console.log(`Public base URL: ${PUBLIC_BASE_URL}`);
});
