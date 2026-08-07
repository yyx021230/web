'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  Eye, EyeOff, Mail, Lock,
  Github, Loader2, Sparkles,
} from 'lucide-react';
import { authApi } from '@/services/authApi';

function OpenAIIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={className}>
      <g fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 3.8c2.1-1.2 4.8.2 5.1 2.6 2.3.4 3.7 2.9 2.6 5 .9 2.2-.7 4.6-3 4.8-1.2 2.1-4 2.5-5.8.9-2.3.4-4.4-1.5-4.2-3.9-1.8-1.5-1.7-4.4.2-5.8.1-2.4 2.5-4.1 4.8-3.3" />
        <path d="M8.1 7.3l3.9-2.2 3.9 2.2v4.5L12 14 8.1 11.8z" />
        <path d="M12 14v4.1M15.9 7.3l3.2 1.8M8.1 11.8l-3.2 1.8M12 5.1v4.2" />
      </g>
    </svg>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  /* If already logged in (has token), verify and redirect */
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      authApi.getMe()
        .then(res => {
          localStorage.setItem('app_current_user', JSON.stringify(res.data));
          router.replace('/editor');
        })
        .catch(() => {
          localStorage.removeItem('token');
          localStorage.removeItem('app_current_user');
        });
    }
  }, [router]);

  const handleLogin = async () => {
    setError('');
    if (!username || !password) { setError('请输入用户名和密码'); return; }
    setLoading(true);
    try {
      const res = await authApi.login({ username, password });
      localStorage.setItem('token', res.data.access_token);
      const userRes = await authApi.getMe();
      localStorage.setItem('app_current_user', JSON.stringify(userRes.data));
      router.push('/editor');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '登录失败';
      setError(msg.includes('401') ? '用户名或密码错误' : msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-scene min-h-screen overflow-hidden text-slate-950">
      <header className="relative z-10 flex items-center justify-between px-6 py-5 md:px-10">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 text-white shadow-lg shadow-indigo-300/40">
            <OpenAIIcon className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">AI Creative Studio</div>
            <div className="text-[11px] uppercase tracking-[0.24em] text-slate-400">Cloud Liquid Studio</div>
          </div>
        </div>
      </header>

      <main className="relative z-10 flex min-h-[calc(100vh-84px)] items-center justify-end px-5 pb-8 md:px-10">
        <section className="hidden flex-1 self-stretch lg:block">
          <div className="login-brand-copy">
            <div className="login-brand-panel">
              <Sparkles className="mb-5 h-7 w-7 text-indigo-500" />
              <h1 className="text-5xl font-semibold leading-tight tracking-[-0.05em] text-slate-950">
                AI Creative Studio
              </h1>
              <p className="mt-5 max-w-md text-base leading-8 text-slate-500">
                一站式 AI 创意设计平台，集编辑、AI 生图、图库管理、工作流于一体。
              </p>
            </div>
          </div>
        </section>

        <section className="mx-auto flex w-full max-w-[500px] items-center justify-center lg:mx-0 lg:justify-end">
          <div className="login-card-overlay w-full rounded-[34px] p-6 md:p-8">
            <div className="mb-8 text-center">
              <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-3xl border border-white/80 bg-white/70 text-indigo-600 shadow-[0_18px_48px_rgba(79,103,146,0.16)] backdrop-blur-xl">
                <OpenAIIcon className="h-8 w-8" />
              </div>
              <h2 className="text-3xl font-semibold tracking-[-0.035em] text-slate-950">欢迎回来</h2>
              <p className="mt-2 text-sm leading-6 text-slate-500">登录以继续你的创作之旅</p>
            </div>

            {error && (
              <div className="mb-4 rounded-2xl border border-red-100 bg-red-50/90 px-4 py-3 text-sm text-red-600">{error}</div>
            )}

            <div className="space-y-4">
              <div>
                <label className="text-sm font-semibold block mb-2 text-slate-800">用户名 / 邮箱</label>
                <div className="relative">
                  <Mail className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text" value={username} onChange={e => setUsername(e.target.value)}
                    placeholder="请输入用户名或邮箱"
                    className="w-full rounded-2xl border border-slate-200 bg-white/76 py-3.5 pl-11 pr-4 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none focus:ring-4 focus:ring-indigo-100"
                  />
                </div>
              </div>

              <div>
                <label className="text-sm font-semibold block mb-2 text-slate-800">密码</label>
                <div className="relative">
                  <Lock className="absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="请输入密码"
                    onKeyDown={e => { if (e.key === 'Enter') handleLogin(); }}
                    className="w-full rounded-2xl border border-slate-200 bg-white/76 py-3.5 pl-11 pr-11 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 focus:border-indigo-300 focus:outline-none focus:ring-4 focus:ring-indigo-100"
                  />
                  <button
                    type="button" onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-4 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-800"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              <div className="flex items-center justify-between text-sm">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" className="rounded border-slate-300" />
                  <span className="text-slate-500">记住我</span>
                </label>
                <button type="button" disabled className="text-slate-400 cursor-not-allowed" title="即将上线">忘记密码？</button>
              </div>

              <button
                onClick={handleLogin}
                disabled={loading}
                className={cn(
                  'w-full flex items-center justify-center gap-2 rounded-2xl py-3.5 text-sm font-semibold text-white shadow-lg transition-all',
                  loading ? 'bg-indigo-300 cursor-not-allowed' : 'bg-gradient-to-r from-indigo-500 to-violet-500 shadow-indigo-300/40 hover:-translate-y-0.5 hover:shadow-indigo-300/60'
                )}
              >
                {loading ? (<><Loader2 className="h-4 w-4 animate-spin" />登录中...</>) : ('登录')}
              </button>

              <div className="flex items-center gap-3 my-2">
                <div className="flex-1 h-px bg-slate-200" />
                <span className="text-xs text-slate-400">或</span>
                <div className="flex-1 h-px bg-slate-200" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <button disabled className="flex cursor-not-allowed items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white/62 py-3 text-sm font-semibold text-slate-400 opacity-70" title="即将上线">
                  <svg className="h-4 w-4" viewBox="0 0 24 24"><path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                  Google
                </button>
                <button disabled className="flex cursor-not-allowed items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white/62 py-3 text-sm font-semibold text-slate-400 opacity-70" title="即将上线">
                  <Github className="h-4 w-4" />
                  GitHub
                </button>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
