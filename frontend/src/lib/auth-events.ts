export const AUTH_REQUIRED_EVENT = 'creative-studio:auth-required';
export const AUTH_STATE_CHANGED_EVENT = 'creative-studio:auth-state-changed';

export type AuthRequiredDetail = {
  next?: string;
  reason?: string;
};

export function requestAuthentication(detail: AuthRequiredDetail = {}) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<AuthRequiredDetail>(AUTH_REQUIRED_EVENT, { detail }));
}

export function notifyAuthStateChanged() {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(AUTH_STATE_CHANGED_EVENT));
}
