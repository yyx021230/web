import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const ACCOUNT_ID = process.env.ACCOUNT_ID || "云环晖懂车学弟-汤钏";
const MONTH = process.env.REPORT_MONTH || "2026-05";
const MODEL = process.env.REPORT_MODEL || "gpt-5.5";
const OPENAI_BASE = process.env.OPENAI_BASE_URL || "http://47.98.127.132:48731/v1";
const OPENAI_KEY = process.env.OPENAI_API_KEY || "";
const API_BASE = process.env.REPORT_API_BASE_URL || "http://127.0.0.1:9091";
const OUTPUT_ROOT = process.env.REPORT_OUTPUT_ROOT || path.join(process.cwd(), "monthly_outputs");
const ROOT_DIR = path.join(OUTPUT_ROOT, ACCOUNT_ID, MONTH);

if (!OPENAI_KEY) {
  throw new Error("OPENAI_API_KEY is required");
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function writeJson(filePath, data) {
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
}

function writeText(filePath, text) {
  fs.writeFileSync(filePath, text);
}

function addDays(dateKey, days) {
  const date = new Date(`${dateKey}T00:00:00+08:00`);
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}

function getMonthWeekWindows(monthKey) {
  const [year, month] = monthKey.split("-").map(Number);
  const monthStart = new Date(Date.UTC(year, month - 1, 1));
  const monthEnd = new Date(Date.UTC(year, month, 0));
  const startDay = monthStart.getUTCDay();
  const mondayOffset = startDay === 0 ? -6 : 1 - startDay;
  const firstWeekStart = new Date(monthStart);
  firstWeekStart.setUTCDate(firstWeekStart.getUTCDate() + mondayOffset);

  const windows = [];
  let cursor = new Date(firstWeekStart);
  while (cursor <= monthEnd) {
    const start = cursor.toISOString().slice(0, 10);
    const endDate = new Date(cursor);
    endDate.setUTCDate(endDate.getUTCDate() + 6);
    const end = endDate.toISOString().slice(0, 10);
    windows.push({ startDate: start, endDate: end });
    cursor.setUTCDate(cursor.getUTCDate() + 7);
  }
  return windows;
}

function curlJson(url) {
  const stdout = execFileSync("curl", ["--noproxy", "*", "-s", url], {
    encoding: "utf8",
    maxBuffer: 50 * 1024 * 1024,
  });
  return JSON.parse(stdout);
}

function round(value, digits = 2) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return 0;
  const factor = 10 ** digits;
  return Math.round(num * factor) / factor;
}

function buildWeeklyInput(payload) {
  const report = payload.accountWeeklyReport || {};
  const chartData = report.chartData || {};
  const sourceMix = chartData.sourceMix || {};
  const paidFunnel = chartData.paidFunnel || [];
  const tagMatrix = chartData.tagMatrix || [];
  const totals = chartData.totals || {};
  const paidTotals = totals.paid || {};
  const allTotals = totals.all || {};
  const leadTopic = [...tagMatrix]
    .filter((item) => item.dimension === "内容主题")
    .sort((a, b) => (b.leads || 0) - (a.leads || 0) || (b.consult || 0) - (a.consult || 0))[0] || null;
  const organicTopic = [...tagMatrix]
    .filter((item) => item.dimension === "内容主题")
    .sort((a, b) => (b.organicEngagement || 0) - (a.organicEngagement || 0))[0] || null;
  return {
    accountLabel: report.summary?.accountLabel || payload.meta?.accountLabel || ACCOUNT_ID,
    period: report.reportWeekPeriod || {},
    currentWeek: {
      summary: report.summary,
      weeklyTrend: report.weeklyTrend,
      sourceMix: {
        total: sourceMix.total || 0,
        paid: sourceMix.paid || 0,
        organicOnly: sourceMix.organicOnly || 0,
      },
      kpis: {
        fee: round(allTotals.fee || 0, 2),
        impression: allTotals.impression || 0,
        click: allTotals.click || 0,
        organicEngagement: allTotals.organicEngagement || 0,
        organicLiked: allTotals.organicLiked || 0,
        organicComments: allTotals.organicComments || 0,
        organicCollected: allTotals.organicCollected || 0,
        organicShared: allTotals.organicShared || 0,
        paidCtr: round((paidFunnel.find((item) => item.key === "click")?.rate || paidTotals.ctr || 0), 2),
        consult: paidTotals.consult || 0,
        leads: paidTotals.leads || 0,
        leadRate: round((paidFunnel.find((item) => item.key === "leads")?.rate || 0), 2),
        leadCost: round(paidTotals.leadCost || 0, 2),
      },
      topSignals: {
        leadTopic,
        organicTopic,
      },
    },
    previousWeeklyReport: report.previousWeeklyReportContext || null,
    posts: (report.allPostBreakdowns || report.postBreakdowns || []).map((item) => ({
      id: item.id,
      title: item.title,
      publishedAt: item.publishedAt,
      sourceType: item.sourceType,
      content: String(item.content || item.contentPreview || "").slice(0, 260),
      contentPreview: item.contentPreview || "",
      contentTags: item.contentTags || {},
      metrics: item.metrics || {},
      why: item.why || "",
      nextAction: item.nextAction || "",
      sampleConfidence: item.sampleConfidence || "",
      creativeRole: item.creativeRole || "",
    })),
  };
}

function buildRepresentativePosts(monthPayloads) {
  const posts = monthPayloads.flatMap((payload) => payload.accountWeeklyReport?.allPostBreakdowns || payload.accountWeeklyReport?.postBreakdowns || []);
  const withMetrics = posts.map((post) => ({ ...post, metrics: post.metrics || {} }));
  const bestConversion = [...withMetrics].sort((a, b) => (b.metrics.leads || 0) - (a.metrics.leads || 0) || (b.metrics.consult || 0) - (a.metrics.consult || 0)).slice(0, 5);
  const highClickLowConversion = [...withMetrics].filter((post) => (post.metrics.click || 0) > 0 && (post.metrics.leads || 0) === 0).sort((a, b) => (b.metrics.ctr || 0) - (a.metrics.ctr || 0)).slice(0, 5);
  const highSpendLowResult = [...withMetrics].filter((post) => (post.metrics.fee || 0) > 0 && (post.metrics.leads || 0) === 0).sort((a, b) => (b.metrics.fee || 0) - (a.metrics.fee || 0)).slice(0, 5);
  const highOrganic = [...withMetrics].sort((a, b) => (b.metrics.organicEngagement || 0) - (a.metrics.organicEngagement || 0)).slice(0, 5);
  return {
    bestConversion,
    highClickLowConversion,
    highSpendLowResult,
    highOrganic,
  };
}

