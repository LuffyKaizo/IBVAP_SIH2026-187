import React, { useState, useEffect } from 'react';
import { ThemeToggle } from './ThemeToggle';

interface HeaderProps {
  isOperational?: boolean;
  onOpenDiagnostics?: () => void;
  onNavigateToAlerts?: () => void;
  activeAlertCount?: number;
  userName?: string;
  userRole?: string;
  onLogout?: () => void;
  isSidebarOpen?: boolean;
  onToggleSidebar?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  isOperational = true,
  onOpenDiagnostics,
  onNavigateToAlerts,
  activeAlertCount = 3,
  userName = 'COMMANDER SHARMA',
  userRole = 'DUTY COMMANDER',
  onLogout,
  isSidebarOpen = true,
  onToggleSidebar,
}) => {
  const [utcTime, setUtcTime] = useState<string>('00:00:00 UTC');

  useEffect(() => {
    const updateClock = () => {
      const now = new Date();
      setUtcTime(now.toISOString().substring(11, 19) + ' UTC');
    };
    updateClock();
    const interval = setInterval(updateClock, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-surface border-b border-outline-variant z-50 flex items-center px-4 justify-between select-none">
      {/* Left: Brand */}
      <div className="flex items-center gap-3">
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="p-1.5 rounded-lg hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
            title={isSidebarOpen ? 'Collapse Sidebar' : 'Expand Sidebar'}
          >
            <span className="material-symbols-outlined text-[20px]">
              {isSidebarOpen ? 'menu_open' : 'menu'}
            </span>
          </button>
        )}
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-on-primary font-bold font-mono text-[11px] tracking-wider">
          IB
        </div>
        <div className="flex flex-col">
          <span className="text-[13px] font-bold text-primary tracking-[0.06em] leading-none">
            IBVAP
          </span>
          <span className="text-[10px] text-on-surface-variant leading-none mt-0.5 hidden sm:block">
            Intelligent Border Video Analytics Platform
          </span>
        </div>

        {/* System Status */}
        <div className="hidden md:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-surface-container-low border border-outline-variant">
          <span className={`w-2 h-2 rounded-full ${isOperational ? 'bg-success' : 'bg-error'}`} />
          <span className="text-[10px] font-semibold text-on-surface tracking-wider">
            {isOperational ? 'SYSTEM ONLINE' : 'FAULT'}
          </span>
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-2 sm:gap-3">
        {/* Alerts */}
        {activeAlertCount > 0 ? (
          <button
            onClick={onNavigateToAlerts}
            className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-error-container border border-error/20 text-on-error-container rounded-lg text-[11px] font-bold cursor-pointer hover:bg-error/10 transition-colors"
          >
            <span className="material-symbols-outlined text-[14px]">crisis_alert</span>
            <span>ALERTS: {activeAlertCount}</span>
          </button>
        ) : (
          <div className="hidden sm:flex items-center gap-1.5 px-3 py-1.5 bg-success-container border border-success/20 text-success rounded-lg text-[11px] font-semibold">
            <span className="material-symbols-outlined text-[14px]">check_circle</span>
            <span>ALL SECURE</span>
          </div>
        )}

        {/* Health */}
        {onOpenDiagnostics && (
          <button
            onClick={onOpenDiagnostics}
            className="hidden md:flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-container-low hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
            title="System Health"
          >
            <span className="material-symbols-outlined text-[15px] text-primary">health_and_safety</span>
            <span>Health</span>
          </button>
        )}

        <ThemeToggle />

        {/* UTC Time */}
        <div className="hidden sm:flex flex-col items-end border-l border-outline-variant pl-3">
          <span className="text-[9px] text-on-surface-variant font-mono tracking-wider">UTC</span>
          <span className="text-[11px] font-mono font-bold text-on-surface">{utcTime}</span>
        </div>

        {/* Operator */}
        <div className="flex items-center gap-2 border-l border-outline-variant pl-3">
          <div className="flex flex-col items-end hidden lg:flex">
            <span className="text-[9px] text-on-surface-variant font-medium">{userRole}</span>
            <span className="text-[11px] text-primary font-bold">{userName}</span>
          </div>
          <div className="w-8 h-8 rounded-lg bg-primary-container text-primary flex items-center justify-center">
            <span className="material-symbols-outlined text-[17px]">person</span>
          </div>
          {onLogout && (
            <button
              onClick={onLogout}
              className="ml-1 p-1.5 rounded-lg hover:bg-error-container text-on-surface-variant hover:text-error transition-colors cursor-pointer"
              title="Sign Out"
            >
              <span className="material-symbols-outlined text-[17px]">logout</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
