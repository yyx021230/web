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

/** AI 生图元数据 */
export interface AIMeta {
  prompt: string;
  ref_images?: string[];  // 参考图 URL 列表
  model?: string;
  size?: string;
  style?: string;
  count?: number;
  quality?: string;
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
  /** AI 生图元数据（type === 'template' 时有值） */
  ai_meta?: AIMeta | null;
}

export const editorApi = {
  // ===== Projects =====
  getProjects: (page = 1, limit = 20) =>
    api.get<ProjectListResponse>('/projects', { params: { page, limit } }),

  getProject: (id: number) =>
    api.get<ProjectDetail>(`/projects/${id}`),

  createProject: (data: { name: string; fabric_json?: string; thumbnail?: string; status?: string }) =>
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
  getMaterials: (category?: string, page = 1, limit = 20, owner: boolean = false, excludeCategory?: string) => {
    const params: Record<string, unknown> = { page, limit };
    if (category) params.category = category;
    if (owner) params.owner = true;
    if (excludeCategory) params.exclude_category = excludeCategory;
    return api.get<{ items: Material[]; total: number }>('/materials', { params });
  },

  uploadMaterial: (file: File, target?: 'drafts' | 'templates') => {
    const formData = new FormData();
    formData.append('file', file);
    if (target) formData.append('target', target);
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
    tags?: string[];
  }) =>
    api.put(`/materials/${id}`, data),

  /** 获取单个素材详情（用于加载设计稿） */
  getMaterial: (id: number) =>
    api.get<Material>(`/materials/${id}`),

  /** 批量删除所有素材（清空草稿箱） */
  deleteAllMaterials: () =>
    api.delete('/materials/all'),

  /** 保存 AI 生图结果到模版库 */
  saveAITemplate: (data: {
    name: string;
    url: string;
    ai_meta?: AIMeta;
    width?: number;
    height?: number;
    tags?: string[];
  }) =>
    api.post('/materials/template', data),

  /** 下载远程图片到本地（用于过期链接重下载） */
  downloadRemoteImage: (id: number, url?: string) =>
    api.post(`/materials/${id}/download`, { url }),

  /** 获取当前用户存储使用情况 */
  getStorageUsage: () =>
    api.get<{
      used_bytes: number;
      used_mb: number;
      file_count: number;
      total_items: number;
      limit_bytes: number;
      limit_mb: number;
      percent: number;
    }>('/materials/storage-usage'),

  /** 重命名模版文件夹 */
  renameFolder: (oldName: string, newName: string) =>
    api.put(`/materials/folders/${encodeURIComponent(oldName)}`, { new_name: newName }),

  /** 删除模版文件夹（图片移至未分类） */
  deleteFolder: (name: string) =>
    api.delete(`/materials/folders/${encodeURIComponent(name)}`),
};