function buildMonthlyAggregate(monthPayloads) {
  const totals = {
    postCount: 0,
    paidCount: 0,
    organicCount: 0,
    impression: 0,
    click: 0,
    consult: 0,
    leads: 0,
    fee: 0,
    organicLiked: 0,
    organicComments: 0,
    organicCollected: 0,
    organicShared: 0,
    organicEngagement: 0,
  };

  const weeklySnapshots = monthPayloads.map((payload) => {
    const all = payload.accountWeeklyReport?.chartData?.totals?.all || {};
    const paid = payload.accountWeeklyReport?.chartData?.totals?.paid || {};
    const organic = payload.accountWeeklyReport?.chartData?.totals?.organic || {};
    totals.postCount += Number(all.count || 0);
    totals.paidCount += Number(paid.count || 0);
    totals.organicCount += Number(organic.count || 0);
    totals.impression += Number(all.impression || 0);
    totals.click += Number(all.click || 0);
    totals.consult += Number(all.consult || 0);
    totals.leads += Number(all.leads || 0);
    totals.fee += Number(all.fee || 0);
    totals.organicLiked += Number(all.organicLiked || 0);
    totals.organicComments += Number(all.organicComments || 0);
    totals.organicCollected += Number(all.organicCollected || 0);
    totals.organicShared += Number(all.organicShared || 0);
    totals.organicEngagement += Number(all.organicEngagement || 0);
    return {
      weekStart: payload.accountWeeklyReport?.reportWeekPeriod?.startDate,
      weekEnd: payload.accountWeeklyReport?.reportWeekPeriod?.endDate,
      postCount: Number(all.count || 0),
      impression: Number(all.impression || 0),
      click: Number(all.click || 0),
      consult: Number(all.consult || 0),
      leads: Number(all.leads || 0),
      fee: round(all.fee || 0, 2),
      ctr: all.impression ? round((Number(all.click || 0) / Number(all.impression)) * 100, 2) : 0,
      cpl: all.leads ? round(Number(all.fee || 0) / Number(all.leads), 2) : null,
    };
  });

  const monthlyCtr = totals.impression ? round((totals.click / totals.impression) * 100, 2) : 0;
  const monthlyCpl = totals.leads ? round(totals.fee / totals.leads, 2) : null;
  return {
    totals: {
      ...totals,
      fee: round(totals.fee, 2),
      ctr: monthlyCtr,
      cpl: monthlyCpl,
    },
    weeklySnapshots,
  };
}

function compactWeeklyReport(report = {}, period = {}) {
  return {
    period,
    summaryHeadline: report.summaryHeadline || "",
    summaryParagraphs: (report.summaryParagraphs || []).slice(0, 3),
    decisionBoard: (report.decisionBoard || []).slice(0, 5).map((item) => ({
      action: item.action || "",
      target: item.target || item.title || "",
      reason: item.reason || "",
      confidence: item.confidence || "",
      nextStep: item.nextStep || "",
    })),
    coreMetrics: (report.coreMetrics || []).slice(0, 6).map((item) => ({
      label: item.label || item.name || item.title || "",
      value: item.value || "",
      note: item.note || "",
    })),
    heroPosts: (report.heroPosts || []).slice(0, 2).map((item) => ({
      title: item.title,
      metric: item.metric || item.metrics || "",
      reason: item.reason || "",
    })),
    weakPosts: (report.weakPosts || []).slice(0, 2).map((item) => ({
      title: item.title,
      metric: item.metric || item.metrics || "",
      reason: item.reason || "",
    })),
    tomorrowChecklist: (report.tomorrowChecklist || []).slice(0, 3).map((item) => ({
      slot: item.slot || "",
      topic: item.topic || "",
      title: item.title || "",
      testVariable: item.testVariable || "",
    })),
    nextWeekFocus: (report.nextWeekFocus || report.nextWeekPlan || []).slice(0, 3).map((item) => ({
      title: item.title || item.focus || "",
      items: (item.items || []).slice(0, 3),
    })),
  };
}

function compactBatchSummary(summary = {}, period = {}) {
  return {
    period,
    batchHeadline: summary.batchHeadline || "",
    batchSummaryParagraphs: (summary.batchSummaryParagraphs || []).slice(0, 3),
    bestPosts: (summary.bestPosts || []).slice(0, 2).map((item) => ({
      title: item.title,
      metric: item.metric,
      reason: item.reason,
    })),
    weakPosts: (summary.weakPosts || []).slice(0, 2).map((item) => ({
      title: item.title,
      metric: item.metric,
      reason: item.reason,
    })),
    recurringIssues: (summary.recurringIssues || []).slice(0, 4),
    monthlyCarryForward: (summary.monthlyCarryForward || []).slice(0, 4),
  };
}

function compactRepresentativePosts(posts = {}) {
  const compactList = (items = []) => items.slice(0, 4).map((item) => ({
    title: item.title,
    sourceType: item.sourceType,
    metric: {
      fee: round(item.metrics?.fee || 0, 2),
      impression: item.metrics?.impression || 0,
      click: item.metrics?.click || 0,
      ctr: item.metrics?.ctr || 0,
      consult: item.metrics?.consult || 0,
      leads: item.metrics?.leads || 0,
      organicEngagement: item.metrics?.organicEngagement || 0,
    },
    contentTags: item.contentTags || {},
  }));
  return {
    bestConversion: compactList(posts.bestConversion),
    highClickLowConversion: compactList(posts.highClickLowConversion),
    highSpendLowResult: compactList(posts.highSpendLowResult),
    highOrganic: compactList(posts.highOrganic),
  };
}

function tryParseJsonObject(text) {
  const source = String(text || "").trim();
  if (!source) return null;
  try {
    return JSON.parse(source);
  } catch {}
  const firstBrace = source.indexOf("{");
  const lastBrace = source.lastIndexOf("}");
  if (firstBrace >= 0 && lastBrace > firstBrace) {
    const candidate = source.slice(firstBrace, lastBrace + 1);
    try {
      return JSON.parse(candidate);
    } catch {}
  }
  return null;
}

