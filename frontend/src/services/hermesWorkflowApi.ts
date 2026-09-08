import api from './api';

export type HermesStatus =
  | 'queued' | 'running' | 'review_pending' | 'approved'
  | 'changes_requested' | 'ready_to_publish' | 'published' | 'failed';

export interface HermesAccount {
  id: number;
  name: string;
  group?: string | null;
  labels?: string | null;
  owner_user_id?: number | null;
  owner_name?: string | null;
}

export interface HermesPolicy {
  case_id: string;
  brand: string;
  vehicle_model: string;
  policy_source: string;
  policy_source_title: string;
  policy_source_url: string;
  policy_deadline?: string | null;
  public_deadline?: string | null;
  allow_multi_config_quote: boolean;
  quote_rows: Array<{
    configuration?: string;
    official_guide_price?: string;
    national_scrappage_after_price?: string;
    provincial_trade_in_after_price?: string;
  }>;
  policy_text: string;
}

export interface HermesPost {
  id: number;
  run_id: number;
  environment_id: number;
  owner_user_id?: number | null;
  slot: number;
  account_name: string;
  vehicle_model: string;
  case_id?: string | null;
  status: string;
  title?: string | null;
  content?: string | null;
  image_url?: string | null;
  hard_pass: boolean;
  version?: string;
  revision?: number;
  source_detail?: Record<string, unknown>;
  review_comment?: string | null;
  reviewed_at?: string | null;
  publish_status: string;
  publish_target_environment_id?: number | null;
  scheduled_publish_at?: string | null;
}

export interface HermesReferenceExample { id: number; title: string; content: string; image_url?: string; preview_note?: string; source_section_title?: string; kind: 'copy' | 'image'; }
export interface HermesReferenceType { id: string; name: string; description: string; structure: string; accent: string; reference_count: number; preview_count: number; examples: HermesReferenceExample[]; }
export interface HermesReferenceCatalog { version: string; source: string; synced_at?: string | null; source_note: string; copy_types: HermesReferenceType[]; image_types: HermesReferenceType[]; library_counts: { copy: number; image: number }; }

export interface HermesRun {
  id: number;
  run_key: string;
  name?: string;
  source: string;
  workflow_mode?: 'batch' | 'single';
  status: HermesStatus | string;
  requested_by?: number | null;
  scheduled_for?: string | null;
  parameters: {
    name?: string;
    copy_type?: string;
    image_type?: string;
    selection_contract?: { version: string; mode: string; copy_label?: string; image_label?: string; rule: string };
    policy_snapshot_at?: string;
    policy_fingerprint?: string;
    accounts?: Array<{
      environment_id: number;
      account_name: string;
      owner_user_id?: number | null;
      vehicle_model: string;
      case_id?: string | null;
    }>;
    posts_per_account?: number;
    instruction?: string;
    regeneration?: { post_id: number; run_id: number; revision: number; reason: string; requested_by: number; requested_at: string };
  };
  total_posts: number;
  generated_posts: number;
  approved_posts: number;
  rejected_posts: number;
  failed_posts?: number;
  pending_review_posts?: number;
  assigned_failed?: number;
  assigned_pending_review?: number;
  assigned_posts?: number;
  assigned_status?: HermesStatus | string;
  assigned_generated?: number;
  assigned_approved?: number;
  assigned_rejected?: number;
  accounts?: string[];
  vehicles?: string[];
  worker_id?: string | null;
  error?: string | null;
  created_at: string;
  updated_at?: string | null;
  posts?: HermesPost[];
}

export interface HermesRunQuery {
  workflow_mode?: 'batch' | 'single';
  status?: string; search?: string; source?: string; environment_id?: number;
  date_from?: string; date_to?: string; page?: number; limit?: number;
}

export type HermesReviewResult = HermesRun & { regenerated_run_id?: number };

export type HermesPublishItem = { post_id: number; environment_id: number; scheduled_at: string; expected_version?: string };

export interface HermesSchedule {
  id: number;
  name: string;
  enabled: boolean;
  run_time: string;
  timezone: string;
  posts_per_account: number;
  accounts: Array<{
    environment_id: number;
    account_name?: string;
    owner_user_id?: number | null;
    vehicle_model: string;
    case_id?: string | null;
  }>;
  instruction?: string | null;
  last_enqueued_for?: string | null;
  last_run_id?: number | null;
}

export interface HermesPublishQuery { page?: number; limit?: number; search?: string; environment_id?: number; planned?: boolean; }

