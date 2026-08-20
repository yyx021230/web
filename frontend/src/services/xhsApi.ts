import api, { resolveDirectApiBaseURL } from './api';

export interface XHSEnvironment {
  id: number;
  shop_id: string;
  account_name: string;
  profile_url?: string;
  sync_cloud_session_id?: string;
  sync_cloud_api_key?: string;
  sync_cloud_update_config?: string;
  sync_browser_start_config?: string;
  xhs_account_id?: string;
  login_phone_number?: string;
  xhs_account_type?: 'enterprise_professional' | 'enterprise_employee' | 'personal' | string;
  is_sync_runner?: boolean;
  notes?: string;
  proxy_info?: string;
  group_name?: string;
  labels?: string;
  status: string;
}

export interface XHSBrowserEnvironmentStatus {
  environment_id: number;
  shop_id: string;
  account_name: string;
  browser_status: 'online' | 'offline' | 'busy' | 'error' | 'unknown' | string;
  is_online: boolean;
  checked_at?: string | null;
  source?: string | null;
  error?: string | null;
}

export interface XHSPost {
  id: number;
  user_id: number;
  environment_id: number;
  feed_id?: string;
  xsec_token?: string;
  post_url?: string;
  title: string;
  content: string;
  image_urls?: string[];
  tags?: string[];
  ai_origin_type: string;
  account_name?: string | null;
  status: string;
  like_count: number;
  comment_count: number;
  collect_count: number;
  share_count: number;
  view_count: number;
  published_at?: string;
  scheduled_at?: string;
  last_synced_at?: string;
  created_at?: string;
}

export interface PublishRequest {
  environment_id: number;
  title: string;
  content: string;
  image_paths: string[];
  tags?: string[];
  ai_origin_type?: string;
  is_original?: boolean;
  visibility?: string;
  scheduled_at?: string;
}

export interface PostUpdateRequest {
  title?: string;
  content?: string;
  tags?: string[];
  ai_origin_type?: string;
  scheduled_at?: string;
}

export interface XHSReportItem {
  account_name: string;
  account_id?: string | null;
  row_count: number;
  rows: Record<string, any>[];
  aggregation_data: Record<string, any>;
  error?: string | null;
}

export type XHSReportType = 'simple' | 'standard' | 'creative' | 'simple_note' | 'standard_note';

export interface XHSReportResponse {
  report_type: XHSReportType;
  start_date: string;
  end_date: string;
  account_id?: string | null;
  account_name?: string | null;
  total_accounts: number;
  total_rows: number;
  page: number;
  limit: number;
  items: XHSReportItem[];
  rows: Record<string, any>[];
}

export interface XHSCreativeCompareTag {
  key: 'manual' | 'text_ai' | 'image_ai' | 'all_ai';
  label: string;
}

export interface XHSCreativeComparePeriod {
  period_key: string;
  period_label: string;
  period_start: string;
  period_end: string;
  tags: Record<string, Record<string, number>>;
}

export interface XHSCreativeCompareGranularity {
  periods: XHSCreativeComparePeriod[];
  totals_by_tag: Record<string, Record<string, number>>;
  overall: Record<string, number>;
}

export interface XHSCreativeReportCompareResponse {
  report_type: 'creative';
  start_date: string;
  end_date: string;
  account_id?: string | null;
  account_name?: string | null;
  tags: XHSCreativeCompareTag[];
  granularities: Record<'day' | 'week' | 'month', XHSCreativeCompareGranularity>;
}

