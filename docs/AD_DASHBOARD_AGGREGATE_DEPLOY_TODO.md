# 投流看板聚合层改造上线记录

## 背景

投流看板在频繁切换投手、账号、日期等参数时，原逻辑会现场读取 `xhs_report_daily` 原始 JSON 明细并在 Python 中聚合内容标签、笔记、品牌、趋势等模块。用户连续切换参数时，多个重型冷算请求会叠加，容易把 Docker/Postgres 磁盘 IO 打满。

本次改造目标是把重计算从“用户打开看板/切换参数时”前移到“报表同步完成后”，看板优先读取聚合表。

## 本次本地改动点

1. 新增投流聚合表模型和迁移：
   - `xhs_ad_stats_daily_account`
   - `xhs_ad_stats_daily_buyer`
   - `xhs_ad_stats_daily_brand`
   - `xhs_ad_stats_daily_note`
   - `xhs_ad_stats_daily_content_tag`

2. 新增聚合刷新链路：
   - `XHSService.refresh_xhs_ad_aggregates(...)`
   - `simple/standard` 刷新账号、投手、品牌聚合。
   - `simple_note/standard_note/creative` 刷新笔记、内容标签聚合。

3. 报表刷新后自动触发聚合：
   - 入口在 `XHSService.refresh_jg_report_cache(...)`。
   - 所以后台定时任务、后台手动刷新、单账号刷新只要走这个入口，都会自动刷新聚合表。
   - 聚合刷新完成后会调用 `invalidate_ad_dashboard_caches()` 清理投流看板进程内缓存。

4. 投流看板读取聚合表：
   - `/xhs/ad-dashboard` 优先读取账号/品牌聚合。
   - `/xhs/ad-dashboard/content-tags` 优先读取内容标签/笔记聚合。
   - 聚合表无数据时保留旧原始明细实时计算作为 fallback。

5. 防止频繁切换参数打爆服务：
   - 前端投流看板请求增加短防抖。
   - 前端旧请求使用 `AbortController` 取消。
   - 后端内容标签冷算增加并发闸门：`_AD_CONTENT_TAG_COMPUTE_CONCURRENCY = 1`。
   - 即使多个内容标签请求同时进入，也会排队，不会并发扫库。

6. 快照版本升级：
   - `ad-dashboard-v2-aggregate`
   - `ad-content-tags-v2-aggregate`
   - 避免上线后继续命中旧算法生成的快照。

## 本地验证结论

### 1. 报表刷新会更新聚合数据

已用隔离 SQLite 临时库验证真实调用链：

```text
refresh_jg_report_cache()
  -> 写入 xhs_report_daily
  -> refresh_xhs_ad_aggregates()
  -> 写入聚合表
```

测试结果：

```text
simple_result.aggregate_result = account 1 / buyer 1 / brand 1
simple_note_result.aggregate_result = note 1 / content_tag 1
聚合表实际写入成功
fee=100，conversion=5 与原始报表一致
```

### 2. 频繁切换参数不会再打爆 Docker 磁盘 IO

改造后看板优先读聚合表，不再每次切投手都扫 `xhs_report_daily` 原始 JSON 明细。

另外有三层保护：

```text
前端防抖
前端取消旧请求
后端内容标签冷算串行闸门
```

本地用户视角 API 测试：

```text
投手主看板：0.03s - 0.79s
投手内容标签缓存命中：0.06s - 0.16s
管理员切某个投手缓存命中：0.32s - 0.36s
```

仍需注意：内容标签冷读全量数据时仍然可能较慢，但会排队读聚合，不会像之前一样并发打原始明细导致 IO 风暴。

## 上线后必须执行的事情

### 1. 备份数据库

上线前先备份 Windows 端 Postgres 数据库，避免迁移或聚合初始化失败时无法回滚。

### 2. 执行数据库迁移

部署新代码后，需要让 Alembic 创建 5 张聚合表。

确认表存在：

```sql
SELECT COUNT(*) FROM xhs_ad_stats_daily_account;
SELECT COUNT(*) FROM xhs_ad_stats_daily_buyer;
SELECT COUNT(*) FROM xhs_ad_stats_daily_brand;
SELECT COUNT(*) FROM xhs_ad_stats_daily_note;
SELECT COUNT(*) FROM xhs_ad_stats_daily_content_tag;
```

### 3. 初始化近 90 天聚合数据

不是近 30 天，是近 90 天。

需要对以下报表类型分别跑近 90 天刷新或聚合初始化：

```text
simple
standard
simple_note
standard_note
creative
```

推荐方式：

```text
优先：走现有报表刷新入口，days=90
原因：可以重新拉原始报表，并自动触发聚合刷新。
```

如果确认 `xhs_report_daily` 里近 90 天原始数据已经完整，也可以只跑聚合刷新脚本，但上线首轮建议走完整刷新链路，保证原始数据和聚合数据一致。

### 4. 初始化后检查聚合行数

聚合初始化完成后检查：

```sql
SELECT COUNT(*) FROM xhs_ad_stats_daily_account;
SELECT COUNT(*) FROM xhs_ad_stats_daily_buyer;
SELECT COUNT(*) FROM xhs_ad_stats_daily_brand;
SELECT COUNT(*) FROM xhs_ad_stats_daily_note;
SELECT COUNT(*) FROM xhs_ad_stats_daily_content_tag;
```

并抽查某一天、某个投手、某个账号：

```sql
SELECT *
FROM xhs_ad_stats_daily_account
WHERE stat_date = CURRENT_DATE - INTERVAL '1 day'
LIMIT 20;
```

### 5. 打开投流看板验证

验证项：

```text
管理员打开投流看板。
管理员切换不同投手。
投手账号登录打开投流看板。
切换日期范围。
切换广告账号。
内容标签矩阵正常显示。
笔记表正常显示。
品牌表正常显示。
```

### 6. 观察 Docker / Postgres IO

重点观察：

```text
频繁切换投手时 Docker 磁盘 IO 不再打满。
后台报表刷新期间 IO 上升是允许的，但不能导致前台页面不可用。
```

### 7. 后续优化待办

如果冷读内容标签仍觉得慢，下一阶段继续做：

```text
聚合刷新后自动预热全量 + 每个投手快照。
内容标签接口拆分：矩阵/量级、TOP 笔记、笔记表分页分开加载。
笔记表 note_rows 改为分页接口，不再跟内容标签一次性返回上千条。
```

## 上线注意

这次不建议只部署代码不初始化聚合表。否则上线后第一次看板访问仍会 fallback 到旧实时计算，无法完全验证效果。

正确顺序：

```text
备份数据库
部署代码
执行迁移
跑近 90 天报表刷新/聚合初始化
检查聚合表行数
打开看板验证
观察 IO
```
