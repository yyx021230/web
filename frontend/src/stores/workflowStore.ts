import { create } from 'zustand';

export interface WorkflowConfig {
  id: string;
  name: string;
  description: string;
  difyInstanceUrl: string;
  apiKey: string;
  appId: string;
  appType: 'workflow' | 'chat' | 'completion';
  inputsSchema: Record<string, unknown>;
  enabled: boolean;
}

export interface WorkflowRun {
  id: string;
  workflowId: string;
  inputs: Record<string, unknown>;
  outputs?: Record<string, unknown>;
  status: 'running' | 'succeeded' | 'failed' | 'stopped';
  error?: string;
  startedAt: Date;
  finishedAt?: Date;
  elapsedMs?: number;
}

interface WorkflowState {
  workflows: WorkflowConfig[];
  currentRun: WorkflowRun | null;
  runLogs: WorkflowRun[];
  isRunning: boolean;

  // Actions
  setWorkflows: (workflows: WorkflowConfig[]) => void;
  runWorkflow: (workflowId: string, inputs: Record<string, unknown>) => Promise<void>;
  stopWorkflow: (taskId: string) => Promise<void>;
  fetchRunLogs: (workflowId?: string) => Promise<void>;
}

export const useWorkflowStore = create<WorkflowState>((set) => ({
  workflows: [],
  currentRun: null,
  runLogs: [],
  isRunning: false,

  setWorkflows: (workflows: WorkflowConfig[]) => set({ workflows }),

  runWorkflow: async (_workflowId: string, _inputs: Record<string, unknown>) => {
    set({ isRunning: true });
    // TODO: Call Dify API via backend
    set({ isRunning: false });
  },

  stopWorkflow: async (_taskId: string) => {
    // TODO: Call stop API
  },

  fetchRunLogs: async (_workflowId?: string) => {
    // TODO: Fetch logs from API
  },
}));
