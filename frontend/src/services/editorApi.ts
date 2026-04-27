import api from './api';

export interface Project {
  id: number;
  name: string;
  thumbnail: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends Project {
  fabric_json: string | null;
}

export interface ProjectListResponse {
  items: Project[];
  total: number;
  page: number;
  limit: number;
}

export interface Template {
  id: number;
  name: string;
  description: string | null;
  thumbnail: string | null;
  fabric_json: string | null;
  category: string;
  tags: string[];
}

export interface Material {
  id: number;
  name: string;
  type: string;
  url: string | null;
  width: number;
  height: number;
  thumbnail: string | null;
  category: string | null;
  tags: string[];
  created_at: string;
  /** 设计稿的完整 Fabric JSON（type === 'design' 时有值） */
  design_json?: Record<string, unknown> | null;
}

export const editorApi = {
  // ===== Projects =====
  getProjects: (page = 1, limit = 20) =>
    api.get<ProjectListResponse>('/projects', { params: { page, limit } }),

  getProject: (id: number) =>
    api.get<ProjectDetail>(`/projects/${id}`),

  createProject: (data: { name: string; fabric_json?: string; thumbnail?: string }) =>
    api.post('/projects', data),

  updateProject: (id: number, data: { name?: string; fabric_json?: string; thumbnail?: string; status?: string }) =>
    api.put(`/projects/${id}`, data),

  deleteProject: (id: number) =>
    api.delete(`/projects/${id}`),

  // ===== Templates =====
  getTemplates: (category?: string, page = 1, limit = 20) => {
    const params: Record<string, unknown> = { page, limit };
    if (category) params.category = category;
    return api.get<{ items: Template[]; total: number }>('/templates', { params });
  },

  getTemplate: (id: number) =>
    api.get<Template>(`/templates/${id}`),

  createTemplate: (data: { name: string; fabric_json: string; category: string }) =>
    api.post('/templates', data),

  updateTemplate: (id: number, data: { name?: string; fabric_json?: string; category?: string }) =>
    api.put(`/templates/${id}`, data),

  deleteTemplate: (id: number) =>
    api.delete(`/templates/${id}`),

  // ===== Materials =====
  getMaterials: (category?: string, page = 1, limit = 20) => {
    const params: Record<string, unknown> = { page, limit };
    if (category) params.category = category;
    return api.get<{ items: Material[]; total: number }>('/materials', { params });
  },

  uploadMaterial: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/materials/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  deleteMaterial: (id: number) =>
    api.delete(`/materials/${id}`),

  /** 保存编辑器设计稿到草稿箱 */
  saveDesign: (data: {
    name: string;
    design_json: unknown;
    thumbnail?: string;
    width?: number;
    height?: number;
  }) =>
    api.post('/materials/design', data),

  /** 更新已有的设计稿 */
  updateMaterial: (id: number, data: {
    name?: string;
    design_json?: unknown;
    thumbnail?: string;
    width?: number;
    height?: number;
  }) =>
    api.put(`/materials/${id}`, data),

  /** 获取单个素材详情（用于加载设计稿） */
  getMaterial: (id: number) =>
    api.get<Material>(`/materials/${id}`),

  /** 批量删除所有素材（清空草稿箱） */
  deleteAllMaterials: () =>
    api.delete('/materials/all'),
};
