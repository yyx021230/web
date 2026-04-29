import api from './api';

export interface DifyWorkflowRunParams {
  inputs: Record<string, unknown>;
  files?: Array<{ type: string; transfer_method: string; url?: string }>;
  response_mode?: 'blocking' | 'streaming';
}

export interface DifyWorkflowLog {
  id: string;
  workflow_id: string;
  status: 'succeeded' | 'failed' | 'stopped';
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  error?: string;
  started_at: string;
  finished_at?: string;
  elapsed_ms: number;
}

export const difyApi = {
  // Run workflow (async - background task)
  runTask: (workflowId: string, params: { inputs: Record<string, string> }) =>
    api.post(`/workflows/${workflowId}/tasks`, params),

  // Get task list
  getTasks: () =>
    api.get('/workflows/tasks'),

  // Run workflow (sync)
  runWorkflow: (workflowId: string, params: DifyWorkflowRunParams) =>
    api.post(`/workflows/${workflowId}/run`, params),

  // Run workflow with SSE streaming
  runWorkflowStream: (workflowId: string, params: DifyWorkflowRunParams) =>
    api.post(`/workflows/${workflowId}/run`, { ...params, response_mode: 'streaming' }),

  // Chat
  chat: (appId: string, query: string, conversationId?: string) =>
    api.post(`/workflows/${appId}/chat`, { query, conversation_id: conversationId }),

  // Stop task
  stopTask: (taskId: string | number) =>
    api.post(`/workflows/tasks/${taskId}/stop`),

  // Delete task
  deleteTask: (taskId: string) =>
    api.delete(`/workflows/tasks/${taskId}`),

  // Mark task as viewed
  markTaskViewed: (taskId: string) =>
    api.patch(`/workflows/tasks/${taskId}/view`),

  // Get logs (all workflows)
  getAllLogs: (page = 1, limit = 20) =>
    api.get<{ items: DifyWorkflowLog[]; total: number }>('/workflows/logs', {
      params: { page, limit },
    }),

  // Get logs for specific workflow
  getLogs: (workflowId: string, page = 1, limit = 20) =>
    api.get<{ items: DifyWorkflowLog[]; total: number }>(`/workflows/${workflowId}/logs`, {
      params: { page, limit },
    }),

  // List workflows
  listWorkflows: () =>
    api.get('/workflows'),

  // Create workflow config
  createWorkflow: (data: {
    api_key: string;
    base_url?: string;
    app_name: string;
    app_type: string;
    description?: string;
    inputs_schema?: Record<string, any>;
  }) => api.post('/workflows', data),

  // Update workflow
  updateWorkflow: (workflowId: string, data: {
    api_key?: string;
    app_name?: string;
    app_type?: string;
    description?: string;
    inputs_schema?: Record<string, any>;
    base_url?: string;
    is_enabled?: boolean;
  }) => api.put(`/workflows/${workflowId}`, data),

  // Delete workflow
  deleteWorkflow: (workflowId: string) =>
    api.delete(`/workflows/${workflowId}`),

  // Fetch params from Dify
  fetchParams: (data: { base_url?: string; api_key: string }) =>
    api.post('/workflows/fetch-params', data),

  // Upload file to Dify
  uploadFile: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/workflows/files/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};
