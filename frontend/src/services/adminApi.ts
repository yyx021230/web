import api from './api';

export const adminApi = {
  // Dashboard stats
  getOverview: (username?: string) =>
    api.get<{
      user_count: number;
      project_count: number;
      material_count: number;
      ai_task_count: number;
      workflow_count: number;
      run_log_count: number;
      storage_bytes: number;
      storage_mb: number;
      ai_tasks_24h: number;
      ai_success_rate_24h: number;
      ai_tasks_today?: number;
      ai_success_rate_today?: number;
    }>('/admin/stats/overview', { params: { username } }),

  getAiTrend: (days = 7) =>
    api.get<{
      ai_daily: Array<{ date: string; total: number; by_model: Record<string, number> }>;
      ai_models: Array<{ model: string; total: number; success: number; failed: number; avg_seconds: number }>;
      wf_daily: Array<{ date: string; succeeded: number; failed: number; running: number; stopped: number }>;
    }>('/admin/stats/ai-trend', { params: { days } }),

  getActiveTasks: (username?: string) =>
    api.get<Array<{ id: number; type: string; username: string; model: string; status?: string; created_at: string }>>('/admin/stats/active-tasks', { params: { username } }),

  getRankings: (username?: string) =>
    api.get('/admin/stats/rankings', { params: { username } }),

  getStorage: () =>
    api.get<{
      total_bytes: number;
      total_mb: number;
      by_type: Array<{ type: string; count: number; bytes: number; mb: number }>;
    }>('/admin/stats/storage'),

  getUsageSeries: (granularity: 'hour' | 'day' | 'week', username?: string) =>
    api.get<{
      granularity: 'hour' | 'day' | 'week';
      buckets: Array<{ key: string; label: string; start: string; end: string }>;
      ai: {
        names?: string[];
        series: Record<string, number[]>;
        total_records: number;
        matched_records: number;
        raw_model_counts: Record<string, number>;
      };
      workflow: {
        names: string[];
        series: Record<string, number[]>;
        total_records: number;
      };
    }>('/admin/stats/usage-series', { params: { granularity, username } }),

  getXhsPublishSeries: (granularity: 'hour' | 'day' | 'week', username?: string) =>
    api.get<{
      granularity: 'hour' | 'day' | 'week';
      buckets: Array<{ key: string; label: string; start: string; end: string }>;
      series: Record<string, number[]>;
      total_records: number;
    }>('/admin/stats/xhs-publish-series', { params: { granularity, username } }),

  getXhsPublishedPosts: (params: { page?: number; limit?: number; username?: string } = {}) =>
    api.get<{
      items: Array<{
        id: number;
        source_type: string;
        source_label: string;
        title: string;
        username: string;
        environment_name: string;
        post_url: string | null;
        feed_id: string | null;
        published_at: string | null;
        like_count: number;
        comment_count: number;
        collect_count: number;
        share_count: number;
        created_at: string | null;
      }>;
      total: number;
      page: number;
      limit: number;
    }>('/admin/stats/xhs-published-posts', { params }),

  // Users
  getUsers: (page = 1, limit = 20) =>
    api.get<{ items: Array<{ id: number; username: string; display_name?: string | null; email: string; avatar: string | null; is_active: boolean; role: string; roles?: string[]; created_at: string }>; total: number; page: number; limit: number }>('/admin/users', { params: { page, limit: Math.min(limit, 100) } }),

  updateUserProfile: (userId: number, data: { display_name?: string | null }) =>
    api.patch(`/admin/users/${userId}/profile`, data),

  updateUserRole: (userId: number, role: string) =>
    api.patch(`/admin/users/${userId}/role`, { role }),

  updateUserRoles: (userId: number, roles: string[]) =>
    api.patch(`/admin/users/${userId}/roles`, { roles }),

  updateUserActive: (userId: number, is_active: boolean) =>
    api.patch(`/admin/users/${userId}/active`, { is_active }),

  getUserWorkflows: (userId: number) =>
    api.get<{ id: number; app_name: string; app_type: string; description: string | null; is_enabled: boolean }[]>(`/admin/users/${userId}/workflows`),

  setUserWorkflows: (userId: number, workflowIds: number[]) =>
    api.post(`/admin/users/${userId}/workflows`, { workflow_ids: workflowIds }),

  getUserStats: (userId: number) =>
    api.get<{ ai_tasks: number; wf_tasks: number; projects: number; storage_mb: number }>(`/admin/users/${userId}/stats`),

  batchDeleteUserTasks: (userId: number, type: 'ai' | 'workflow') =>
    api.post('/admin/users/batch-delete-tasks', { user_id: userId, type }),

  createUser: (data: { username: string; display_name?: string; email: string; password: string; role?: string; roles?: string[] }) =>
    api.post('/admin/users', data),

  deleteUser: (userId: number) =>
    api.delete(`/admin/users/${userId}`),

  // Materials
  getMaterials: (params: { page?: number; limit?: number; username?: string; category?: string; type?: string }) =>
    api.get<{ items: any[]; total: number; page: number; limit: number }>('/admin/materials', { params }),

  deleteMaterial: (materialId: number) =>
    api.delete(`/admin/materials/${materialId}`),
  batchDeleteMaterials: (material_ids: number[]) =>
    api.post<{ deleted: number }>('/admin/materials/batch-delete', { material_ids }),

  getTemplates: (page = 1, limit = 20) =>
    api.get<{ items: Array<{ id: number; name: string; url: string; width: number; height: number; ai_meta: Record<string, unknown> | null; created_by: number | null; created_at: string }>; total: number; page: number; limit: number }>('/admin/materials/templates', { params: { page, limit } }),

  // User detail
  getUserDetail: (userId: number) =>
    api.get<{ user: { id: number; username: string; email: string; avatar: string | null; role: string; roles?: string[]; is_active: boolean; created_at: string }; stats: { project_count: number; material_count: number; ai_task_count: number; ai_task_24h: number; workflow_count: number; dify_task_count: number; dify_run_log_count: number; copywriting_count: number }; recent_ai_tasks: Array<{ id: number; model_name: string; prompt: string; status: string; created_at: string }>; recent_dify_tasks: Array<{ id: number; workflow_id: number; status: string; created_at: string }> }>(`/admin/users/${userId}/detail`),

  // Resources (ai-tasks, copywritings)
  getAiTasks: (params: { page?: number; limit?: number; username?: string; status?: string; model_name?: string }) =>
    api.get<{
      items: Array<{
        id: number;
        user_id: number;
        username: string | null;
        model_name: string;
        provider_name?: string | null;
        provider_kind?: string | null;
        prompt: string;
        status: string;
        result_urls: string[] | null;
        error: string | null;
        elapsed_seconds: number | null;
        created_at: string;
      }>;
      total: number;
      page: number;
      limit: number;
    }>('/admin/resources/ai-tasks', { params }),

  getAiTaskDetail: (taskId: number) =>
    api.get<{
      id: number;
      user_id: number;
      username: string | null;
      model_name: string;
      provider_name?: string | null;
      provider_kind?: string | null;
      prompt: string;
      negative_prompt?: string | null;
      params: Record<string, unknown>;
      status: string;
      result_urls: string[];
      error: string | null;
      upstream_debug?: Record<string, unknown> | null;
      elapsed_seconds: number | null;
      created_at: string | null;
      finished_at: string | null;
      logs: Array<{
        timestamp: string | null;
        finished_at?: string | null;
        level: string;
        title: string;
        message: string;
        payload?: Record<string, unknown> | null;
      }>;
    }>(`/admin/resources/ai-tasks/${taskId}`),

  failAiTask: (taskId: number, reason?: string) =>
    api.post(`/admin/resources/ai-tasks/${taskId}/fail`, { reason }),

  getWorkflowTasks: (params: { page?: number; limit?: number; username?: string; status?: string; workflow_id?: number }) =>
    api.get<{ items: any[]; total: number; page: number; limit: number }>('/admin/resources/workflow-tasks', { params }),

  getWorkflowTaskDetail: (taskId: number) =>
    api.get<{
      id: number;
      user_id: number;
      username: string | null;
      workflow_id: number;
      workflow_name: string;
      task_id?: string | null;
      status: string;
      inputs: Record<string, unknown>;
      outputs: Record<string, unknown>;
      error: string | null;
      progress?: string | null;
      elapsed_ms: number | null;
      created_at: string | null;
      finished_at: string | null;
      logs: Array<{
        id: number;
        timestamp: string | null;
        finished_at?: string | null;
        level: string;
        title: string;
        message: string;
        status: string;
        task_id?: string | null;
        elapsed_ms?: number | null;
        payload?: Record<string, unknown> | null;
      }>;
    }>(`/admin/resources/workflow-tasks/${taskId}`),

  deleteWorkflowTask: (taskId: number) =>
    api.delete(`/admin/resources/workflow-tasks/${taskId}`),

  getProjects: (params: { page?: number; limit?: number; username?: string; status?: string }) =>
    api.get<{ items: any[]; total: number; page: number; limit: number }>('/admin/resources/projects', { params }),

  deleteProject: (projectId: number) =>
    api.delete(`/admin/resources/projects/${projectId}`),
  batchDeleteProjects: (project_ids: number[]) =>
    api.post<{ deleted: number }>('/admin/resources/projects/batch-delete', { project_ids }),

  getAdminCopywritings: (page = 1, limit = 20, username?: string, category?: string, search?: string) =>
    api.get<{ items: Array<{ id: number; title: string; content: string; tags: string[]; category: string; created_by: number | null; created_at: string }>; total: number; page: number; limit: number }>('/admin/resources/copywritings', { params: { page, limit, username, category, search } }),

  deleteAdminCopywriting: (id: number) =>
    api.delete(`/admin/resources/copywritings/${id}`),

  getScrapeReviewTasks: (page = 1, limit = 20, status?: string) =>
    api.get<{
      items: Array<{
        id: number;
        name: string;
        source: string;
        status: string;
        max_items: number;
        candidate_count: number;
        pending_count: number;
        approved_count: number;
        rejected_count: number;
        needs_second_review_count: number;
        saved_path: string | null;
        last_error: string | null;
        source_config: Record<string, unknown>;
        run_meta: Record<string, unknown>;
        run_summary: {
          requested_max_items: number;
          actual_count: number;
          saved_count: number;
          keyword_mode: string;
          configured_keywords: string[];
          configured_keyword_count: number;
          history_dedupe_days: number;
          search_returned_count: number;
          considered_count: number;
          duplicate_filtered_count: number;
          history_filtered_count: number;
          shortfall_count: number;
          search_shortage_count: number;
        };
        reviewers: Array<{ id: number; username: string }>;
        created_at: string;
        started_at: string | null;
        finished_at: string | null;
      }>;
      total: number;
      page: number;
      limit: number;
    }>('/admin/copy-review/tasks', { params: { page, limit, status } }),

  createScrapeReviewTask: (data: {
    name: string;
    source?: string;
    source_config: Record<string, unknown>;
    max_items: number;
    reviewer_ids?: number[];
  }) => api.post('/admin/copy-review/tasks', data),

  assignScrapeReviewTasks: (data: { task_ids: number[]; reviewer_ids: number[] }) =>
    api.post<{ assigned_task_count: number; task_ids: number[]; reviewer_ids: number[] }>('/admin/copy-review/tasks/assign', data),

  getScrapeReviewTaskDetail: (id: number) =>
    api.get<{
      id: number;
      name: string;
      source: string;
      status: string;
      source_config: Record<string, unknown>;
      max_items: number;
      candidate_count: number;
      pending_count: number;
      approved_count: number;
      rejected_count: number;
      needs_second_review_count: number;
      saved_path: string | null;
      last_error: string | null;
      run_summary: {
        requested_max_items: number;
        actual_count: number;
        saved_count: number;
        keyword_mode: string;
        configured_keywords: string[];
        configured_keyword_count: number;
        history_dedupe_days: number;
        search_returned_count: number;
        considered_count: number;
        duplicate_filtered_count: number;
        history_filtered_count: number;
        shortfall_count: number;
        search_shortage_count: number;
      };
      run_meta: Record<string, unknown>;
      reviewers: Array<{ id: number; username: string }>;
      created_at: string;
      started_at: string | null;
      finished_at: string | null;
    }>(`/admin/copy-review/tasks/${id}`),

  getScrapeReviewCandidates: (taskId: number, status?: string) =>
    api.get<{
      items: Array<{
        id: number;
        external_id: string;
        title: string;
        content: string;
        author: string | null;
        source: string;
        source_keyword: string | null;
        post_url: string | null;
        publish_date: string | null;
        copy_type: string | null;
        brand: string | null;
        likes: number;
        comments: number;
        collects: number;
        shares: number;
        views: number;
        review_status: string;
        reviewer_id: number | null;
        reviewer_name: string | null;
        review_note: string | null;
        reviewed_at: string | null;
        copywriting_id: number | null;
      }>;
    }>(`/admin/copy-review/tasks/${taskId}/candidates`, { params: { status } }),

  runScrapeReviewTask: (id: number) =>
    api.post<{ created: number; total: number; saved_path?: string | null }>(`/admin/copy-review/tasks/${id}/run`),

  // Admin workflows
  getAdminWorkflows: (page = 1, limit = 20, search?: string, created_by?: number) =>
    api.get<{ items: Array<{ id: number; name: string; app_type: string; description: string | null; enabled: boolean; inputs_schema: Record<string, unknown>; base_url: string; api_key_prefix: string; created_by: number | null; created_by_name: string | null; created_at: string }>; total: number; page: number; limit: number }>('/admin/workflows', { params: { page, limit, search, created_by } }),

  createAdminWorkflow: (data: { app_name: string; app_type: string; api_key: string; base_url?: string; description?: string; inputs_schema?: Record<string, unknown> }) =>
    api.post('/admin/workflows', data),

  updateAdminWorkflow: (id: number, data: { app_name?: string; app_type?: string; api_key?: string; base_url?: string; description?: string; inputs_schema?: Record<string, unknown>; is_enabled?: boolean }) =>
    api.put(`/admin/workflows/${id}`, data),

  deleteAdminWorkflow: (id: number) =>
    api.delete(`/admin/workflows/${id}`),

  fetchAdminWorkflowParams: (base_url: string, api_key: string) =>
    api.post('/admin/workflows/fetch-params', { base_url, api_key }),

  runAdminWorkflow: (id: number, inputs: Record<string, unknown>, response_mode = 'blocking') =>
    api.post(`/admin/workflows/${id}/run`, { inputs, response_mode }),

  createAdminDifyTask: (id: number, inputs: Record<string, unknown>, user_id?: number) =>
    api.post(`/admin/workflows/${id}/tasks`, { inputs, user_id }),

  // Admin dify tasks
  getAdminDifyTasks: (page = 1, limit = 20, username?: string, workflow_id?: number, status?: string) =>
    api.get<{ items: Array<{ id: number; workflow_id: number; workflow_name?: string; user_id: number; user_name: string | null; status: string; inputs: Record<string, unknown>; outputs: Record<string, unknown>; error: string | null; progress: string; elapsed_ms: number | null; viewed: number; created_at: string; finished_at: string | null }>; total: number; page: number; limit: number }>('/admin/workflows/tasks', { params: { page, limit, username, workflow_id, status } }),

  deleteAdminDifyTask: (id: number) =>
    api.delete(`/admin/workflows/tasks/${id}`),

  failAdminDifyTask: (id: number, reason?: string) =>
    api.post(`/admin/workflows/tasks/${id}/fail`, { reason }),

  markAdminTaskViewed: (id: number) =>
    api.patch(`/admin/workflows/tasks/${id}/view`),

  // Admin run logs
  getAdminRunLogs: (page = 1, limit = 20, username?: string, workflow_id?: number, status?: string) =>
    api.get<{ items: Array<{ id: number; workflow_id: number; user_id: number; user_name: string | null; status: string; inputs: Record<string, unknown>; outputs: Record<string, unknown>; error: string | null; task_id: string; started_at: string; finished_at: string | null; elapsed_ms: number | null }>; total: number; page: number; limit: number }>('/admin/workflows/logs', { params: { page, limit, username, workflow_id, status } }),

  // Admin prompts
  getPromptCategories: (page = 1, limit = 100, search?: string) =>
    api.get<{ items: Array<{ id: number; name: string; start_intro: string | null; sort_order: number; example_count: number; created_at: string }>; total: number; page: number; limit: number }>('/admin/prompts/categories', { params: { page, limit, search } }),
  getPromptOverview: () =>
    api.get<{
      total_categories: number;
      total_examples: number;
      public_examples: number;
      private_examples: number;
      with_image_examples: number;
      pending_reports: number;
    }>('/admin/prompts/overview'),

  createPromptCategory: (data: { name: string; start_intro?: string; sort_order?: number }) =>
    api.post('/admin/prompts/categories', data),

  updatePromptCategory: (id: number, data: { name?: string; start_intro?: string; sort_order?: number }) =>
    api.put(`/admin/prompts/categories/${id}`, data),

  deletePromptCategory: (id: number) =>
    api.delete(`/admin/prompts/categories/${id}`),

  getPromptExamples: (page = 1, limit = 50, category_id?: number, param_type?: string, search?: string) =>
    api.get<{ items: Array<{ id: number; category_id: number; category_name: string; param_type: string; image_num: number; image_url: string | null; name: string | null; chinese_example: string; english_example: string; ul_list: string[]; sort_order: number; is_public: boolean; created_by: number | null; created_by_name: string | null; created_at: string }>; total: number; page: number; limit: number }>('/admin/prompts/examples', { params: { page, limit, category_id, param_type, search } }),

  createPromptExample: (data: { category_id: number; param_type: string; chinese_example: string; english_example: string; image_url?: string; name?: string; ul_list?: string[]; sort_order?: number; is_public?: boolean }) =>
    api.post('/admin/prompts/examples', data),

  updatePromptExample: (id: number, data: { param_type?: string; chinese_example?: string; english_example?: string; image_url?: string; name?: string; ul_list?: string[]; sort_order?: number; category_id?: number; is_public?: boolean }) =>
    api.put(`/admin/prompts/examples/${id}`, data),

  deletePromptExample: (id: number) =>
    api.delete(`/admin/prompts/examples/${id}`),

  cleanupPromptExamplesNoImage: () =>
    api.post<{ deleted_count: number; sample_ids: number[]; executed_at: string }>('/admin/prompts/cleanup-no-image'),

  importPrompts: (data: Record<string, unknown>) =>
    api.post('/admin/prompts/import', data),

  uploadPromptImage: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<{ url: string }>('/prompts/upload-image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  getPromptReports: (page = 1, limit = 20, status?: string) =>
    api.get<{ items: Array<{ id: number; prompt_id: number; prompt_name: string; prompt_text: string; reason: string; details: string | null; status: string; reporter_id: number; reporter_name: string; created_at: string; resolved_at: string | null; resolution_note: string | null }>; total: number; page: number; limit: number }>('/admin/prompts/reports', { params: { page, limit, status } }),

  resolvePromptReport: (id: number, data: { action: 'hide' | 'reject'; note?: string }) =>
    api.post(`/admin/prompts/reports/${id}/resolve`, data),

  batchResolvePromptReports: (data: { report_ids: number[]; action: 'hide' | 'reject'; note?: string }) =>
    api.post('/admin/prompts/reports/batch-resolve', data),

  getPromptReportStats: () =>
    api.get<{ total: number; pending: number; resolved: number; rejected: number; by_reason: Array<{ reason: string; count: number }> }>('/admin/prompts/reports/stats'),

  getPromptAuditLogs: (page = 1, limit = 20, action?: string, operator_name?: string) =>
    api.get<{ items: Array<{ id: number; prompt_id: number; prompt_name: string; action: string; operator_id: number | null; operator_name: string | null; details: string | null; created_at: string }>; total: number; page: number; limit: number }>('/admin/prompts/audit-logs', { params: { page, limit, action, operator_name } }),

  // Admin car models
  getCarModelsAll: () =>
    api.get<Record<string, Record<string, Array<{ label: string; url: string }>>>>('/admin/car-models/all'),

  exportCarModelsJson: () =>
    api.get<Blob>('/admin/car-models/export', {
      responseType: 'blob',
      headers: { Accept: 'application/json' },
    }),

  updateCarModelImages: (data: { brand: string; model: string; images: Array<{ label: string; url: string }> }) =>
    api.put('/admin/car-models/model', data),

  deleteCarModel: (data: { brand: string; model: string }) =>
    api.delete('/admin/car-models/model', { data }),

  deleteCarModelImage: (data: { brand: string; model: string; label: string; url: string }) =>
    api.delete('/admin/car-models/model/image', { data }),

  replaceCarModelsJson: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<{ brands: number; models: number; backup_file: string }>('/admin/car-models/replace', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  importCarModelFolder: (data: {
    brand: string;
    model: string;
    already_cleaned: boolean;
    clean_method: 'ocr' | 'gptimage2';
    overwrite: boolean;
    files: File[];
  }) => {
    const formData = new FormData();
    formData.append('brand', data.brand);
    formData.append('model', data.model);
    formData.append('already_cleaned', String(data.already_cleaned));
    formData.append('clean_method', data.clean_method);
    formData.append('overwrite', String(data.overwrite));
    data.files.forEach((file) => formData.append('files', file));
    return api.post<{
      brand: string;
      model: string;
      already_cleaned: boolean;
      clean_method: string | null;
      overwrite: boolean;
      imported_angles: string[];
      missing_angles: string[];
      warnings: string[];
      images: Array<{ label: string; url: string }>;
      backup_file: string;
    }>('/admin/car-models/import-folder', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  // Admin AI image providers
  getAiImageProviders: (model_name = 'gptimage2') =>
    api.get<Array<{
      id: number;
      name: string;
      model_name: string;
      provider_kind: string;
      provider_model: string;
      endpoint_url: string;
      api_key_prefix: string;
      is_enabled: boolean;
      is_default: boolean;
      priority: number;
      weight: number;
      supports_text_input: boolean;
      supports_image_input: boolean;
      config: Record<string, unknown>;
      last_health_status: string;
      last_health_error: string | null;
      last_checked_at: string | null;
      last_used_at: string | null;
      success_count: number;
      failure_count: number;
      avg_latency_ms: number | null;
      current_running: number;
      max_concurrent: number;
      created_by: number | null;
      created_at: string | null;
      updated_at: string | null;
    }>>('/admin/ai-image/providers', { params: { model_name } }),

  createAiImageProvider: (data: {
    name: string;
    model_name?: string;
    provider_kind?: string;
    provider_model?: string;
    endpoint_url: string;
    api_key: string;
    is_enabled?: boolean;
    is_default?: boolean;
    priority?: number;
    weight?: number;
    supports_text_input?: boolean;
    supports_image_input?: boolean;
    config?: Record<string, unknown>;
  }) => api.post('/admin/ai-image/providers', data),

  updateAiImageProvider: (id: number, data: {
    name?: string;
    model_name?: string;
    provider_kind?: string;
    provider_model?: string;
    endpoint_url?: string;
    api_key?: string;
    is_enabled?: boolean;
    is_default?: boolean;
    priority?: number;
    weight?: number;
    supports_text_input?: boolean;
    supports_image_input?: boolean;
    config?: Record<string, unknown>;
  }) => api.put(`/admin/ai-image/providers/${id}`, data),

  deleteAiImageProvider: (id: number) =>
    api.delete(`/admin/ai-image/providers/${id}`),

  toggleAiImageProvider: (id: number, is_enabled: boolean) =>
    api.post(`/admin/ai-image/providers/${id}/enable`, { is_enabled }),

  setDefaultAiImageProvider: (id: number) =>
    api.post(`/admin/ai-image/providers/${id}/default`),

  checkAiImageProvider: (id: number) =>
    api.post(`/admin/ai-image/providers/${id}/health-check`),

  testAiImageProvider: (id: number, data: {
    prompt: string;
    width?: number;
    height?: number;
    quality?: string;
    count?: number;
  }) =>
    api.post<{
      id: number;
      task_id: string;
      status: string;
      image_urls: string[];
      error: string | null;
      elapsed_seconds: number | null;
      provider: {
        id: number;
        name: string;
        provider_kind: string;
        provider_model: string;
      };
    }>(`/admin/ai-image/providers/${id}/test`, data),

  getAiImageProviderTestTask: (taskId: string) =>
    api.get<{
      id: number;
      task_id: string;
      status: string;
      image_urls: string[];
      error: string | null;
      elapsed_seconds: number | null;
      provider: {
        id: number;
        name: string;
        provider_kind: string;
        provider_model: string;
      };
    }>(`/admin/ai-image/providers/test-tasks/${taskId}`),

  checkAllAiImageProviders: (model_name = 'gptimage2') =>
    api.post('/admin/ai-image/providers/health-check', null, { params: { model_name } }),

  getXhsAdAccountAssignments: () =>
    api.get<Array<{
      account_id: string;
      account_name: string;
      token_status?: string | null;
      user_id?: number | null;
      buyer_username?: string | null;
      buyer_display_name?: string | null;
      buyer_email?: string | null;
      xhs_account_id?: string | null;
      xhs_account_name?: string | null;
      xhs_owner_name?: string | null;
    }>>('/admin/xhs/ad-account-assignments'),

  createXhsAdAccount: (data: { account_id: string; account_name: string }) =>
    api.post('/admin/xhs/ad-accounts', data),

  updateXhsAdAccount: (data: { account_id: string; new_account_id?: string | null; account_name: string }) =>
    api.patch('/admin/xhs/ad-accounts', data),

  deleteXhsAdAccount: (accountId: string) =>
    api.delete(`/admin/xhs/ad-accounts/${encodeURIComponent(accountId)}`),

  assignXhsAdAccountBuyer: (accountId: string, userId: number) =>
    api.post('/admin/xhs/ad-account-assign', { account_id: accountId, user_id: userId }),

  unassignXhsAdAccountBuyer: (accountId: string) =>
    api.post('/admin/xhs/ad-account-unassign', { account_id: accountId }),

  updateXhsAdAccountProfessionalMapping: (data: {
    account_id: string;
    xhs_account_id?: string | null;
    xhs_account_name?: string | null;
    xhs_owner_name?: string | null;
  }) =>
    api.post('/admin/xhs/ad-account-professional-mapping', data),
};
