import React, { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { CameraFeed, AiTrackingMetadata } from '../types';
import { useAiCameraStream } from '../hooks/useAiCameraStream';
import { useAuth } from '../contexts/AuthContext';
import { AIBoundingBoxOverlay } from '../components/AIBoundingBoxOverlay';
import { AIFaceOverlay } from '../components/AIFaceOverlay';

interface CamerasMonitoringViewProps {
  cameras: CameraFeed[];
  selectedCameraId?: string;
  onSelectCamera?: (id: string) => void;
  onAiMetadata?: (metadata: AiTrackingMetadata) => void;
}

export const CamerasMonitoringView: React.FC<CamerasMonitoringViewProps> = ({
  cameras,
  selectedCameraId = 'CAM-04',
  onSelectCamera,
  onAiMetadata,
}) => {
  const [internalCameraId, setInternalCameraId] = useState<string>(selectedCameraId);
  const currentSelectedId = selectedCameraId || internalCameraId;
  const activeCamera = cameras.find((c) => c.id === currentSelectedId) || cameras[0];

  if (!activeCamera) {
    return (
      <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
        <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-xl">videocam</span>
              Cameras &amp; Live Streams
            </h1>
            <p className="text-[12px] text-on-surface-variant mt-0.5">
              Real-time CCTV monitoring &middot; Target tracking &middot; PTZ controls
            </p>
          </div>
        </div>
        <div className="bg-surface border border-outline-variant rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-[48px] text-on-surface-variant/40 block mb-3">videocam_off</span>
          <p className="text-on-surface-variant text-sm">No cameras registered</p>
          <p className="text-on-surface-variant/60 text-[11px] mt-1">Camera feeds will appear here once cameras are connected</p>
        </div>
      </div>
    );
  }

  const [isNightFilter, setIsNightFilter] = useState(activeCamera.isNightMode);
  const [isRecording, setIsRecording] = useState(false);
  const [ptzPan, setPtzPan] = useState({ pan: 0, tilt: 0, zoom: 1 });
  const [snapshotMessage, setSnapshotMessage] = useState<string | null>(null);
  const [showTechDetails, setShowTechDetails] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // AI Pipeline integration
  const [aiEnabled, setAiEnabled] = useState(true);
  const [aiToggleLoading, setAiToggleLoading] = useState(false);
  const aiStream = useAiCameraStream();
  const { token } = useAuth();
  // Use backend AI state from metadata when available, fallback to local state
  const backendAiEnabled = aiStream.metadata?.ai_enabled;
  const isRealAi = (backendAiEnabled !== undefined ? backendAiEnabled : aiEnabled) && aiStream.isConnected;

  // Always compute the real video URL for the MJPEG stream
  const AI_BASE = (import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8000');
  const realVideoUrl = currentSelectedId && token
    ? AI_BASE + '/video/stream/' + currentSelectedId + '?token=' + token
    : '';

  // Always connect WebSocket for the selected camera (AI state is backend-controlled)
  useEffect(() => {
    if (currentSelectedId) {
      aiStream.connect(currentSelectedId, token || undefined);
    }
    return () => { aiStream.disconnect(); };
  }, [currentSelectedId, token]);

  // Forward AI metadata to parent for alert processing
  useEffect(() => {
    if (aiStream.metadata && onAiMetadata) {
      onAiMetadata(aiStream.metadata);
    }
  }, [aiStream.metadata]);

  // ESC to exit fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsFullscreen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isFullscreen]);

  // Lock body scroll when fullscreen
  useEffect(() => {
    if (isFullscreen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isFullscreen]);

  const handleTakeSnapshot = () => {
    setSnapshotMessage(`Snapshot saved from ${activeCamera.id} at ${new Date().toISOString().substring(11, 19)} UTC`);
    setTimeout(() => setSnapshotMessage(null), 3500);
  };

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">videocam</span>
            Cameras &amp; Live Streams
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">
            Real-time CCTV monitoring &middot; Target tracking &middot; PTZ controls
          </p>
        </div>
        {snapshotMessage && (
          <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
            <span className="material-symbols-outlined text-[14px]">check_circle</span>
            {snapshotMessage}
          </div>
        )}
      </div>

      {/* Main 3-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* LEFT: Camera List (3 cols) */}
        <div className="lg:col-span-3 bg-surface border border-outline-variant rounded-xl flex flex-col overflow-hidden">
          <div className="p-3 bg-surface-container-low border-b border-outline-variant flex items-center justify-between">
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Channels ({cameras.length})</span>
            <span className="text-[10px] font-semibold text-on-surface-variant flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant" /> —
            </span>
          </div>
          <div className="flex flex-col divide-y divide-outline-variant/40 overflow-y-auto max-h-[640px]">
            {cameras.map((camera) => {
              const isSelected = camera.id === activeCamera.id;
              const hasThreat = camera.detections.some((d) => d.isThreat);
              return (
                <button
                  key={camera.id}
                  onClick={() => {
                    setInternalCameraId(camera.id);
                    onSelectCamera?.(camera.id);
                    setIsNightFilter(camera.isNightMode);
                  }}
                  className={`p-3 cursor-pointer transition-all flex flex-col gap-1 border-l-4 text-left ${
                    isSelected
                      ? 'bg-primary/10 border-primary text-primary'
                      : 'hover:bg-surface-container-high border-transparent text-on-surface'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono font-bold text-[12px]">{camera.id}</span>
                      <span className="text-[10px] text-on-surface-variant truncate">&middot; {camera.name}</span>
                    </div>
                    {hasThreat && <span className="w-2 h-2 rounded-full bg-error" />}
                  </div>
                  <div className="text-[10px] text-on-surface-variant flex items-center justify-between">
                    <span>{camera.location}</span>
                    <span className="font-mono font-semibold text-on-surface">
                      {camera.detections.length} Target{camera.detections.length !== 1 ? 's' : ''}
                    </span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* CENTER: Live Feed (6 cols) */}
        <div className="lg:col-span-6 flex flex-col gap-3">
          <div className="bg-surface border border-outline-variant rounded-xl flex flex-col overflow-hidden">
            {/* Feed Header */}
            <div className="h-9 bg-surface-container-low border-b border-outline-variant px-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                <span className="text-[11px] font-bold text-primary font-mono">{activeCamera.id}</span>
                <span className="text-[11px] text-on-surface font-medium">&mdash; {activeCamera.name}</span>
              </div>
              <div className="flex items-center gap-2 text-[10px]">
                {isRealAi && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold flex items-center gap-1 ${aiStream.status?.ai_processing ? 'bg-success-container text-success' : 'bg-error-container text-error'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${aiStream.status?.ai_processing ? 'bg-success' : 'bg-error'}`} />
                    AI {aiStream.status?.ai_processing ? 'LIVE' : 'OFFLINE'}
                  </span>
                )}
                {isRealAi && aiStream.status?.camera && aiStream.status.camera.status !== 'CONNECTED' && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold flex items-center gap-1 ${
                    aiStream.status.camera.status === 'STALE' ? 'bg-warning-container text-warning'
                    : aiStream.status.camera.status === 'RECONNECTING' || aiStream.status.camera.status === 'CONNECTING' ? 'bg-primary-container text-primary'
                    : 'bg-error-container text-error'}`}>
                    {aiStream.status.camera.status}
                    {aiStream.status.camera.reconnectCount > 0 && ` (${aiStream.status.camera.reconnectCount})`}
                  </span>
                )}
                {isRealAi && aiStream.status?.camera?.syncState && aiStream.status.camera.syncState !== 'IDLE' && (
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold flex items-center gap-1 ${
                    aiStream.status.camera.syncState === 'SYNCING' ? 'bg-warning-container text-warning'
                    : aiStream.status.camera.syncState === 'COMPLETED' ? 'bg-success-container text-success'
                    : 'bg-error-container text-error'}`}>
                    <span className={`w-1.5 h-1.5 rounded-full ${aiStream.status.camera.syncState === 'SYNCING' ? 'bg-warning animate-pulse' : aiStream.status.camera.syncState === 'COMPLETED' ? 'bg-success' : 'bg-error'}`} />
                    SD {aiStream.status.camera.syncState}
                    {aiStream.status.camera.pendingFootageCount !== undefined && aiStream.status.camera.pendingFootageCount > 0 && ` (${aiStream.status.camera.pendingFootageCount})`}
                  </span>
                )}
                {isRecording && (
                  <span className="text-error font-bold flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-error" /> REC
                  </span>
                )}
                <span className="text-on-surface-variant font-mono">{activeCamera.location}</span>
              </div>
            </div>

            {/* Video */}
            <div className="relative w-full aspect-video bg-surface-container-low overflow-hidden select-none">
              <img
                src={realVideoUrl || undefined}
                alt={activeCamera.name}
                className="w-full h-full object-cover transition-transform duration-300"
                style={{
                  transform: `scale(${ptzPan.zoom}) translate(${ptzPan.pan}px, ${ptzPan.tilt}px)`,
                  filter: isNightFilter ? 'grayscale(75%) brightness(1.2) contrast(1.2) hue-rotate(90deg)' : 'none',
                }}
              />
              {isNightFilter && <div className="absolute inset-0 bg-emerald-950/30 mix-blend-color pointer-events-none" />}

              {/* AI Bounding Box Overlay (real pipeline) */}
              {isRealAi && (
                <AIBoundingBoxOverlay detections={aiStream.metadata?.detections || []} trackContext={aiStream.metadata?.track_context} />
              )}

              {/* AI Face Overlay (detection only) */}
              {isRealAi && (
                <AIFaceOverlay faces={aiStream.metadata?.faces || []} />
              )}
            </div>

            {/* Actions Toolbar */}
            <div className="p-3 bg-surface-container-low border-t border-outline-variant flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <button
                  onClick={async () => {
                    if (!currentSelectedId || aiToggleLoading) return;
                    const newState = !aiEnabled;
                    setAiToggleLoading(true);
                    try {
                      const res = await fetch(`/api/cameras/${currentSelectedId}/ai-toggle`, {
                        method: 'POST',
                        headers: {
                          'Content-Type': 'application/json',
                          ...(token ? { Authorization: `Bearer ${token}` } : {}),
                        },
                        body: JSON.stringify({ ai_enabled: newState }),
                      });
                      if (res.ok) {
                        const data = await res.json();
                        setAiEnabled(data.ai_enabled);
                      }
                      // On failure: keep previous state
                    } catch {
                      // On network error: keep previous state
                    } finally {
                      setAiToggleLoading(false);
                    }
                  }}
                  disabled={aiToggleLoading}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${aiEnabled ? 'bg-success-container text-success border-success/30' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'}`}
                >
                  <span className="material-symbols-outlined text-[14px]">smart_toy</span> AI {aiToggleLoading ? '...' : aiEnabled ? 'ON' : 'OFF'}
                </button>
                <button
                  onClick={handleTakeSnapshot}
                  className="px-3 py-1.5 rounded-lg bg-surface hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface font-semibold flex items-center gap-1.5 cursor-pointer transition-colors"
                >
                  <span className="material-symbols-outlined text-[14px] text-primary">photo_camera</span> Snapshot
                </button>
                <button
                  onClick={() => setIsRecording(!isRecording)}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${
                    isRecording ? 'bg-error text-on-error border-error' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'
                  }`}
                >
                  <span className="material-symbols-outlined text-[14px]">{isRecording ? 'stop_circle' : 'fiber_manual_record'}</span>
                  {isRecording ? 'Stop' : 'Record'}
                </button>
                <button
                  onClick={() => setIsNightFilter(!isNightFilter)}
                  className={`px-3 py-1.5 rounded-lg border text-[11px] font-semibold flex items-center gap-1.5 cursor-pointer transition-colors ${
                    isNightFilter ? 'bg-tertiary text-on-tertiary border-tertiary' : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface'
                  }`}
                >
                  <span className="material-symbols-outlined text-[14px]">nightlight</span> Night
                </button>
              </div>
              <button
                onClick={() => setIsFullscreen(!isFullscreen)}
                className="px-3 py-1.5 rounded-lg bg-surface hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface font-semibold flex items-center gap-1 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[14px]">fullscreen</span> Fullscreen
              </button>
            </div>
          </div>
        </div>

        {/* RIGHT: Active Targets + PTZ (3 cols) */}
        <div className="lg:col-span-3 flex flex-col gap-4">
          {/* Targets */}
          <div className="bg-surface border border-outline-variant rounded-xl flex flex-col overflow-hidden">
            <div className="p-3 bg-surface-container-low border-b border-outline-variant flex items-center justify-between">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Active Targets</span>
              <span className="text-[10px] font-semibold text-primary font-mono">{isRealAi ? (aiStream.metadata?.detections?.length || 0) : activeCamera.detections.length} DETECTED</span>
            </div>
            <div className="p-3 flex flex-col gap-2 max-h-[300px] overflow-y-auto">
              {isRealAi ? (
                (aiStream.metadata?.detections || []).length === 0 ? (
                  <div className="py-6 text-center text-[11px] text-on-surface-variant">
                    <span className="material-symbols-outlined text-[20px] text-on-surface-variant/50 block mb-1">smart_toy</span>
                    AI detecting... {aiStream.status?.ai_processing ? '(' + aiStream.status.processing_fps.toFixed(1) + ' FPS)' : 'connecting'}
                  </div>
                ) : (
                  aiStream.metadata!.detections.map((det, idx) => (
                    <div
                      key={'ai-tgt-' + det.track_id + '-' + idx}
                      className="p-3 rounded-lg border border-outline-variant bg-surface-container-low flex flex-col gap-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[12px] text-primary">{det.class_name.toUpperCase()} #{det.track_id}</span>
                        <span className="font-mono text-[11px] font-bold text-success">{Math.round(det.confidence * 100)}%</span>
                      </div>
                      <div className="text-[10px] text-on-surface-variant">AI Pipeline - Real-time tracking</div>
                    </div>
                  ))
                )
              ) : (
                activeCamera.detections.length === 0 ? (
                  <div className="py-6 text-center text-[11px] text-on-surface-variant">No active targets</div>
                ) : (
                  activeCamera.detections.map((det) => (
                    <div
                      key={det.id}
                      className={`p-3 rounded-lg border ${
                        det.isThreat ? 'border-error/30 bg-error-container/20' : 'border-outline-variant bg-surface-container-low'
                      } flex flex-col gap-1`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-[12px] text-primary">{det.classType.toUpperCase()} {det.trackId}</span>
                        <span className="font-mono text-[11px] font-bold text-success">{det.confidence}%</span>
                      </div>
                      <div className="text-[11px] text-on-surface-variant">
                        Status: <span className={det.isThreat ? 'text-error font-bold' : 'text-on-surface font-medium'}>{det.status}</span>
                      </div>
                      <div className="text-[10px] text-on-surface-variant truncate">Zone: <span className="font-medium text-on-surface">{det.zone}</span></div>
                      {det.plateNumber && (
                        <div className="mt-1 pt-1 border-t border-outline-variant/40 flex items-center justify-between text-[11px]">
                          <span className="text-on-surface-variant">Plate:</span>
                          <span className="font-mono font-bold text-primary bg-primary-container px-1.5 py-0.5 rounded">{det.plateNumber}</span>
                        </div>
                      )}
                    </div>
                  ))
                )
              )}
            </div>
          </div>

          {/* PTZ Controls */}
          <div className="bg-surface border border-outline-variant rounded-xl p-4">
            <div className="flex items-center justify-between mb-3 border-b border-outline-variant pb-2">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">PTZ Controls</span>
              <span className="text-[10px] text-success font-semibold">Motor Ready</span>
            </div>
            <div className="flex flex-col items-center gap-3">
              <div className="grid grid-cols-3 gap-1.5 w-32 h-32">
                <div />
                <button onClick={() => setPtzPan((p) => ({ ...p, tilt: Math.min(25, p.tilt + 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-lg flex items-center justify-center text-primary cursor-pointer"><span className="material-symbols-outlined text-[18px]">expand_less</span></button>
                <div />
                <button onClick={() => setPtzPan((p) => ({ ...p, pan: Math.max(-40, p.pan - 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-lg flex items-center justify-center text-primary cursor-pointer"><span className="material-symbols-outlined text-[18px]">chevron_left</span></button>
                <button onClick={() => setPtzPan({ pan: 0, tilt: 0, zoom: 1 })} className="bg-surface-container-high border border-outline-variant rounded-lg flex items-center justify-center text-[9px] text-on-surface-variant font-bold cursor-pointer">CENTER</button>
                <button onClick={() => setPtzPan((p) => ({ ...p, pan: Math.min(40, p.pan + 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-lg flex items-center justify-center text-primary cursor-pointer"><span className="material-symbols-outlined text-[18px]">chevron_right</span></button>
                <div />
                <button onClick={() => setPtzPan((p) => ({ ...p, tilt: Math.max(-25, p.tilt - 8) }))} className="bg-surface-container-low hover:bg-surface-container-high border border-outline-variant rounded-lg flex items-center justify-center text-primary cursor-pointer"><span className="material-symbols-outlined text-[18px]">expand_more</span></button>
                <div />
              </div>
              <div className="w-full flex items-center justify-between pt-2 border-t border-outline-variant text-[11px]">
                <span className="text-on-surface-variant">Zoom</span>
                <div className="flex items-center gap-2">
                  <button onClick={() => setPtzPan((p) => ({ ...p, zoom: Math.max(1, p.zoom - 0.2) }))} className="px-2 py-0.5 bg-surface-container-low border border-outline-variant rounded text-on-surface cursor-pointer">-</button>
                  <span className="font-mono text-primary font-bold">{ptzPan.zoom.toFixed(1)}x</span>
                  <button onClick={() => setPtzPan((p) => ({ ...p, zoom: Math.min(3, p.zoom + 0.2) }))} className="px-2 py-0.5 bg-surface-container-low border border-outline-variant rounded text-on-surface cursor-pointer">+</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Technical Details (Progressive Disclosure) */}
      <div className="bg-surface border border-outline-variant rounded-xl overflow-hidden">
        <button
          onClick={() => setShowTechDetails(!showTechDetails)}
          className="w-full p-3 bg-surface-container-low hover:bg-surface-container-high flex items-center justify-between text-[11px] font-bold text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
        >
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[16px]">terminal</span>
            <span>Technical Stream Details</span>
          </div>
          <div className="flex items-center gap-1 text-primary">
            <span>{showTechDetails ? 'Hide' : 'Expand'}</span>
            <span className="material-symbols-outlined text-[14px]">{showTechDetails ? 'expand_less' : 'expand_more'}</span>
          </div>
        </button>
        {showTechDetails && (
          <div className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-4 border-t border-outline-variant text-[11px]">
            <div><span className="text-on-surface-variant block mb-0.5">RTSP URL</span><span className="font-mono text-on-surface">{activeCamera.rtspUrl}</span></div>
            <div><span className="text-on-surface-variant block mb-0.5">Resolution</span><span className="font-mono text-on-surface">{activeCamera.resolution} &middot; {activeCamera.bitrate}</span></div>
            <div><span className="text-on-surface-variant block mb-0.5">Inference</span><span className="font-mono text-on-surface">{activeCamera.fps} FPS &middot; 32ms Latency</span></div>
            <div><span className="text-on-surface-variant block mb-0.5">Coordinates</span><span className="font-mono text-on-surface">{activeCamera.coordinates}</span></div>
            {isRealAi && aiStream.status && (
              <>
                <div><span className="text-on-surface-variant block mb-0.5">AI Pipeline</span><span className="font-mono text-success">Connected &middot; {aiStream.status.resolution}</span></div>
                <div><span className="text-on-surface-variant block mb-0.5">Processing FPS</span><span className="font-mono text-on-surface">{aiStream.status.processing_fps.toFixed(1)}</span></div>
                <div><span className="text-on-surface-variant block mb-0.5">Source FPS</span><span className="font-mono text-on-surface">{aiStream.status.source_fps.toFixed(1)}</span></div>
                <div><span className="text-on-surface-variant block mb-0.5">Frames Processed</span><span className="font-mono text-on-surface">{aiStream.status.frames_processed.toLocaleString()}</span></div>
              </>
            )}
          </div>
        )}
      </div>

      {/* FULLSCREEN PORTAL */}
      {isFullscreen && createPortal(
        <div
          style={{ position: 'fixed', inset: 0, zIndex: 9999, background: '#000', display: 'flex', flexDirection: 'column' }}
        >
          <div style={{ position: 'relative', flex: 1, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <img
              src={realVideoUrl || undefined}
              alt={activeCamera.name}
              style={{
                position: 'absolute', top: 0, left: 0, width: '100%', height: '100%',
                objectFit: 'cover',
                transform: `scale(${ptzPan.zoom}) translate(${ptzPan.pan}px, ${ptzPan.tilt}px)`,
                filter: isNightFilter ? 'grayscale(75%) brightness(1.2) contrast(1.2) hue-rotate(90deg)' : 'none',
              }}
            />
            {isNightFilter && <div style={{ position: 'absolute', inset: 0, background: 'rgba(2, 44, 30, 0.3)', mixBlendMode: 'color', pointerEvents: 'none' }} />}

            {/* AI Bounding Box Overlay in fullscreen */}
            {isRealAi && (
              <AIBoundingBoxOverlay detections={aiStream.metadata?.detections || []} trackContext={aiStream.metadata?.track_context} />
            )}

            {/* AI Face Overlay in fullscreen (detection only) */}
            {isRealAi && (
              <AIFaceOverlay faces={aiStream.metadata?.faces || []} />
            )}
          </div>

          {/* Top overlay bar */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0,
            padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'linear-gradient(to bottom, rgba(0,0,0,0.75), transparent)', zIndex: 10,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#3E7655', animation: 'pulse 2s infinite' }} />
              <span style={{ fontSize: '14px', fontWeight: 700, color: '#fff', fontFamily: 'JetBrains Mono, monospace' }}>{activeCamera.id}</span>
              <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.8)' }}>&mdash; {activeCamera.name}</span>
              <span style={{ fontSize: '12px', color: 'rgba(255,255,255,0.5)' }}>{activeCamera.location}</span>
              {isRealAi && (
                <span style={{
                  padding: '2px 8px', borderRadius: '4px', fontSize: '10px', fontWeight: 700,
                  backgroundColor: aiStream.status?.ai_processing ? 'rgba(62,118,85,0.8)' : 'rgba(184,76,76,0.8)',
                  color: '#fff',
                }}>
                  AI {aiStream.status?.ai_processing ? 'LIVE' : 'OFFLINE'}
                </span>
              )}
            </div>
            <button
              onClick={() => setIsFullscreen(false)}
              style={{
                padding: '10px', borderRadius: '8px', cursor: 'pointer',
                backgroundColor: 'rgba(255,255,255,0.15)', border: 'none', color: '#fff',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: '22px' }}>fullscreen_exit</span>
            </button>
          </div>

          {/* Bottom overlay bar */}
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0,
            padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            background: 'linear-gradient(to top, rgba(0,0,0,0.75), transparent)', zIndex: 10,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              {isRealAi && aiStream.metadata?.detections ? (
                <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.9)' }}>
                  Targets: {aiStream.metadata.detections.map((d) => '#' + d.track_id).join(', ')}
                </span>
              ) : activeCamera.detections.length > 0 ? (
                <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.9)' }}>
                  Targets: {activeCamera.detections.map((d) => d.trackId).join(', ')}
                </span>
              ) : (
                <span style={{ fontSize: '13px', color: 'rgba(255,255,255,0.5)' }}>No Active Targets</span>
              )}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button onClick={handleTakeSnapshot} style={{
                padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none',
                backgroundColor: 'rgba(255,255,255,0.15)', color: '#fff',
                fontSize: '12px', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px',
              }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>photo_camera</span> Snapshot
              </button>
              <button onClick={() => setIsRecording(!isRecording)} style={{
                padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none',
                backgroundColor: isRecording ? 'rgba(184,76,76,0.8)' : 'rgba(255,255,255,0.15)',
                color: '#fff', fontSize: '12px', fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: '6px',
              }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>{isRecording ? 'stop_circle' : 'fiber_manual_record'}</span> {isRecording ? 'Stop' : 'Record'}
              </button>
              <button onClick={() => setIsNightFilter(!isNightFilter)} style={{
                padding: '8px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none',
                backgroundColor: isNightFilter ? 'rgba(76,139,139,0.6)' : 'rgba(255,255,255,0.15)',
                color: '#fff', fontSize: '12px', fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: '6px',
              }}>
                <span className="material-symbols-outlined" style={{ fontSize: '16px' }}>nightlight</span> Night
              </button>
            </div>
          </div>

          <div style={{
            position: 'absolute', bottom: '60px', left: '50%', transform: 'translateX(-50%)',
            fontSize: '11px', color: 'rgba(255,255,255,0.3)', zIndex: 10,
          }}>
            Press ESC to exit fullscreen
          </div>
        </div>, document.body
      )}
    </div>
  );
};