async function callModel(prompt, retryLabel) {
  const body = JSON.stringify({
    model: MODEL,
    temperature: 0.28,
    max_completion_tokens: 4200,
    messages: [{ role: "user", content: prompt }],
  });
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const stdout = execFileSync("curl", [
      "-L",
      "-s",
      "-X",
      "POST",
      `${OPENAI_BASE}/chat/completions`,
      "-H",
      "Content-Type: application/json",
      "-H",
      `Authorization: Bearer ${OPENAI_KEY}`,
      "--data-binary",
      body,
    ], {
      encoding: "utf8",
      maxBuffer: 50 * 1024 * 1024,
    });
    const data = tryParseJsonObject(stdout);
    if (!data) {
      if (attempt < 4) {
        execFileSync("sleep", ["2"]);
        continue;
      }
      throw new Error(`${retryLabel} failed: model response was not valid JSON envelope`);
    }
    const errorMessage = data?.error?.message || "";
    if (errorMessage && /temporarily unavailable/i.test(errorMessage) && attempt < 4) {
      execFileSync("sleep", ["2"]);
      continue;
    }
    if (data?.error) {
      throw new Error(`${retryLabel} failed: ${JSON.stringify(data.error)}`);
    }
    const content = String(data?.choices?.[0]?.message?.content || "")
      .trim()
      .replace(/^```json\s*/i, "")
      .replace(/^```\s*/i, "")
      .replace(/\s*```$/, "");
    const parsed = tryParseJsonObject(content);
    if (!parsed) {
      if (attempt < 4) {
        execFileSync("sleep", ["2"]);
        continue;
      }
      throw new Error(`${retryLabel} failed: model content was not valid JSON`);
    }
    return parsed;
  }
  throw new Error(`${retryLabel} failed after retries`);
}

async function callModelText(prompt, retryLabel) {
  const body = JSON.stringify({
    model: MODEL,
    temperature: 0.28,
    max_completion_tokens: 4200,
    messages: [{ role: "user", content: prompt }],
  });
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const stdout = execFileSync("curl", [
      "-L",
      "-s",
      "-X",
      "POST",
      `${OPENAI_BASE}/chat/completions`,
      "-H",
      "Content-Type: application/json",
      "-H",
      `Authorization: Bearer ${OPENAI_KEY}`,
      "--data-binary",
      body,
    ], {
      encoding: "utf8",
      maxBuffer: 50 * 1024 * 1024,
    });
    const data = tryParseJsonObject(stdout);
    if (!data) {
      if (attempt < 4) {
        execFileSync("sleep", ["2"]);
        continue;
      }
      throw new Error(`${retryLabel} failed: model response was not valid JSON envelope`);
    }
    const errorMessage = data?.error?.message || "";
    if (errorMessage && /temporarily unavailable/i.test(errorMessage) && attempt < 4) {
      execFileSync("sleep", ["2"]);
      continue;
    }
    if (data?.error) {
      throw new Error(`${retryLabel} failed: ${JSON.stringify(data.error)}`);
    }
    const content = String(data?.choices?.[0]?.message?.content || "").trim();
    if (content) return content.replace(/^```markdown\s*/i, "").replace(/^```\s*/i, "").replace(/\s*```$/, "");
    if (attempt < 4) {
      execFileSync("sleep", ["2"]);
      continue;
    }
    throw new Error(`${retryLabel} failed: empty content`);
  }
  throw new Error(`${retryLabel} failed after retries`);
}

