'use client';

import { useState, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';
import {
  Palette, Settings, Download,
  Undo2, Redo2, ZoomIn, ZoomOut, Maximize, User,
  Sparkles, GalleryHorizontalEnd, Workflow, LogIn, Save, LogOut,
  LayoutGrid, FileText, BookOpen, Shield,
  Loader2, Send, BarChart3,
  Target,
} from 'lucide-react';
import { authApi } from '@/services/authApi';
import { EditorProvider, useEditorContext } from '@/contexts/EditorContext';

const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || 'dev';
const GIT_COMMIT = process.env.NEXT_PUBLIC_GIT_COMMIT || 'unknown';

const navItems = [
  { id: 'editor', icon: Palette, label: '编辑器', href: '/editor' },
  { id: 'library', icon: LayoutGrid, label: '模板库', href: '/library' },
  { id: 'gallery', icon: GalleryHorizontalEnd, label: '我的图库', href: '/gallery' },
  { id: 'ai', icon: Sparkles, label: 'AI 生图', href: '/ai' },
  { id: 'prompts', icon: BookOpen, label: '提示词宝库', href: '/prompts' },
  { id: 'copywriting', icon: FileText, label: '文案库', href: '/copywriting' },
  { id: 'workflows', icon: Workflow, label: '内容工作台', href: '/workflows' },
  { id: 'publish', icon: Send, label: '发布管理', href: '/publish' },
  { id: 'insights', icon: BarChart3, label: '数据看板', href: '/insights' },
  { id: 'ad-insights', icon: Target, label: '投流看板', href: '/ad-insights' },
];

function EditorToolbar() {
  const ctx = useEditorContext();
  return (
    <>
      <div className="h-4 w-px bg-border" />
      <div className="flex items-center gap-0.5">
        <button
          onClick={ctx.triggerUndo}
          disabled={!ctx.canUndo}
          className={cn('flex h-7 w-7 items-center justify-center rounded-md transition-colors', ctx.canUndo ? 'text-muted-foreground hover:bg-accent' : 'opacity-30 cursor-not-allowed')}
          title="撤销 Ctrl+Z"
        >
          <Undo2 className="h-3.5 w-3.5" />
        </button>
        <button
          onClick={ctx.triggerRedo}
          disabled={!ctx.canRedo}
          className={cn('flex h-7 w-7 items-center justify-center rounded-md transition-colors', ctx.canRedo ? 'text-muted-foreground hover:bg-accent' : 'opacity-30 cursor-not-allowed')}
          title="重做 Ctrl+Shift+Z"
        >
          <Redo2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="h-4 w-px bg-border" />
      <div className="flex items-center gap-0.5">
        <button onClick={() => ctx.setZoom(z => Math.max(25, z - 25))} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent" title="缩小">
          <ZoomOut className="h-3.5 w-3.5" />
        </button>
        <span className="min-w-[40px] text-center text-xs font-medium tabular-nums">{ctx.zoom}%</span>
        <button onClick={() => ctx.setZoom(z => Math.min(200, z + 25))} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent" title="放大">
          <ZoomIn className="h-3.5 w-3.5" />
        </button>
        <button onClick={() => ctx.setZoom(100)} className="flex h-7 px-1.5 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent" title="适应">
          <Maximize className="h-3.5 w-3.5" />
        </button>
      </div>
    </>
  );
}

function HeaderActions() {
  const ctx = useEditorContext();
  const pathname = usePathname();
  const [currentUser, setCurrentUser] = useState<{ username: string; display_name?: string | null; role?: string; roles?: string[] } | null>(null);

  useEffect(() => {
    try {
      const u = JSON.parse(localStorage.getItem('app_current_user') || 'null');
      setCurrentUser(u);
    } catch { /* ignore */ }
  }, []);

  const handleLogout = () => {
    authApi.logout();
    setCurrentUser(null);
    window.location.href = '/';
  };

  const canAccessAdmin = currentUser && (currentUser.role === 'admin' || currentUser.roles?.includes('admin') || currentUser.username === 'dev');

  return (
    <div className="flex items-center gap-1.5">
      {pathname === '/editor' && (
        <>
          <button
            onClick={ctx.triggerSave}
            disabled={ctx.isSaving}
            className={cn('flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium shadow-sm transition-colors',
              ctx.isSaving ? 'bg-primary/50 text-white cursor-wait' :
              ctx.hasUnsavedChanges
                ? 'bg-amber-500 text-white hover:bg-amber-600'
                : 'bg-accent text-muted-foreground hover:bg-accent/80')}
          >
            <Save className={cn('h-3.5 w-3.5', ctx.isSaving && 'animate-spin')} />
            {ctx.isSaving ? '保存中...' : ctx.hasUnsavedChanges ? '保存' : '已保存'}
          </button>
          <button
            onClick={ctx.triggerExport}
            className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-white shadow-sm transition-colors hover:bg-primary/90"
          >
            <Download className="h-3.5 w-3.5" />
            导出
          </button>
        </>
      )}
      {currentUser ? (
        <div className="flex items-center gap-2">
          {canAccessAdmin && (
            <a
              href="/admin"
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 transition-colors"
              title="进入管理后台"
            >
              <Shield className="h-3.5 w-3.5" />
              管理后台
            </a>
          )}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-accent/50">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-primary">
              <User className="h-3.5 w-3.5" />
            </div>
            <span className="text-xs font-medium">{currentUser.display_name || currentUser.username}</span>
          </div>
          <button onClick={handleLogout} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-red-500" title="退出登录">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      ) : (
        <a href="/" className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground transition-colors">
          <LogIn className="h-3.5 w-3.5" />
          登录
        </a>
      )}
      <button className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent">
        <Settings className="h-4 w-4" />
      </button>
    </div>
  );
}

function ProjectName() {
  const ctx = useEditorContext();
  const pathname = usePathname();
  if (pathname !== '/editor') return null;
  return (
    <input
      value={ctx.projectName}
      onChange={(e) => ctx.setProjectName(e.target.value)}
      className="text-sm font-semibold bg-transparent border-b border-transparent focus:border-primary/50 focus:outline-none rounded px-1 py-0.5 w-32 hover:border-border"
      title="点击修改项目名称"
    />
  );
}

function MainLayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  const getActiveNav = () => {
    if (pathname.startsWith('/editor')) return 'editor';
    if (pathname.startsWith('/library')) return 'library';
    if (pathname.startsWith('/gallery')) return 'gallery';
    if (pathname.startsWith('/ai')) return 'ai';
    if (pathname.startsWith('/prompts')) return 'prompts';
    if (pathname.startsWith('/copywriting')) return 'copywriting';
    if (pathname.startsWith('/workflows')) return 'workflows';
    if (pathname.startsWith('/insights')) return 'insights';
    if (pathname.startsWith('/ad-insights')) return 'ad-insights';
    if (pathname.startsWith('/publish')) return 'publish';
    if (pathname.startsWith('/posts')) return 'publish';
    return 'editor';
  };

  const activeNav = getActiveNav();

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-background">
      {/* ===== 顶部 Header ===== */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b bg-card px-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-purple-600 shadow-sm">
              <Palette className="h-4 w-4 text-white" />
            </div>
            <span className="text-sm font-semibold tracking-tight">AI Creative Studio</span>
            <span
              className="rounded-full border border-border bg-muted/60 px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
              title={`Commit ${GIT_COMMIT}`}
            >
              v{APP_VERSION.replace(/^v/, '')}
            </span>
          </div>
          {pathname === '/editor' && <EditorToolbar />}
        </div>
        <div className="flex items-center gap-3">
          <ProjectName />
          <HeaderActions />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ===== 左侧导航 ===== */}
        <aside className="flex w-[52px] shrink-0 flex-col border-r bg-card">
          <nav className="flex flex-1 flex-col items-center gap-1 py-2">
            {navItems.map((item) => {
              const isActive = activeNav === item.id;
              return (
                <div key={item.id} className="relative group">
                  <a
                    href={item.href}
                    className={cn(
                      'flex h-10 w-10 items-center justify-center rounded-lg transition-all',
                      isActive
                        ? 'bg-primary text-white shadow-sm'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                    )}
                  >
                    <item.icon className="h-[18px] w-[18px]" />
                  </a>
                  <span className="absolute left-full ml-3 hidden whitespace-nowrap rounded-md bg-popover px-2.5 py-1.5 text-xs font-medium shadow-md border group-hover:block z-50">
                    {item.label}
                  </span>
                </div>
              );
            })}
          </nav>
        </aside>

        {/* ===== 主内容 ===== */}
        <main className="flex-1 overflow-hidden bg-canvas-bg">
          {children}
        </main>
      </div>
    </div>
  );
}