export interface XHSAccountNote {
  id: number;
  environment_id: number;
  account_name: string;
  profile_nickname?: string | null;
  red_id?: string | null;
  feed_id: string | null;
  identity_status: 'resolved' | 'creator_only' | 'homepage_only' | 'ambiguous' | string;
  creator_identity_key?: string | null;
  identity_match_method?: string | null;
  identity_match_confidence?: number | null;
  creator_published_at_raw?: string | null;
  creator_first_seen_at?: string | null;
  creator_last_seen_at?: string | null;
  creator_synced_at?: string | null;
  homepage_synced_at?: string | null;
  source_post_id?: number | null;
  xsec_token?: string | null;
  post_url?: string | null;
  cover_image_url?: string | null;
  title: string;
  content?: string | null;
  image_urls?: string[] | null;
  ai_origin_type?: string | null;
  primary_content_tag?: string | null;
  secondary_content_tag?: string | null;
  status: string;
  content_status?: string | null;
  content_missing_reason?: string | null;
  liked_count: number;
  comment_count: number;
  collected_count: number;
  share_count: number;
  view_count: number;
  exposure_count: number;
  cover_click_rate: number;
  is_promoted?: boolean;
  promoted_first_seen_at?: string | null;
  promoted_last_seen_at?: string | null;
  promoted_source?: string | null;
  published_at?: string | null;
  detail_synced_at?: string | null;
  sort_index: number;
  assigned_runner_environment_id?: number | null;
  assigned_runner_account_name?: string | null;
  assignment_updated_at?: string | null;
  owner_user_id?: number | null;
  owner_username?: string | null;
  owner_role?: string | null;
  has_paid_report?: boolean;
  has_creative_report?: boolean;
  today_browse_count?: number;
  first_synced_at?: string | null;
  last_seen_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface XHSAccountNoteListResponse {
  items: XHSAccountNote[];
  total: number;
  page: number;
  limit: number;
  total_accounts: number;
  dashboard?: XHSInsightsDashboard | null;
}

export interface XHSInsightsDashboard {
  metrics?: {
    activeAccounts: number;
    totalPosts: number;
    totalViews: number;
    totalLikes: number;
    totalComments: number;
    totalCollects: number;
    totalShares: number;
    totalEngagement: number;
    avgViews: number;
    avgComments: number;
    qualityCount: number;
    lowQualityCount: number;
  };
  trend?: Array<{
    label: string;
    posts: number;
    views: number;
    engagement: number;
    comments: number;
  }>;
  accountSummaries?: Array<Record<string, any>>;
  postRankings?: Array<Record<string, any>>;
  operatorRows?: Array<Record<string, any>>;
  carTypeStats?: Array<Record<string, any>>;
}

export interface XHSAccountNoteSyncResponse {
  synced_accounts: number;
  created_notes: number;
  updated_notes: number;
  metric_synced_notes: number;
  total_notes: number;
  deferred_homepage_notes?: number;
  deferred_homepage_items?: Array<{
    environment_id: number;
    account_name: string;
    feed_id: string;
    title: string;
    published_at?: string | null;
    reason: string;
  }>;
  exported_rows?: number;
  unmatched_notes?: number;
  duplicate_title_skips?: number;
  message?: string | null;
}

export interface XHSAccountNoteDetailSyncResponse {
  total_notes: number;
  matched_notes?: number;
  synced_notes: number;
  failed_notes: number;
  skipped_notes?: number;
}

export interface XHSAccountNoteSyncJobProgress {
  phase?: string | null;
  detail?: string | null;
  current?: number | null;
  total?: number | null;
  percent?: number | null;
  runner_id?: number | null;
  runner_name?: string | null;
  round?: number | null;
  runner_index?: number | null;
  runner_count?: number | null;
  current_note_id?: number | null;
  current_feed_id?: string | null;
  created_notes?: number | null;
  updated_notes?: number | null;
  deferred_homepage_notes?: number | null;
  synced_notes?: number | null;
  failed_notes?: number | null;
  synced_accounts?: number | null;
  matched_notes?: number | null;
  skipped_notes?: number | null;
  metric_synced_notes?: number | null;
  exported_rows?: number | null;
  unmatched_notes?: number | null;
  duplicate_title_skips?: number | null;
  sync_mode?: 'all' | 'unpublished_only' | null;
  account_name?: string | null;
  account_index?: number | null;
  account_total?: number | null;
  updated_at?: string | null;
}

export interface XHSAccountNoteSyncJob {
  job_id: string;
  job_type: 'account_notes_sync' | 'account_note_details_sync' | 'account_note_engagement_sync';
  environment_id?: number | null;
  scrape_environment_id?: number | null;
  scrape_environment_ids?: string | null;
  sync_account_limit?: number | null;
  sync_mode?: 'all' | 'unpublished_only' | null;
  sync_limit?: number | null;
  sync_limit_per_runner?: number | null;
  pause_seconds_min?: number | null;
  pause_seconds_max?: number | null;
  cancel_requested?: boolean;
  status: 'queued' | 'running' | 'cancelling' | 'succeeded' | 'failed' | 'cancelled';
  message: string;
  progress?: XHSAccountNoteSyncJobProgress | null;
  result?: XHSAccountNoteSyncResponse | XHSAccountNoteDetailSyncResponse | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  history_run_id?: number | null;
}

export interface XHSAccountSyncHistoryItem {
  id: number;
  environment_id?: number | null;
  account_name: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  message?: string | null;
  error?: string | null;
  result?: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface XHSAccountSyncHistoryRun {
  id: number;
  job_id: string;
  sync_kind: 'posts' | 'engagement' | 'details';
  source: 'manual' | 'retry_failed' | string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  message?: string | null;
  error?: string | null;
  parent_run_id?: number | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  summary: { total: number; succeeded: number; failed: number; cancelled: number; running: number };
  items: XHSAccountSyncHistoryItem[];
}

export interface XHSSyncRunnerBrowseOverview {
  date: string;
  days: number;
  total_views_today: number;
  runners: Array<{
    environment_id: number;
    account_name: string;
    assigned_notes: number;
    assigned_accounts: Array<{
      environment_id: number;
      account_name: string;
      note_count: number;
    }>;
    today_link_clicks: number;
    today_sync_views: number;
    today_total_views: number;
    timeline: Array<{
      date: string;
      link_clicks: number;
      sync_views: number;
      total_views: number;
    }>;
  }>;
  recent_events: Array<{
    id: number;
    runner_environment_id: number;
    runner_account_name?: string | null;
    note_id: number;
    note_feed_id?: string | null;
    note_title?: string | null;
    note_post_url?: string | null;
    source_environment_id?: number | null;
    source_account_name?: string | null;
    browse_source: string;
    job_id?: string | null;
    created_at?: string | null;
  }>;
}

export interface XHSReportRefreshJob {
  job_id: string;
  job_type: 'report_refresh';
  report_type: XHSReportType;
  account_id?: string | null;
  account_name?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  days?: number | null;
  status: 'queued' | 'running' | 'succeeded' | 'failed';
  message: string;
  result?: { updated_accounts: number; updated_rows: number; errors: string[]; start_date: string; end_date: string } | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface XHSAdDashboardResponse {
  start_date: string;
  end_date: string;
  previous_start_date: string;
  previous_end_date: string;
  filters: {
    account_ids: string[];
    xhs_account_ids?: string[];
    report_type: 'all' | 'simple' | 'standard';
    buyer_user_id?: number | null;
    accounts: Array<{ account_id: string; account_name: string; token_status?: string | null; has_token: boolean; buyer_user_id?: number | null; buyer_username?: string | null; buyer_display_name?: string | null; xhs_account_id?: string | null; xhs_account_name?: string | null; xhs_owner_name?: string | null }>;
    buyers: Array<{ user_id: number; username: string; display_name?: string | null; email?: string | null; account_count: number }>;
    xhs_accounts?: Array<{ xhs_account_id: string; xhs_account_name: string; xhs_owner_name?: string | null; account_ids: string[]; account_count: number }>;
  };
  summary: Record<string, number>;
  kpis: Array<{ key: string; label: string; value: number; previous_value: number; delta: number; delta_rate: number; value_type: 'currency' | 'integer' | 'percent' | string }>;
  owner_rows: Array<Record<string, any>>;
  quadrant: { avg_x: number; avg_y: number; points: Array<Record<string, any>> };
  content_tag_level?: 'primary' | 'secondary';
  content_tag_primary?: string | null;
  content_tag_children?: Record<string, {
    quadrant: { avg_x: number; avg_y: number; points: Array<Record<string, any>> };
    creative_tags: Array<Record<string, any>>;
    content_tag_level?: 'primary' | 'secondary';
    content_tag_primary?: string | null;
  }>;
  funnel: Array<Record<string, any>>;
  creative_tags: Array<Record<string, any>>;
  top_notes: Record<string, Record<string, any>>;
  comparison_rows: Array<Record<string, any>>;
  trend: Array<Record<string, any>>;
  brand_rows: Array<Record<string, any>>;
  note_rows: Array<Record<string, any>>;
  ai_summary: { title: string; summary: string; actions: string[] };
}

export interface XHSProfileStatOwnerRow {
  owner_id: string;
  owner_name: string;
  owner_role: string;
  account_names: string[];
  account_count: number;
  days: number;
  total_visits: number;
  leads: number;
  natural_source_count: number;
  ad_paid_count: number;
  natural_openings: number;
  ad_openings: number;
  natural_leads: number;
  special_natural_leads: number;
  ad_leads: number;
  direct_private_count: number;
  private_leads: number;
  comment_users: number;
  comment_leads: number;
  xhs_ad_leads: number;
  natural_opening_conversion_rate: number;
  ad_opening_conversion_rate: number;
  comment_lead_rate: number;
  private_lead_rate: number;
}

export interface XHSProfileStatOwnerResponse {
  start_date: string;
  end_date: string;
  owner_rows: XHSProfileStatOwnerRow[];
  total: Record<string, number>;
  assignment_summary?: {
    assigned_owner_count: number;
    assigned_account_count: number;
    assigned_active_account_count: number;
    covered_owner_count: number;
    covered_account_count: number;
    unmatched_profile_account_count: number;
  };
}

// --- API functions ---

export async function uploadImage(file: File): Promise<{ file_name: string; file_path: string }> {
  const formData = new FormData();
  formData.append('files', file);

  const response = await api.post('/xhs/upload-image', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

export async function uploadImages(files: File[]): Promise<Array<{ file_name: string; file_path: string }>> {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append('files', file);
  });

  const response = await api.post('/xhs/upload-image', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });

