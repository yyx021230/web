export type AppType = 'workflow' | 'chat' | 'completion';

export interface DifyInstance {
  id: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  isDefault: boolean;
}

export interface WorkflowConfig {
  id: string;
  instanceId: string;
  appId: string;
  name: string;
  description: string;
  appType: AppType;
  inputsSchema: Record<string, InputField>;
  enabled: boolean;
  lastRunAt?: string;
}

export interface InputField {
  type: 'text' | 'paragraph' | 'number' | 'file' | 'select';
  label: string;
  required: boolean;
  options?: string[];
  placeholder?: string;
}

export interface WorkflowRun {
  id: string;
  workflowId: string;
  workflowName: string;
  inputs: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  status: 'running' | 'succeeded' | 'failed' | 'stopped';
  error?: string;
  startedAt: string;
  finishedAt?: string;
  elapsedMs?: number;
}

export interface SSEWorkflowEvent {
  event:
    | 'workflow_started'
    | 'node_started'
    | 'node_finished'
    | 'workflow_finished'
    | 'message';
  task_id: string;
  data: Record<string, unknown>;
}
