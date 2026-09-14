'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import * as Dialog from '@radix-ui/react-dialog';
import { AlertCircle, Eye, EyeOff, Loader2, LockKeyhole, UserRound, X } from 'lucide-react';
import { authApi, type User } from '@/services/authApi';
import {
  AUTH_REQUIRED_EVENT,
  AUTH_STATE_CHANGED_EVENT,
  notifyAuthStateChanged,
  type AuthRequiredDetail,
} from '@/lib/auth-events';
import styles from './AuthSession.module.css';

type LoginRequest = AuthRequiredDetail;

type AuthSessionValue = {
  user: User | null;
  checking: boolean;
  loginOpen: boolean;
  requestLogin: (request?: LoginRequest) => void;
  logout: () => void;
};

const AuthSessionContext = createContext<AuthSessionValue | null>(null);
const PUBLIC_ROUTES = new Set(['/prompts']);

function safeNextPath(value: string | null | undefined) {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/ai';
  return value;
}

export function useOptionalAuthSession() {
  return useContext(AuthSessionContext);
}

export function useAuthSession() {
  const session = useOptionalAuthSession();
  if (!session) throw new Error('useAuthSession must be used within AuthSessionProvider');
  return session;
}

export function AuthSessionProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [loginOpen, setLoginOpen] = useState(false);
  const [nextPath, setNextPath] = useState('/ai');
  const [reason, setReason] = useState('登录后继续使用完整创作工具');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const requestLogin = useCallback((request: LoginRequest = {}) => {
    setNextPath(safeNextPath(request.next));
    setReason(request.reason || '登录后继续使用完整创作工具');
    setError('');
    setLoginOpen(true);
  }, []);

  const readStoredUser = useCallback(() => {
    try {
      const raw = localStorage.getItem('app_current_user');
      setUser(raw ? JSON.parse(raw) as User : null);
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      setChecking(false);
      return;
    }
    authApi.getMe()
      .then(res => {
        localStorage.setItem('app_current_user', JSON.stringify(res.data));
        setUser(res.data);
      })
      .catch(() => {
        authApi.logout();
        setUser(null);
      })
      .finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    const handleRequired = (event: Event) => {
      authApi.logout();
      setUser(null);
      requestLogin((event as CustomEvent<AuthRequiredDetail>).detail || {});
    };
    const handleStateChanged = () => readStoredUser();
    window.addEventListener(AUTH_REQUIRED_EVENT, handleRequired);
    window.addEventListener(AUTH_STATE_CHANGED_EVENT, handleStateChanged);
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, handleRequired);
      window.removeEventListener(AUTH_STATE_CHANGED_EVENT, handleStateChanged);
    };
  }, [readStoredUser, requestLogin]);

  useEffect(() => {
    if (pathname !== '/prompts') return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('login') !== '1') return;
    requestLogin({
      next: params.get('next') || '/ai',
      reason: params.get('reason') || '登录后继续访问刚才的页面',
    });
    window.history.replaceState(window.history.state, '', '/prompts');
  }, [pathname, requestLogin]);

  const logout = useCallback(() => {
    authApi.logout();
    // Navigate before publishing an unauthenticated render. Otherwise the route
    // gate can briefly see the protected page without a user and reopen login.
    window.location.assign('/prompts');
  }, []);

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!username.trim() || !password) {
      setError('请输入用户名和密码');
      return;
    }
    setSubmitting(true);
    try {
      const login = await authApi.login({ username: username.trim(), password });
      localStorage.setItem('token', login.data.access_token);
      const current = await authApi.getMe();
      localStorage.setItem('app_current_user', JSON.stringify(current.data));
      setUser(current.data);
      notifyAuthStateChanged();
      setLoginOpen(false);
      setPassword('');
      window.location.assign(safeNextPath(nextPath));
    } catch (caught) {
      authApi.logout();
      const message = caught instanceof Error ? caught.message : '登录失败，请稍后重试';
      setError(/401|password|credential|用户名|密码|认证/i.test(message) ? '用户名或密码不正确' : message);
    } finally {
      setSubmitting(false);
    }
  };

  const value = useMemo<AuthSessionValue>(() => ({
    user,
    checking,
    loginOpen,
    requestLogin,
    logout,
  }), [checking, loginOpen, logout, requestLogin, user]);

  return (
    <AuthSessionContext.Provider value={value}>
      {children}
      <Dialog.Root open={loginOpen} onOpenChange={open => { if (!submitting) setLoginOpen(open); }}>
        <Dialog.Portal>
          <Dialog.Overlay className={styles.overlay} />
          <Dialog.Content className={styles.dialog} aria-describedby="auth-login-description">
            <Dialog.Close className={styles.close} aria-label="关闭登录弹窗"><X size={17} /></Dialog.Close>
            <header className={styles.welcome}>
              <img className={styles.brand} src="/brand/creative-studio-integrated-v2.png" alt="Creative Studio" />
              <Dialog.Title className={styles.title}>欢迎回来</Dialog.Title>
              <Dialog.Description id="auth-login-description" className={styles.subtitle}>{reason}</Dialog.Description>
            </header>
            <form className={styles.form} onSubmit={submitLogin}>
              <label className={styles.field}>
                <span className={styles.label}>用户名 / 邮箱</span>
                <span className={styles.inputWrap}>
                  <UserRound className={styles.inputIcon} />
                  <input className={styles.input} value={username} onChange={event => setUsername(event.target.value)}
                    autoComplete="username" autoFocus placeholder="请输入用户名或邮箱" />
                </span>
              </label>
              <label className={styles.field}>
                <span className={styles.label}>密码</span>
                <span className={styles.inputWrap}>
                  <LockKeyhole className={styles.inputIcon} />
                  <input className={styles.input} type={showPassword ? 'text' : 'password'} value={password}
                    onChange={event => setPassword(event.target.value)} autoComplete="current-password" placeholder="请输入密码" />
                  <button className={styles.passwordToggle} type="button" onClick={() => setShowPassword(value => !value)}
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}>
                    {showPassword ? <EyeOff /> : <Eye />}
                  </button>
                </span>
              </label>
              {error && <div className={styles.error} role="alert"><AlertCircle />{error}</div>}
              <button className={styles.submit} type="submit" disabled={submitting}>
                {submitting ? <><Loader2 className="animate-spin" />正在登录</> : '登录并继续'}
              </button>
              <p className={styles.footnote}>账号由管理员统一创建，如需开通请联系系统管理员</p>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </AuthSessionContext.Provider>
  );
}

export function AuthRouteGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, checking, loginOpen } = useAuthSession();
  const isPublic = PUBLIC_ROUTES.has(pathname);

  useEffect(() => {
    if (isPublic || checking || user || loginOpen) return;
    const next = `${pathname}${window.location.search}`;
    window.location.replace(`/prompts?login=1&next=${encodeURIComponent(next)}`);
  }, [checking, isPublic, loginOpen, pathname, user]);

  if (!isPublic && !user && !loginOpen) {
    return (
      <div className={styles.routeLoader} aria-busy="true">
        <div className={styles.routeLoaderInner}><Loader2 className="animate-spin" />正在打开登录入口</div>
      </div>
    );
  }
  return <>{children}</>;
}