  if (Array.isArray(response.data?.files)) {
    return response.data.files;
  }
  if (response.data?.file_path) {
    return [response.data];
  }
  return [];
}

export async function getEnvironments(): Promise<XHSEnvironment[]> {
  const response = await api.get('/xhs/environments');
  return response.data;
}

export async function getXhsBrowserEnvironmentStatuses(params: { refresh?: boolean } = {}): Promise<XHSBrowserEnvironmentStatus[]> {
  try {
    const response = await api.get('/admin/xhs/browser-statuses', { params });
    return response.data;
  } catch (error: any) {
    if (String(error?.message || '').includes('Not Found')) {
      return [];
    }
    throw error;
  }
}

export async function publishPost(data: PublishRequest): Promise<{ post_id: number; feed_id?: string; status: string; scheduled_at?: string }> {
  const response = await api.post(`${resolveDirectApiBaseURL()}/xhs/publish`, data);
  return response.data;
}

export async function getPosts(params: { page?: number; limit?: number; status?: string } = {}): Promise<{ items: XHSPost[]; total: number; page: number; limit: number }> {
  const response = await api.get('/xhs/posts', { params });
  return response.data;
}

export async function getPostDetail(postId: number): Promise<XHSPost> {
  const response = await api.get(`/xhs/posts/${postId}`);
  return response.data;
}

export async function syncPostStats(postId: number): Promise<{ post_id: number; like_count: number; comment_count: number; collect_count: number; share_count: number; view_count: number; status: string; sync_reason?: string; last_synced_at?: string }> {
  const response = await api.get(`/xhs/posts/${postId}/stats`);
  return response.data;
}

export async function updatePost(postId: number, data: PostUpdateRequest): Promise<XHSPost> {
  const response = await api.patch(`/xhs/posts/${postId}`, data);
  return response.data;
}

export async function cancelPost(postId: number): Promise<XHSPost> {
  const response = await api.post(`/xhs/posts/${postId}/cancel`);
  return response.data;
}

export async function publishPostNow(postId: number): Promise<XHSPost> {
  const response = await api.post(`/xhs/posts/${postId}/publish-now`);
  return response.data;
}

export async function deletePost(postId: number): Promise<XHSPost> {
  const response = await api.delete(`/xhs/posts/${postId}`);
  return response.data;
}

export async function getXhsReport(
  reportType: XHSReportType,
  params: { account_id?: string; account_name?: string; start_date?: string; end_date?: string; days?: number; page?: number; limit?: number; ai_origin_filter?: string } = {}
): Promise<XHSReportResponse> {
  const endpointMap: Record<XHSReportType, string> = {
    simple: '/xhs/report/simple',
    standard: '/xhs/report/standard',
    creative: '/xhs/report/creative',
    simple_note: '/xhs/report/simple-note',
    standard_note: '/xhs/report/standard-note',
  };
  const endpoint = endpointMap[reportType];
  const response = await api.get(endpoint, { params });
  return response.data;
}

export async function getXhsCreativeReportCompare(
  params: { account_id?: string; account_name?: string; start_date?: string; end_date?: string; days?: number } = {}
): Promise<XHSCreativeReportCompareResponse> {
  const response = await api.get('/xhs/report/creative/compare', {
    params: {
      account_id: params.account_id,
      account_name: params.account_name,
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
    },
  });
  return response.data;
}

export async function getXhsReportAccounts(): Promise<Array<{
  account_id: string;
  account_name: string;
  has_token: boolean;
  token_status?: string | null;
  token_message?: string | null;
  token_timestamp?: string | null;
}>> {
  const response = await api.get('/xhs/report/accounts');
  return response.data;
}

export async function getXhsAdDashboard(params: {
  start_date?: string;
  end_date?: string;
  days?: number;
  account_ids?: string[];
  xhs_account_ids?: string[];
  report_type?: 'all' | 'simple' | 'standard';
  buyer_user_id?: number | null;
  include_content_tags?: boolean;
  signal?: AbortSignal;
} = {}): Promise<XHSAdDashboardResponse> {
  const response = await api.get('/xhs/ad-dashboard', {
    signal: params.signal,
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
      account_ids: params.account_ids?.join(',') || undefined,
      xhs_account_ids: params.xhs_account_ids?.join(',') || undefined,
      report_type: params.report_type,
      buyer_user_id: params.buyer_user_id || undefined,
      include_content_tags: params.include_content_tags,
    },
  });
  return response.data;
}

export async function getXhsProfileStatOwnerRows(params: {
  start_date?: string;
  end_date?: string;
  days?: number;
} = {}): Promise<XHSProfileStatOwnerResponse> {
  const response = await api.get('/xhs/profile-stat/owners', {
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
    },
  });
  return response.data;
}

