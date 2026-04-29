import { useState, useEffect, useCallback } from 'react';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
  id: string;
  title?: string;
  message: string;
  type: ToastType;
  duration?: number;
}

const listeners = new Set<(toasts: Toast[]) => void>();
let toasts: Toast[] = [];

function notify() {
  listeners.forEach(fn => fn([...toasts]));
}

export function addToast(toast: Omit<Toast, 'id'>) {
  const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const t: Toast = { ...toast, id, duration: toast.duration ?? (toast.type === 'error' ? 5000 : 3000) };
  toasts = [...toasts, t];
  notify();
  if (t.duration && t.duration > 0) {
    setTimeout(() => removeToast(id), t.duration);
  }
  return id;
}

export function removeToast(id: string) {
  toasts = toasts.filter(t => t.id !== id);
  notify();
}

export function toast(message: string, type: ToastType = 'info') {
  return addToast({ message, type });
}

toast.success = (message: string) => addToast({ message, type: 'success' });
toast.error = (message: string) => addToast({ message, type: 'error' });
toast.warning = (message: string) => addToast({ message, type: 'warning' });
toast.info = (message: string) => addToast({ message, type: 'info' });

export function useToast() {
  const [items, setItems] = useState<Toast[]>(toasts);

  useEffect(() => {
    const fn = (next: Toast[]) => setItems(next);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);

  return {
    toasts: items,
    dismiss: removeToast,
    success: useCallback((msg: string) => addToast({ message: msg, type: 'success' }), []),
    error: useCallback((msg: string) => addToast({ message: msg, type: 'error' }), []),
    warning: useCallback((msg: string) => addToast({ message: msg, type: 'warning' }), []),
    info: useCallback((msg: string) => addToast({ message: msg, type: 'info' }), []),
  };
}
