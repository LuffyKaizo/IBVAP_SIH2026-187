import { useAiAlerts } from './hooks/useAiAlerts';
import { useAiAnpr } from './hooks/useAiAnpr';
import React, { useState, useEffect, useCallback } from 'react';
import { Header } from './components/Header';
import { Sidebar, NavPath } from './components/Sidebar';
import { Footer } from './components/Footer';
import { CommandPaletteModal } from './components/CommandPaletteModal';
import { SystemDiagnosticsModal } from './components/SystemDiagnosticsModal';
import { AuthProvider, useAuth } from './contexts/AuthContext';

// IBVAP Core Views
import { LoginView } from './views/LoginView';
import { CommandDashboardView } from './views/CommandDashboardView';
import { CamerasMonitoringView } from './views/CamerasMonitoringView';
import { AiAnalyticsView } from './views/AiAnalyticsView';
import { AnprView } from './views/AnprView';
import { IntrusionZonesView } from './views/IntrusionZonesView';
import { EventIntelligenceView } from './views/EventIntelligenceView';
import { AnalyticsView } from './views/AnalyticsView';
import { ReportsView } from './views/ReportsView';
import { SettingsView } from './views/SettingsView';

import {
  CameraFeed,
  BorderAlert,
  AnprRecord,
  VirtualZone,
  SuspiciousEventItem,
  HourlySurveillanceActivity,
  SurveillanceReportItem,
  SystemSettingsConfig,
  IbvapDashboardStats,
} from './types';

import {
  INITIAL_SYSTEM_CONFIG,
} from './mockData';