function buildWeeklyPrompt(input) {
  return [
    "你是资深小红书账号运营负责人，现在要基于本周全量帖子明细、结构化数据、以及上周周报/上周摘要，生成一份真正能指导下周执行的《小红书账号级文字周报》。",
    "整份报告必须完全由你生成，不要复述提示词，不要输出 markdown，不要输出解释，只返回 JSON。",
    "报告不是传统汇报稿，而是周执行指挥单：先拍板，再看样本，再给明天能直接发的内容卡。",
    "报告风格必须先重点后细节，宁可短一点，也不要写成长篇作文或重复结论。",
    "你不能发明事实；没有的数据必须明确写“暂无”“未接入”或“当前缺少数据支持”，不能脑补。",
    "你必须优先结合本周所有已发布帖子逐条判断：哪些帖子是亮点样本，哪些帖子是问题样本，问题在哪，具体怎么改。",
    "你必须参考上周周报或上周有效周摘要来写环比、延续问题和下周规划；如果上周只有摘要，也要明确这是摘要不是完整周报。",
    "报告视角必须是运营执行视角，不要写空泛方法论，不要只讲抽象标签，要尽量落到题材、车型、标题、封面、正文开头、承接动作。",
    "你必须严格避开导流、极限低价、夸张刺激类违规表达，用更中性的运营语言表达动作建议。",
    "返回 JSON，字段必须严格包含：summaryHeadline, summaryParagraphs, decisionBoard, coreMetrics, thresholdRules, heroPosts, weakPosts, nextWeekDirections, templateKit, appendices。",
    "summaryHeadline: 必须写成一条完整结论句，至少同时包含本周状态判断、当前最主要问题或亮点、下周主动作，不要太短。",
    "summaryParagraphs: 控制在 2-3 条，只保留最重要背景，尽量写成“本周真正学到的规律”，不要和拍板动作重复，也不要复述发帖量、曝光、消耗这些事实本身。",
    "decisionBoard: 3-5 条，每条必须有 action, target, reason, confidence, nextStep。action 只能是：继续投、暂停、复测、改承接、观察。",
    "coreMetrics: 主报告里严格控制为 5 项关键经营数字，优先只保留：消耗、点击、CTR、咨询/线索、CPL。不要再把曝光、点赞、评论、浏览量/阅读量放进主报告；这些如需说明，放到 note 或附录。主报告里的 note 要非常短，尽量不超过15字，只做最小必要说明，不要写成长句解释。",
    "thresholdRules: 3-4 条，给出这周统一过线标准，格式尽量包含 label, rule, note。比如点击过线、咨询过线、线索过线、止损线。不要每个方向一套口径互相打架，尽量给统一基准，再说明例外。",
    "heroPosts: 最多 2 条。优质帖子不需要写成长篇改稿建议，也不要再往下展开标题方向、封面方向、正文开头、收口动作。这里只回答4件事：它的数据表现是什么、它为什么比普通样本更强、它相较于低效样本赢在哪、这条成功里最值得保留的结构是什么。reason 不能只写线索数，必须尽量同时结合曝光/点击/点赞/评论/咨询/线索中的可用指标。每条尽量返回：title, metric, reason, contrastPoint, takeaway。",
    "weakPosts: 最多 2 条。主报告里只需要 concise 版本：title, metric, reason, action。reason 不能只写点击率低或无线索，必须尽量结合曝光、点击、互动、正文承接、封面表达、车型表达、时间点一致性等多因素判断问题；不要片面归因。尤其当标题写6月、正文写5月时，不能一句话草率下结论，你必须先解释清楚两者关系：到底是“5月在预测6月政策”、还是“标题和正文口径真的没对齐”、还是“用户读完后会误解时间点”。只有当用户理解会被打断、信任被削弱或动作被延迟时，才能把它认定为明确问题。换句话说，你要先把问题链路说清楚，再给修改动作。",
    "coverGuide 不能只给2个词，必须足够具体到能指导运营做图。至少尽量包含：mainVisual（主视觉）、overlayCopy（封面上应该出现的文案，2-3行）、layoutFocus（信息层级）、avoid（不要怎么做）。",
    "nextWeekDirections: 主报告里只保留 2 条，标题固定叫方向一、方向二。它们必须是下周真正优先执行的主方向，不能再放低置信度探索方向。每条更像执行方向卡，尽量包含：priorityOrder, why, topicsAndVehicles, hypothesis, samplePlan, budgetPlan, successThreshold, stopThreshold, mainTestVariable, deliveryType, titleHow, coverHow, openingHow, closingHow。priorityOrder 要明确写出执行顺序，例如“S09 > L07 > L06/S05补测”或“元PLUS主救，其余比亚迪观察/暂停”。特别注意：方向二不要再把多个比亚迪车型都放进主执行方向，主报告里只保留元PLUS作为本周主救车型；宋PRO、海狮06、元UP这类只允许放进 appendices.rewriteCases 或 observationPool，不要继续占用正文主方向。不要在主报告里写“待排”“待负责人”“待预算确认”这类草稿字段。",
    "templateKit: 返回 3-4 组模板卡数组，每组都要包含 titleTemplate, coverTemplate, openingTemplate, ctaTemplate。不要写成理论，尽量写成内容团队能直接照着套的半成品表达。",
    "appendices: 必须包含 rewriteCases 和 openQuestions；如果还有低置信度但值得观察的车系或方向，把它们放到 observationPool，而不是挤进主报告的 nextWeekDirections。openQuestions 只保留仍需补口径或拍板的2-3个真正关键问题。如果主报告里比亚迪方向只保留元PLUS作为主救车型，那么 rewriteCases 也只保留元PLUS这一条，比亚迪其他车型不要再给详细改稿卡。",
    `输入数据：${JSON.stringify(input)}`,
  ].join("\n");
}

function buildWeeklyFallbackReport(bootstrap) {
  const report = bootstrap.accountWeeklyReport || {};
  const summary = report.summary || {};
  const totals = report.chartData?.totals?.all || {};
  const paid = report.chartData?.totals?.paid || {};
  const topLeadTopic = [...(report.chartData?.tagMatrix || [])]
    .filter((item) => item.dimension === "内容主题")
    .sort((a, b) => (b.leads || 0) - (a.leads || 0) || (b.consult || 0) - (a.consult || 0))[0];
  return {
    summaryHeadline: `${summary.accountLabel || ACCOUNT_ID} 本周先把 ${topLeadTopic?.label || "当前主线题材"} 的样本做扎实，当前重点不是铺更多方向，而是围绕已有正向信号补复测并收掉低效内容。`,
    summaryParagraphs: [
      `本周共发布 ${totals.count || 0} 条，其中投放 ${paid.count || 0} 条；当前周数据可作为基线，但还不足以定义稳定规律。`,
      `本周曝光 ${totals.impression || 0}、点击 ${totals.click || 0}、咨询 ${totals.consult || 0}、线索 ${totals.leads || 0}，主要信号集中在已有正向题材。`,
      "本周周报由结构化保底摘要生成，后续如补到完整模型版，可再替换。",
    ],
    decisionBoard: [
      {
        action: "复测",
        target: `${topLeadTopic?.label || "当前主线题材"}样本`,
        reason: "当前主线已出现相对更强的咨询/线索信号，但样本仍不够稳定。",
        confidence: "中",
        nextStep: "保持题材不变，只补 2-3 条控变量样本。",
      },
      {
        action: "暂停",
        target: "无明显信号的泛铺方向",
        reason: "当前周更需要收样本，而不是继续把车型和表达铺散。",
        confidence: "中",
        nextStep: "先停掉低信号方向，把内容位让给主线复测。",
      },
    ],
    coreMetrics: [
      { name: "发布量", value: `${totals.count || 0}条`, note: "当前只作为本周基线。" },
      { name: "曝光量", value: String(totals.impression || 0), note: "仅统计当前周已接入数据。" },
      { name: "浏览量/阅读量", value: "未接入", note: "当前暂无可用阅读深度数据。" },
      { name: "点击率", value: totals.impression ? `${round((Number(totals.click || 0) / Number(totals.impression)) * 100, 2)}%` : "0%", note: "先看基础吸引力。" },
      { name: "点赞", value: String(totals.organicLiked || 0), note: "当前自然互动仅作辅助判断。" },
      { name: "评论", value: String(totals.organicComments || 0), note: "公开互动强度仍偏弱。" },
      { name: "咨询/线索", value: `咨询${totals.consult || 0}，线索${totals.leads || 0}`, note: "后续仍需补控变量复测。" },
    ],
    heroPosts: [],
    weakPosts: [],
    nextWeekDirections: [
      {
        title: "方向一",
        why: `当前 ${topLeadTopic?.label || "主线题材"} 已出现相对更强的咨询或线索信号，适合继续补样本验证稳定性。`,
        topic: `继续围绕 ${topLeadTopic?.label || "当前主线题材"} 做 2-3 条控变量样本，先不扩更多车型。`,
        titleDirection: [
          "车型名和时间点放前面",
          "把本地参考方案或核对清单说清楚",
        ],
        coverGuide: {
          mainVisual: "车型实拍或正侧车图做主体，右侧或下方只保留一块清晰信息区。",
          overlayCopy: ["车型名", "本地方案/核对清单", "6月信息点"],
          layoutFocus: "第一眼先看到车型，第二眼看到利益点，第三眼看到时间点。",
          avoid: "不要满屏政策词，不要把文案堆成三段长句。",
        },
        openingDirection: [
          "先写看这台车的人最容易忽略的本地差异",
          "再写预算、配置、置换三项里要先核对什么",
        ],
        ctaDirection: [
          "统一用合规咨询动作或页面留资动作",
          "让用户明确提交城市、车型、预算、购车阶段",
        ],
        testVariable: "优先保持题材不变，只测试标题、封面或正文开头一个变量。",
      },
      {
        title: "方向二",
        why: "高点击低线索样本说明首屏有吸引力，但正文和收口没有接住高意向用户。",
        topic: "针对高点击低线索车型，重点做配置差异、预算场景、本地方案核对类内容。",
        titleDirection: [
          "不要只写泛政策，要把车型和决策场景写进标题",
          "优先写首购、换购、预算区间、配置选择"
        ],
        coverGuide: {
          mainVisual: "车型图配一张简洁的信息卡，突出预算或配置对比。",
          overlayCopy: ["车型名", "预算/配置", "先核对3项"],
          layoutFocus: "车型名最大，第二层写预算或配置差异，第三层再写时间点。",
          avoid: "不要只写情绪词，不要只写“别乱买”“别买贵”这类空提醒。",
        },
        openingDirection: [
          "第一句就说明这条适合谁看",
          "第二句写清本地参考信息或配置差异",
        ],
        ctaDirection: [
          "收口动作明确要什么信息，不要泛泛让用户来问",
        ],
        testVariable: "优先改正文前3行和收口动作，不先动封面。",
      },
    ],
  };
}

