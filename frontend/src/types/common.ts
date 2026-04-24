export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
}

export interface FileUpload {
  id: string;
  name: string;
  url: string;
  mimeType: string;
  size: number;
  createdAt: string;
}
