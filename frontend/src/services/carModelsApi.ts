import api from './api';

export interface CarImageData {
  brand: string;
  model: string;
  images: { label: string; url: string; model?: string }[];
}

export const carModelsApi = {
  getBrands: () =>
    api.get<string[]>('/car-models/brands'),

  getModels: (brand?: string) =>
    api.get<Record<string, string[]>>('/car-models/models', brand ? { params: { brand } } : undefined),

  getCarImages: (brand: string, model?: string) =>
    api.get<CarImageData>('/car-models/images', { params: { brand, model } }),

  getAllData: () =>
    api.get<Record<string, Record<string, { label: string; url: string }[]>>>('/car-models/all'),
};