function buildBatchFallbackSummary(bootstrap, weeklyReport) {
  const report = bootstrap.accountWeeklyReport || {};
  const totals = report.chartData?.totals?.all || {};
  const posts = report.allPostBreakdowns || report.postBreakdowns || [];
  const bestPosts = [...posts]
    .sort((a, b) => (b.metrics?.leads || 0) - (a.metrics?.leads || 0) || (b.metrics?.consult || 0) - (a.metrics?.consult || 0))
    .slice(0, 2)
    .map((item) => ({
      title: item.title,
      metric: `咨询${item.metrics?.consult || 0}，线索${item.metrics?.leads || 0}`,
      reason: "本批次里相对更有结果信号。",
      carryForward: "可继续进入月度代表帖子池观察。",
    }));
  const weakPosts = [...posts]
    .sort((a, b) => (b.metrics?.fee || 0) - (a.metrics?.fee || 0))
    .slice(0, 2)
    .map((item) => ({
      title: item.title,
      metric: `消耗${round(item.metrics?.fee || 0, 2)}，线索${item.metrics?.leads || 0}`,
      reason: "消耗存在但结果偏弱。",
      carryForward: "适合进入月度低效样本池。",
    }));
  return {
    batchHeadline: `${report.summary?.accountLabel || ACCOUNT_ID} 本批次先保留高信号样本，其他内容以结构化保底摘要继续参与月报。`,
    batchSummaryParagraphs: [
      `本批次共 ${totals.count || 0} 条内容，当前主要看样本质量而不是绝对量。`,
      `本批次曝光 ${totals.impression || 0}、点击 ${totals.click || 0}、咨询 ${totals.consult || 0}、线索 ${totals.leads || 0}。`,
      "本批次摘要由结构化保底逻辑生成，可继续作为月报输入。",
    ],
    batchMetrics: [
      { label: "发布量", value: `${totals.count || 0}条`, note: "本批次样本总量。" },
      { label: "曝光量", value: String(totals.impression || 0), note: "本批次已接入曝光。" },
      { label: "咨询/线索", value: `咨询${totals.consult || 0}，线索${totals.leads || 0}`, note: "用于判断后续是否继续追踪。" },
      { label: "点赞", value: String(totals.organicLiked || 0), note: "自然互动只作辅助信号。" },
    ],
    bestPosts,
    weakPosts,
    highClickLowConversionPosts: [],
    highOrganicSignalPosts: [],
    patternSummary: {
      topics: (report.chartData?.tagMatrix || []).filter((item) => item.dimension === "内容主题").slice(0, 3),
      vehicles: (report.chartData?.tagMatrix || []).filter((item) => item.dimension === "车型实体").slice(0, 3),
      titleStyles: (report.chartData?.tagMatrix || []).filter((item) => item.dimension === "标题表达").slice(0, 3),
      bodyStyles: (report.chartData?.tagMatrix || []).filter((item) => item.dimension === "正文结构").slice(0, 3),
      ctaStyles: (report.chartData?.tagMatrix || []).filter((item) => item.dimension === "转化动作").slice(0, 3),
    },
    recurringIssues: ["当前批次使用结构化保底摘要，需以后续完整模型摘要补充细节。"],
    monthlyCarryForward: [
      weeklyReport?.summaryHeadline || `${ACCOUNT_ID} 当前批次仍以主线样本复测为主。`,
    ],
  };
}