export async function getXhsAdDashboardContentTags(params: {
  start_date?: string;
  end_date?: string;
  days?: number;
  account_ids?: string[];
  xhs_account_ids?: string[];
  report_type?: 'all' | 'simple' | 'standard';
  buyer_user_id?: number | null;
  level?: 'primary' | 'secondary';
  primary_tag?: string | null;
  signal?: AbortSignal;
} = {}): Promise<Pick<XHSAdDashboardResponse, 'quadrant' | 'creative_tags' | 'top_notes' | 'note_rows' | 'content_tag_level' | 'content_tag_primary' | 'content_tag_children'>> {
  const response = await api.get('/xhs/ad-dashboard/content-tags', {
    signal: params.signal,
    params: {
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
      account_ids: params.account_ids?.join(',') || undefined,
      xhs_account_ids: params.xhs_account_ids?.join(',') || undefined,
      report_type: params.report_type,
      buyer_user_id: params.buyer_user_id || undefined,
      level: params.level,
      primary_tag: params.primary_tag || undefined,
    },
  });
  return response.data;
}

export async function exportXhsAdDashboardTable(
  table: 'brand' | 'note',
  params: {
    start_date?: string;
    end_date?: string;
    days?: number;
    account_ids?: string[];
    xhs_account_ids?: string[];
    report_type?: 'all' | 'simple' | 'standard';
    buyer_user_id?: number | null;
  } = {}
): Promise<Blob> {
  const response = await api.get('/xhs/ad-dashboard/export', {
    params: {
      table,
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
      account_ids: params.account_ids?.join(',') || undefined,
      xhs_account_ids: params.xhs_account_ids?.join(',') || undefined,
      report_type: params.report_type,
      buyer_user_id: params.buyer_user_id || undefined,
    },
    responseType: 'blob',
  });
  return response.data;
}

