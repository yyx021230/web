'use client';

import { useEffect } from 'react';
import { usePathname } from 'next/navigation';
import AppSidebar from '@/components/navigation/AppSidebar';
import { AuthRouteGate, AuthSessionProvider } from '@/components/auth/AuthSession';
import shell from '@/components/navigation/workspace-shell.module.css';

function MainLayoutInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className={shell.shell}>
      <AppSidebar pathname={pathname} />
      <main className={shell.viewport}>
        <div key={pathname} className={shell.routeStage}>{children}</div>
      </main>
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

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthSessionProvider>
      <DevAutoLogin />
      <MainLayoutInner>
        <AuthRouteGate>{children}</AuthRouteGate>
      </MainLayoutInner>
    </AuthSessionProvider>
  );
}
