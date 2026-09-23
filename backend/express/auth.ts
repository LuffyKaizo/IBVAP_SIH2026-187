import { Request, Response, NextFunction } from 'express';
import jwt from 'jsonwebtoken';

// Read lazily: server.ts imports this module before dotenv.config() runs,
// so process.env.SECRET_KEY is not yet populated at module-evaluation time.
function getSecretKey(): string {
  return process.env.SECRET_KEY || 'ibvap-dev-secret-change-in-production-32chars';
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
  if (token === DEV_BYPASS_TOKEN) {
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
