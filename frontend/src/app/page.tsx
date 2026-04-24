'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  Palette, Eye, EyeOff, Mail, Lock, UserPlus,
  Github, Loader2, CheckCircle2,
} from 'lucide-react';
import { authApi } from '@/services/authApi';

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

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

  const handleRegister = async () => {
    setError(''); setSuccess('');
    if (!username || !email || !password) { setError('请填写所有字段'); return; }
    if (username.length < 3) { setError('用户名至少3个字符'); return; }
    if (!email.includes('@')) { setError('请输入有效邮箱'); return; }
    if (password.length < 6) { setError('密码至少6个字符'); return; }
    setLoading(true);
    try {
      const res = await authApi.register({ username, email, password });
      localStorage.setItem('token', res.data.access_token);
      const userRes = await authApi.getMe();
      localStorage.setItem('app_current_user', JSON.stringify(userRes.data));
      setSuccess('注册成功！正在跳转...');
      setTimeout(() => router.push('/editor'), 500);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '注册失败';
      if (msg.includes('400')) {
        setError(msg.includes('用户名') ? '用户名已存在' : '邮箱已被注册');
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex bg-background">
      {/* Left: Branding panel */}
      <div className="hidden lg:flex lg:w-1/2 flex-col items-center justify-center bg-gradient-to-br from-indigo-600 via-purple-600 to-pink-500 p-12 relative overflow-hidden">
        <div className="absolute inset-0">
          <div className="absolute top-20 left-20 w-72 h-72 bg-white/5 rounded-full blur-3xl" />
          <div className="absolute bottom-20 right-20 w-96 h-96 bg-white/5 rounded-full blur-3xl" />
        </div>
        <div className="relative z-10 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-white/20 backdrop-blur-sm shadow-xl mx-auto mb-8">
            <Palette className="h-8 w-8 text-white" />
          </div>
          <h1 className="text-4xl font-bold text-white mb-4">AI Creative Studio</h1>
          <p className="text-lg text-white/70 mb-12 max-w-md mx-auto">
            一站式 AI 创意设计平台，集编辑、AI 生图、图库管理、工作流于一体
          </p>
          <div className="grid grid-cols-2 gap-4 max-w-sm mx-auto">
            {[
              { label: '专业编辑器', desc: '拖拽式可视化设计' },
              { label: 'AI 智能生图', desc: '多模型一键生成' },
              { label: '工作流集成', desc: 'Dify 无缝对接' },
              { label: '图库管理', desc: '智能分类搜索' },
            ].map((f, i) => (
              <div key={i} className="flex flex-col items-center gap-2 rounded-xl bg-white/10 backdrop-blur-sm p-4 border border-white/10">
                <span className="text-sm font-medium text-white">{f.label}</span>
                <span className="text-xs text-white/50">{f.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right: Auth form */}
      <div className="flex-1 flex flex-col">
        {/* Top bar */}
        <div className="flex items-center justify-between px-6 py-3 border-b">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-purple-600 shadow-sm">
              <Palette className="h-4 w-4 text-white" />
            </div>
            <span className="text-sm font-semibold">AI Creative Studio</span>
          </div>
        </div>

        {/* Form area */}
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="w-full max-w-sm">
            <div className="mb-8">
              <h2 className="text-2xl font-bold">{mode === 'login' ? '欢迎回来' : '创建账户'}</h2>
              <p className="text-muted-foreground mt-1">
                {mode === 'login' ? '登录以继续你的创作之旅' : '注册即可免费使用所有功能'}
              </p>
            </div>

            {error && (
              <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-600">{error}</div>
            )}
            {success && (
              <div className="mb-4 rounded-lg bg-green-50 border border-green-200 px-4 py-3 text-sm text-green-600 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4" />{success}
              </div>
            )}

            <div className="space-y-4">
              {mode === 'register' && (
                <div>
                  <label className="text-sm font-medium block mb-1.5">用户名</label>
                  <div className="relative">
                    <UserPlus className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text" value={username} onChange={e => setUsername(e.target.value)}
                      placeholder="请输入用户名"
                      className="w-full rounded-lg border bg-background py-2.5 pl-10 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  </div>
                </div>
              )}

              {mode === 'login' && (
                <div>
                  <label className="text-sm font-medium block mb-1.5">用户名 / 邮箱</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="text" value={username} onChange={e => setUsername(e.target.value)}
                      placeholder="请输入用户名或邮箱"
                      className="w-full rounded-lg border bg-background py-2.5 pl-10 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  </div>
                </div>
              )}

              {mode === 'register' && (
                <div>
                  <label className="text-sm font-medium block mb-1.5">邮箱</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input
                      type="email" value={email} onChange={e => setEmail(e.target.value)}
                      placeholder="请输入邮箱"
                      className="w-full rounded-lg border bg-background py-2.5 pl-10 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                    />
                  </div>
                </div>
              )}

              <div>
                <label className="text-sm font-medium block mb-1.5">密码</label>
                <div className="relative">
                  <Lock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type={showPassword ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="请输入密码"
                    onKeyDown={e => { if (e.key === 'Enter') { mode === 'login' ? handleLogin() : handleRegister(); } }}
                    className="w-full rounded-lg border bg-background py-2.5 pl-10 pr-10 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
                  />
                  <button
                    type="button" onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              {mode === 'login' && (
                <div className="flex items-center justify-between text-sm">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" className="rounded border-gray-300" />
                    <span className="text-muted-foreground">记住我</span>
                  </label>
                  <button type="button" onClick={() => alert('模拟：跳转到第三方密码重置页面')} className="text-primary hover:underline">忘记密码？</button>
                </div>
              )}

              <button
                onClick={mode === 'login' ? handleLogin : handleRegister}
                disabled={loading}
                className={cn(
                  'w-full flex items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium text-white shadow-sm transition-all',
                  loading ? 'bg-primary/70 cursor-not-allowed' : 'bg-primary hover:bg-primary/90'
                )}
              >
                {loading ? (<><Loader2 className="h-4 w-4 animate-spin" />{mode === 'login' ? '登录中...' : '注册中...'}</>) : (<>{mode === 'login' ? '登录' : '注册'}</>)}
              </button>

              <div className="flex items-center gap-3 my-2">
                <div className="flex-1 h-px bg-border" />
                <span className="text-xs text-muted-foreground">或</span>
                <div className="flex-1 h-px bg-border" />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <button onClick={() => alert('模拟：通过 Google 账号登录\n（实际实现将跳转到 Google OAuth 授权页）')} className="flex items-center justify-center gap-2 rounded-lg border py-2.5 text-sm font-medium hover:bg-accent transition-colors">
                  <svg className="h-4 w-4" viewBox="0 0 24 24"><path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z"/><path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                  Google
                </button>
                <button onClick={() => alert('模拟：通过 GitHub 账号登录\n（实际实现将跳转到 GitHub OAuth 授权页）')} className="flex items-center justify-center gap-2 rounded-lg border py-2.5 text-sm font-medium hover:bg-accent transition-colors">
                  <Github className="h-4 w-4" />
                  GitHub
                </button>
              </div>
            </div>

            <p className="text-center text-sm text-muted-foreground mt-8">
              {mode === 'login' ? '还没有账户？' : '已有账户？'}
              <button onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); setSuccess(''); }} className="text-primary font-medium hover:underline ml-1">
                {mode === 'login' ? '立即注册' : '返回登录'}
              </button>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
