'use client';

import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import { toast } from '@/lib/toast';
import {
  Palette, LayoutDashboard, Users, Workflow, ImagePlus, BarChart3, LogOut, Menu, X, BookOpen,
  FolderKanban, Activity, MessageSquare, Loader2, Send,
  Bot, Target, Clock3,
} from 'lucide-react';
import { authApi } from '@/services/authApi';

const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || 'dev';
const GIT_COMMIT = process.env.NEXT_PUBLIC_GIT_COMMIT || 'unknown';

const navItems = [
  { id: 'dashboard', icon: LayoutDashboard, label: '运营总览', href: '/admin' },
  { id: 'users', icon: Users, label: '用户管理', href: '/admin/users' },
  { id: 'xhs', icon: Send, label: '小红书管理', href: '/admin/xhs' },
  { id: 'xhs-schedules', icon: Clock3, label: '定时任务', href: '/admin/xhs-schedules' },
  { id: 'xhs-buyers', icon: Target, label: '投手分配', href: '/admin/xhs-buyers' },
  { id: 'workflows', icon: Workflow, label: '工作流与日志', href: '/admin/workflows' },
  { id: 'ai-image', icon: Bot, label: '生图入口', href: '/admin/ai-image' },
  { id: 'tasks', icon: Activity, label: '任务中心', href: '/admin/tasks' },
  { id: 'projects', icon: FolderKanban, label: '项目管理', href: '/admin/projects' },
  { id: 'gallery', icon: ImagePlus, label: '资产中心', href: '/admin/gallery' },
  { id: 'copywritings', icon: BookOpen, label: '文案管理', href: '/admin/copywritings' },
  { id: 'prompts', icon: MessageSquare, label: '提示词管理', href: '/admin/prompts' },
  { id: 'api-usage', icon: BarChart3, label: 'API 使用', href: '/admin/api-usage' },
];

function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      toast.error('请先登录');
      router.replace('/');
      return;
    }

    // Check admin role
    const raw = localStorage.getItem('app_current_user');
    try {
      const user = JSON.parse(raw || '{}');
      const isDev = process.env.NODE_ENV === 'development';
      if (isDev || user.role === 'admin' || user.roles?.includes('admin') || user.username === 'dev') {
        setChecking(false);
        return;
      }
    } catch { /* ignore */ }

    // Not admin — verify with server
    authApi.getMe()
      .then(res => {
        const user = res.data;
        localStorage.setItem('app_current_user', JSON.stringify(user));
        if (user.role === 'admin' || user.roles?.includes('admin')) {
          setChecking(false);
        } else {
          toast.error('无权访问管理后台');
          router.replace('/');
        }
      })
      .catch(() => {
        toast.error('无权访问管理后台');
        router.replace('/');
      });
  }, [router]);

  if (checking) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
      </div>
    );
  }

  return <>{children}</>;
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const activeNav = (() => {
    if (pathname.startsWith('/admin/users')) return 'users';
    if (pathname.startsWith('/admin/xhs-schedules')) return 'xhs-schedules';
    if (pathname.startsWith('/admin/xhs-buyers')) return 'xhs-buyers';
    if (pathname.startsWith('/admin/xhs')) return 'xhs';
    if (pathname.startsWith('/admin/workflows')) return 'workflows';
    if (pathname.startsWith('/admin/ai-image')) return 'ai-image';
    if (pathname.startsWith('/admin/tasks')) return 'tasks';
    if (pathname.startsWith('/admin/projects')) return 'projects';
    if (pathname.startsWith('/admin/gallery')) return 'gallery';
    if (pathname.startsWith('/admin/copywritings')) return 'copywritings';
    if (pathname.startsWith('/admin/prompts')) return 'prompts';
    if (pathname.startsWith('/admin/api-usage')) return 'api-usage';
    return 'dashboard';
  })();

  const handleLogout = () => {
    authApi.logout();
    window.location.href = '/';
  };

  return (
    <div className="flex h-screen w-full bg-gray-50">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={cn(
        'fixed inset-y-0 left-0 z-50 w-56 bg-white border-r shadow-sm transition-transform lg:translate-x-0 lg:static lg:z-0',
        sidebarOpen ? 'translate-x-0' : '-translate-x-full'
      )}>
        {/* Logo */}
        <div className="flex items-center justify-between h-14 border-b px-5">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600">
              <Palette className="h-4 w-4 text-white" />
            </div>
            <span className="text-sm font-semibold">管理后台</span>
          </div>
          <button onClick={() => setSidebarOpen(false)} className="lg:hidden">
            <X className="h-4 w-4 text-muted-foreground" />
          </button>
        </div>

        {/* Nav */}
        <nav className="p-3 space-y-0.5">
          {navItems.map(item => (
            <a
              key={item.id}
              href={item.href}
              className={cn(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                activeNav === item.id
                  ? 'bg-indigo-50 text-indigo-700'
                  : 'text-gray-700 hover:bg-gray-100'
              )}
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </a>
          ))}
        </nav>

        {/* Footer */}
        <div className="absolute bottom-0 left-0 right-0 p-3 border-t">
          <div
            className="mb-2 flex items-center justify-between rounded-md bg-gray-50 px-3 py-1.5 text-[11px] text-gray-500"
            title={`Commit ${GIT_COMMIT}`}
          >
            <span>当前版本</span>
            <span className="font-medium text-gray-700">v{APP_VERSION.replace(/^v/, '')}</span>
          </div>
          <a href="/" className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 transition-colors">
            <Palette className="h-4 w-4" />
            返回前台
          </a>
          <button onClick={handleLogout} className="flex items-center gap-2 w-full rounded-lg px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors">
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex h-14 items-center justify-between border-b bg-white px-5 shrink-0">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden flex h-8 w-8 items-center justify-center rounded-md hover:bg-gray-100">
            <Menu className="h-5 w-5 text-gray-600" />
          </button>
          <div className="flex-1" />
          <span className="text-sm text-gray-500">
            {navItems.find(n => n.id === activeNav)?.label}
          </span>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto p-5">
          <AdminGuard>{children}</AdminGuard>
        </main>
      </div>
    </div>
  );
}
