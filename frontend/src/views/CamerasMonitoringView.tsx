import React, { useState, useEffect, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { CameraFeed, AiTrackingMetadata, AiTrackedObject, AiFaceDetection, TrackContext, AiCameraStatus, VirtualZone } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { AIBoundingBoxOverlay } from '../components/AIBoundingBoxOverlay';
import { AIFaceOverlay } from '../components/AIFaceOverlay';
import { useIntrusionZoneController, IntrusionZoneLayer, IntrusionZoneButton, ZoneManageMenu, ZoneStatusPanel } from '../components/IntrusionZoneLayer';

interface CamerasMonitoringViewProps {
  cameras: CameraFeed[];
  zones: VirtualZone[];
  selectedCameraId?: string;
  onSelectCamera?: (id: string) => void;
  onAiMetadata?: (metadata: AiTrackingMetadata) => void;
  onSaveZone?: (zone: VirtualZone) => void;
  onDeleteZone?: (id: string) => void;
}

type ViewMode = 'grid' | 'single';
type ContextMenuAction = 'open' | 'fullscreen' | 'analysis' | 'alerts' | 'anpr' | 'ai-toggle' | 'zone';

interface ContextMenuState {
  cameraId: string;
  x: number;
  y: number;
}

interface CameraTileState {
  metadata: AiTrackingMetadata | null;
  status: AiCameraStatus | null;
  isConnected: boolean;
  aiEnabled: boolean;
}

function useCameraTileStream(cameraId: string, token: string | null) {
  const AI_BASE = (import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8000');
  const [state, setState] = useState<CameraTileState>({
    metadata: null, status: null, isConnected: false, aiEnabled: true,
  });
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cameraIdRef = useRef(cameraId);
  const tokenRef = useRef(token);
  cameraIdRef.current = cameraId;
  tokenRef.current = token;

  const cleanup = useCallback(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    if (reconnectRef.current) { clearTimeout(reconnectRef.current); reconnectRef.current = null; }
    if (statusIntervalRef.current) { clearInterval(statusIntervalRef.current); statusIntervalRef.current = null; }
  }, []);

  const fetchStatus = useCallback(async () => {
    const cid = cameraIdRef.current;
    const tkn = tokenRef.current;
    if (!cid) return;
    try {
      const url = AI_BASE + '/status?camera_id=' + cid;
      const headers: Record<string, string> = {};
      if (tkn) headers['Authorization'] = 'Bearer ' + tkn;
      const resp = await fetch(url, { headers });
      if (!resp.ok) return;
      const data = await resp.json();
      const pipeline = data.pipeline || data;
      setState((prev) => ({
        ...prev,
        status: {
          camera_id: cid,
          video_connected: pipeline.video_connected ?? false,
          ai_processing: pipeline.ai_processing ?? false,
          processing_fps: pipeline.processing_fps ?? 0,
          source_fps: pipeline.source_fps ?? 0,
          resolution: pipeline.resolution ?? '',
          frames_processed: pipeline.frames_processed ?? 0,
          total_detections: pipeline.total_detections ?? 0,
          websocket_clients: pipeline.websocket_clients ?? 0,
          camera: pipeline.camera,
        },
      }));
    } catch { /* ignore */ }
  }, [AI_BASE]);

  const connectInternal = useCallback(() => {
    cleanup();
    const cid = cameraIdRef.current;
    const tkn = tokenRef.current;
    if (!cid) return;
    const wsUrl = AI_BASE.replace('http://', 'ws://').replace('https://', 'wss://')
      + '/ws/cameras/' + cid + (tkn ? '?token=' + tkn : '');
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => {
        setState((prev) => ({ ...prev, isConnected: true }));
        fetchStatus();
        statusIntervalRef.current = setInterval(fetchStatus, 3000);
      };
      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.camera_id) {
            setState((prev) => ({
              ...prev,
              metadata: data,
              aiEnabled: data.ai_enabled !== undefined ? data.ai_enabled : prev.aiEnabled,
            }));
          }
        } catch { /* ignore */ }
      };
      ws.onclose = () => {
        setState((prev) => ({ ...prev, isConnected: false, metadata: null }));
        if (statusIntervalRef.current) { clearInterval(statusIntervalRef.current); statusIntervalRef.current = null; }
        reconnectRef.current = setTimeout(connectInternal, 3000);
      };
      ws.onerror = () => {
        setState((prev) => ({ ...prev, isConnected: false }));
      };
    } catch {
      reconnectRef.current = setTimeout(connectInternal, 3000);
    }
  }, [AI_BASE, cleanup, fetchStatus]);

  useEffect(() => {
    connectInternal();
    return cleanup;
  }, [cameraId, token, connectInternal, cleanup]);

  const videoUrl = cameraId && token
    ? AI_BASE + '/video/stream/' + cameraId + '?token=' + token
    : '';

  return { ...state, videoUrl, AI_BASE };
}

// ─── Camera Tile (Grid Mode) ────────────────────────────────────────────────

interface CameraTileProps {
  camera: CameraFeed;
  token: string | null;
  zones: VirtualZone[];
  onOpen: (id: string) => void;
  onContextMenu: (cameraId: string, x: number, y: number) => void;
  onAiMetadata?: (metadata: AiTrackingMetadata) => void;
  onToggleAi?: (cameraId: string, enabled: boolean) => void;
  onAiStateChange?: (cameraId: string, enabled: boolean) => void;
  onSaveZone?: (zone: VirtualZone) => void;
  onDeleteZone?: (id: string) => void;
}

