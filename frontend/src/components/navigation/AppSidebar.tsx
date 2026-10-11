'use client';

import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import Link from 'next/link';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import {
  Sparkles, GalleryHorizontalEnd, Workflow, LogIn, LogOut,
  FileText, BookOpen, Shield, Send, BarChart3, Target,
  PanelLeftClose, PanelLeftOpen, ChevronsUpDown, ArrowUpRight,
  Hash, ChevronDown,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useOptionalAuthSession } from '@/components/auth/AuthSession';
import { AUTH_STATE_CHANGED_EVENT, requestAuthentication } from '@/lib/auth-events';
import { promptsApi } from '@/services/promptsApi';
import {
  PROMPT_LIBRARY_FILTER_EVENT,
  readPromptLibraryFilter,
  setPromptLibraryFilter,
  type PromptLibraryFilter,
  type PromptSourceFilter,
} from '@/lib/prompt-library-filter';
import shell from './workspace-shell.module.css';

const groups = [
  { label: '创作', items: [
    { icon: BookOpen, label: '首页', href: '/prompts' },
    { icon: Sparkles, label: '生图', href: '/ai' },
    { icon: Workflow, label: '工作台', href: '/workflows' },
    { icon: FileText, label: '文案', href: '/copywriting' },
    { icon: GalleryHorizontalEnd, label: '图库', href: '/gallery' },
  ] },
  { label: '运营', items: [
    { icon: Send, label: '发布', href: '/publish', aliases: ['/posts'] },
    { icon: BarChart3, label: '数据', href: '/insights' },
    { icon: Target, label: '投流', href: '/ad-insights' },
  ] },
];

const promptSourceLabels: Record<PromptSourceFilter, string> = {
  all: '全部素材',
  external: '外部素材',
  internal: '内部素材',
  performance: '优质帖子',
};

type CurrentUser = { username: string; display_name?: string | null; role?: string; roles?: string[] };