function renderWeeklyMarkdown(payload, report) {
  const lines = [];
  const account = payload.meta?.accountLabel || ACCOUNT_ID;
  lines.push(`# ${account}｜周报预览`);
  lines.push("");
  lines.push(`周期：${payload.accountWeeklyReport?.reportWeekPeriod?.startDate || ""} ~ ${payload.accountWeeklyReport?.reportWeekPeriod?.endDate || ""}`);
  lines.push("");
  lines.push("## 一句话结论");
  lines.push(report.summaryHeadline || "暂无");
  lines.push("");
  if (report.decisionBoard?.length) {
    lines.push("## 本周请拍板的3件事");
    report.decisionBoard.slice(0, 3).forEach((item) => {
      lines.push(`### ${item.action || "观察"}｜${item.target || "未命名对象"}`);
      if (item.reason) lines.push(`- 原因：${item.reason}`);
      if (item.nextStep) lines.push(`- 下步：${item.nextStep}`);
      if (item.confidence) lines.push(`- 置信度：${item.confidence}`);
    });
    lines.push("");
  }
  const primaryCoreMetrics = selectWeeklyPrimaryCoreMetrics(report.coreMetrics);
  if (primaryCoreMetrics.length) {
    lines.push("## 经营结果总览");
    primaryCoreMetrics.forEach((item) => {
      const label = item.label || item.name || item.title || item.metric || "未命名指标";
      lines.push(`- ${label}：${item.value}`);
    });
    lines.push("");
  }
  const templateGroups = Array.isArray(report.templateKit)
    ? report.templateKit.filter(Boolean)
    : report.templateKit && typeof report.templateKit === "object"
      ? [report.templateKit]
      : [];
  if (report.nextWeekDirections?.length) {
    lines.push("## 下周执行表");
    report.nextWeekDirections.slice(0, 2).forEach((item, index) => {
      const template = pickWeeklyTemplateForDirection(item, templateGroups);
      lines.push(`### ${item.title || item.name || `方向${index + 1}`}｜${item.topic || item.topicsAndVehicles || "未命名方向"}`);
      if (item.deliveryType) lines.push(`- 处理动作：${item.deliveryType}`);
      if (item.why) lines.push(`- 为什么做：${item.why}`);
      if (item.priorityOrder) lines.push(`- 执行优先级：${item.priorityOrder}`);
      const samplePlan = normalizeWeeklySamplePlan(item);
      if (samplePlan) lines.push(`- 样本安排：${samplePlan}`);
      if (item.budgetPlan) lines.push(`- 预算建议：${item.budgetPlan}`);
      if (item.testVariable || item.mainTestVariable) lines.push(`- 测试变量：${item.testVariable || item.mainTestVariable}`);
      if (item.successThreshold) lines.push(`- 成功阈值：${item.successThreshold}`);
      if (item.stopThreshold) lines.push(`- 止损阈值：${item.stopThreshold}`);
      if (template?.titleTemplate) lines.push(`- 直接套用标题：${template.titleTemplate}`);
      else if (item.titleDirection?.length) lines.push(`- 标题方向：${item.titleDirection.join("；")}`);
      else if (item.titleHow) lines.push(`- 标题方向：${item.titleHow}`);
      if (template?.coverTemplate) lines.push(`- 直接套用封面：${template.coverTemplate}`);
      else if (item.coverHow) lines.push(`- 封面方向：${item.coverHow}`);
    });
    lines.push("");
  }
  if (report.thresholdRules?.length || report.summaryParagraphs?.length || templateGroups.length || report.heroPosts?.[0] || report.weakPosts?.[0]) {
    lines.push("## 附录：执行优化建议");
    if (report.thresholdRules?.length) {
      lines.push("### 执行前统一标准线");
      report.thresholdRules.slice(0, 4).forEach((item) => {
        const label = item.label || item.name || "未命名标准";
        const rule = item.rule || item.value || "";
        const note = item.note ? `｜${item.note}` : "";
        lines.push(`- ${label}：${rule}${note}`);
      });
    }
    if (report.summaryParagraphs?.length) {
      lines.push("### 本周真正学到的3条规律");
      report.summaryParagraphs.slice(0, 3).forEach((item) => lines.push(`- ${item}`));
    }
    if (templateGroups.length) {
      lines.push("### 本周可复用模板");
      templateGroups.slice(0, 4).forEach((item, index) => {
        lines.push(`- 模板${index + 1}｜标题：${item.titleTemplate || "暂无"}｜封面：${item.coverTemplate || "暂无"}｜开头：${item.openingTemplate || "暂无"}｜收口：${item.ctaTemplate || "暂无"}`);
      });
    }
    if (report.heroPosts?.[0]) {
      const item = report.heroPosts[0];
      lines.push("### 优质帖子举例分析");
      lines.push(`- ${item.title || item.post || item.name || "未命名帖子"}`);
      if (item.metric || item.metrics) lines.push(`- 数据：${item.metric || item.metrics}`);
      if (item.reason) lines.push(`- 原因：${item.reason}`);
      if (item.contrastPoint) lines.push(`- 好在哪：${item.contrastPoint}`);
      if (item.takeaway) lines.push(`- 可延续：${item.takeaway}`);
      else if (item.action) lines.push(`- 可延续：${item.action}`);
    }
    if (report.weakPosts?.[0]) {
      const item = report.weakPosts[0];
      lines.push("### 低质量帖子举例分析");
      lines.push(`- ${item.title || item.post || item.name || "未命名帖子"}`);
      if (item.metric || item.metrics) lines.push(`- 数据：${item.metric || item.metrics}`);
      if (item.reason) lines.push(`- 问题：${item.reason}`);
      if (item.action) lines.push(`- 修改：${item.action}`);
    }
    lines.push("");
  }
  return lines.join("\n");
}

function pickWeeklyTemplateForDirection(direction, templateGroups) {
  if (!templateGroups.length || !direction) return null;
  const text = String(direction.topic || direction.topicsAndVehicles || direction.name || direction.why || "");
  const tokens = text
    .split(/[、，,\s；;：:｜|\/]/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 2);
  return (
    templateGroups.find((template) =>
      tokens.some((token) => String(template.titleTemplate || "").includes(token) || String(template.coverTemplate || "").includes(token))
    ) || templateGroups[0]
  );
}

function selectWeeklyPrimaryCoreMetrics(coreMetrics) {
  const metrics = Array.isArray(coreMetrics) ? coreMetrics : [];
  const priorities = [
    { key: "消耗", patterns: ["消耗"] },
    { key: "点击", patterns: ["点击"] },
    { key: "CTR", patterns: ["ctr"] },
    { key: "咨询/线索", patterns: ["咨询/线索", "咨询", "线索"] },
    { key: "CPL", patterns: ["cpl"] },
  ];
  const selected = [];
  const used = new Set();
  priorities.forEach((priority) => {
    const match = metrics.find((item, index) => {
      if (used.has(index)) return false;
      const label = String(item.label || item.name || item.title || item.metric || "").toLowerCase();
      return priority.patterns.some((pattern) => label.includes(pattern.toLowerCase()));
    });
    if (match) {
      const index = metrics.indexOf(match);
      if (index >= 0) used.add(index);
      selected.push(match);
    }
  });
  if (selected.length) return selected;
  return metrics.slice(0, 5);
}