export async function refreshXhsReportCache(
  reportType: XHSReportType,
  params: { account_id?: string; account_name?: string; start_date?: string; end_date?: string; days?: number } = {}
): Promise<{ updated_accounts: number; updated_rows: number; errors: string[]; start_date: string; end_date: string }> {
  const response = await api.post('/xhs/report/refresh', null, {
    params: {
      report_type: reportType,
      account_id: params.account_id,
      account_name: params.account_name,
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
    },
  });
  const job = response.data as XHSReportRefreshJob;
  return waitForXhsReportRefreshJob(job.job_id);
}

export async function getXhsReportRefreshJob(jobId: string): Promise<XHSReportRefreshJob> {
  const response = await api.get(`/xhs/report/refresh-jobs/${jobId}`);
  return response.data;
}

async function waitForXhsReportRefreshJob(
  jobId: string,
  options: { intervalMs?: number; timeoutMs?: number } = {}
): Promise<{ updated_accounts: number; updated_rows: number; errors: string[]; start_date: string; end_date: string }> {
  const intervalMs = options.intervalMs ?? 2000;
  const timeoutMs = options.timeoutMs ?? 25 * 60 * 1000;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const job = await getXhsReportRefreshJob(jobId);
    if (job.status === 'succeeded') {
      if (!job.result) {
        throw new Error('报表刷新任务已完成，但缺少结果数据');
      }
      return job.result;
    }
    if (job.status === 'failed') {
      throw new Error(job.error || job.message || '报表刷新失败');
    }
    await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
  }

  throw new Error('报表刷新超时，请稍后查看结果');
}