// Only retry read requests. A lost POST response must never create a second task.
async function read<T>(url: string, config: { params?: unknown; timeout?: number } = {}) {
  for (let attempt = 0; ; attempt++) {
    try { return await api.get<T>(url, { timeout: 20000, ...config }); }
    catch (error) {
      const e = error as Error & { status?: number };
      const transient = e.status ? [502, 503, 504].includes(e.status) : /network error|timeout/i.test(e.message || '');
      if (!transient || attempt >= 2) throw error;
      await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 300 : 900));
    }
  }
}

export const hermesWorkflowApi = {
  referenceTypes: () => read<HermesReferenceCatalog>('/hermes-workflows/reference-types'),
  bootstrap: () => read<{ accounts: HermesAccount[]; vehicle_models: string[]; policies: HermesPolicy[]; limits: { max_posts_per_run: number } }>('/hermes-workflows/bootstrap'),
  createRun: (payload: { name?: string; account_id: number; vehicle_model: string; case_id?: string; post_count: number; copy_type?: string; image_type?: string; instruction?: string }) =>
    api.post<HermesRun>('/hermes-workflows/runs', payload),
  createBatchRun: (payload: {
    name?: string;
    accounts: Array<{ environment_id: number; post_count: number }>;
    vehicle_models: string[];
    instruction?: string;
  }) => api.post<HermesRun>('/hermes-workflows/runs/batch', payload),
  listRuns: (query?: HermesRunQuery | string) => read<{ items: HermesRun[]; total: number }>('/hermes-workflows/runs', { params: { limit: 8, ...(typeof query === 'string' ? { status: query } : query) } }),
  getRun: (runId: number) => read<HermesRun>(`/hermes-workflows/runs/${runId}`),
  reviewPost: (postId: number, action: 'approve' | 'reject', comment?: string, expected_version?: string, regenerate = false) =>
    api.post<HermesReviewResult>(`/hermes-workflows/posts/${postId}/review`, { action, comment, expected_version, ...(regenerate ? { regenerate: true } : {}) }),
  editPost: (postId: number, payload: { title: string; content: string; comment: string; expected_version: string }) =>
    api.patch<HermesPost>(`/hermes-workflows/posts/${postId}`, payload),
  cancelRun: (runId: number) => api.post(`/hermes-workflows/runs/${runId}/cancel`),
  listPublishCandidates: (query?: HermesPublishQuery) => read<{ items: HermesPost[]; total: number }>('/hermes-workflows/publish-candidates', { params: query }),
  savePublishPlan: (items: HermesPublishItem[]) =>
    api.post<{ items: HermesPost[] }>('/hermes-workflows/publish-plan', { items }),

  adminBootstrap: () => read<{
    schedule: HermesSchedule;
    policies: HermesPolicy[];
    accounts: HermesAccount[];
    status_counts: Record<string, number>;
    workers: Array<{
      worker_id: string;
      status: string;
      current_run_id?: number | null;
      online: boolean;
      last_seen_at: string;
      capabilities?: { models?: string[]; case_ids?: string[]; image_ocr?: string };
    }>;
  }>('/admin/hermes-workflows/bootstrap'),
  updateSchedule: (payload: {
    enabled: boolean;
    run_time: string;
    posts_per_account: number;
    accounts: Array<{ environment_id: number; vehicle_model: string; case_id?: string | null }>;
    instruction?: string;
  }) => api.put<HermesSchedule>('/admin/hermes-workflows/schedule', payload),
  runScheduleNow: () => api.post<HermesRun>('/admin/hermes-workflows/schedule/run-now'),
  adminListRuns: (query?: HermesRunQuery | string) => read<{ items: HermesRun[]; total: number }>('/admin/hermes-workflows/runs', { params: { limit: 8, ...(typeof query === 'string' ? { status: query } : query) } }),
  adminGetRun: (runId: number) => read<HermesRun>(`/admin/hermes-workflows/runs/${runId}`),
  adminReviewPost: (postId: number, action: 'approve' | 'reject', comment?: string, expected_version?: string, regenerate = false) =>
    api.post<HermesReviewResult>(`/admin/hermes-workflows/posts/${postId}/review`, { action, comment, expected_version, ...(regenerate ? { regenerate: true } : {}) }),
  adminPublishCandidates: (query?: HermesPublishQuery) => read<{ items: HermesPost[]; total: number }>('/admin/hermes-workflows/publish-candidates', { params: query }),
  adminSavePublishPlan: (items: HermesPublishItem[]) => api.post('/admin/hermes-workflows/publish-plan', { items }),
  preparePublish: (runId: number) => api.post(`/admin/hermes-workflows/runs/${runId}/publish`),
};
