'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import * as Dialog from '@radix-ui/react-dialog';
import { AlertCircle, Eye, EyeOff, Loader2, LockKeyhole, UserRound, X } from 'lucide-react';
import { authApi, type User } from '@/services/authApi';
import { forgetLocalAuthentication, isBrowserSession, observeSessionChanges, reportUserActivity } from '@/services/browserSession';
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
  verificationError: string;
  retryVerification: () => void;
};

const AuthSessionContext = createContext<AuthSessionValue | null>(null);
const PUBLIC_ROUTES = new Set(['/prompts']);

function safeNextPath(value: string | null | undefined) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value)) return '/ai';
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
  const router = useRouter();
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
  const [verificationError, setVerificationError] = useState('');
  const [verificationAttempt, setVerificationAttempt] = useState(0);
  const lastUserId = useRef<number | null>(null);
  const verificationVersion = useRef(0);
  const logoutInProgress = useRef(false);
  useEffect(() => { if (user?.id) lastUserId.current = user.id; }, [user?.id]);
  const retryVerification = useCallback(() => {
    if (localStorage.getItem('creative_auth_mode') === 'logout-pending') {
      void authApi.logout().then(() => window.location.assign('/prompts')).catch(() => {
        setVerificationError('服务器会话撤销仍未确认，请联网后重试退出');
      });
    } else setVerificationAttempt(value => value + 1);
  }, []);

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
    readStoredUser();
    if (!localStorage.getItem('token') && localStorage.getItem('creative_auth_mode') !== 'session') {
      setChecking(false);
      return;
    }
    let active = true;
    const version = verificationVersion.current;
    setChecking(true);
    setVerificationError('');
    authApi.getMe()
      .then(res => {
        if (!active || version !== verificationVersion.current) return;
        localStorage.setItem('app_current_user', JSON.stringify(res.data));
        setUser(res.data);
      })
      .catch((caught: Error & { status?: number }) => {
        if (!active || version !== verificationVersion.current) return;
        if (caught.status === 401 || caught.status === 403) {
          forgetLocalAuthentication(isBrowserSession() ? 'expired' : 'legacy-expired');
          setUser(null);
          requestLogin({ next: pathname, reason: '登录状态已失效，请重新登录后继续' });
        } else {
          setVerificationError('暂时无法验证登录状态，请重试；登录信息未清除');
        }
      })
      .finally(() => { if (active && version === verificationVersion.current) setChecking(false); });
    return () => { active = false; };
    // Route changes must not remount or discard an in-progress operation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readStoredUser, verificationAttempt]);

  useEffect(() => {
    const handleRequired = (event: Event) => {
      verificationVersion.current += 1;
      setChecking(false);
      setUser(null);
      setVerificationError('');
      requestLogin((event as CustomEvent<AuthRequiredDetail>).detail || {});
    };
    const handleStateChanged = () => {
      // A different tab may log out while /me is already in flight.
      verificationVersion.current += 1;
      if (!logoutInProgress.current) setChecking(false);
      try {
        const cached = JSON.parse(localStorage.getItem('app_current_user') || 'null') as User | null;
        if (cached?.id && lastUserId.current !== null && cached.id !== lastUserId.current) {
          window.location.reload();
          return;
        }
      } catch { /* Invalid cache is not an authenticated identity. */ }
      readStoredUser();
      if (!localStorage.getItem('app_current_user') && !PUBLIC_ROUTES.has(pathname)
        && !['logged-out', 'logout-pending'].includes(localStorage.getItem('creative_auth_mode') || '')) {
        requestLogin({ next: pathname });
      }
    };
    const stopObserving = observeSessionChanges();
    window.addEventListener(AUTH_REQUIRED_EVENT, handleRequired);
    window.addEventListener(AUTH_STATE_CHANGED_EVENT, handleStateChanged);
    return () => {
      window.removeEventListener(AUTH_REQUIRED_EVENT, handleRequired);
      window.removeEventListener(AUTH_STATE_CHANGED_EVENT, handleStateChanged);
      stopObserving();
    };
  }, [pathname, readStoredUser, requestLogin]);

  useEffect(() => {
    if (!user) return;
    let lastSent = 0;
    const activity = (event?: Event) => {
      if (document.visibilityState !== 'visible' || (event && !event.isTrusted)
        || Date.now() - lastSent < 60000) return;
      lastSent = Date.now();
      void reportUserActivity().catch(() => { /* Offline activity is not authentication failure. */ });
    };
    activity();
    const events = ['pointerdown', 'keydown', 'wheel', 'touchstart'];
    events.forEach(name => window.addEventListener(name, activity, { passive: true }));
    return () => events.forEach(name => window.removeEventListener(name, activity));
  }, [user?.id]);

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
    verificationVersion.current += 1;
    logoutInProgress.current = true;
    setChecking(true);
    setUser(null);
    setLoginOpen(false);
    void authApi.logout().then(() => window.location.assign('/prompts')).catch(() => {
      setUser(null);
      setChecking(false);
      setVerificationError('本机已退出，但服务器会话撤销未确认，请联网后重试退出');
    }).finally(() => { logoutInProgress.current = false; });
  }, []);

  const submitLogin = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!username.trim() || !password) {
      setError('请输入用户名和密码');
      return;
    }
    setSubmitting(true);
    verificationVersion.current += 1;
    const version = verificationVersion.current;
    setChecking(false);
    try {
      await authApi.login({ username: username.trim(), password });
      if (version !== verificationVersion.current) return;
      const current = await authApi.getMe();
      if (version !== verificationVersion.current) return;
      localStorage.setItem('app_current_user', JSON.stringify(current.data));
      setUser(current.data);
      notifyAuthStateChanged();
      setLoginOpen(false);
      setPassword('');
      setVerificationError('');
      if (lastUserId.current !== null && lastUserId.current !== current.data.id) {
        // Never keep another account's mounted drafts or task views alive.
        window.location.assign(safeNextPath(nextPath));
      } else if (safeNextPath(nextPath) !== `${pathname}${window.location.search}`) router.push(safeNextPath(nextPath));
    } catch (caught) {
      if (version !== verificationVersion.current) return;
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
    verificationError,
    retryVerification,
  }), [checking, loginOpen, logout, requestLogin, user, verificationError, retryVerification]);

  return (
    <AuthSessionContext.Provider value={value}>
      {children}
      <Dialog.Root open={loginOpen} onOpenChange={open => { if (!submitting) setLoginOpen(open); }}>
        <Dialog.Portal>
          <Dialog.Overlay className={styles.overlay} />
          <Dialog.Content className={styles.dialog}>
            <Dialog.Close className={styles.close} aria-label="关闭登录弹窗"><X size={17} /></Dialog.Close>
            <header className={styles.welcome}>
              <img className={styles.brand} src="/brand/creative-studio-integrated-v2.png" alt="Creative Studio" />
              <Dialog.Title className={styles.title}>欢迎回来</Dialog.Title>
              <Dialog.Description className={styles.subtitle}>{reason}</Dialog.Description>
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
  const { user, checking, loginOpen, verificationError, retryVerification } = useAuthSession();
  const isPublic = PUBLIC_ROUTES.has(pathname);

  useEffect(() => {
    if (isPublic || checking || user || loginOpen || verificationError) return;
    const next = `${pathname}${window.location.search}`;
    window.location.replace(`/prompts?login=1&next=${encodeURIComponent(next)}`);
  }, [checking, isPublic, loginOpen, pathname, user, verificationError]);

  if (!isPublic && !user && !loginOpen) {
    return (
      <div className={styles.routeLoader} aria-busy="true">
        <div className={styles.routeLoaderInner}>{verificationError
          ? <><span role="alert">{verificationError}</span><button onClick={retryVerification}>重试</button></>
          : <><Loader2 className="animate-spin" />正在打开登录入口</>}</div>
      </div>
    );
  }
  return <>{children}</>;
}