function isWeeklyYuanPlusDirection(report) {
  return Array.isArray(report.nextWeekDirections)
    && report.nextWeekDirections.some((item) => /元plus/i.test(String(item.topic || item.topicsAndVehicles || item.title || item.name || "")));
}

function normalizeWeeklySamplePlan(item) {
  const title = String(item.title || item.name || "");
  const topic = String(item.topic || item.topicsAndVehicles || "");
  if (/方向一/.test(title) || /深蓝/i.test(topic)) {
    return "先做S09 2条，再做L07 2条，其余仅保留1个补测位。";
  }
  if (/方向二/.test(title) || /元plus/i.test(topic)) {
    return "先做元PLUS 1条承接修正版，过线后再补第2条；其余比亚迪本周不抢排期。";
  }
  return item.samplePlan || "";
}

function buildBatchPrompt(template, input) {
  return `${template}\n\n输入数据：${JSON.stringify(input)}`;
}

function buildMonthlyPrompt(template, input) {
  return `${template}\n\n输入数据：${JSON.stringify(input)}`;
}

function buildMonthlyMarkdownPrompt(input) {
  return [
    "你是资深小红书内容运营负责人。",
    "现在基于本月所有周报、帖子批次摘要、月度结构化总数据和代表帖子池，直接生成一份完整的小红书账号级月报。",
    "不要输出 JSON，直接输出 Markdown 月报正文。",
    "月报必须和周报区分开：重点回答这个月真正跑通了什么、哪些只是偶发、哪些方向该继续放大、哪些该暂停、下个月资源怎么分。",
    "不能发明事实，没有的数据就明确写“未接入”。",
    "请用以下结构输出：",
    "1. 本月经营结论",
    "2. 本月经营看板",
    "3. 下月资源分配",
    "4. 本月稳定有效打法",
    "5. 本月低效打法 / 无效消耗",
    "6. 本月代表帖子复盘",
    "7. 下月作战图",
    "8. 月度模板与沉淀",
    "语言要像真正给运营负责人看的月报，但要兼顾管理者与执行层：前面更像经营判断，后面更像可复用打法与模板库。",
    `输入数据：${JSON.stringify(input)}`,
  ].join("\n");
}

function buildMonthlyMarkdown(report, monthKey) {
  const lines = [];
  lines.push(`# ${ACCOUNT_ID}｜月报预览`);
  lines.push("");
  lines.push(`周期：${monthKey}`);
  lines.push("");
  lines.push("## 本月经营结论");
  lines.push(report.monthlyHeadline || "暂无");
  lines.push("");
  const managementSummary = report.managementSummary || report.monthlySummaryParagraphs || [];
  if (managementSummary.length) {
    lines.push("## 先看重点");
    managementSummary.forEach((item) => lines.push(`- ${item}`));
    lines.push("");
  }
  if (report.monthlyCoreMetrics?.length) {
    lines.push("## 本月经营看板");
    report.monthlyCoreMetrics.forEach((item) => lines.push(`- ${item.label}：${item.value}${item.note ? `｜${item.note}` : ""}`));
    lines.push("");
  }
  if (report.resourceAllocation?.length) {
    lines.push("## 下月资源分配");
    report.resourceAllocation.slice(0, 6).forEach((item) => {
      lines.push(`### ${item.action || item.bucket || "待定"}｜${item.target || item.title || "未命名方向"}`);
      if (item.reason) lines.push(`- 原因：${item.reason}`);
      if (item.evidence) lines.push(`- 依据：${item.evidence}`);
      if (item.nextAction) lines.push(`- 动作：${item.nextAction}`);
    });
    lines.push("");
  }
  if (report.winningPatterns?.length) {
    lines.push("## 稳定有效打法");
    report.winningPatterns.slice(0, 3).forEach((item) => {
      lines.push(`### ${item.title}`);
      if (item.reason) lines.push(`- 判断：${item.reason}`);
      if (item.structure) {
        const structureBits = Object.entries(item.structure).filter(([, value]) => value).map(([key, value]) => `${key}=${value}`);
        if (structureBits.length) lines.push(`- 结构：${structureBits.join("；")}`);
      }
      if (item.examples?.length) lines.push(`- 例子：${item.examples.join("；")}`);
      if (item.nextAction) lines.push(`- 下月动作：${item.nextAction}`);
    });
    lines.push("");
  }
  if (report.losingPatterns?.length) {
    lines.push("## 低效打法 / 无效消耗");
    report.losingPatterns.slice(0, 3).forEach((item) => {
      lines.push(`### ${item.title}`);
      if (item.reason) lines.push(`- 问题：${item.reason}`);
      if (item.examples?.length) lines.push(`- 例子：${item.examples.join("；")}`);
      if (item.decision) lines.push(`- 处理：${item.decision}`);
    });
    lines.push("");
  }
  if (report.representativePosts?.length) {
    lines.push("## 本月代表帖子复盘");
    report.representativePosts.slice(0, 4).forEach((item) => {
      lines.push(`### ${item.title || item.type || "代表帖子"}`);
      if (item.metric) lines.push(`- 数据：${item.metric}`);
      if (item.reason) lines.push(`- 代表性：${item.reason}`);
      if (item.lesson) lines.push(`- 启发：${item.lesson}`);
    });
    lines.push("");
  }
  if (report.nextMonthBattlePlan?.length || report.nextMonthStrategy?.length) {
    lines.push("## 下月作战图");
    (report.nextMonthBattlePlan || report.nextMonthStrategy || []).slice(0, 5).forEach((item) => {
      lines.push(`### ${item.title || item.stream || "下月动作"}`);
      (item.items || []).forEach((step) => lines.push(`- ${step}`));
      if (item.note) lines.push(`- 备注：${item.note}`);
    });
    lines.push("");
  }
  const toolkit = report.monthlyToolkit || report.monthlySOP;
  if (toolkit) {
    lines.push("## 月度模板与沉淀");
    if (toolkit.topicDirections?.length || toolkit.topics?.length) {
      lines.push(`- 可复用题材：${(toolkit.topicDirections || toolkit.topics || []).slice(0, 6).join("；")}`);
    }
    if (toolkit.titleTemplates?.length || toolkit.titles?.length) {
      lines.push(`- 标题方向：${(toolkit.titleTemplates || toolkit.titles || []).slice(0, 6).join("；")}`);
    }
    if (toolkit.coverTemplates?.length || toolkit.covers?.length) {
      lines.push(`- 封面方向：${(toolkit.coverTemplates || toolkit.covers || []).slice(0, 6).join("；")}`);
    }
    if (toolkit.openingTemplates?.length || toolkit.bodies?.length) {
      lines.push(`- 正文开头：${(toolkit.openingTemplates || toolkit.bodies || []).slice(0, 6).join("；")}`);
    }
    if (toolkit.ctaTemplates?.length || toolkit.cta?.length) {
      lines.push(`- 收口动作：${(toolkit.ctaTemplates || toolkit.cta || []).slice(0, 6).join("；")}`);
    }
    if (toolkit.stopList?.length || toolkit.pitfalls?.length) {
      lines.push(`- 暂停清单：${(toolkit.stopList || toolkit.pitfalls || []).slice(0, 6).join("；")}`);
    }
    lines.push("");
  }
  if (report.dataGaps?.length) {
    lines.push("## 数据缺口");
    report.dataGaps.slice(0, 4).forEach((item) => {
      if (typeof item === "string") {
        lines.push(`- ${item}`);
      } else {
        lines.push(`- ${item.label || item.title || "未命名缺口"}：${item.note || item.reason || ""}`);
      }
    });
    lines.push("");
  }
  return lines.join("\n");
}

