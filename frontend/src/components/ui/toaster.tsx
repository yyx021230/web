'use client';

import * as Toast from '@radix-ui/react-toast';
import { useToast, type ToastType } from '@/lib/toast';
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from 'lucide-react';

const icons: Record<ToastType, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const colors: Record<ToastType, { bg: string; border: string; icon: string }> = {
  success: { bg: 'bg-emerald-50', border: 'border-emerald-200', icon: 'text-emerald-500' },
  error: { bg: 'bg-red-50', border: 'border-red-200', icon: 'text-red-500' },
  warning: { bg: 'bg-amber-50', border: 'border-amber-200', icon: 'text-amber-500' },
  info: { bg: 'bg-sky-50', border: 'border-sky-200', icon: 'text-sky-500' },
};

export function Toaster() {
  const { toasts, dismiss } = useToast();

  return (
    <Toast.Provider swipeDirection="right">
      {toasts.map(t => {
        const c = colors[t.type];
        const Icon = icons[t.type];
        return (
          <Toast.Root
            key={t.id}
            className={`fixed bottom-4 right-4 z-[9999] flex items-start gap-3 rounded-xl border shadow-lg px-4 py-3 max-w-sm animate-slide-in ${c.bg} ${c.border}`}
            duration={t.duration}
            onOpenChange={open => { if (!open) dismiss(t.id); }}
          >
            <Icon className={`h-5 w-5 shrink-0 mt-0.5 ${c.icon}`} />
            <div className="flex-1 min-w-0">
              {t.title && <Toast.Title className="text-sm font-semibold text-gray-900">{t.title}</Toast.Title>}
              <Toast.Description className="text-sm text-gray-600 mt-0.5 leading-relaxed">{t.message}</Toast.Description>
            </div>
            <Toast.Close className="shrink-0 text-gray-400 hover:text-gray-600" aria-label="关闭">
              <X className="h-4 w-4" />
            </Toast.Close>
          </Toast.Root>
        );
      })}
      <Toast.Viewport className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 w-full max-w-sm" />
    </Toast.Provider>
  );
}
