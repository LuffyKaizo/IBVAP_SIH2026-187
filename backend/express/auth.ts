import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';

// Read lazily: server.ts imports this module before dotenv.config() runs,
// so process.env.SECRET_KEY is not yet populated at module-evaluation time.
export function isProduction(): boolean {
  const env = (process.env.APP_ENV || process.env.NODE_ENV || '').toLowerCase();
  return env === 'production' || env === 'prod';
}

// Production startup guard: hard-fail on missing required env, never fall
// back to development defaults. Called once from startServer().
export function requireProductionEnv(): void {
  if (!isProduction()) return;
  // SCREENING_MODE/VITE_SCREENING_MODE are deliberately allowed here: the
  // deployed demo opts in explicitly via render.yaml (no login page). The
  // hardcoded dev bypass token still must never be active in production.
  const missing = ['SECRET_KEY', 'AI_SERVICE_URL'].filter((k) => !process.env[k]);
  if ((process.env.DEV_AUTH_BYPASS || '').toLowerCase() === 'true') {
    missing.push('DEV_AUTH_BYPASS must not be enabled in production');
  }
  if (missing.length > 0) {
    console.error('[IBVAP FATAL] Production env validation failed:');
    for (const m of missing) console.error('  - ' + m);
    process.exit(1);
  }
}

function getSecretKey(): string {
  const key = process.env.SECRET_KEY;
  if (key) return key;
  if (isProduction()) {
    throw new Error('SECRET_KEY is not set — refusing to authenticate requests in production');
  }
  return 'ibvap-dev-secret-change-in-production-32chars';
}

// Development-only bypass: requires BOTH an explicit opt-in flag and a
// non-production environment. Production never honors the hardcoded token.
function isDevBypassEnabled(): boolean {
  return !isProduction() && (process.env.DEV_AUTH_BYPASS || '').toLowerCase() === 'true';
}

export interface AuthUser {
  user_id: string;
  email: string;
  role: string;
}

declare global {
  namespace Express {
    interface Request {
      user?: AuthUser;
    }
  }
}

const DEV_BYPASS_TOKEN = 'dev-bypass-token';
const DEV_ADMIN_USER: AuthUser = {
  user_id: 'dev-admin',
  email: 'admin@ibvap.local',
  role: 'ADMIN',
};

export function verifyToken(req: Request, res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    res.status(401).json({ detail: 'Not authenticated' });
    return;
  }
  const token = authHeader.substring(7);
  if (isDevBypassEnabled() && token === DEV_BYPASS_TOKEN) {
    req.user = DEV_ADMIN_USER;
    next();
    return;
  }
  try {
    const decoded = jwt.verify(token, getSecretKey()) as AuthUser & { sub: string; exp: number };
    req.user = {
      user_id: decoded.sub || decoded.user_id,
      email: decoded.email,
      role: decoded.role,
    };
    next();
  } catch {
    res.status(401).json({ detail: 'Invalid or expired token' });
  }
}

export function requireRole(...roles: string[]) {
  return (req: Request, res: Response, next: NextFunction): void => {
    if (!req.user) {
      res.status(401).json({ detail: 'Not authenticated' });
      return;
    }
    if (!roles.includes(req.user.role)) {
      res.status(403).json({ detail: 'Insufficient permissions' });
      return;
    }
    next();
  };
}

export function optionalAuth(req: Request, res: Response, next: NextFunction): void {
  const authHeader = req.headers.authorization;
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    next();
    return;
  }
  const token = authHeader.substring(7);
  try {
    const decoded = jwt.verify(token, getSecretKey()) as AuthUser & { sub: string };
    req.user = {
      user_id: decoded.sub || decoded.user_id,
      email: decoded.email,
      role: decoded.role,
    };
  } catch {
    // Ignore invalid token for optional auth
  }
  next();
}