async function main() {
  ensureDir(ROOT_DIR);
  const weeklyDir = path.join(ROOT_DIR, "weekly_reports");
  const batchDir = path.join(ROOT_DIR, "batch_summaries");
  ensureDir(weeklyDir);
  ensureDir(batchDir);

  const weekWindows = getMonthWeekWindows(MONTH);
  const weeklyPayloads = [];
  const weeklyReports = [];
  const batchSummaries = [];

  const batchTemplate = readText("/Users/yyx/ztqc/web/monthly_post_batch_summary_prompt.md");
  const monthlyTemplate = readText("/Users/yyx/ztqc/web/monthly_report_prompt.md");

  for (const window of weekWindows) {
    const tag = `${window.startDate}_${window.endDate}`;
    const bootstrapPath = path.join(weeklyDir, `${tag}.bootstrap.json`);
    const bootstrap = fs.existsSync(bootstrapPath)
      ? JSON.parse(readText(bootstrapPath))
      : curlJson(`${API_BASE}/api/bootstrap?accountId=${encodeURIComponent(ACCOUNT_ID)}&startDate=${window.startDate}&endDate=${window.endDate}`);
    writeJson(bootstrapPath, bootstrap);
    weeklyPayloads.push(bootstrap);

    const weeklyInput = buildWeeklyInput(bootstrap);
    const weeklyReportPath = path.join(weeklyDir, `${tag}.weekly_report.json`);
    let weeklyReport;
    if (fs.existsSync(weeklyReportPath)) {
      weeklyReport = JSON.parse(readText(weeklyReportPath));
    } else {
      try {
        weeklyReport = await callModel(buildWeeklyPrompt(weeklyInput), `weekly report ${tag}`);
      } catch {
        weeklyReport = buildWeeklyFallbackReport(bootstrap);
      }
    }
    weeklyReports.push({ window, report: weeklyReport });
    writeJson(weeklyReportPath, weeklyReport);
    writeText(path.join(weeklyDir, `${tag}.weekly_report.md`), renderWeeklyMarkdown(bootstrap, weeklyReport));

    const batchInput = {
      accountLabel: ACCOUNT_ID,
      batchPeriod: window,
      weeklyReport,
      totals: bootstrap.accountWeeklyReport?.chartData?.totals || {},
      tags: bootstrap.accountWeeklyReport?.chartData?.tagMatrix || [],
      posts: (bootstrap.accountWeeklyReport?.allPostBreakdowns || bootstrap.accountWeeklyReport?.postBreakdowns || []).map((item) => ({
        id: item.id,
        title: item.title,
        sourceType: item.sourceType,
        metrics: item.metrics || {},
        contentTags: item.contentTags || {},
        contentPreview: item.contentPreview || "",
      })),
    };
    const batchSummaryPath = path.join(batchDir, `${tag}.batch_summary.json`);
    let batchSummary;
    if (fs.existsSync(batchSummaryPath)) {
      batchSummary = JSON.parse(readText(batchSummaryPath));
    } else {
      try {
        batchSummary = await callModel(buildBatchPrompt(batchTemplate, batchInput), `batch summary ${tag}`);
      } catch {
        batchSummary = buildBatchFallbackSummary(bootstrap, weeklyReport);
      }
    }
    batchSummaries.push({ window, summary: batchSummary });
    writeJson(batchSummaryPath, batchSummary);
  }

  const monthlyAggregate = buildMonthlyAggregate(weeklyPayloads);
  const representativePosts = buildRepresentativePosts(weeklyPayloads);
  const monthlyInput = {
    accountLabel: ACCOUNT_ID,
    month: MONTH,
    weekWindows,
    monthlyAggregate,
    weeklyReports: weeklyReports.map((item) => compactWeeklyReport(item.report, item.window)),
    batchSummaries: batchSummaries.map((item) => compactBatchSummary(item.summary, item.window)),
    representativePosts: compactRepresentativePosts(representativePosts),
  };
  writeJson(path.join(ROOT_DIR, "monthly_input.json"), monthlyInput);

  const monthlyReportPath = path.join(ROOT_DIR, "monthly_report.json");
  const monthlyMarkdownPath = path.join(ROOT_DIR, "monthly_report.md");
  if (fs.existsSync(monthlyReportPath)) {
    const monthlyReport = JSON.parse(readText(monthlyReportPath));
    writeText(monthlyMarkdownPath, buildMonthlyMarkdown(monthlyReport, MONTH));
  } else {
    try {
      const monthlyReport = await callModel(buildMonthlyPrompt(monthlyTemplate, monthlyInput), "monthly report");
      writeJson(monthlyReportPath, monthlyReport);
      writeText(monthlyMarkdownPath, buildMonthlyMarkdown(monthlyReport, MONTH));
    } catch {
      const markdownReport = await callModelText(buildMonthlyMarkdownPrompt(monthlyInput), "monthly markdown report");
      writeText(monthlyMarkdownPath, markdownReport);
    }
  }

  console.log(monthlyMarkdownPath);
}

await main();