export const AppInner: React.FC = () => {
  const { isAuthenticated, isInitializing, user, logout, getAuthHeaders } = useAuth();

  // Authenticated fetch helper — includes JWT in all API calls
  const authFetch = useCallback(async (url: string, init?: RequestInit): Promise<Response> => {
    const headers: Record<string, string> = {
      ...getAuthHeaders(),
      ...(init?.headers as Record<string, string> || {}),
    };
    return fetch(url, { ...init, headers });
  }, [getAuthHeaders]);
  const [currentPath, setCurrentPath] = useState<NavPath>('command-dashboard');
  const [selectedCameraId, setSelectedCameraId] = useState<string>('CAM-04');
  const [selectedAlertId, setSelectedAlertId] = useState<string>('ALT-8821');
  const [isOperational, setIsOperational] = useState(true);

  const [cameras, setCameras] = useState<CameraFeed[]>([]);
  const [alerts, setAlerts] = useState<BorderAlert[]>([]);
  const [anprRecords, setAnprRecords] = useState<AnprRecord[]>([]);
  const [zones, setZones] = useState<VirtualZone[]>([]);
  const [suspiciousEvents, setSuspiciousEvents] = useState<SuspiciousEventItem[]>([]);
  const [hourlyActivity, setHourlyActivity] = useState<HourlySurveillanceActivity[]>(
    Array.from({ length: 24 }, (_, i) => ({
      hour: `${String(i).padStart(2, '0')}:00`,
      hourNum: i,
      peopleCount: 0,
      vehicleCount: 0,
      alertsCount: 0,
      anprHits: 0,
      intrusionBreaches: 0,
      nightActivityIndex: 0,
      totalDensity: 0,
    }))
  );
  const [reports, setReports] = useState<SurveillanceReportItem[]>([]);
  const [systemConfig, setSystemConfig] = useState<SystemSettingsConfig>(INITIAL_SYSTEM_CONFIG);
  const [dashboardStats, setDashboardStats] = useState<IbvapDashboardStats>({
    activeCameras: 0,
    totalCameras: 0,
    peopleDetected: 0,
    vehiclesDetected: 0,
    activeAlerts: 0,
    anprEvents: 0,
    intrusionEvents: 0,
    systemHealthPercent: 0,
    alertsBySeverity: { critical: 0, high: 0, medium: 0, info: 0 },
  });

  // AI alert integration
  const { aiAlerts, processMetadata: processAiMetadata, handleAction: handleAiAlertAction, clearAlerts: clearAiAlerts } = useAiAlerts();
  const { aiAnprRecords, processMetadata: processAiAnprMetadata } = useAiAnpr();

  // Combined metadata processor for alerts, ANPR, hourly activity, and suspicious events
  const processAllAiMetadata = useCallback((metadata: any) => {
    processAiMetadata(metadata);
    processAiAnprMetadata(metadata);

    // Accumulate hourly activity from real detections
    if (metadata?.detections && Array.isArray(metadata.detections)) {
      const now = new Date();
      const currentHour = now.getHours();
      setHourlyActivity((prev) => {
        const updated = [...prev];
        const entry = { ...updated[currentHour] };
        for (const det of metadata.detections) {
          if (det.class_name === 'person') entry.peopleCount += 1;
          else if (['car', 'truck', 'bus', 'motorcycle'].includes(det.class_name)) entry.vehicleCount += 1;
        }
        updated[currentHour] = entry;
        return updated;
      });
    }

    // Accumulate suspicious events from real backend events
    if (metadata?.events && Array.isArray(metadata.events)) {
      setSuspiciousEvents((prev) => {
        const existingIds = new Set(prev.map((e) => e.id));
        const newEvents: SuspiciousEventItem[] = metadata.events
          .filter((e: any) => !existingIds.has(e.event_id))
          .map((e: any) => ({
            id: e.event_id,
            timestamp: new Date(e.timestamp).toLocaleTimeString('en-US', { hour12: false }) + ' UTC',
            cameraId: e.camera_id,
            eventType: e.event_type,
            severity: e.severity,
            trackId: `#${e.track_id}`,
            zone: e.zone_name || e.zone_id,
            description: `${e.event_type.replace(/_/g, ' ').toLowerCase()} detected`,
            status: e.status,
          }));
        return [...newEvents, ...prev].slice(0, 50); // Keep last 50
      });
    }

    // Update dashboard stats from real data
    if (metadata?.camera) {
      setDashboardStats((prev) => ({
        ...prev,
        activeCameras: metadata.camera.connected ? 1 : 0,
      }));
    }
  }, [processAiMetadata, processAiAnprMetadata]);

  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isDiagnosticsModalOpen, setIsDiagnosticsModalOpen] = useState(false);

  // API Ingestion
  const fetchCameras = useCallback(async () => {
    try {
      const res = await authFetch('/api/cameras');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) setCameras(data);
      }
    } catch { /* fallback */ }
  }, [authFetch]);

  const fetchAlerts = useCallback(async () => {
    try {
      const res = await authFetch('/api/alerts');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setAlerts(data);
      }
    } catch { /* fallback */ }
  }, [authFetch]);

  const fetchDashboardStats = useCallback(async () => {
    try {
      const res = await authFetch('/api/dashboard/stats');
      if (res.ok) {
        const data = await res.json();
        setDashboardStats((prev) => ({ ...prev, ...data }));
      }
    } catch { /* fallback */ }
  }, [authFetch]);

  const fetchReports = useCallback(async () => {
    try {
      const res = await authFetch('/api/reports');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setReports(data);
      }
    } catch { /* fallback */ }
  }, [authFetch]);

  const fetchZones = useCallback(async () => {
    try {
      const res = await authFetch('/api/zones');
      if (res.ok) {
        const data = await res.json();
        const zoneList = data.zones || data;
        if (Array.isArray(zoneList) && zoneList.length > 0) {
          setZones(zoneList.map((z: any) => ({
            id: z.id,
            name: z.name,
            cameraId: z.camera_id,
            type: z.zone_type || 'POLYGON_ZONE',
            coordinates: (z.points || []).map((p: any) => ({ x: p.x * 100, y: p.y * 100 })),
            severity: z.severity || 'CRITICAL',
            rule: z.rule || 'RESTRICTED_ENTRY',
            loiteringThresholdSec: 30,
            isActive: z.enabled !== false,
            color: z.severity === 'CRITICAL' ? '#ef4444' : z.severity === 'HIGH' ? '#f97316' : '#eab308',
          })));
        }
      }
    } catch { /* fallback */ }
  }, [authFetch]);

  useEffect(() => {
    fetchCameras();
    fetchAlerts();
    fetchDashboardStats();
    fetchReports();
    fetchZones();
    // Periodic refresh for dashboard stats
    const statsInterval = setInterval(fetchDashboardStats, 10000);
    return () => clearInterval(statsInterval);
  }, [fetchCameras, fetchAlerts, fetchDashboardStats, fetchReports, fetchZones]);

  // Global Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleSelectCamera = (id: string) => { setSelectedCameraId(id); setCurrentPath('cameras'); };
  const handleSelectAlert = (id: string) => { setSelectedAlertId(id); setCurrentPath('event-intelligence'); };
  const handleActionAlert = (id: string, action: 'ACKNOWLEDGE' | 'RESOLVE') => {
    setAlerts((prev) => prev.map((a) => (a.id === id ? { ...a, status: action === 'ACKNOWLEDGE' ? 'ACKNOWLEDGED' : 'RESOLVED' } : a)));
    // Also handle AI alerts
    handleAiAlertAction(id, action);
  };

  const handleAddCamera = async (newCam: { camera_id: string; name: string; source: string; source_type: string; location: string; camera_type?: string }) => {
    try {
      const res = await authFetch('/api/cameras', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newCam),
      });
      if (res.ok) {
        await fetchCameras();
      }
    } catch { /* ignore */ }
  };
  const handleAddAnprRecord = (newRec: AnprRecord) => { setAnprRecords((prev) => [newRec, ...prev]); };
  const handleSaveZone = (newZone: VirtualZone) => {
    setZones((prev) => { const idx = prev.findIndex((z) => z.id === newZone.id); if (idx >= 0) { const c = [...prev]; c[idx] = newZone; return c; } return [newZone, ...prev]; });
    // Persist to backend
    authFetch('/api/zones', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: newZone.id,
        camera_id: newZone.cameraId,
        name: newZone.name,
        points: (newZone.coordinates || []).map((c) => ({ x: c.x / 100, y: c.y / 100 })),
        enabled: newZone.isActive,
        severity: newZone.severity,
        zone_type: newZone.type,
        rule: newZone.rule,
      }),
    }).catch(() => {});
  };
  const handleDeleteZone = (id: string) => { setZones((prev) => prev.filter((z) => z.id !== id)); };
  const handleGenerateReport = (newReport: Partial<SurveillanceReportItem>) => { setReports((prev) => [newReport as SurveillanceReportItem, ...prev]); };

  const handleLogin = (_username: string, _role = 'DUTY COMMANDER') => {
    // Login is now handled by AuthContext
  };
  const handleLogout = () => { logout(); };

  // Screening-mode: show splash while auth initializes, then proceed normally
  const isScreeningMode = import.meta.env.VITE_SCREENING_MODE === 'true';
  if (isScreeningMode && isInitializing) {
    return (
      <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-6 select-none">
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-primary text-4xl">shield</span>
          <h1 className="text-2xl font-bold text-on-surface tracking-tight">IBVAP</h1>
        </div>
        <p className="text-sm text-on-surface-variant">Initializing screening session...</p>
        <div className="w-48 h-1 rounded-full bg-surface-container overflow-hidden">
          <div className="h-full bg-primary animate-pulse rounded-full" style={{ width: '60%' }} />
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginView onLogin={handleLogin} />;
  }

  return (
    <div className="min-h-screen bg-background text-on-surface font-body-base flex flex-col selection:bg-primary selection:text-on-primary">
      <Header
        isOperational={isOperational}
        onOpenDiagnostics={() => setIsDiagnosticsModalOpen(true)}
        onNavigateToAlerts={() => setCurrentPath('event-intelligence')}
        activeAlertCount={alerts.filter((a) => a.status === 'ACTIVE').length}
        userName={user?.full_name || user?.email || 'USER'}
        userRole={user?.role || 'VIEWER'}
        onLogout={handleLogout}
        isSidebarOpen={isSidebarOpen}
        onToggleSidebar={() => setIsSidebarOpen((p) => !p)}
      />

      <Sidebar
        currentPath={currentPath}
        onNavigate={setCurrentPath}
        activeAlertCount={alerts.filter((a) => a.status === 'ACTIVE').length}
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen((p) => !p)}
        userRole={user?.role}
      />

      <main className={`pt-14 pb-10 min-h-screen flex flex-col flex-grow transition-all duration-300 ${isSidebarOpen ? 'pl-[260px]' : 'pl-0'}`}>
        {currentPath === 'command-dashboard' && (
          <CommandDashboardView
            stats={dashboardStats}
            alerts={[...alerts.filter(a => !a.source || a.source !== "AI"), ...aiAlerts]}
            cameras={cameras}
            onNavigate={setCurrentPath}
            onSelectCamera={handleSelectCamera}
            onSelectAlert={handleSelectAlert}
          />
        )}
        {currentPath === 'cameras' && (
          <CamerasMonitoringView cameras={cameras} selectedCameraId={selectedCameraId} onSelectCamera={setSelectedCameraId} onAiMetadata={processAllAiMetadata} />
        )}
        {currentPath === 'ai-analytics' && <AiAnalyticsView />}
        {currentPath === 'anpr' && <AnprView records={anprRecords} onAddRecord={handleAddAnprRecord} />}
        {currentPath === 'intrusion-zones' && (
          <IntrusionZonesView zones={zones} cameras={cameras} alerts={alerts} onSaveZone={handleSaveZone} onDeleteZone={handleDeleteZone} />
        )}
        {currentPath === 'event-intelligence' && (
          <EventIntelligenceView
            alerts={[...alerts.filter(a => !a.source || a.source !== 'AI'), ...aiAlerts]}
            suspiciousEvents={suspiciousEvents}
            selectedAlertId={selectedAlertId}
            onSelectAlert={setSelectedAlertId}
            onActionAlert={handleActionAlert}
            onSelectCamera={handleSelectCamera}
          />
        )}
        {currentPath === 'analytics' && <AnalyticsView hourlyData={hourlyActivity} />}
        {currentPath === 'reports' && <ReportsView reports={reports} onGenerateReport={handleGenerateReport} />}
        {currentPath === 'settings' && (
          <SettingsView config={systemConfig} cameras={cameras} onSaveConfig={setSystemConfig} onAddCamera={handleAddCamera} />
        )}
      </main>

      <Footer coordinates="DEMO BORDER SECTOR — INDIA" />

      <SystemDiagnosticsModal isOpen={isDiagnosticsModalOpen} onClose={() => setIsDiagnosticsModalOpen(false)} />

      <CommandPaletteModal
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        alerts={alerts}
        cameras={cameras}
        anprRecords={anprRecords}
        onSelectCamera={handleSelectCamera}
        onSelectAlert={handleSelectAlert}
        onNavigate={setCurrentPath}
      />
    </div>
  );
};

export const App: React.FC = () => (
  <AuthProvider>
    <AppInner />
  </AuthProvider>
);

export default App;