export default function AppSidebar({ pathname }: { pathname: string }) {
  const session = useOptionalAuthSession();
  const [collapsed, setCollapsed] = useState(false);
  const [storedUser, setStoredUser] = useState<CurrentUser | null>(null);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const navItemRefs = useRef<Record<string, HTMLAnchorElement | null>>({});
  const [indicator, setIndicator] = useState({ top: 0, height: 32, visible: false });
  const [promptFilter, setPromptFilter] = useState<PromptLibraryFilter>({ source: 'all', category: '' });
  const [promptCategories, setPromptCategories] = useState<Array<{ name: string; count: number }>>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(true);

  useEffect(() => {
    try {
      setStoredUser(JSON.parse(localStorage.getItem('app_current_user') || 'null'));
      setCollapsed(localStorage.getItem('app_sidebar_collapsed') === 'true');
    } catch { /* A damaged preference must not block navigation. */ }
  }, []);

  useEffect(() => setPendingHref(null), [pathname]);

  useEffect(() => {
    if (!pathname.startsWith('/prompts')) return;
    const syncFilter = (filter: PromptLibraryFilter) => setPromptFilter(filter);
    const handleFilterChange = (event: Event) => syncFilter((event as CustomEvent<PromptLibraryFilter>).detail);
    const handlePopState = () => syncFilter(readPromptLibraryFilter(window.location.search));
    syncFilter(readPromptLibraryFilter(window.location.search));
    window.addEventListener(PROMPT_LIBRARY_FILTER_EVENT, handleFilterChange);
    window.addEventListener('popstate', handlePopState);
    return () => {
      window.removeEventListener(PROMPT_LIBRARY_FILTER_EVENT, handleFilterChange);
      window.removeEventListener('popstate', handlePopState);
    };
  }, [pathname]);

  useEffect(() => {
    if (!pathname.startsWith('/prompts') || collapsed) return;
    let cancelled = false;
    setCategoriesLoading(true);
    const sourceKind = promptFilter.source === 'all' ? undefined : promptFilter.source;
    promptsApi.getCategories(sourceKind)
      .then(response => {
        if (!cancelled) setPromptCategories(response.data.categories);
      })
      .catch(() => {
        if (!cancelled) setPromptCategories([]);
      })
      .finally(() => {
        if (!cancelled) setCategoriesLoading(false);
      });
    return () => { cancelled = true; };
  }, [collapsed, pathname, promptFilter.source]);

  useEffect(() => {
    const syncStoredUser = () => {
      try { setStoredUser(JSON.parse(localStorage.getItem('app_current_user') || 'null')); }
      catch { setStoredUser(null); }
    };
    window.addEventListener(AUTH_STATE_CHANGED_EVENT, syncStoredUser);
    return () => window.removeEventListener(AUTH_STATE_CHANGED_EVENT, syncStoredUser);
  }, []);

  const toggleSidebar = () => {
    const next = !collapsed;
    setCollapsed(next);
    try { localStorage.setItem('app_sidebar_collapsed', String(next)); } catch { /* Optional preference. */ }
  };
  const currentUser = session ? session.user : storedUser;
  const canAccessAdmin = currentUser && (currentUser.role === 'admin' || currentUser.roles?.includes('admin') || currentUser.username === 'dev');
  const name = currentUser?.display_name || currentUser?.username || '未登录';
  const labelClass = collapsed ? 'hidden' : 'hidden md:block';
  const openLogin = (next = '/ai', reason?: string) => {
    if (session) session.requestLogin({ next, reason });
    else requestAuthentication({ next, reason });
  };
  const protectNavigation = (event: React.MouseEvent<HTMLAnchorElement>, href: string, label: string) => {
    if (currentUser || href === '/prompts') return;
    event.preventDefault();
    openLogin(href, `登录后进入${label}`);
  };
  const beginNavigation = (event: React.MouseEvent<HTMLAnchorElement>, href: string, label: string) => {
    protectNavigation(event, href, label);
    if (!event.defaultPrevented && pathname !== href) setPendingHref(href);
  };
  const choosePromptCategory = (category: string) => {
    setPromptLibraryFilter({ source: promptFilter.source, category });
  };
  const visualPathname = pendingHref || pathname;
  const activeHref = groups.flatMap(group => group.items).find(item => {
    const paths = [item.href, ...('aliases' in item ? item.aliases || [] : [])];
    return paths.some(path => visualPathname === path || visualPathname.startsWith(path + '/'));
  })?.href;

  useLayoutEffect(() => {
    const navigation = navigationRef.current;
    const activeItem = activeHref ? navItemRefs.current[activeHref] : null;
    if (!navigation || !activeItem) {
      setIndicator(current => ({ ...current, visible: false }));
      return;
    }

    const positionIndicator = () => {
      const navigationRect = navigation.getBoundingClientRect();
      const itemRect = activeItem.getBoundingClientRect();
      setIndicator({
        top: itemRect.top - navigationRect.top + navigation.scrollTop,
        height: itemRect.height,
        visible: true,
      });
    };

    positionIndicator();
    window.addEventListener('resize', positionIndicator);
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(positionIndicator);
    observer?.observe(navigation);
    observer?.observe(activeItem);
    return () => {
      window.removeEventListener('resize', positionIndicator);
      observer?.disconnect();
    };
  }, [activeHref, collapsed]);

  return (
    <aside aria-label="工作空间导航" className={cn(shell.sidebar, collapsed && shell.collapsed)}>
      <div className={cn(shell.brandRow, collapsed && shell.brandRowCollapsed)}>
        <Link href="/prompts" prefetch aria-label="AI Creative Studio" title="AI Creative Studio" className={shell.brand}>
          <img src="/brand/creative-studio-integrated-v2.png" alt="Creative Studio" width={2172} height={724} className={shell.brandImage} draggable={false} />
          <img src="/brand/creative-studio-glass-mark.png" alt="" width={1280} height={1280} className={shell.compactBrandMark} draggable={false} />
        </Link>
        <button type="button" onClick={toggleSidebar} aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'} aria-expanded={!collapsed}
          className={shell.collapseButton}>
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </button>
      </div>

      <nav ref={navigationRef} aria-label="主导航" className={shell.navigation}>
        <span
          aria-hidden="true"
          className={shell.navIndicator}
          style={{ height: indicator.height, opacity: indicator.visible ? 1 : 0, transform: `translate3d(0, ${indicator.top}px, 0)` }}
        />
        {groups.map(group => (
          <Fragment key={group.label}>
            {group.label === '运营' && pathname.startsWith('/prompts') && !collapsed && (
              <section className={shell.promptFilters} aria-label="标签筛选">
                <button
                  type="button"
                  className={shell.filterHeadingButton}
                  aria-expanded={tagsOpen}
                  onClick={() => setTagsOpen(value => !value)}
                >
                  <span>标签</span>
                  <ChevronDown aria-hidden="true" className={cn(shell.filterChevron, tagsOpen && shell.filterChevronOpen)} />
                </button>
                {tagsOpen && (
                  <div className={shell.tagList} aria-label={`${promptSourceLabels[promptFilter.source]}标签`}>
                    <button
                      type="button"
                      className={shell.tagItem}
                      aria-pressed={!promptFilter.category}
                      onClick={() => choosePromptCategory('')}
                    >
                      <Hash aria-hidden="true" />
                      <span>全部标签</span>
                    </button>
                    {categoriesLoading && promptCategories.length === 0 ? (
                      <span className={shell.filterStatus}>正在整理标签...</span>
                    ) : promptCategories.length > 0 ? promptCategories.map(category => (
                      <button
                        key={category.name}
                        type="button"
                        className={shell.tagItem}
                        aria-pressed={promptFilter.category === category.name}
                        title={category.name}
                        onClick={() => choosePromptCategory(category.name)}
                      >
                        <span className={shell.tagName}>{category.name}</span>
                      </button>
                    )) : (
                      <span className={shell.filterStatus}>当前素材暂无标签</span>
                    )}
                  </div>
                )}
              </section>
            )}
            <div role="group" aria-label={group.label} className={shell.group}>
              <p className={cn(shell.groupLabel, labelClass)}>{group.label}</p>
              <div className="space-y-1">
                {group.items.map(item => {
                  const paths = [item.href, ...('aliases' in item ? item.aliases || [] : [])];
                  const active = paths.some(path => visualPathname === path || visualPathname.startsWith(path + '/'));
                  return (
                    <Link key={item.href} href={item.href} prefetch title={item.label} aria-label={item.label} aria-current={active ? 'page' : undefined}
                      ref={node => { navItemRefs.current[item.href] = node; }}
                      onClick={event => beginNavigation(event, item.href, item.label)}
                      className={cn(shell.navItem, pendingHref === item.href && shell.navPending, collapsed ? 'justify-center' : 'justify-center md:justify-start')}>
                      <item.icon />
                      <span className={labelClass}>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          </Fragment>
        ))}
      </nav>

      <div className="mt-5 shrink-0">
        {!collapsed && <Link href="/prompts" prefetch className={shell.inspiration} aria-label="探索创作灵感，浏览提示词宝库">
          <span className="min-w-0 flex-1"><span className="block text-[12px] font-medium text-slate-800">探索创作灵感</span><span className="mt-1 block text-[11px] text-slate-500">从提示词宝库开始下一张好图</span></span>
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-slate-200/70 bg-white"><ArrowUpRight strokeWidth={1.5} className="h-3.5 w-3.5 text-slate-500" /></span>
        </Link>}
        {currentUser ? (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button type="button" aria-label={`账户菜单：${name}`} title={name} className={cn(shell.account, collapsed ? 'justify-center' : 'justify-center md:justify-start')}>
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#272830] text-xs font-medium text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]">{Array.from(name)[0]?.toUpperCase()}</span>
                <span className={cn('min-w-0 flex-1', labelClass)}><span className="block truncate text-[13px] font-medium text-slate-700">{name}</span><span className="mt-0.5 block text-[10px] text-slate-400">个人工作空间</span></span>
                <ChevronsUpDown className={cn('h-3.5 w-3.5 shrink-0 text-slate-400', labelClass)} />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content side="right" align="end" sideOffset={12} collisionPadding={12} className="z-[100] w-56 rounded-2xl border border-slate-200 bg-white p-1.5 shadow-[0_12px_40px_rgba(15,23,42,0.12)]">
                <DropdownMenu.Label className="px-3 py-2 text-xs text-slate-500"><span className="block truncate font-medium text-slate-800">{name}</span><span className="mt-1 block truncate text-[11px]">{currentUser.username}</span></DropdownMenu.Label>
                <DropdownMenu.Separator className="my-1 h-px bg-slate-100" />
                {canAccessAdmin && <DropdownMenu.Item asChild><Link href="/admin" className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-700 outline-none data-[highlighted]:bg-slate-50"><Shield className="h-4 w-4" />管理后台</Link></DropdownMenu.Item>}
                <DropdownMenu.Item onSelect={() => session?.logout() || window.location.assign('/prompts')} className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-xs text-red-500 outline-none data-[highlighted]:bg-red-50"><LogOut className="h-4 w-4" />退出登录</DropdownMenu.Item>
                <DropdownMenu.Separator className="my-1 h-px bg-slate-100" />
                <div className="px-3 py-2 text-[10px] text-slate-400" title={`Commit ${process.env.NEXT_PUBLIC_GIT_COMMIT || 'unknown'}`}>版本 v{(process.env.NEXT_PUBLIC_APP_VERSION || 'dev').replace(/^v/, '')}</div>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        ) : (
          <div className={shell.loginRow}>
            <button type="button" title="登录" aria-label="登录" onClick={() => openLogin('/ai', '登录后开始你的下一次创作')}
              className={shell.loginButton}>
              <LogIn /><span className="sr-only">登录</span><span className={labelClass}>开始使用</span>
            </button>
            <span className={cn(shell.loginHint, labelClass)}>登录后同步创作记录</span>
          </div>
        )}
      </div>
    </aside>
  );
}
