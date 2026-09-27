import React, { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { CameraFeed, BorderAlert, DashboardKpiStats, VirtualZone } from '../types';
import { NavPath } from '../components/Sidebar';
import { useAuth } from '../contexts/AuthContext';
import { ZonePolygons } from '../components/IntrusionZoneLayer';
import { streamBaseUrl } from '../lib/streamUrl';

interface CommandDashboardViewProps {
  stats: DashboardKpiStats;
  cameras: CameraFeed[];
  alerts: BorderAlert[];
  zones: VirtualZone[];
  onNavigate: (path: NavPath) => void;
  onSelectCamera?: (cameraId: string) => void;
  onSelectAlert: (alertId: string) => void;
  onReplaceCamera?: (cameraId: string, source: string, sourceType: string) => void;
  onDeleteCamera?: (cameraId: string) => void;
}

export const CommandDashboardView: React.FC<CommandDashboardViewProps> = ({
  stats,
  cameras,
  alerts,
  zones,
  onNavigate,
  onSelectCamera,
  onSelectAlert,
  onReplaceCamera,
  onDeleteCamera,
}) => {
  const { getAuthHeaders } = useAuth();
  const AI_BASE = (import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8000');
  const authToken = getAuthHeaders()['Authorization']?.replace('Bearer ', '') || '';

  const [acknowledgedAlerts, setAcknowledgedAlerts] = useState<Record<string, boolean>>({});

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{ cameraId: string; x: number; y: number } | null>(null);

  // Replace modal state
  const [replaceModal, setReplaceModal] = useState<{ cameraId: string; currentSource: string; currentSourceType: string } | null>(null);
  const [replaceSource, setReplaceSource] = useState('');
  const [replaceSourceType, setReplaceSourceType] = useState('video');

  // Delete confirmation state
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const handleAcknowledge = (alertId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setAcknowledgedAlerts((prev) => ({ ...prev, [alertId]: true }));
  };

  const activeThreatsCount = alerts.filter((a) => !acknowledgedAlerts[a.id] && a.status === 'ACTIVE').length;

  // Context menu handler
  const handleContextMenu = useCallback((cameraId: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ cameraId, x: e.clientX, y: e.clientY });
  }, []);

  // Close context menu on click outside
  useEffect(() => {
    if (!contextMenu) return;
    const handler = () => setContextMenu(null);
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, [contextMenu]);

  // Open replace modal
  const handleOpenReplace = useCallback((cameraId: string) => {
    const cam = cameras.find((c) => c.id === cameraId);
    setReplaceModal({ cameraId, currentSource: cam?.rtspUrl || '', currentSourceType: 'video' });
    setReplaceSource(cam?.rtspUrl || '');
    setReplaceSourceType('video');
    setContextMenu(null);
  }, [cameras]);

  // Submit replace
  const handleReplaceSubmit = useCallback(() => {
    if (replaceModal && replaceSource.trim()) {
      onReplaceCamera?.(replaceModal.cameraId, replaceSource.trim(), replaceSourceType);
      setReplaceModal(null);
    }
  }, [replaceModal, replaceSource, replaceSourceType, onReplaceCamera]);

  // Open delete confirmation
  const handleOpenDelete = useCallback((cameraId: string) => {
    setDeleteConfirm(cameraId);
    setContextMenu(null);
  }, []);

  // Confirm delete
  const handleConfirmDelete = useCallback(() => {
    if (deleteConfirm) {
      onDeleteCamera?.(deleteConfirm);
      setDeleteConfirm(null);
    }
  }, [deleteConfirm, onDeleteCamera]);

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* ═══ PAGE HEADER ═══ */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight">
            Command Dashboard
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">
            Real-time surveillance overview · Border security operations
          </p>
        </div>
        <span className="text-[11px] text-success font-semibold flex items-center gap-1.5">
          <span className="w-2 h-2 rounded-full bg-success" />
          OPERATIONAL
        </span>
      </div>

      {/* ═══ TOP: 4 KPI CARDS ═══ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. Cameras Online */}
        <button
          onClick={() => onNavigate('cameras')}
          className="bg-surface p-4 rounded-xl border border-outline-variant hover:border-primary/30 hover:shadow-md transition-all cursor-pointer text-left group"
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] font-semibold text-on-surface-variant tracking-wide uppercase">Cameras Online</span>
            <span className="material-symbols-outlined text-primary text-[20px]">videocam</span>
          </div>
          <div className="text-2xl font-bold text-on-surface">
            {stats.activeCameras} <span className="text-sm font-normal text-on-surface-variant">/ {stats.totalCameras}</span>
          </div>
          <div className="flex items-center gap-1.5 mt-2">
            <span className="w-2 h-2 rounded-full bg-success" />
            <span className="text-[11px] text-success font-semibold">All Streams Active</span>
          </div>
        </button>

        {/* 2. Active Threats */}
        <button
          onClick={() => onNavigate('event-intelligence')}
          className={`p-4 rounded-xl border transition-all cursor-pointer text-left group ${
            activeThreatsCount > 0
              ? 'bg-error-container/40 border-error/20 hover:border-error/40'
              : 'bg-surface border-outline-variant hover:border-primary/30'
          }`}
        >
          <div className="flex items-center justify-between mb-3">
            <span className={`text-[11px] font-semibold tracking-wide uppercase ${activeThreatsCount > 0 ? 'text-error' : 'text-on-surface-variant'}`}>
              Active Threats
            </span>
            <span className={`material-symbols-outlined text-[20px] ${activeThreatsCount > 0 ? 'text-error' : 'text-on-surface-variant'}`}>
              crisis_alert
            </span>
          </div>
          <div className={`text-2xl font-bold ${activeThreatsCount > 0 ? 'text-error' : 'text-on-surface'}`}>
            {activeThreatsCount}
          </div>
          <div className="mt-2">
            <span className={`text-[11px] font-semibold ${activeThreatsCount > 0 ? 'text-error/80' : 'text-on-surface-variant'}`}>
              {activeThreatsCount > 0 ? 'Requires Immediate Action' : 'All Clear'}
            </span>
          </div>
        </button>

        {/* 3. People / Vehicles */}
        <button
          onClick={() => onNavigate('analytics')}
          className="bg-surface p-4 rounded-xl border border-outline-variant hover:border-primary/30 hover:shadow-md transition-all cursor-pointer text-left group"
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] font-semibold text-on-surface-variant tracking-wide uppercase">People / Vehicles</span>
            <span className="material-symbols-outlined text-primary text-[20px]">groups</span>
          </div>
          <div className="text-2xl font-bold text-on-surface">
            {stats.peopleDetected} <span className="text-base text-on-surface-variant font-normal">/ {stats.vehiclesDetected}</span>
          </div>
          <div className="mt-2">
            <span className="text-[11px] text-on-surface-variant">Tracked across all sectors</span>
          </div>
        </button>

        {/* 4. System Status */}
        <button
          onClick={() => onNavigate('settings')}
          className="bg-surface p-4 rounded-xl border border-outline-variant hover:border-primary/30 hover:shadow-md transition-all cursor-pointer text-left group"
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-[11px] font-semibold text-on-surface-variant tracking-wide uppercase">System Status</span>
            <span className="material-symbols-outlined text-success text-[20px]">verified</span>
          </div>
          <div className="text-2xl font-bold text-success">NORMAL</div>
          <div className="mt-2">
            <span className="text-[11px] text-on-surface-variant">{stats.systemHealthPercent}% Health · All Nodes Ready</span>
          </div>
        </button>
      </div>

      {/* ═══ MAIN: ACTIVE INCIDENTS + LIVE CAMERAS ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* LEFT: Live Surveillance (7 cols) */}
        <div className="lg:col-span-7 flex flex-col gap-3">
          <div className="flex items-center justify-between border-b border-outline-variant pb-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-[18px]">grid_view</span>
              <h2 className="text-[13px] font-bold text-on-surface tracking-wide">Live Surveillance</h2>
            </div>
            <button
              onClick={() => onNavigate('cameras')}
              className="text-[11px] text-primary hover:underline font-semibold flex items-center gap-1 cursor-pointer"
            >
              View All
              <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {cameras.map((camera) => {
              const hasThreat = camera.detections.some((d) => d.isThreat);
              const cameraZones = zones.filter((z) => z.cameraId === camera.id);
              return (
                <button
                  key={camera.id}
                  onClick={() => {
                    onSelectCamera?.(camera.id);
                    onNavigate('cameras');
                  }}
                  onContextMenu={(e) => handleContextMenu(camera.id, e)}
                  className={`bg-surface rounded-xl border overflow-hidden transition-all cursor-pointer text-left group hover:shadow-md ${
                    hasThreat ? 'border-error/30 hover:border-error/50' : 'border-outline-variant hover:border-primary/30'
                  }`}
                >
                  {/* Camera Card Header */}
                  <div className="h-8 bg-surface-container-low px-3 flex items-center justify-between border-b border-outline-variant/50">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-bold text-primary font-mono">{camera.id}</span>
                      <span className="text-[10px] text-on-surface-variant truncate">· {camera.location}</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className={`w-1.5 h-1.5 rounded-full ${camera.sourceType === 'video' ? 'bg-warning' : 'bg-success'}`} />
                      <span className={`text-[9px] font-bold ${camera.sourceType === 'video' ? 'text-warning' : 'text-success'}`}>
                        {camera.sourceType === 'video' ? 'VIDEO' : 'LIVE'}
                      </span>
                    </div>
                  </div>

                  {/* Video Preview — uses the same MJPEG stream as the individual camera view */}
                  <div className="relative w-full aspect-video bg-surface-container-low overflow-hidden">
                    {camera.id && authToken ? (
                      <img
                        src={streamBaseUrl(AI_BASE, camera.id) + '/video/stream/' + camera.id + '?token=' + authToken}
                        alt={camera.name}
                        className="w-full h-full object-cover opacity-90 group-hover:scale-[1.02] transition-transform duration-500"
                      />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center bg-surface-container text-on-surface-variant text-xs">No preview</div>
                    )}

                    {/* Intrusion zone outlines (display-only) */}
                    {cameraZones.length > 0 && <ZonePolygons zones={cameraZones} />}

                    {/* Bounding boxes */}
                    {camera.detections.map((det) => (
                      <div
                        key={det.id}
                        className={`absolute border-2 ${
                          det.isThreat
                            ? 'border-error'
                            : det.classType === 'vehicle'
                            ? 'border-tertiary'
                            : 'border-secondary'
                        }`}
                        style={{
                          left: `${det.bbox.x}%`,
                          top: `${det.bbox.y}%`,
                          width: `${det.bbox.w}%`,
                          height: `${det.bbox.h}%`,
                        }}
                      >
                        <div
                          className={`absolute -top-[18px] left-0 px-1.5 py-[2px] text-[9px] font-mono font-bold whitespace-nowrap rounded ${
                            det.isThreat
                              ? 'bg-error text-on-error'
                              : det.classType === 'vehicle'
                              ? 'bg-tertiary text-on-tertiary'
                              : 'bg-secondary text-on-secondary'
                          }`}
                        >
                          {det.trackId} | {det.confidence}%
                        </div>
                      </div>
                    ))}

                    {/* Threat overlay */}
                    {hasThreat && (
                      <div className="absolute top-2 right-2 px-2 py-1 bg-error/90 text-on-error rounded-md text-[10px] font-bold flex items-center gap-1">
                        <span className="material-symbols-outlined text-[12px]">warning</span>
                        INTRUSION
                      </div>
                    )}

                    {/* Camera name */}
                    <div className="absolute bottom-2 left-2 px-2 py-0.5 bg-on-surface/70 text-surface text-[10px] rounded font-medium">
                      {camera.name}
                    </div>
                  </div>

                  {/* Card Footer */}
                  <div className="px-3 py-2 flex items-center justify-between border-t border-outline-variant/30">
                    <div className="text-[11px] text-on-surface-variant">
                      {camera.detections.length > 0 ? (
                        <span>
                          Targets:{' '}
                          <span className="text-on-surface font-semibold">
                            {camera.detections.map((d) => `${d.trackId}`).join(', ')}
                          </span>
                        </span>
                      ) : (
                        <span>No Active Targets</span>
                      )}
                    </div>
                    <span className="text-[11px] text-primary font-semibold group-hover:underline flex items-center gap-0.5">
                      Inspect <span className="material-symbols-outlined text-[12px]">chevron_right</span>
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* RIGHT: Active Incidents (5 cols) */}
        <div className="lg:col-span-5 flex flex-col gap-3">
          <div className="flex items-center justify-between border-b border-outline-variant pb-2">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-error text-[18px]">crisis_alert</span>
              <h2 className="text-[13px] font-bold text-on-surface tracking-wide">
                Active Incidents ({alerts.filter((a) => a.status === 'ACTIVE').length})
              </h2>
            </div>
            <button
              onClick={() => onNavigate('event-intelligence')}
              className="text-[11px] text-primary hover:underline font-semibold flex items-center gap-1 cursor-pointer"
            >
              View All
              <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
            </button>
          </div>

          <div className="flex flex-col gap-2.5 max-h-[520px] overflow-y-auto pr-1">
            {alerts.map((alert) => {
              const isCrit = alert.severity === 'CRITICAL';
              const isMed = alert.severity === 'HIGH' || alert.severity === 'MEDIUM';
              const severityLabel = alert.severity === 'HIGH' ? 'MEDIUM' : alert.severity;
              const isAck = acknowledgedAlerts[alert.id];

              return (
                <button
                  key={alert.id}
                  onClick={() => {
                    onSelectAlert(alert.id);
                    onNavigate('event-intelligence');
                  }}
                  className={`w-full p-3.5 rounded-xl border-l-4 transition-all cursor-pointer text-left flex flex-col gap-2 ${
                    isAck
                      ? 'bg-surface border-outline-variant/40 opacity-60'
                      : isCrit
                      ? 'bg-error-container/30 border-error hover:bg-error-container/50'
                      : isMed
                      ? 'bg-warning-container/40 border-warning hover:bg-warning-container/60'
                      : 'bg-surface border-outline-variant hover:border-primary/30'
                  } border border-outline-variant/50`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-[9px] font-bold px-2 py-0.5 rounded ${
                          isCrit
                            ? 'bg-error text-on-error'
                            : isMed
                            ? 'bg-warning text-on-warning'
                            : 'bg-surface-container-high text-on-surface'
                        }`}
                      >
                        {severityLabel}
                      </span>
                      {isAck && (
                        <span className="text-[9px] bg-surface-container-high text-on-surface-variant px-2 py-0.5 rounded font-mono">
                          ACK
                        </span>
                      )}
                    </div>
                    <span className="text-[10px] text-on-surface-variant font-mono">{alert.timestamp}</span>
                  </div>

                  <div className="text-[13px] font-semibold text-on-surface leading-tight">{alert.title}</div>

                  <div className="text-[10px] text-on-surface-variant flex items-center gap-1.5">
                    <span className="font-semibold text-primary">{alert.cameraId}</span>
                    <span>·</span>
                    <span>{alert.zone}</span>
                    <span>·</span>
                    <span className="font-mono">{alert.trackId}</span>
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-2 pt-1">
                    <span
                      className="px-2.5 py-1 bg-surface border border-outline-variant text-[10px] text-on-surface rounded-lg font-semibold hover:bg-surface-container-high transition-colors cursor-pointer flex items-center gap-1"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectCamera?.(alert.cameraId);
                      }}
                    >
                      <span className="material-symbols-outlined text-[12px]">videocam</span>
                      View Camera
                    </span>
                    {!isAck && (
                      <span
                        className="px-2.5 py-1 bg-surface border border-outline-variant text-[10px] text-on-surface rounded-lg font-semibold hover:bg-surface-container-high transition-colors cursor-pointer flex items-center gap-1"
                        onClick={(e) => handleAcknowledge(alert.id, e)}
                      >
                        <span className="material-symbols-outlined text-[12px] text-success">check</span>
                        Acknowledge
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* ═══ BOTTOM: RECENT EVENTS ═══ */}
      <div className="bg-surface rounded-xl border border-outline-variant p-4">
        <div className="flex items-center justify-between mb-3 border-b border-outline-variant pb-2">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[18px]">history</span>
            <h3 className="text-[13px] font-bold text-on-surface tracking-wide">Recent Events</h3>
          </div>
          <span className="text-[10px] text-success font-semibold flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-success" />
            LIVE
          </span>
        </div>

        <div className="divide-y divide-outline-variant/40 max-h-48 overflow-y-auto">
          {alerts
            .filter((a) => a.status === 'ACTIVE')
            .slice(0, 5)
            .map((item) => (
              <div key={item.id} className="py-2.5 flex items-center justify-between text-[12px] gap-3">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-primary font-semibold">{item.timestamp}</span>
                  <span className="font-mono text-on-surface-variant text-[11px]">{item.cameraId}</span>
                  <span className="text-on-surface">{item.title}</span>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-[9px] font-bold shrink-0 ${
                    item.severity === 'CRITICAL'
                      ? 'bg-error-container text-on-error-container'
                      : item.severity === 'HIGH' || item.severity === 'MEDIUM'
                      ? 'bg-warning-container text-on-warning-container'
                      : item.severity === 'LOW'
                      ? 'bg-surface-container-high text-on-surface-variant'
                      : 'bg-primary-container text-on-primary-container'
                  }`}
                >
                  {item.severity === 'HIGH' ? 'MEDIUM' : item.severity}
                </span>
              </div>
            ))}
          {alerts.filter((a) => a.status === 'ACTIVE').length === 0 && (
            <div className="py-6 text-center text-on-surface-variant/50 text-[12px]">
              No active alerts
            </div>
          )}
        </div>
      </div>

      {/* ═══ CONTEXT MENU ═══ */}
      {contextMenu && createPortal(
        <div
          className="fixed z-[9999]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="bg-surface border border-outline-variant rounded-xl shadow-xl py-1 min-w-[180px] overflow-hidden">
            <div className="px-3 py-2 border-b border-outline-variant/50 bg-surface-container-low">
              <span className="text-[11px] font-bold text-primary font-mono">{contextMenu.cameraId}</span>
            </div>
            <button onClick={() => { onSelectCamera?.(contextMenu.cameraId); onNavigate('cameras'); setContextMenu(null); }} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">open_in_new</span> Open Camera
            </button>
            <button onClick={() => { onSelectCamera?.(contextMenu.cameraId); onNavigate('cameras'); setContextMenu(null); }} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">fullscreen</span> Fullscreen
            </button>
            <div className="border-t border-outline-variant/50 my-0.5" />
            <button onClick={() => { onSelectCamera?.(contextMenu.cameraId); onNavigate('cameras'); setContextMenu(null); }} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors" data-testid="ctx-menu-zone">
              <span className="material-symbols-outlined text-[14px]">fence</span> Intrusion Zone
            </button>
            <button onClick={() => handleOpenReplace(contextMenu.cameraId)} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">swap_horiz</span> Replace Camera
            </button>
            <button onClick={() => handleOpenDelete(contextMenu.cameraId)} className="w-full px-3 py-2 text-left text-[11px] text-error hover:bg-error-container/30 flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">delete</span> Delete Camera
            </button>
          </div>
        </div>,
        document.body
      )}

      {/* ═══ REPLACE CAMERA MODAL ═══ */}
      {replaceModal && createPortal(
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-on-surface/50 backdrop-blur-sm" onClick={() => setReplaceModal(null)}>
          <div className="bg-surface border border-outline-variant rounded-xl shadow-2xl w-full max-w-md mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-outline-variant bg-surface-container-low">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-primary text-[18px]">swap_horiz</span>
                <h3 className="text-[13px] font-bold text-on-surface">Replace Camera Source</h3>
              </div>
              <p className="text-[11px] text-on-surface-variant mt-1 font-mono">{replaceModal.cameraId}</p>
            </div>
            <div className="px-5 py-4 space-y-3 text-[11px]">
              <div>
                <label className="block text-on-surface-variant font-medium mb-1">SOURCE TYPE</label>
                <select value={replaceSourceType} onChange={(e) => setReplaceSourceType(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none">
                  <option value="video">LOCAL VIDEO (MP4)</option>
                  <option value="rtsp">RTSP STREAM</option>
                  <option value="webcam">WEBCAM</option>
                </select>
              </div>
              <div>
                <label className="block text-on-surface-variant font-medium mb-1">{replaceSourceType === 'rtsp' ? 'RTSP URL' : replaceSourceType === 'webcam' ? 'WEBCAM INDEX' : 'VIDEO FILE PATH'}</label>
                <input type="text" value={replaceSource} onChange={(e) => setReplaceSource(e.target.value)} placeholder={replaceSourceType === 'video' ? './data/cameras/cam-01.mp4' : replaceSourceType === 'rtsp' ? 'rtsp://192.168.1.101:554/live' : '0'} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-primary outline-none" />
              </div>
            </div>
            <div className="px-5 py-3 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setReplaceModal(null)} className="px-4 py-2 text-[11px] font-semibold text-on-surface-variant hover:text-on-surface rounded-lg cursor-pointer transition-colors">Cancel</button>
              <button onClick={handleReplaceSubmit} disabled={!replaceSource.trim()} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed">Replace Source</button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* ═══ DELETE CONFIRMATION MODAL ═══ */}
      {deleteConfirm && createPortal(
        <div className="fixed inset-0 z-[10000] flex items-center justify-center bg-on-surface/50 backdrop-blur-sm" onClick={() => setDeleteConfirm(null)}>
          <div className="bg-surface border border-outline-variant rounded-xl shadow-2xl w-full max-w-sm mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-outline-variant bg-error-container/20">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-error text-[18px]">delete</span>
                <h3 className="text-[13px] font-bold text-on-surface">Delete Camera</h3>
              </div>
            </div>
            <div className="px-5 py-4">
              <p className="text-[12px] text-on-surface">
                Delete <span className="font-mono font-bold text-error">{deleteConfirm}</span>?
              </p>
              <p className="text-[11px] text-on-surface-variant mt-1">This will remove the camera from monitoring.</p>
            </div>
            <div className="px-5 py-3 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setDeleteConfirm(null)} className="px-4 py-2 text-[11px] font-semibold text-on-surface-variant hover:text-on-surface rounded-lg cursor-pointer transition-colors">Cancel</button>
              <button onClick={handleConfirmDelete} className="px-4 py-2 bg-error hover:bg-error/90 text-on-error rounded-lg text-[11px] font-bold cursor-pointer transition-colors">Delete Camera</button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};
