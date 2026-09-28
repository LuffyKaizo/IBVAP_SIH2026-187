import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion } from 'motion/react';
import CursorGrid from '../components/CursorGrid';
import { useTheme } from '../components/ThemeProvider';
import { useAuth } from '../contexts/AuthContext';

interface LoginViewProps {
  onLogin: (username: string, role?: string) => void;
}

const ORBITAL_NODES = [
  { label: 'YOLOv8x', sublabel: 'Real-Time Detection', color: '#3E7655', startAngle: 0 },
  { label: 'ANPR', sublabel: 'Plate OCR Engine', color: '#3E7655', startAngle: 120 },
  { label: 'Tripwire', sublabel: 'Intrusion Detection', color: '#356B7A', startAngle: 240 },
];

const TRUST_METRICS = [
  { value: '99.9%', label: 'Uptime' },
  { value: '<32ms', label: 'Inference' },
];

const ORBIT_RADIUS = 80;
const ORBIT_PERIOD = 20;

function useOrbitPositions(nodeCount: number) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cardRefs = useRef<(HTMLDivElement | null)[]>([]);

  const setCardRef = useCallback((el: HTMLDivElement | null, index: number) => {
    cardRefs.current[index] = el;
  }, []);

  useEffect(() => {
    const start = performance.now();
    let raf: number;

    const tick = (now: number) => {
      const elapsed = (now - start) / 1000;
      const angularSpeed = (2 * Math.PI) / ORBIT_PERIOD;

      for (let i = 0; i < nodeCount; i++) {
        const card = cardRefs.current[i];
        if (!card) continue;
        const baseAngle = (ORBITAL_NODES[i]?.startAngle ?? 0) * (Math.PI / 180);
        const angle = baseAngle + elapsed * angularSpeed;
        const x = Math.cos(angle) * ORBIT_RADIUS;
        const y = Math.sin(angle) * ORBIT_RADIUS;
        card.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px)`;
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [nodeCount]);

  return { containerRef, setCardRef };
}

export const LoginView: React.FC<LoginViewProps> = ({ onLogin }) => {
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const { containerRef, setCardRef } = useOrbitPositions(ORBITAL_NODES.length);
  const { login, demoLogin } = useAuth();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isDemoLoading, setIsDemoLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [utcTime, setUtcTime] = useState(new Date().toISOString().substring(11, 19));

  useEffect(() => {
    const interval = setInterval(
      () => setUtcTime(new Date().toISOString().substring(11, 19)),
      1000,
    );
    return () => clearInterval(interval);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) {
      setErrorMsg('Please enter a valid email address.');
      return;
    }
    if (!password.trim()) {
      setErrorMsg('Please enter your password.');
      return;
    }
    setErrorMsg(null);
    setIsLoading(true);
    const result = await login(email.trim(), password);
    setIsLoading(false);
    if (!result.success) {
      setErrorMsg(result.error || 'Login failed. Please check your credentials.');
    }
  };

  const handleQuickDemo = async () => {
    setErrorMsg(null);
    setIsDemoLoading(true);
    // Enters the existing application through the existing screening
    // bypass — same session + same App entry path as a normal login.
    const result = await demoLogin();
    setIsDemoLoading(false);
    if (!result.success) {
      setErrorMsg(result.error || 'Demo mode is unavailable.');
    }
  };

  const handleOAuthLogin = (_provider: string) => {
    setErrorMsg('SSO login coming soon. Use email/password.');
  };

  return (
    <div className="relative min-h-screen w-full flex flex-col justify-between p-4 sm:p-6 lg:p-8 select-none overflow-hidden bg-background text-on-surface">
      {/* Cursor Grid Background */}
      <div className="absolute inset-0 z-0 pointer-events-none">
        <CursorGrid
          cellSize={70}
          color={isDark ? '#5A6A6C' : '#A4B2B0'}
          radius={160}
          falloff="smooth"
          holdTime={500}
          fadeDuration={1000}
          lineWidth={0.8}
          maxOpacity={isDark ? 0.3 : 0.15}
          fillOpacity={0}
          gridOpacity={isDark ? 0.05 : 0.03}
          cellRadius={2}
          clickPulse
          pulseSpeed={500}
          className="pointer-events-auto"
        />
      </div>

      {/* HEADER */}
      <motion.header
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-6xl mx-auto flex items-center justify-between py-2"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center text-on-primary font-bold font-mono text-sm tracking-wider">
            IB
          </div>
          <div>
            <div className="text-sm font-bold text-primary tracking-[0.12em] font-mono uppercase">
              IBVAP
            </div>
            <div className="text-[11px] text-on-surface-variant tracking-wide">
              Intelligent Border Video Analytics Platform
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 border border-outline-variant rounded-lg text-[11px] text-on-surface-variant font-mono bg-surface/80">
            <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
            <span>ENCRYPTED</span>
          </div>
          <div className="px-3 py-1.5 border border-outline-variant rounded-lg text-[11px] text-on-surface-variant font-mono tracking-wider bg-surface/80">
            {utcTime} UTC
          </div>
        </div>
      </motion.header>

      {/* MAIN SPLIT-PANEL CARD */}
      <main className="relative z-10 w-full max-w-6xl mx-auto my-auto py-4">
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="backdrop-blur-xl border border-outline-variant rounded-2xl shadow-lg overflow-hidden grid grid-cols-1 lg:grid-cols-12 bg-surface/95"
        >
          {/* LEFT PANEL — Sign-In */}
          <div className="lg:col-span-7 p-6 sm:p-8 lg:p-10 flex flex-col justify-between relative">
            <div
              className="absolute top-0 left-0 right-0 h-[1px]"
              style={{
                background: 'linear-gradient(to right, transparent, rgba(53,107,122,0.3), transparent)',
              }}
            />

            <div>
              <motion.div
                initial={{ opacity: 0, x: -16 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.15, duration: 0.5 }}
                className="mb-7"
              >
                <div className="flex items-center gap-2 mb-3">
                  <div className="w-1 h-6 rounded-full bg-primary" />
                  <h1 className="text-2xl font-bold text-on-surface tracking-tight font-mono">
                    Welcome back
                  </h1>
                </div>
                <p className="text-[13px] text-on-surface-variant pl-3">
                  Sign in to access the intelligence and surveillance console.
                </p>
              </motion.div>

              {/* OAuth Buttons */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.25, duration: 0.45 }}
                className="grid grid-cols-2 gap-3 mb-6"
              >
                <button
                  type="button"
                  onClick={() => handleOAuthLogin('DefenseSSO')}
                  className="group py-3 px-4 border border-outline-variant rounded-xl text-[13px] font-semibold text-on-surface flex items-center justify-center gap-2.5 transition-all duration-200 cursor-pointer bg-surface-container-low hover:bg-surface-container-high hover:border-primary/30"
                >
                  <span className="material-symbols-outlined text-[18px] text-on-surface-variant group-hover:text-primary transition-colors">
                    shield
                  </span>
                  Defense SSO
                </button>
                <button
                  type="button"
                  onClick={() => handleOAuthLogin('GovC2')}
                  className="group py-3 px-4 border border-outline-variant rounded-xl text-[13px] font-semibold text-on-surface flex items-center justify-center gap-2.5 transition-all duration-200 cursor-pointer bg-surface-container-low hover:bg-surface-container-high hover:border-tertiary/30"
                >
                  <span className="material-symbols-outlined text-[18px] text-on-surface-variant group-hover:text-tertiary transition-colors">
                    account_tree
                  </span>
                  National C2 Hub
                </button>
              </motion.div>

              {/* Divider */}
              <div className="flex items-center gap-3 mb-6">
                <div className="flex-1 h-px bg-outline-variant" />
                <span className="text-[10px] font-semibold tracking-wider text-on-surface-variant">
                  OPERATOR CREDENTIALS
                </span>
                <div className="flex-1 h-px bg-outline-variant" />
              </div>

              {/* Form */}
              <form onSubmit={handleSubmit}>
                {/* Email */}
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.3, duration: 0.4 }}
                  className="mb-4"
                >
                  <label className="text-[11px] font-bold text-on-surface-variant tracking-wider block mb-1.5">
                    EMAIL ADDRESS
                  </label>
                  <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl border border-outline-variant bg-surface-container-low transition-all focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/10">
                    <span className="material-symbols-outlined text-[18px] text-on-surface-variant">
                      person
                    </span>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="flex-1 bg-transparent outline-none text-[14px] font-mono text-on-surface placeholder:text-on-surface-variant/50"
                      placeholder="you@example.com"
                      autoComplete="email"
                    />
                  </div>
                </motion.div>

                {/* Password */}
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.35, duration: 0.4 }}
                  className="mb-5"
                >
                  <label className="text-[11px] font-bold text-on-surface-variant tracking-wider block mb-1.5">
                    PASSWORD
                  </label>
                  <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl border border-outline-variant bg-surface-container-low transition-all focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/10">
                    <span className="material-symbols-outlined text-[18px] text-on-surface-variant">
                      lock
                    </span>
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="flex-1 bg-transparent outline-none text-[14px] text-on-surface placeholder:text-on-surface-variant/50"
                      placeholder="••••••••"
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="p-1 rounded-lg hover:bg-surface-container-high transition-colors cursor-pointer"
                      tabIndex={-1}
                    >
                      <span className="material-symbols-outlined text-[18px] text-on-surface-variant">
                        {showPassword ? 'visibility_off' : 'visibility'}
                      </span>
                    </button>
                  </div>
                </motion.div>

                {/* Remember Me */}
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.4, duration: 0.4 }}
                  className="flex items-center justify-between mb-6"
                >
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <div
                      className={`relative w-4 h-4 rounded border-2 transition-all flex items-center justify-center ${
                        rememberMe
                          ? 'bg-primary border-primary'
                          : 'border-outline-variant bg-transparent group-hover:border-on-surface-variant'
                      }`}
                      onClick={() => setRememberMe(!rememberMe)}
                    >
                      {rememberMe && (
                        <span className="material-symbols-outlined text-on-primary text-[12px]">
                          check
                        </span>
                      )}
                    </div>
                    <span className="text-[12px] text-on-surface-variant">
                      Remember this operator
                    </span>
                  </label>
                  <button
                    type="button"
                    className="text-[12px] font-semibold text-primary hover:underline cursor-pointer"
                  >
                    Forgot password?
                  </button>
                </motion.div>

                {/* Error */}
                {errorMsg && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="mb-4 px-3 py-2 rounded-lg bg-error-container border border-error/20 text-error text-[12px] font-medium"
                  >
                    {errorMsg}
                  </motion.div>
                )}

                {/* Submit */}
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.45, duration: 0.4 }}
                >
                  <button
                    type="submit"
                    disabled={isLoading}
                    className={`w-full py-3 rounded-xl text-[13px] font-bold tracking-wider transition-all duration-200 cursor-pointer ${
                      isLoading
                        ? 'bg-primary/50 text-on-primary/70 cursor-wait'
                        : 'bg-primary hover:bg-primary/90 text-on-primary shadow-sm hover:shadow-md'
                    }`}
                  >
                    {isLoading ? (
                      <span className="flex items-center justify-center gap-2">
                        <span className="w-4 h-4 border-2 border-on-primary/30 border-t-on-primary rounded-full animate-spin" />
                        AUTHENTICATING…
                      </span>
                    ) : (
                      'SIGN IN TO CONSOLE'
                    )}
                  </button>
                </motion.div>
              </form>
            </div>

            {/* Quick Demo */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.6, duration: 0.5 }}
              className="mt-6 pt-4 border-t border-outline-variant"
            >
              <button
                type="button"
                onClick={handleQuickDemo}
                disabled={isDemoLoading || isLoading}
                className="w-full py-2.5 rounded-xl text-[12px] font-semibold border border-dashed border-outline-variant text-on-surface-variant hover:border-primary/40 hover:text-primary hover:bg-primary/5 transition-all cursor-pointer disabled:opacity-60 disabled:cursor-wait"
              >
                <span className="material-symbols-outlined text-[14px] mr-1.5 align-middle">
                  rocket_launch
                </span>
                {isDemoLoading ? 'ENTERING DEMO…' : 'Demo Mode'}
              </button>
            </motion.div>
          </div>

          {/* RIGHT PANEL — Orbital Trust Ring */}
          <div className="lg:col-span-5 relative flex flex-col items-center justify-center p-8 overflow-hidden bg-gradient-to-br from-background via-surface-dim to-surface-container-low">
            <div
              className="absolute top-0 left-0 right-0 h-[1px]"
              style={{
                background: 'linear-gradient(to right, transparent, rgba(53,107,122,0.2), transparent)',
              }}
            />

            {/* Orbital Rings Container */}
            <div className="relative w-[320px] h-[320px] flex items-center justify-center">
              {/* Outer Ring */}
              <div
                className="absolute inset-0 rounded-full border border-primary/10"
                style={{ animation: 'orbital-spin 30s linear infinite' }}
              />

              {/* Middle Ring */}
              <div
                className="absolute rounded-full border border-dashed border-primary/15"
                style={{ inset: '25%', animation: 'orbital-spin-reverse 20s linear infinite' }}
              />

              {/* Inner Ring */}
              <div
                className="absolute rounded-full border border-tertiary/12"
                style={{ inset: '38%', animation: 'orbital-pulse 4s ease-in-out infinite' }}
              />

              {/* Trust Badge Nodes — JS-driven orbit, always horizontal */}
              <div ref={containerRef} className="absolute inset-0 flex items-center justify-center pointer-events-none">
                {ORBITAL_NODES.map((node, i) => (
                  <div
                    key={node.label}
                    ref={(el) => setCardRef(el, i)}
                    className="absolute pointer-events-auto"
                    style={{ willChange: 'transform' }}
                  >
                    <div className="px-2 py-1 rounded-lg border border-outline-variant text-center whitespace-nowrap bg-surface/90">
                      <div className="w-1.5 h-1.5 rounded-full mx-auto mb-0.5" style={{ background: node.color }} />
                      <div className="text-[8px] font-bold tracking-wide text-on-surface">{node.label}</div>
                      <div className="text-[7px] text-on-surface-variant">{node.sublabel}</div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Center Hub */}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="relative">
                  <div className="absolute inset-[-8px] rounded-full border-2 border-primary/15" style={{ animation: 'orbital-pulse 3s ease-in-out infinite' }} />
                  <div className="w-16 h-16 rounded-full flex items-center justify-center border-2 border-primary/20 shadow-md bg-surface">
                    <span className="material-symbols-outlined text-[28px] text-primary">shield</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Quote Card */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5, duration: 0.5 }}
              className="mt-6 p-4 rounded-xl border border-outline-variant bg-surface/80 max-w-[300px]"
            >
              <div className="flex items-center gap-2 mb-2">
                <div className="w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-bold bg-primary-container text-primary">
                  AS
                </div>
                <div>
                  <div className="text-[12px] font-semibold text-on-surface">Commander A. Sharma</div>
                  <div className="text-[10px] text-on-surface-variant">Duty Commander · Sector 04</div>
                </div>
                <span className="material-symbols-outlined text-[14px] text-primary ml-auto">verified</span>
              </div>
              <p className="text-[12px] leading-relaxed italic text-on-surface-variant">
                "IBVAP has transformed our border surveillance capability. Response time reduced
                by 60% with AI-powered threat detection."
              </p>
            </motion.div>

            {/* Trust Metrics */}
            <div className="flex items-center gap-6 mt-5">
              {TRUST_METRICS.map((metric) => (
                <div key={metric.label} className="text-center">
                  <div className="text-[16px] font-bold font-mono text-on-surface">{metric.value}</div>
                  <div className="text-[10px] text-on-surface-variant">{metric.label}</div>
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      </main>

      {/* FOOTER */}
      <motion.footer
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.7, duration: 0.5 }}
        className="relative z-10 w-full max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between py-2 gap-2"
      >
        <div className="flex items-center gap-2 text-[10px] text-on-surface-variant">
          <span className="material-symbols-outlined text-[12px]">gpp_maybe</span>
          <span>CLASSIFICATION: RESTRICTED</span>
        </div>
        <div className="text-[10px] text-on-surface-variant">
          Authorized personnel only · All access logged · {new Date().getFullYear()} IBVAP
        </div>
      </motion.footer>
    </div>
  );
};

export default LoginView;
