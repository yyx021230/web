'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, Files } from 'lucide-react';

export default function GlobalMaterialsPage() {
  const router = useRouter();

  useEffect(() => {
    const timer = setTimeout(() => router.replace('/admin/gallery'), 1200);
    return () => clearTimeout(timer);
  }, [router]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="max-w-lg rounded-2xl border bg-white p-8 text-center shadow-sm">
        <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600">
          <Files className="h-5 w-5" />
        </div>
        <h1 className="text-lg font-semibold">素材管理已合并到资产中心</h1>
        <p className="mt-2 text-sm text-gray-500">
          为了避免“素材管理”和“图库管理”功能重复，后台统一收敛为“资产中心”。
        </p>
        <button
          type="button"
          onClick={() => router.replace('/admin/gallery')}
          className="mx-auto mt-5 inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          前往资产中心
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
