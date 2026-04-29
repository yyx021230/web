import api from './api';

export const adminApi = {
  // Dashboard stats
  getOverview: () =>
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
    }>('/admin/stats/overview'),

  getAiTrend: (days = 7) =>
    api.get<{
      ai_daily: Array<{ date: string; total: number; by_model: Record<string, number> }>;
      ai_models: Array<{ model: string; total: number; success: number; failed: number; avg_seconds: number }>;
      wf_daily: Array<{ date: string; succeeded: number; failed: number; running: number; stopped: number }>;
    }>('/admin/stats/ai-trend', { params: { days } }),

  getActiveTasks: () =>
    api.get<Array<{ id: number; type: string; username: string; model: string; status?: string; created_at: string }>>('/admin/stats/active-tasks'),

  getRankings: () =>
    api.get('/admin/stats/rankings'),

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
        series: { image2: number[]; seedream: number[] };
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

  // Users
  getUsers: (page = 1, limit = 20) =>
    api.get<{ items: Array<{ id: number; username: string; email: string; avatar: string | null; is_active: boolean; role: string; created_at: string }>; total: number; page: number; limit: number }>('/admin/users', { params: { page, limit } }),

  updateUserRole: (userId: number, role: string) =>
    api.patch(`/admin/users/${userId}/role`, { role }),

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

  createUser: (data: { username: string; email: string; password: string; role?: string }) =>
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
    api.get<{ user: { id: number; username: string; email: string; avatar: string | null; role: string; is_active: boolean; created_at: string }; stats: { project_count: number; material_count: number; ai_task_count: number; ai_task_24h: number; workflow_count: number; dify_task_count: number; dify_run_log_count: number; copywriting_count: number }; recent_ai_tasks: Array<{ id: number; model_name: string; prompt: string; status: string; created_at: string }>; recent_dify_tasks: Array<{ id: number; workflow_id: number; status: string; created_at: string }> }>(`/admin/users/${userId}/detail`),

  // Resources (ai-tasks, copywritings)
  getAiTasks: (params: { page?: number; limit?: number; username?: string; status?: string; model_name?: string }) =>
    api.get<{ items: any[]; total: number; page: number; limit: number }>('/admin/resources/ai-tasks', { params }),

  getWorkflowTasks: (params: { page?: number; limit?: number; username?: string; status?: string; workflow_id?: number }) =>
    api.get<{ items: any[]; total: number; page: number; limit: number }>('/admin/resources/workflow-tasks', { params }),

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
    api.get<{ items: Array<{ id: number; workflow_id: number; user_id: number; user_name: string | null; status: string; inputs: Record<string, unknown>; outputs: Record<string, unknown>; error: string | null; progress: string; elapsed_ms: number | null; viewed: number; created_at: string; finished_at: string | null }>; total: number; page: number; limit: number }>('/admin/workflows/tasks', { params: { page, limit, username, workflow_id, status } }),

  deleteAdminDifyTask: (id: number) =>
    api.delete(`/admin/workflows/tasks/${id}`),

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
};