export async function exportXhsReport(
  reportType: XHSReportType,
  params: { account_id?: string; start_date?: string; end_date?: string; days?: number; ai_origin_filter?: string } = {}
): Promise<Blob> {
  const response = await api.get('/xhs/report/export', {
    params: {
      report_type: reportType,
      account_id: params.account_id,
      start_date: params.start_date,
      end_date: params.end_date,
      days: params.days,
      ai_origin_filter: params.ai_origin_filter,
    },
    responseType: 'blob',
  });
  return response.data;
}

export async function getXhsAccountNotes(
  params: { page?: number; limit?: number; environment_id?: number; keyword?: string; ai_origin_type?: string; status?: string } = {}
): Promise<XHSAccountNoteListResponse> {
  const response = await api.get('/xhs/account-notes', { params });
  return response.data;
}

export async function getXhsInsightAccountNotes(
  params: { start_date?: string; end_date?: string; limit?: number; status?: string } = {}
): Promise<XHSAccountNoteListResponse> {
  const response = await api.get('/xhs/account-notes/insights', { params });
  return response.data;
}

export async function syncXhsAccountNotes(
  params: {
    environment_id?: number;
    scrape_environment_id?: number;
    scrape_environment_ids?: string;
    sync_account_limit?: number;
    runner_account_assignments?: string;
    concurrency?: number;
  } = {}
): Promise<XHSAccountNoteSyncJob> {
  const response = await api.post('/xhs/account-notes/sync', null, { params });
  return response.data;
}

export async function syncXhsAccountNoteEngagements(
  params: {
    environment_id?: number;
    target_environment_ids?: string;
    sync_account_limit?: number;
    runner_account_assignments?: string;
    concurrency?: number;
  } = {}
): Promise<XHSAccountNoteSyncJob> {
  const response = await api.post('/xhs/account-notes/sync-engagement', null, { params });
  return response.data;
}

