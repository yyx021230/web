'use client';

import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from 'react';

interface EditorContextValue {
  zoom: number;
  setZoom: (z: number | ((prev: number) => number)) => void;
  canUndo: boolean;
  canRedo: boolean;
  triggerUndo: () => void;
  triggerRedo: () => void;
  triggerSave: () => void;
  triggerExport: () => void;
  projectName: string;
  setProjectName: (n: string) => void;
  hasUnsavedChanges: boolean;
  setHasUnsavedChanges: (b: boolean) => void;
  projectId: number | null;
  setProjectId: (id: number | null) => void;
  isSaving: boolean;
  setIsSaving: (b: boolean) => void;
  /* Internal setters for editor page to register its own callbacks */
  _setUndoFn: (fn: () => void) => void;
  _setRedoFn: (fn: () => void) => void;
  _setSaveFn: (fn: () => void) => void;
  _setExportFn: (fn: () => void) => void;
  _setPushHistoryFn: (fn: (...args: unknown[]) => void) => void;
  _historyRef: React.MutableRefObject<{ stack: unknown[]; idx: number }>;
  _setCanUndo: React.Dispatch<React.SetStateAction<boolean>>;
  _setCanRedo: React.Dispatch<React.SetStateAction<boolean>>;
}

const EditorContext = createContext<EditorContextValue | null>(null);

export function EditorProvider({ children }: { children: ReactNode }) {
  const [zoom, setZoom] = useState(100);
  const [projectName, setProjectName] = useState('未命名设计');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [projectId, setProjectId] = useState<number | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  const historyRef = useRef<{ stack: unknown[]; idx: number }>({ stack: [], idx: 0 });
  const undoFnRef = useRef<() => void>(() => {});
  const redoFnRef = useRef<() => void>(() => {});
  const saveFnRef = useRef<() => void>(() => {});
  const exportFnRef = useRef<() => void>(() => {});

  const value: EditorContextValue = {
    zoom, setZoom,
    canUndo, canRedo,
    triggerUndo: useCallback(() => undoFnRef.current(), []),
    triggerRedo: useCallback(() => redoFnRef.current(), []),
    triggerSave: useCallback(() => saveFnRef.current(), []),
    triggerExport: useCallback(() => exportFnRef.current(), []),
    projectName, setProjectName,
    hasUnsavedChanges, setHasUnsavedChanges,
    projectId, setProjectId,
    isSaving, setIsSaving,
    _setUndoFn: (fn) => { undoFnRef.current = fn; },
    _setRedoFn: (fn) => { redoFnRef.current = fn; },
    _setSaveFn: (fn) => { saveFnRef.current = fn; },
    _setExportFn: (fn) => { exportFnRef.current = fn; },
    _setPushHistoryFn: (_fn: (...args: unknown[]) => void) => { /* pushHistory is handled directly by editor, not through context */ },
    _historyRef: historyRef,
    _setCanUndo: setCanUndo,
    _setCanRedo: setCanRedo,
  };

  return <EditorContext.Provider value={value}>{children}</EditorContext.Provider>;
}

export function useEditorContext() {
  const ctx = useContext(EditorContext);
  if (!ctx) throw new Error('useEditorContext must be used within EditorProvider');
  return ctx;
}