const CameraTile: React.FC<CameraTileProps> = ({ camera, token, zones, onOpen, onContextMenu, onAiMetadata, onToggleAi, onAiStateChange, onSaveZone, onDeleteZone }) => {
  const stream = useCameraTileStream(camera.id, token);
  const isRealAi = stream.metadata?.ai_enabled !== undefined
    ? stream.metadata.ai_enabled && stream.isConnected
    : stream.isConnected;
  const detections = stream.metadata?.detections || [];
  const faces = stream.metadata?.faces || [];
  const trackContext = stream.metadata?.track_context || [];
  const events = stream.metadata?.events || [];
  const aiProcessing = stream.status?.ai_processing ?? false;
  const health = stream.status?.camera;
  const zoneCtl = useIntrusionZoneController({
    cameraId: camera.id,
    zones,
    onSaveZone: onSaveZone || (() => {}),
    onDeleteZone: onDeleteZone || (() => {}),
    events,
  });

  useEffect(() => {
    if (stream.metadata && onAiMetadata) {
      onAiMetadata(stream.metadata);
    }
  }, [stream.metadata, onAiMetadata]);

  useEffect(() => {
    onAiStateChange?.(camera.id, stream.aiEnabled);
  }, [stream.aiEnabled, camera.id, onAiStateChange]);

  const handleContextMenu = (e: React.MouseEvent) => {
    e.preventDefault();
    onContextMenu(camera.id, e.clientX, e.clientY);
  };

  const handleTileClick = () => {
    onOpen(camera.id);
  };

  return (
    <div
      className="bg-surface border border-outline-variant rounded-xl overflow-hidden cursor-pointer group hover:border-primary/40 transition-all flex flex-col"
      onContextMenu={handleContextMenu}
    >
      {/* Header */}
      <div className="h-8 bg-surface-container-low border-b border-outline-variant px-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`w-1.5 h-1.5 rounded-full ${stream.isConnected ? 'bg-success' : 'bg-error'}`} />
          <span className="text-[11px] font-bold text-primary font-mono">{camera.id}</span>
          <span className="text-[10px] text-on-surface-variant truncate max-w-[100px]">{camera.name}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {isRealAi && (
            <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold flex items-center gap-0.5 ${aiProcessing ? 'bg-success-container text-success' : 'bg-error-container text-error'}`}>
              <span className={`w-1 h-1 rounded-full ${aiProcessing ? 'bg-success' : 'bg-error'}`} />
              AI {aiProcessing ? 'LIVE' : 'OFF'}
            </span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onToggleAi?.(camera.id, !stream.aiEnabled); }}
            className={`px-1.5 py-0.5 rounded text-[8px] font-bold border cursor-pointer transition-colors ${
              stream.aiEnabled
                ? 'bg-success-container text-success border-success/30'
                : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface-variant'
            }`}
          >
            {stream.aiEnabled ? 'AI ON' : 'AI OFF'}
          </button>
          <IntrusionZoneButton controller={zoneCtl} compact />
        </div>
      </div>

      {/* Video */}
      <div className="relative w-full aspect-video bg-surface-container-low overflow-hidden" onClick={handleTileClick}>
        <img
          src={stream.videoUrl || undefined}
          alt={camera.name}
          className="w-full h-full object-cover"
        />
        <IntrusionZoneLayer controller={zoneCtl} />
        {isRealAi && (
          <AIBoundingBoxOverlay detections={detections} trackContext={trackContext} events={events} />
        )}
        {isRealAi && (
          <AIFaceOverlay faces={faces} />
        )}
        {/* Status overlay */}
        {!stream.isConnected && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-container/80">
            <div className="text-center">
              <span className="material-symbols-outlined text-[24px] text-on-surface-variant/50 block mb-1">videocam_off</span>
              <span className="text-[10px] text-on-surface-variant">Connecting...</span>
            </div>
          </div>
        )}
        {/* Camera name overlay */}
        <div className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 bg-on-surface/70 text-surface text-[9px] rounded font-medium">
          {camera.name}
        </div>
        {health && health.status !== 'CONNECTED' && (
          <div className="absolute top-1.5 right-1.5 px-1.5 py-0.5 bg-warning-container text-warning text-[8px] rounded font-bold">
            {health.status}
          </div>
        )}
      </div>

      {/* Footer: targets + status */}
      <div className="px-3 py-2 flex items-center justify-between border-t border-outline-variant/30 text-[10px]">
        <div className="flex items-center gap-2">
          <span className="text-on-surface-variant">
            {detections.length > 0 ? (
              <span className="font-semibold text-on-surface">{detections.length} Target{detections.length !== 1 ? 's' : ''}</span>
            ) : (
              <span>No Targets</span>
            )}
          </span>
          {stream.status && (
            <span className="text-on-surface-variant font-mono">{stream.status.processing_fps.toFixed(1)} FPS</span>
          )}
        </div>
        <span className="text-primary font-semibold opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-0.5">
          Open <span className="material-symbols-outlined text-[11px]">chevron_right</span>
        </span>
      </div>
      {zoneCtl.menuPos && <ZoneManageMenu controller={zoneCtl} />}
      {zoneCtl.statusPos && <ZoneStatusPanel controller={zoneCtl} />}
    </div>
  );
};

// ─── Single Camera View ──────────────────────────────────────────────────────

interface SingleCameraViewProps {
  camera: CameraFeed;
  cameras: CameraFeed[];
  token: string | null;
  zones: VirtualZone[];
  onSelectCamera: (id: string) => void;
  onBack: () => void;
  onAiMetadata?: (metadata: AiTrackingMetadata) => void;
  onToggleAi?: (cameraId: string, enabled: boolean) => void;
  onSaveZone?: (zone: VirtualZone) => void;
  onDeleteZone?: (id: string) => void;
  pendingCreate?: boolean;
  onPendingCreateHandled?: () => void;
}

const SingleCameraView: React.FC<SingleCameraViewProps> = ({ camera, cameras, token, zones, onSelectCamera, onBack, onAiMetadata, onToggleAi, onSaveZone, onDeleteZone, pendingCreate, onPendingCreateHandled }) => {
  const stream = useCameraTileStream(camera.id, token);
  const [isNightFilter, setIsNightFilter] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [ptzPan, setPtzPan] = useState({ pan: 0, tilt: 0, zoom: 1 });
  const [snapshotMessage, setSnapshotMessage] = useState<string | null>(null);
  const [showTechDetails, setShowTechDetails] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [ptzCollapsed, setPtzCollapsed] = useState(true);
  const [ptzFocused, setPtzFocused] = useState(false);
  const ptzPanelRef = useRef<HTMLDivElement>(null);

  const isRealAi = stream.metadata?.ai_enabled !== undefined
    ? stream.metadata.ai_enabled && stream.isConnected
    : stream.isConnected;
  const detections = stream.metadata?.detections || [];
  const faces = stream.metadata?.faces || [];
  const trackContext = stream.metadata?.track_context || [];
  const events = stream.metadata?.events || [];
  const aiProcessing = stream.status?.ai_processing ?? false;
  const health = stream.status?.camera;
  const zoneCtl = useIntrusionZoneController({
    cameraId: camera.id,
    zones,
    onSaveZone: onSaveZone || (() => {}),
    onDeleteZone: onDeleteZone || (() => {}),
    events,
  });

  // Context-menu "Create Zone" deep-link: enter create mode once ready.
  useEffect(() => {
    if (pendingCreate) {
      zoneCtl.startCreate();
      onPendingCreateHandled?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCreate, camera.id]);

  useEffect(() => {
    if (stream.metadata && onAiMetadata) {
      onAiMetadata(stream.metadata);
    }
  }, [stream.metadata, onAiMetadata]);

  // ESC to exit fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setIsFullscreen(false); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isFullscreen]);

  useEffect(() => {
    if (isFullscreen) { document.body.style.overflow = 'hidden'; }
    else { document.body.style.overflow = ''; }
    return () => { document.body.style.overflow = ''; };
  }, [isFullscreen]);

  // Keyboard PTZ control
  useEffect(() => {
    if (!ptzFocused) return;
    const handler = (e: KeyboardEvent) => {
      const step = e.shiftKey ? 4 : 8;
      switch (e.key) {
        case 'ArrowUp': e.preventDefault(); setPtzPan((p) => ({ ...p, tilt: Math.min(25, p.tilt + step) })); break;
        case 'ArrowDown': e.preventDefault(); setPtzPan((p) => ({ ...p, tilt: Math.max(-25, p.tilt - step) })); break;
        case 'ArrowLeft': e.preventDefault(); setPtzPan((p) => ({ ...p, pan: Math.max(-40, p.pan - step) })); break;
        case 'ArrowRight': e.preventDefault(); setPtzPan((p) => ({ ...p, pan: Math.min(40, p.pan + step) })); break;
        case '+': case '=': e.preventDefault(); setPtzPan((p) => ({ ...p, zoom: Math.min(3, +(p.zoom + 0.2).toFixed(1)) })); break;
        case '-': e.preventDefault(); setPtzPan((p) => ({ ...p, zoom: Math.max(1, +(p.zoom - 0.2).toFixed(1)) })); break;
        case '0': e.preventDefault(); setPtzPan({ pan: 0, tilt: 0, zoom: 1 }); break;
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [ptzFocused]);

  const handleTakeSnapshot = () => {
    setSnapshotMessage(`Snapshot saved from ${camera.id} at ${new Date().toISOString().substring(11, 19)} UTC`);
    setTimeout(() => setSnapshotMessage(null), 3500);
  };

  const handleToggleAi = () => {
    onToggleAi?.(camera.id, !stream.aiEnabled);
  };

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-surface-container-high border border-outline-variant text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer">
            <span className="material-symbols-outlined text-[18px]">arrow_back</span>
          </button>
          <div>
            <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-xl">videocam</span>
              {camera.id} — {camera.name}
            </h1>
            <p className="text-[12px] text-on-surface-variant mt-0.5">{camera.location}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {snapshotMessage && (
            <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
              <span className="material-symbols-outlined text-[14px]">check_circle</span> {snapshotMessage}
            </div>
          )}
          <button
            onClick={() => setShowAnalysis(!showAnalysis)}
            className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${
              showAnalysis ? 'bg-primary-container text-primary border-primary/30' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">analytics</span> Analysis
          </button>
        </div>
      </div>

      {/* Main Layout */}
      <div className={`grid grid-cols-1 lg:grid-cols-12 gap-5`}>
        {/* Video Feed */}
        <div className={`flex flex-col gap-3 ${showAnalysis ? 'lg:col-span-8' : 'lg:col-span-12'}`}>
          <div className="bg-surface border border-outline-variant rounded-xl flex flex-col overflow-hidden">
            {/* Feed Header */}
            <div className="h-9 bg-surface-container-low border-b border-outline-variant px-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full ${stream.isConnected ? 'bg-success' : 'bg-error'}`} />
                <span className="text-[11px] font-bold text-primary font-mono">{camera.id}</span>
                <span className="text-[11px] text-on-surface font-medium">&mdash; {camera.name}</span>
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                {isRealAi && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold flex items-center gap-1 ${aiProcessing ? 'bg-success-container text-success' : 'bg-error-container text-error'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${aiProcessing ? 'bg-success' : 'bg-error'}`} />
                    AI {aiProcessing ? 'LIVE' : 'OFFLINE'}
                  </span>
                )}
                {health && health.status !== 'CONNECTED' && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold flex items-center gap-1 ${
                    health.status === 'STALE' ? 'bg-warning-container text-warning'
                    : health.status === 'RECONNECTING' || health.status === 'CONNECTING' ? 'bg-primary-container text-primary'
                    : 'bg-error-container text-error'}`}>
                    {health.status}
                    {health.reconnectCount > 0 && ` (${health.reconnectCount})`}
                  </span>
                )}
                {isRecording && (
                  <span className="text-error font-bold flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-error" /> REC
                  </span>
                )}
                <span className="text-on-surface-variant font-mono">{camera.location}</span>
              </div>
            </div>

            {/* Video */}
            <div className="relative w-full aspect-video bg-surface-container-low overflow-hidden select-none">
              <img
                src={stream.videoUrl || undefined}
                alt={camera.name}
                className="w-full h-full object-cover transition-transform duration-300"
                style={{
                  transform: `scale(${ptzPan.zoom}) translate(${ptzPan.pan}px, ${ptzPan.tilt}px)`,
                  filter: isNightFilter ? 'grayscale(75%) brightness(1.2) contrast(1.2) hue-rotate(90deg)' : 'none',
                }}
              />
              {isNightFilter && <div className="absolute inset-0 bg-emerald-950/30 mix-blend-color pointer-events-none" />}
              <IntrusionZoneLayer controller={zoneCtl} />
              {isRealAi && <AIBoundingBoxOverlay detections={detections} trackContext={trackContext} events={events} />}
              {isRealAi && <AIFaceOverlay faces={faces} />}
              {!stream.isConnected && (
                <div className="absolute inset-0 flex items-center justify-center bg-surface-container/80">
                  <div className="text-center">
                    <span className="material-symbols-outlined text-[48px] text-on-surface-variant/40 block mb-2">videocam_off</span>
                    <p className="text-on-surface-variant text-sm">Connecting to camera...</p>
                  </div>
                </div>
              )}

              {/* Floating PTZ Overlay */}
              <div
                ref={ptzPanelRef}
                tabIndex={0}
                onFocus={() => setPtzFocused(true)}
                onBlur={() => setPtzFocused(false)}
                className={`absolute bottom-3 right-3 z-20 transition-all duration-200 ${ptzCollapsed ? 'w-auto' : 'w-56'}`}
              >
                {ptzCollapsed ? (
                  <button
                    onClick={() => setPtzCollapsed(false)}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-on-surface/70 text-surface text-[11px] font-semibold backdrop-blur-sm hover:bg-on-surface/85 transition-colors cursor-pointer border border-white/10"
                    title="PTZ Controls (click to expand)"
                  >
                    <span className="material-symbols-outlined text-[15px]">gamepad</span>
                    PTZ
                  </button>
                ) : (
                  <div className="bg-surface/95 backdrop-blur-md border border-outline-variant rounded-xl shadow-2xl overflow-hidden">
                    <div className="px-3 py-1.5 bg-surface-container-low border-b border-outline-variant flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className="material-symbols-outlined text-[13px] text-primary">gamepad</span>
                        <span className="text-[10px] font-bold text-on-surface tracking-wide uppercase">PTZ</span>
                        {ptzFocused && <span className="px-1.5 py-0.5 bg-primary-container text-primary text-[8px] font-bold rounded">KEYS</span>}
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-[9px] text-success font-semibold">Ready</span>
                        <button onClick={() => setPtzCollapsed(true)} className="p-0.5 rounded hover:bg-surface-container-high text-on-surface-variant cursor-pointer" title="Minimize">
                          <span className="material-symbols-outlined text-[13px]">minimize</span>
                        </button>
                      </div>
                    </div>
                    <div className="p-3 flex flex-col items-center gap-2">
                      <div className="grid grid-cols-3 gap-1 w-28">
                        <div />
                        <button onClick={() => setPtzPan((p) => ({ ...p, tilt: Math.min(25, p.tilt + 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-md flex items-center justify-center text-primary cursor-pointer h-7" title="Tilt Up">
                          <span className="material-symbols-outlined text-[15px]">expand_less</span>
                        </button>
                        <div />
                        <button onClick={() => setPtzPan((p) => ({ ...p, pan: Math.max(-40, p.pan - 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-md flex items-center justify-center text-primary cursor-pointer h-7" title="Pan Left">
                          <span className="material-symbols-outlined text-[15px]">chevron_left</span>
                        </button>
                        <button onClick={() => setPtzPan({ pan: 0, tilt: 0, zoom: 1 })} className="bg-surface-container-high border border-outline-variant rounded-md flex items-center justify-center text-[8px] text-on-surface-variant font-bold cursor-pointer h-7" title="Center">
                          CTR
                        </button>
                        <button onClick={() => setPtzPan((p) => ({ ...p, pan: Math.min(40, p.pan + 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-md flex items-center justify-center text-primary cursor-pointer h-7" title="Pan Right">
                          <span className="material-symbols-outlined text-[15px]">chevron_right</span>
                        </button>
                        <div />
                        <button onClick={() => setPtzPan((p) => ({ ...p, tilt: Math.max(-25, p.tilt - 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-md flex items-center justify-center text-primary cursor-pointer h-7" title="Tilt Down">
                          <span className="material-symbols-outlined text-[15px]">expand_more</span>
                        </button>
                        <div />
                      </div>
                      <div className="w-full flex items-center justify-between pt-1.5 border-t border-outline-variant text-[10px]">
                        <span className="text-on-surface-variant">Zoom</span>
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => setPtzPan((p) => ({ ...p, zoom: Math.max(1, +(p.zoom - 0.2).toFixed(1)) }))} className="w-5 h-5 bg-surface-container-low border border-outline-variant rounded text-on-surface flex items-center justify-center cursor-pointer text-[11px]">-</button>
                          <span className="font-mono text-primary font-bold min-w-[28px] text-center">{ptzPan.zoom.toFixed(1)}x</span>
                          <button onClick={() => setPtzPan((p) => ({ ...p, zoom: Math.min(3, +(p.zoom + 0.2).toFixed(1)) }))} className="w-5 h-5 bg-surface-container-low border border-outline-variant rounded text-on-surface flex items-center justify-center cursor-pointer text-[11px]">+</button>
                        </div>
                      </div>
                      <div className="text-[8px] text-on-surface-variant/50 text-center">Arrow keys · +/- zoom · 0 reset</div>
                    </div>
                  </div>
                )}
              </div>

              {/* PTZ Position Indicator */}
              {(ptzPan.pan !== 0 || ptzPan.tilt !== 0 || ptzPan.zoom !== 1) && (
                <div className="absolute top-3 left-3 px-2 py-1 bg-on-surface/70 text-surface text-[9px] rounded font-mono backdrop-blur-sm border border-white/10">
                  P:{ptzPan.pan} T:{ptzPan.tilt} Z:{ptzPan.zoom.toFixed(1)}x
                </div>
              )}
            </div>

            {/* Actions Toolbar */}
            <div className="p-3 bg-surface-container-low border-t border-outline-variant flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <button onClick={handleToggleAi} disabled={false}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${stream.aiEnabled ? 'bg-success-container text-success border-success/30' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'}`}>
                  <span className="material-symbols-outlined text-[14px]">smart_toy</span> AI {stream.aiEnabled ? 'ON' : 'OFF'}
                </button>
                <IntrusionZoneButton controller={zoneCtl} />
                <button onClick={handleTakeSnapshot}
                  className="px-3 py-1.5 rounded-lg bg-surface hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface font-semibold flex items-center gap-1.5 cursor-pointer transition-colors">
                  <span className="material-symbols-outlined text-[14px] text-primary">photo_camera</span> Snapshot
                </button>
                <button onClick={() => setIsRecording(!isRecording)}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${isRecording ? 'bg-error text-on-error border-error' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'}`}>
                  <span className="material-symbols-outlined text-[14px]">{isRecording ? 'stop_circle' : 'fiber_manual_record'}</span> {isRecording ? 'Stop' : 'Record'}
                </button>
                <button onClick={() => setIsNightFilter(!isNightFilter)}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${isNightFilter ? 'bg-tertiary text-on-tertiary border-tertiary' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'}`}>
                  <span className="material-symbols-outlined text-[14px]">nightlight</span> Night
                </button>
              </div>
              <button onClick={() => setIsFullscreen(!isFullscreen)}
                className="px-3 py-1.5 rounded-lg bg-surface hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface font-semibold flex items-center gap-1 cursor-pointer">
                <span className="material-symbols-outlined text-[14px]">fullscreen</span> Fullscreen
              </button>
            </div>
          </div>

          {/* Active Targets */}
          <div className="bg-surface border border-outline-variant rounded-xl flex flex-col overflow-hidden">
            <div className="p-3 bg-surface-container-low border-b border-outline-variant flex items-center justify-between">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Active Targets</span>
              <span className="text-[10px] font-semibold text-primary font-mono">{detections.length} DETECTED</span>
            </div>
            <div className="p-3 flex flex-col gap-2 max-h-[250px] overflow-y-auto">
              {detections.length === 0 ? (
                <div className="py-6 text-center text-[11px] text-on-surface-variant">
                  <span className="material-symbols-outlined text-[20px] text-on-surface-variant/50 block mb-1">smart_toy</span>
                  {stream.isConnected ? (aiProcessing ? 'AI detecting...' : 'AI off') : 'Connecting...'}
                </div>
              ) : (
                detections.map((det, idx) => (
                  <div key={'tgt-' + det.track_id + '-' + idx}
                    className="p-3 rounded-lg border border-outline-variant bg-surface-container-low flex flex-col gap-1">
                    <div className="flex items-center justify-between">
                      <span className="font-bold text-[12px] text-primary">{det.class_name.toUpperCase()} #{det.track_id}</span>
                      <span className="font-mono text-[11px] font-bold text-success">{Math.round(det.confidence * 100)}%</span>
                    </div>
                    <div className="text-[10px] text-on-surface-variant">AI Pipeline - Real-time tracking</div>
                  </div>
                ))
              )}
            </div>
          </div>

        </div>

        {/* Analysis Panel */}
        {showAnalysis && (
          <div className="lg:col-span-4 flex flex-col gap-4">
            <div className="bg-surface border border-outline-variant rounded-xl p-4">
              <div className="flex items-center justify-between mb-3 border-b border-outline-variant pb-2">
                <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Camera Analysis</span>
                <button onClick={() => setShowAnalysis(false)} className="text-on-surface-variant hover:text-on-surface cursor-pointer">
                  <span className="material-symbols-outlined text-[16px]">close</span>
                </button>
              </div>
              <div className="space-y-3 text-[11px]">
                <div className="flex justify-between"><span className="text-on-surface-variant">Camera</span><span className="font-mono font-bold text-primary">{camera.id}</span></div>
                <div className="flex justify-between"><span className="text-on-surface-variant">Status</span><span className={`font-semibold ${stream.isConnected ? 'text-success' : 'text-error'}`}>{stream.isConnected ? 'ONLINE' : 'OFFLINE'}</span></div>
                <div className="flex justify-between"><span className="text-on-surface-variant">AI</span><span className={`font-semibold ${stream.aiEnabled ? 'text-success' : 'text-on-surface-variant'}`}>{stream.aiEnabled ? 'ON' : 'OFF'}</span></div>
                <div className="flex justify-between"><span className="text-on-surface-variant">Source Type</span><span className="font-mono text-on-surface">{camera.rtspUrl ? 'RTSP' : 'LOCAL'}</span></div>
                <div className="flex justify-between"><span className="text-on-surface-variant">Location</span><span className="text-on-surface">{camera.location}</span></div>
              </div>
            </div>

            {/* Live Status */}
            {stream.status && (
              <div className="bg-surface border border-outline-variant rounded-xl p-4">
                <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3 border-b border-outline-variant pb-2">Pipeline Status</span>
                <div className="space-y-3 text-[11px]">
                  <div className="flex justify-between"><span className="text-on-surface-variant">Video Connected</span><span className={`font-semibold ${stream.status.video_connected ? 'text-success' : 'text-error'}`}>{stream.status.video_connected ? 'YES' : 'NO'}</span></div>
                  <div className="flex justify-between"><span className="text-on-surface-variant">AI Processing</span><span className={`font-semibold ${stream.status.ai_processing ? 'text-success' : 'text-on-surface-variant'}`}>{stream.status.ai_processing ? 'ACTIVE' : 'IDLE'}</span></div>
                  <div className="flex justify-between"><span className="text-on-surface-variant">Resolution</span><span className="font-mono text-on-surface">{stream.status.resolution || '—'}</span></div>
                  <div className="flex justify-between"><span className="text-on-surface-variant">Processing FPS</span><span className="font-mono text-on-surface">{stream.status.processing_fps.toFixed(1)}</span></div>
                  <div className="flex justify-between"><span className="text-on-surface-variant">Source FPS</span><span className="font-mono text-on-surface">{stream.status.source_fps.toFixed(1)}</span></div>
                  <div className="flex justify-between"><span className="text-on-surface-variant">Frames Processed</span><span className="font-mono text-on-surface">{stream.status.frames_processed.toLocaleString()}</span></div>
                  <div className="flex justify-between"><span className="text-on-surface-variant">Total Detections</span><span className="font-mono text-on-surface">{stream.status.total_detections.toLocaleString()}</span></div>
                </div>
              </div>
            )}

            {/* Detections Detail */}
            <div className="bg-surface border border-outline-variant rounded-xl p-4">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3 border-b border-outline-variant pb-2">Detections ({detections.length})</span>
              <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto">
                {detections.length === 0 ? (
                  <div className="py-4 text-center text-[11px] text-on-surface-variant">No active detections</div>
                ) : (
                  detections.map((det, idx) => (
                    <div key={'det-' + det.track_id + '-' + idx} className="p-2 rounded-lg border border-outline-variant bg-surface-container-low">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[11px] text-primary">{det.class_name.toUpperCase()} #{det.track_id}</span>
                        <span className="font-mono text-[10px] font-bold text-success">{Math.round(det.confidence * 100)}%</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Face Detections */}
            {faces.length > 0 && (
              <div className="bg-surface border border-outline-variant rounded-xl p-4">
                <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3 border-b border-outline-variant pb-2">Face Detection ({faces.length})</span>
                <div className="flex flex-col gap-2 max-h-[200px] overflow-y-auto">
                  {faces.map((face, idx) => (
                    <div key={'face-' + idx} className="p-2 rounded-lg border border-outline-variant bg-surface-container-low">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[11px] text-warning">FACE #{face.personTrackId || idx}</span>
                        <span className="font-mono text-[10px] font-bold text-success">{Math.round(face.confidence * 100)}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Track Context */}
            {trackContext.length > 0 && (
              <div className="bg-surface border border-outline-variant rounded-xl p-4">
                <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3 border-b border-outline-variant pb-2">Track Context ({trackContext.length})</span>
                <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto">
                  {trackContext.map((ctx) => (
                    <div key={'ctx-' + ctx.track_id} className="p-2 rounded-lg border border-outline-variant bg-surface-container-low">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-[11px] text-primary">{ctx.object_class.toUpperCase()} #{ctx.track_id}</span>
                      </div>
                      <div className="grid grid-cols-2 gap-1 text-[10px]">
                        <span className="text-on-surface-variant">Dwell: <span className="text-on-surface font-semibold">{ctx.dwell_seconds}s</span></span>
                        <span className="text-on-surface-variant">Direction: <span className="text-on-surface font-semibold">{ctx.direction}</span></span>
                        {ctx.loitering && <span className="text-warning font-bold">Loitering</span>}
                        {ctx.fence_proximity && <span className="text-error font-bold">Near Fence ({ctx.distance_to_fence.toFixed(1)}m)</span>}
                        {ctx.repeated_entry && <span className="text-warning font-bold">Repeated Entry (#{ctx.entry_count})</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Technical Details */}
            <div className="bg-surface border border-outline-variant rounded-xl overflow-hidden">
              <button onClick={() => setShowTechDetails(!showTechDetails)}
                className="w-full p-3 bg-surface-container-low hover:bg-surface-container-high flex items-center justify-between text-[11px] font-bold text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[16px]">terminal</span>
                  <span>Technical Details</span>
                </div>
                <span className="material-symbols-outlined text-[14px]">{showTechDetails ? 'expand_less' : 'expand_more'}</span>
              </button>
              {showTechDetails && (
                <div className="p-4 grid grid-cols-2 gap-3 border-t border-outline-variant text-[11px]">
                  <div><span className="text-on-surface-variant block mb-0.5">RTSP URL</span><span className="font-mono text-on-surface text-[10px] break-all">{camera.rtspUrl || 'N/A'}</span></div>
                  <div><span className="text-on-surface-variant block mb-0.5">Coordinates</span><span className="font-mono text-on-surface">{camera.coordinates}</span></div>
                  {health && (
                    <>
                      <div><span className="text-on-surface-variant block mb-0.5">Health Status</span><span className="font-mono text-on-surface">{health.status}</span></div>
                      <div><span className="text-on-surface-variant block mb-0.5">Reconnects</span><span className="font-mono text-on-surface">{health.reconnectCount}</span></div>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* FULLSCREEN PORTAL */}
      {isFullscreen && createPortal(
        <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: '#000', display: 'flex', flexDirection: 'column' }}>
          <div style={{ position: 'relative', flex: 1, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <img src={stream.videoUrl || undefined} alt={camera.name}
              style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover',
                transform: `scale(${ptzPan.zoom}) translate(${ptzPan.pan}px, ${ptzPan.tilt}px)`,
                filter: isNightFilter ? 'grayscale(75%) brightness(1.2) contrast(1.2) hue-rotate(90deg)' : 'none' }} />
            {isNightFilter && <div style={{ position: 'absolute', inset: 0, background: 'rgba(2,44,30,0.3)', mixBlendMode: 'color', pointerEvents: 'none' }} />}
            <IntrusionZoneLayer controller={zoneCtl} />
            {isRealAi && <AIBoundingBoxOverlay detections={detections} trackContext={trackContext} events={events} />}
            {isRealAi && <AIFaceOverlay faces={faces} />}

            {/* Fullscreen PTZ Overlay - bottom right */}
            <div style={{ position: 'absolute', bottom: '80px', right: '20px', zIndex: 20 }} tabIndex={0}
              onFocus={() => setPtzFocused(true)} onBlur={() => setPtzFocused(false)}>
              {ptzCollapsed ? (
                <button onClick={() => setPtzCollapsed(false)}
                  style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px', borderRadius: '8px', backgroundColor: 'rgba(255,255,255,0.2)', backdropFilter: 'blur(8px)', color: '#fff', fontSize: '12px', fontWeight: 600, cursor: 'pointer', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>gamepad</span> PTZ
                </button>
              ) : (
                <div style={{ backgroundColor: 'rgba(20,20,30,0.9)', backdropFilter: 'blur(12px)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.1)', overflow: 'hidden', width: '220px' }}>
                  <div style={{ padding: '6px 12px', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span className="material-symbols-outlined" style={{ fontSize: '14px', color: '#7C8CF8' }}>gamepad</span>
                      <span style={{ fontSize: '10px', fontWeight: 700, color: '#fff', letterSpacing: '0.05em' }}>PTZ</span>
                    </div>
                    <button onClick={() => setPtzCollapsed(true)} style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.5)', cursor: 'pointer', padding: '2px' }}>
                      <span className="material-symbols-outlined" style={{ fontSize: '14px' }}>minimize</span>
                    </button>
                  </div>
                  <div style={{ padding: '12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px', width: '112px' }}>
                      <div />
                      <button onClick={() => setPtzPan((p) => ({ ...p, tilt: Math.min(25, p.tilt + 8) }))} style={{ height: '28px', borderRadius: '6px', backgroundColor: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)', color: '#7C8CF8', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <span className="material-symbols-outlined" style={{ fontSize: '15px' }}>expand_less</span>
                      </button>
                      <div />
                      <button onClick={() => setPtzPan((p) => ({ ...p, pan: Math.max(-40, p.pan - 8) }))} style={{ height: '28px', borderRadius: '6px', backgroundColor: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)', color: '#7C8CF8', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <span className="material-symbols-outlined" style={{ fontSize: '15px' }}>chevron_left</span>
                      </button>
                      <button onClick={() => setPtzPan({ pan: 0, tilt: 0, zoom: 1 })} style={{ height: '28px', borderRadius: '6px', backgroundColor: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.1)', color: 'rgba(255,255,255,0.7)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '8px', fontWeight: 700 }}>CTR</button>
                      <button onClick={() => setPtzPan((p) => ({ ...p, pan: Math.min(40, p.pan + 8) }))} style={{ height: '28px', borderRadius: '6px', backgroundColor: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)', color: '#7C8CF8', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <span className="material-symbols-outlined" style={{ fontSize: '15px' }}>chevron_right</span>
                      </button>
                      <div />
                      <button onClick={() => setPtzPan((p) => ({ ...p, tilt: Math.max(-25, p.tilt - 8) }))} style={{ height: '28px', borderRadius: '6px', backgroundColor: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)', color: '#7C8CF8', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <span className="material-symbols-outlined" style={{ fontSize: '15px' }}>expand_more</span>
                      </button>
                      <div />
                    </div>
                    <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '6px', borderTop: '1px solid rgba(255,255,255,0.1)', fontSize: '10px' }}>
                      <span style={{ color: 'rgba(255,255,255,0.5)' }}>Zoom</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <button onClick={() => setPtzPan((p) => ({ ...p, zoom: Math.max(1, +(p.zoom - 0.2).toFixed(1)) }))} style={{ width: '20px', height: '20px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px' }}>-</button>
                        <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#7C8CF8', fontWeight: 700, minWidth: '28px', textAlign: 'center' }}>{ptzPan.zoom.toFixed(1)}x</span>
                        <button onClick={() => setPtzPan((p) => ({ ...p, zoom: Math.min(3, +(p.zoom + 0.2).toFixed(1)) }))} style={{ width: '20px', height: '20px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px' }}>+</button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* Fullscreen PTZ Position Indicator */}
            {(ptzPan.pan !== 0 || ptzPan.tilt !== 0 || ptzPan.zoom !== 1) && (
              <div style={{ position: 'absolute', top: '80px', left: '20px', padding: '4px 8px', backgroundColor: 'rgba(0,0,0,0.6)', color: '#fff', fontSize: '10px', borderRadius: '4px', fontFamily: 'JetBrains Mono, monospace', backdropFilter: 'blur(4px)', zIndex: 20 }}>
                P:{ptzPan.pan} T:{ptzPan.tilt} Z:{ptzPan.zoom.toFixed(1)}x
              </div>
            )}
          </div>
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(to bottom, rgba(0,0,0,0.75), transparent)', zIndex: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: stream.isConnected ? '#3E7655' : '#B44C4C', animation: 'pulse 2s infinite' }} />
              <span style={{ fontSize: '14px', fontWeight: 700, color: '#fff', fontFamily: 'JetBrains Mono, monospace' }}>{camera.id}</span>
              <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.8)' }}>&mdash; {camera.name}</span>
              {isRealAi && (
                <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 700,
                  backgroundColor: aiProcessing ? 'rgba(62,118,85,0.8)' : 'rgba(184,76,76,0.8)', color: '#fff' }}>
                  AI {aiProcessing ? 'LIVE' : 'OFFLINE'}
                </span>
              )}
            </div>
            <button onClick={() => setIsFullscreen(false)}
              style={{ padding: '10px', borderRadius: '8px', cursor: 'pointer', backgroundColor: 'rgba(255,255,255,0.15)', border: 'none', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <span className="material-symbols-outlined" style={{ fontSize: '22px' }}>fullscreen_exit</span>
            </button>
          </div>
          <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'linear-gradient(to top, rgba(0,0,0,0.75), transparent)', zIndex: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              {detections.length > 0 ? (
                <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.9)' }}>Targets: {detections.map((d) => '#' + d.track_id).join(', ')}</span>
              ) : (
                <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}>No Active Targets</span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button onClick={handleTakeSnapshot} style={{ padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: 'rgba(255,255,255,0.15)', color: '#fff', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>photo_camera</span> Snapshot
              </button>
              <button onClick={() => setIsRecording(!isRecording)} style={{ padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: isRecording ? 'rgba(184,76,76,0.8)' : 'rgba(255,255,255,0.15)', color: '#fff', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>{isRecording ? 'stop_circle' : 'fiber_manual_record'}</span> {isRecording ? 'Stop' : 'Record'}
              </button>
              <button onClick={() => setIsNightFilter(!isNightFilter)} style={{ padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: isNightFilter ? 'rgba(76,139,139,0.6)' : 'rgba(255,255,255,0.15)', color: '#fff', fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>nightlight</span> Night
              </button>
            </div>
          </div>
          <div style={{ position: 'absolute', bottom: '60px', left: '50%', transform: 'translateX(-50%)', fontSize: '11px', color: 'rgba(255,255,255,0.3)', zIndex: 10 }}>
            Press ESC to exit fullscreen
          </div>
        </div>, document.body
      )}
      {zoneCtl.menuPos && <ZoneManageMenu controller={zoneCtl} />}
      {zoneCtl.statusPos && <ZoneStatusPanel controller={zoneCtl} />}
    </div>
  );
};

// ─── Main Component ──────────────────────────────────────────────────────────

export const CamerasMonitoringView: React.FC<CamerasMonitoringViewProps> = ({
  cameras,
  zones,
  selectedCameraId,
  onSelectCamera,
  onAiMetadata,
  onSaveZone,
  onDeleteZone,
}) => {
  const { token } = useAuth();
  const [viewMode, setViewMode] = useState<ViewMode>(selectedCameraId ? 'single' : 'grid');
  const [activeCameraId, setActiveCameraId] = useState<string | null>(selectedCameraId || null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [analysisCameraId, setAnalysisCameraId] = useState<string | null>(null);
  const [zoneCreatePending, setZoneCreatePending] = useState<string | null>(null);
  const cameraAiStatesRef = useRef<Record<string, boolean>>({});

  // Sync with parent-selected camera
  useEffect(() => {
    if (selectedCameraId) {
      setActiveCameraId(selectedCameraId);
      setViewMode('single');
    }
  }, [selectedCameraId]);

  const handleAiStateChange = useCallback((cameraId: string, enabled: boolean) => {
    cameraAiStatesRef.current[cameraId] = enabled;
  }, []);

  const activeCamera = cameras.find((c) => c.id === activeCameraId) || null;

  const handleOpenCamera = useCallback((id: string) => {
    setActiveCameraId(id);
    setViewMode('single');
    onSelectCamera?.(id);
  }, [onSelectCamera]);

  const handleBackToGrid = useCallback(() => {
    setViewMode('grid');
    setActiveCameraId(null);
  }, []);

  const handleContextMenu = useCallback((cameraId: string, x: number, y: number) => {
    setContextMenu({ cameraId, x, y });
  }, []);

  const [aiToggleError, setAiToggleError] = useState<string | null>(null);

  const handleToggleAi = useCallback(async (cameraId: string, enabled: boolean) => {
    setAiToggleError(null);
    try {
      const resp = await fetch(`/api/cameras/${cameraId}/ai-toggle`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ai_enabled: enabled }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        setAiToggleError(body.detail || `Failed (${resp.status})`);
        setTimeout(() => setAiToggleError(null), 4000);
      }
    } catch {
      setAiToggleError('Network error - AI backend unreachable');
      setTimeout(() => setAiToggleError(null), 4000);
    }
  }, [token]);

  const handleContextAction = useCallback((action: ContextMenuAction) => {
    if (!contextMenu) return;
    const cid = contextMenu.cameraId;
    setContextMenu(null);
    switch (action) {
      case 'open':
        handleOpenCamera(cid);
        break;
      case 'fullscreen':
        handleOpenCamera(cid);
        break;
      case 'analysis':
        setAnalysisCameraId(cid);
        handleOpenCamera(cid);
        break;
      case 'alerts':
        break;
      case 'anpr':
        break;
      case 'ai-toggle': {
        const currentAi = cameraAiStatesRef.current[cid] !== false;
        handleToggleAi(cid, !currentAi);
        break;
      }
      case 'zone': {
        // Deep-link straight into create mode only when this camera has no zone yet.
        if (!zones.some((z) => z.cameraId === cid)) {
          setZoneCreatePending(cid);
        }
        handleOpenCamera(cid);
        break;
      }
    }
  }, [contextMenu, handleOpenCamera, handleToggleAi, zones]);

  // Close context menu on click outside
  useEffect(() => {
    if (!contextMenu) return;
    const handler = () => setContextMenu(null);
    window.addEventListener('click', handler);
    return () => window.removeEventListener('click', handler);
  }, [contextMenu]);

  // Empty state
  if (cameras.length === 0) {
    return (
      <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
        <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-xl">videocam</span>
              Cameras &amp; Live Streams
            </h1>
            <p className="text-[12px] text-on-surface-variant mt-0.5">Real-time CCTV monitoring &middot; Target tracking &middot; PTZ controls</p>
          </div>
        </div>
        <div className="bg-surface border border-outline-variant rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-[48px] text-on-surface-variant/40 block mb-3">videocam_off</span>
          <p className="text-on-surface-variant text-sm">No cameras registered</p>
          <p className="text-on-surface-variant/60 text-[11px] mt-1">Register cameras in Settings to start monitoring</p>
        </div>
      </div>
    );
  }

  // Single camera view
  if (viewMode === 'single' && activeCamera) {
    return (
      <SingleCameraView
        camera={activeCamera}
        cameras={cameras}
        token={token}
        zones={zones}
        onSelectCamera={handleOpenCamera}
        onBack={handleBackToGrid}
        onAiMetadata={onAiMetadata}
        onToggleAi={handleToggleAi}
        onSaveZone={onSaveZone}
        onDeleteZone={onDeleteZone}
        pendingCreate={zoneCreatePending === activeCamera.id}
        onPendingCreateHandled={() => setZoneCreatePending(null)}
      />
    );
  }

  // Grid view (All Cameras)
  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* AI Toggle Error Toast */}
      {aiToggleError && (
        <div className="px-4 py-2.5 bg-error-container border border-error/20 text-error text-[12px] font-semibold rounded-lg flex items-center gap-2">
          <span className="material-symbols-outlined text-[16px]">error</span> {aiToggleError}
        </div>
      )}

      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">videocam</span>
            All Cameras
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">
            {cameras.length} registered camera{cameras.length !== 1 ? 's' : ''} &middot; Live monitoring wall
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-on-surface-variant font-semibold">
            {cameras.filter((c) => c.status === 'ONLINE').length} ONLINE
          </span>
        </div>
      </div>

      {/* Camera Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {cameras.map((camera) => (
          <CameraTile
            key={camera.id}
            camera={camera}
            token={token}
            zones={zones}
            onOpen={handleOpenCamera}
            onContextMenu={handleContextMenu}
            onAiMetadata={onAiMetadata}
            onToggleAi={handleToggleAi}
            onAiStateChange={handleAiStateChange}
            onSaveZone={onSaveZone}
            onDeleteZone={onDeleteZone}
          />
        ))}
      </div>

      {/* Context Menu */}
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
            <button onClick={() => handleContextAction('open')} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">open_in_new</span> Open Camera
            </button>
            <button onClick={() => handleContextAction('fullscreen')} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">fullscreen</span> Fullscreen
            </button>
            <button onClick={() => handleContextAction('analysis')} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">analytics</span> Camera Analysis
            </button>
            <div className="border-t border-outline-variant/50 my-0.5" />
            <button onClick={() => handleContextAction('ai-toggle')} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">smart_toy</span> Toggle AI
            </button>
            <button onClick={() => handleContextAction('zone')} className="w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors" data-testid="ctx-menu-zone">
              <span className="material-symbols-outlined text-[14px]">fence</span> Intrusion Zone
            </button>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};
