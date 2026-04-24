import { create } from 'zustand';
import type { fabric as FabricType } from 'fabric';

interface EditorState {
  canvas: FabricType.Canvas | null;
  activeTool: string;
  selectedObjects: FabricType.Object[];
  zoom: number;
  history: { undo: () => void; redo: () => void };

  // Actions
  initCanvas: (canvasEl: HTMLCanvasElement) => void;
  setActiveTool: (tool: string) => void;
  setZoom: (zoom: number) => void;
  undo: () => void;
  redo: () => void;
  addImageToCanvas: (imageUrl: string, x?: number, y?: number) => void;
  exportCanvas: (format: 'png' | 'jpeg' | 'svg') => string;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  canvas: null,
  activeTool: 'select',
  selectedObjects: [],
  zoom: 1,
  history: {
    undo: () => {},
    redo: () => {},
  },

  initCanvas: (_canvasEl: HTMLCanvasElement) => {
    // Initialize Fabric.js canvas
    set({ canvas: null as unknown as FabricType.Canvas });
  },

  setActiveTool: (tool: string) => set({ activeTool: tool }),

  setZoom: (zoom: number) => set({ zoom }),

  undo: () => {
    get().history.undo();
  },

  redo: () => {
    get().history.redo();
  },

  addImageToCanvas: (_imageUrl: string, _x = 100, _y = 100) => {
    const { canvas } = get();
    if (!canvas) return;
    // Fabric.js image loading
  },

  exportCanvas: (_format: 'png' | 'jpeg' | 'svg') => {
    const { canvas } = get();
    if (!canvas) return '';
    return '';
  },
}));
