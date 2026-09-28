import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

export interface AuthUser {
  user_id: string;
  email: string;
  full_name: string;
  role: 'ADMIN' | 'OPERATOR' | 'VIEWER';
}

interface AuthContextType {
  token: string | null;
  user: AuthUser | null;
  isAuthenticated: boolean;
  isInitializing: boolean;
  demoMode: boolean;
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  demoLogin: () => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  getAuthHeaders: () => Record<string, string>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'ibvap_token';
const USER_KEY = 'ibvap_user';

// Demo / Screening mode is opt-in only, and requires BOTH flags to be
// explicitly the string "true":
//   - client flag: import.meta.env.VITE_SCREENING_MODE === "true"
//     (undefined/missing/anything-else => normal mode, never demo)
//   - server flag: SCREENING_MODE === "true", enforced by the existing
//     screening-login endpoint (403/404 otherwise).
// Entry is decided solely by these flags — a saved token can never skip
// the Login page.
const isScreeningMode = import.meta.env.VITE_SCREENING_MODE === 'true';

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  // Session always starts empty: normal mode shows Login immediately,
  // demo mode establishes a fresh bypass session below.
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  // Loading state only in screening mode, held until the bypass outcome is
  // known so the Login page never flashes before the Dashboard opens.
  const [isInitializing, setIsInitializing] = useState(isScreeningMode);

  const isAuthenticated = token !== null && user !== null;

  useEffect(() => {
    let cancelled = false;

    // Remove tokens saved by older builds so a stale session can never
    // bypass Login in normal mode.
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);

    if (!isScreeningMode) {
      // Normal mode: nothing to probe — show the Login page right away.
      setIsInitializing(false);
      return;
    }

    // Screening mode: reuse the existing server-side bypass. Only a
    // successful response proves SCREENING_MODE=true on the server;
    // otherwise fall through to the Login page.
    (async () => {
      try {
        const res = await fetch('/api/auth/screening-login', { method: 'POST' });
        if (res.ok) {
          const data = await res.json().catch(() => ({}));
          if (!cancelled && data?.access_token && data?.user) {
            setToken(data.access_token);
            setUser(data.user);
            setDemoMode(true);
          }
        }
      } catch { /* server unreachable — Login page */ }
      if (!cancelled) setIsInitializing(false);
    })();

    return () => { cancelled = true; };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        return { success: false, error: body.detail || 'Login failed' };
      }
      const data = await res.json();
      setToken(data.access_token);
      setUser(data.user);
      // Session lives in memory only — never persisted, so a reload always
      // re-evaluates the mode flags and shows the Login page in normal mode.
      return { success: true };
    } catch (err) {
      return { success: false, error: 'Network error' };
    }
  }, []);

  // Demo Mode button: reuse the EXISTING screening bypass
  // (/api/auth/screening-login) to establish a real session — the same
  // session/token/navigation entry a normal login produces. The server
  // only honors it when SCREENING_MODE=true; no new auth endpoint.
  const demoLogin = useCallback(async () => {
    try {
      const res = await fetch('/api/auth/screening-login', { method: 'POST' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        return { success: false, error: body.detail || 'Demo mode is disabled on this server' };
      }
      const data = await res.json();
      if (!data?.access_token || !data?.user) {
        return { success: false, error: 'Demo session could not be created' };
      }
      setToken(data.access_token);
      setUser(data.user);
      setDemoMode(true);
      return { success: true };
    } catch {
      return { success: false, error: 'Demo service unavailable' };
    }
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }, []);

  const getAuthHeaders = useCallback(() => {
    if (!token) return {};
    return { Authorization: `Bearer ${token}` };
  }, [token]);

  return (
    <AuthContext.Provider
      value={{ token, user, isAuthenticated, isInitializing, demoMode, login, demoLogin, logout, getAuthHeaders }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