/* Dev mode auto-login: ensures API requests have a valid token */
function DevAutoLogin() {
  useEffect(() => {
    const username = process.env.NEXT_PUBLIC_DEV_AUTO_LOGIN_USERNAME;
    const password = process.env.NEXT_PUBLIC_DEV_AUTO_LOGIN_PASSWORD;
    if (
      process.env.NODE_ENV === 'development'
      && process.env.NEXT_PUBLIC_DEV_AUTO_LOGIN === 'true'
      && username
      && password
      && !localStorage.getItem('token')
    ) {
      fetch('/api/backend/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.code === 0 && data.data?.access_token) {
            localStorage.setItem('token', data.data.access_token);
            localStorage.setItem('app_current_user', JSON.stringify({ username: 'dev' }));
            window.location.reload();
          }
        })
        .catch(() => { /* Will fail gracefully — user can login manually */ });
    }
  }, []);
  return null;
}

/* Main app auth guard */
function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    if (pathname === '/') {
      setChecking(false);
      return;
    }

    const token = localStorage.getItem('token');
    if (!token) {
      window.location.href = '/';
      return;
    }

    authApi.getMe()
      .then((res) => {
        localStorage.setItem('app_current_user', JSON.stringify(res.data));
        setChecking(false);
      })
      .catch(() => {
        localStorage.removeItem('token');
        localStorage.removeItem('app_current_user');
        window.location.href = '/';
      });
  }, [pathname]);

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return <>{children}</>;
}

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <EditorProvider>
      <DevAutoLogin />
      <AuthGuard>
        <MainLayoutInner>{children}</MainLayoutInner>
      </AuthGuard>
    </EditorProvider>
  );
}
