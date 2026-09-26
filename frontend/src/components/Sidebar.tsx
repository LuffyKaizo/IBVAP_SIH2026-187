import React, { useState, useEffect, useRef, useCallback } from 'react';

export type NavPath =
  | 'command-dashboard'
  | 'cameras'
  | 'ai-analytics'
  | 'anpr'
  | 'event-intelligence'
  | 'analytics'
  | 'reports'
  | 'settings';

export type NavItemData = {
  path: NavPath;
  label: string;
  icon: string;
  badge?: number;
  shortcut?: string;
  minRole?: string;
};

export type NavGroupData = {
  heading?: string;
  items: NavItemData[];
};

interface SidebarProps {
  currentPath: NavPath;
  onNavigate: (path: NavPath) => void;
  activeAlertCount?: number;
  isOpen?: boolean;
  onToggle?: () => void;
  userRole?: string;
}

const NAV_GROUPS: NavGroupData[] = [
  {
    heading: 'Operations',
    items: [
      { path: 'command-dashboard', label: 'Dashboard', icon: 'dashboard', shortcut: '⌘1' },
      { path: 'cameras', label: 'Cameras', icon: 'videocam', shortcut: '⌘2' },
      { path: 'event-intelligence', label: 'Alerts', icon: 'crisis_alert', badge: 3 },
    ],
  },
  {
    heading: 'Intelligence',
    items: [
      { path: 'anpr', label: 'ANPR', icon: 'directions_car' },
      { path: 'analytics', label: 'Analytics', icon: 'monitoring' },
      { path: 'ai-analytics', label: 'AI Analytics', icon: 'neurology' },
    ],
  },
  {
    heading: 'System',
    items: [
      { path: 'reports', label: 'Reports', icon: 'description' },
      { path: 'settings', label: 'Settings', icon: 'settings', shortcut: '⌘,', minRole: 'ADMIN' },
    ],
  },
];

function NavItem({
  item,
  activeId,
  onSelect,
  userRole,
}: {
  item: NavItemData;
  activeId: NavPath;
  onSelect: (id: NavPath) => void;
  userRole?: string;
}) {
  const isActive = activeId === item.path;
  if (item.minRole && userRole !== item.minRole && userRole !== 'ADMIN') return null;

  return (
    <button
      onClick={() => onSelect(item.path)}
      className={`w-full flex items-center justify-between px-3 py-2 rounded-lg cursor-pointer transition-all duration-150 select-none text-left ${
        isActive
          ? 'bg-primary/10 text-primary font-semibold'
          : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
      }`}
    >
      <div className="flex items-center gap-2.5">
        <span
          className={`material-symbols-outlined text-[18px] transition-colors ${
            isActive ? 'text-primary' : 'text-on-surface-variant/60 group-hover:text-on-surface/60'
          }`}
          style={{
            fontVariationSettings: isActive ? "'FILL' 1, 'wght' 400" : "'FILL' 0, 'wght' 300",
          }}
        >
          {item.icon}
        </span>
        <span className="text-[13px] tracking-wide truncate">{item.label}</span>
      </div>

      <div className="flex items-center gap-1.5">
        {item.shortcut && (
          <kbd className="hidden group-hover:inline-flex items-center justify-center h-5 px-1.5 text-[9px] font-medium font-mono text-on-surface-variant/40 bg-surface-container-high border border-outline-variant rounded">
            {item.shortcut}
          </kbd>
        )}
        {item.badge !== undefined && item.badge > 0 && (
          <span className="flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[9px] font-bold rounded-full bg-error text-on-error">
            {item.badge}
          </span>
        )}
      </div>
    </button>
  );
}

