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
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  getAuthHeaders: () => Record<string, string>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'ibvap_token';
const USER_KEY = 'ibvap_user';

function loadPersistedAuth(): { token: string | null; user: AuthUser | null } {
  try {
    const token = localStorage.getItem(TOKEN_KEY);
    const userRaw = localStorage.getItem(USER_KEY);
    if (token && userRaw) {
      return { token, user: JSON.parse(userRaw) };
    }
  } catch { /* ignore */ }
  return { token: null, user: null };
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const persisted = loadPersistedAuth();
  const [token, setToken] = useState<string | null>(persisted.token);
  const [user, setUser] = useState<AuthUser | null>(persisted.user);
  const [isInitializing, setIsInitializing] = useState(
    import.meta.env.VITE_SCREENING_MODE === 'true' && !persisted.token,
  );

  const isAuthenticated = token !== null && user !== null;

  // Verify persisted token on mount
  useEffect(() => {
    if (persisted.token && persisted.user) {
      fetch('/api/auth/me', {
        headers: { Authorization: `Bearer ${persisted.token}` },
      }).then((res) => {
        if (!res.ok) {
          // Token invalid — clear
          setToken(null);
          setUser(null);
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
        }
      }).catch(() => {
        // Network error — keep token, try later
      }).finally(() => {
        setIsInitializing(false);
      });
    } else {
      setIsInitializing(false);
    }
  }, []);

  // Screening-mode auto-login: call server-side endpoint without credentials.
  // The server generates a real JWT for the actual admin user when SCREENING_MODE=true.
  useEffect(() => {
    if (import.meta.env.VITE_SCREENING_MODE === 'true' && !isAuthenticated) {
      let cancelled = false;
      fetch('/api/auth/screening-login', { method: 'POST' })
        .then((res) => {
          if (!res.ok) return null;
          return res.json();
        })
        .then((data) => {
          if (cancelled || !data?.access_token || !data?.user) return;
          setToken(data.access_token);
          setUser(data.user);
          localStorage.setItem(TOKEN_KEY, data.access_token);
          localStorage.setItem(USER_KEY, JSON.stringify(data.user));
        })
        .catch(() => { /* screening endpoint unavailable — fall through to LoginView */ })
        .finally(() => { if (!cancelled) setIsInitializing(false); });
      return () => { cancelled = true; };
    }
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
      // Persist to localStorage
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      return { success: true };
    } catch (err) {
      return { success: false, error: 'Network error' };
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
    <AuthContext.Provider value={{ token, user, isAuthenticated, isInitializing, login, logout, getAuthHeaders }}>
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
