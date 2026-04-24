export type ToolType =
  | 'select'
  | 'rect'
  | 'circle'
  | 'triangle'
  | 'text'
  | 'image'
  | 'draw'
  | 'eraser';

export interface CanvasConfig {
  width: number;
  height: number;
  backgroundColor: string;
  zoom: number;
}

export interface EditorExportOptions {
  format: 'png' | 'jpeg' | 'svg' | 'json';
  multiplier?: number;
  quality?: number;
}