function SearchModal({ onClose, onNavigate, userRole }: { onClose: () => void; onNavigate: (p: NavPath) => void; userRole?: string }) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const allItems = NAV_GROUPS.flatMap((g) => g.items).filter((item) => !item.minRole || item.minRole === userRole || userRole === 'ADMIN');

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[12vh] bg-on-surface/10 backdrop-blur-sm px-4">
      <div className="absolute inset-0" onClick={onClose} />
      <div className="relative w-full max-w-xl bg-surface border border-outline-variant rounded-xl shadow-xl overflow-hidden">
        <div className="flex items-center px-4 border-b border-outline-variant">
          <span className="material-symbols-outlined text-[18px] text-on-surface-variant/50 mr-3">search</span>
          <input
            ref={inputRef}
            className="flex-1 bg-transparent py-4 outline-none text-[13px] text-on-surface placeholder:text-on-surface-variant/40 font-medium"
            placeholder="Search navigation, cameras, alerts..."
          />
          <kbd
            onClick={onClose}
            className="hidden sm:inline-flex items-center justify-center h-5 px-1.5 ml-2 text-[9px] font-medium font-mono text-on-surface-variant/50 bg-surface-container-high border border-outline-variant rounded cursor-pointer hover:text-on-surface transition-colors"
          >
            ESC
          </kbd>
        </div>

        <div className="p-2 max-h-[300px] overflow-y-auto">
          {allItems.map((item) => (
            <button
              key={item.path + item.label}
              onClick={() => {
                onNavigate(item.path);
                onClose();
              }}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer hover:bg-surface-container-high transition-colors group text-left"
            >
              <span className="material-symbols-outlined text-[16px] text-on-surface-variant/50 group-hover:text-primary transition-colors">
                {item.icon}
              </span>
              <span className="text-[13px] text-on-surface-variant group-hover:text-on-surface transition-colors">
                {item.label}
              </span>
              {item.shortcut && (
                <kbd className="ml-auto text-[9px] font-mono text-on-surface-variant/30 border border-outline-variant rounded px-1 py-0.5">
                  {item.shortcut}
                </kbd>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentPath,
  onNavigate,
  activeAlertCount = 3,
  isOpen = true,
  onToggle,
  userRole,
}) => {
  const [activeId, setActiveId] = useState<NavPath>(currentPath);
  const [isSearchOpen, setIsSearchOpen] = useState(false);

  useEffect(() => {
    setActiveId(currentPath);
  }, [currentPath]);

  const handleSelect = useCallback(
    (id: NavPath) => {
      setActiveId(id);
      onNavigate(id);
    },
    [onNavigate],
  );

  const handleGlobalKey = useCallback((e: KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      setIsSearchOpen((prev) => !prev);
    }
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handleGlobalKey);
    return () => window.removeEventListener('keydown', handleGlobalKey);
  }, [handleGlobalKey]);

  return (
    <>
      <aside className={`fixed left-0 top-14 bottom-0 border-r border-outline-variant bg-surface-container-low flex flex-col z-40 select-none overflow-hidden transition-all duration-300 ease-in-out ${isOpen ? 'w-[260px] opacity-100' : 'w-0 opacity-0 border-r-0'}`}>
        <div className="w-[260px] h-full flex flex-col p-3">
          {/* Search trigger */}
          <button
            onClick={() => setIsSearchOpen(true)}
            className="flex items-center gap-2.5 px-3 py-2 mb-3 rounded-lg bg-surface border border-outline-variant cursor-pointer hover:border-primary/30 hover:bg-surface-container-high transition-all group text-left"
          >
            <span className="material-symbols-outlined text-[16px] text-on-surface-variant/50 group-hover:text-primary transition-colors">search</span>
            <span className="text-[12px] text-on-surface-variant/50">Quick search…</span>
            <kbd className="ml-auto text-[9px] font-mono text-on-surface-variant/30 border border-outline-variant rounded px-1 py-0.5">
              ⌘K
            </kbd>
          </button>

          {/* Navigation */}
          <div className="flex-1 overflow-y-auto [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none] flex flex-col gap-4 mt-1">
            {NAV_GROUPS.map((group, idx) => (
              <div key={idx} className="flex flex-col gap-0.5">
                {group.heading && (
                  <span className="px-3 mb-1 text-[10px] font-bold tracking-[0.12em] text-on-surface-variant/40 uppercase">
                    {group.heading}
                  </span>
                )}
                {group.items.map((item) => (
                  <div key={item.path + item.label} className="group">
                    <NavItem
                      item={item}
                      activeId={activeId}
                      onSelect={handleSelect}
                      userRole={userRole}
                    />
                  </div>
                ))}
              </div>
            ))}
          </div>

          {/* Bottom: System Status */}
          <div className="mt-auto pt-3 border-t border-outline-variant">
            <div className="rounded-lg border border-outline-variant p-3 bg-surface">
              <div className="flex justify-between items-center text-[11px] mb-2">
                <span className="text-on-surface-variant font-medium">System Status</span>
                <span className="text-on-surface-variant font-bold flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant" />
                  —
                </span>
              </div>
              <div className="text-[10px] text-on-surface-variant/60 flex justify-between">
                <span>Streams</span>
                <span className="text-on-surface font-semibold">—</span>
              </div>
            </div>
          </div>
        </div>
      </aside>

      {isSearchOpen && (
        <SearchModal onClose={() => setIsSearchOpen(false)} onNavigate={handleSelect} userRole={userRole} />
      )}
    </>
  );
};