export async function syncXhsAccountNoteDetails(
  params: {
    environment_id?: number;
    target_note_ids?: string;
    scrape_environment_id?: number;
    scrape_environment_ids?: string;
    sync_mode?: 'all' | 'unpublished_only';
    sync_limit?: number;
    sync_limit_per_runner?: number;
    pause_seconds_min?: number;
    pause_seconds_max?: number;
    max_post_age_days?: number;
    concurrency?: number;
  } = {}
): Promise<XHSAccountNoteSyncJob> {
  const response = await api.post('/xhs/account-notes/sync-details', null, { params });
  return response.data;
}

export async function getXhsAccountNoteSyncJob(jobId: string): Promise<XHSAccountNoteSyncJob> {
  const response = await api.get(`/xhs/account-notes/sync-jobs/${jobId}`);
  return response.data;
}

export async function cancelXhsAccountNoteSyncJob(jobId: string): Promise<XHSAccountNoteSyncJob> {
  const response = await api.post(`/xhs/account-notes/sync-jobs/${jobId}/cancel`);
  return response.data;
}

export async function getXhsAccountNoteSyncHistory(limit = 20): Promise<XHSAccountSyncHistoryRun[]> {
  const response = await api.get('/xhs/account-notes/sync-history', { params: { limit } });
  return response.data;
}

export async function retryFailedXhsAccountNoteSyncHistory(runId: number): Promise<XHSAccountNoteSyncJob> {
  const response = await api.post(`/xhs/account-notes/sync-history/${runId}/retry-failed`);
  return response.data;
}

export async function getXhsSyncRunnerBrowseOverview(
  params: { days?: number; limit?: number } = {}
): Promise<XHSSyncRunnerBrowseOverview> {
  const response = await api.get('/admin/xhs/sync-runner-browse-overview', { params });
  return response.data;
}

export async function updateXhsAccountNote(
  noteId: number,
  data: { ai_origin_type?: string | null }
): Promise<XHSAccountNote> {
  const response = await api.patch(`/xhs/account-notes/${noteId}`, data);
  return response.data;
}

export async function recordXhsAccountNoteBrowse(
  noteId: number,
  browseSource: 'link_click' | 'single_sync' | 'bulk_sync' = 'link_click',
): Promise<{ event_id: number; note_id: number; browse_source: string; runner_environment_id: number; runner_account_name?: string | null }> {
  const response = await api.post(`/xhs/account-notes/${noteId}/record-browse`, {
    browse_source: browseSource,
  });
  return response.data;
}

export async function batchUpdateXhsAccountNotes(
  data: { note_ids: number[]; ai_origin_type: 'manual' | 'text_ai' | 'image_ai' | 'all_ai' }
): Promise<{ updated_count: number; requested_count: number; note_ids: number[]; ai_origin_type: string }> {
  const response = await api.post('/xhs/account-notes/batch-update', data);
  return response.data;
}

export async function tagXhsAccountNoteContent(
  data: {
    environment_id?: number;
    keyword?: string;
    ai_origin_type?: string;
    status?: 'active' | 'offline' | 'all';
    concurrency?: number;
  } = {}
): Promise<{
  matched_count: number;
  tagged_count: number;
  failed_count: number;
  concurrency: number;
  primary_counts: Record<string, number>;
  failed_items: Array<{ id: number; title: string; error: string }>;
}> {
  const response = await api.post('/xhs/account-notes/tag-content', data);
  return response.data;
}

export async function syncXhsAccountNoteStats(
  noteId: number,
  params: { scrape_environment_id?: number } = {},
): Promise<XHSAccountNote> {
  const response = await api.post(`/xhs/account-notes/${noteId}/sync-stats`, null, { params });
  return response.data;
}

export async function syncXhsAccountNoteEngagementStats(
  noteId: number,
): Promise<XHSAccountNote> {
  const response = await api.post(`/xhs/account-notes/${noteId}/sync-engagement-stats`);
  return response.data;
}
