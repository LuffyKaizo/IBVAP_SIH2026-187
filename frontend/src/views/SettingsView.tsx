import React, { useState } from 'react';
import { createPortal } from 'react-dom';
import { SystemSettingsConfig, CameraFeed } from '../types';

interface SettingsViewProps {
  config: SystemSettingsConfig;
  cameras: CameraFeed[];
  onSaveConfig?: (newConfig: SystemSettingsConfig) => void;
  onAddCamera?: (camera: { camera_id: string; name: string; source: string; source_type: string; location: string; camera_type?: string }) => Promise<{ success: boolean; message?: string }>;
  onReplaceCamera?: (cameraId: string, source: string, sourceType: string) => Promise<{ success: boolean; message?: string }>;
  onDeleteCamera?: (cameraId: string) => Promise<{ success: boolean; message?: string }>;
  authFetch?: (url: string, init?: RequestInit) => Promise<Response>;
}

interface VideoFileEntry {
  path: string;
  name: string;
  folder: string;
  size_bytes: number;
  extension: string;
}

/** Compute the smallest free camera ID above the highest used numeric suffix (handles gaps and CAM-10+). */
function nextCameraId(cameras: CameraFeed[]): string {
  const used = new Set(
    cameras
      .map((c) => c.id)
      .filter((id): id is string => typeof id === 'string')
      .map((id) => {
        const m = id.match(/^CAM-0*(\d+)$/i);
        return m ? parseInt(m[1], 10) : 0;
      })
  );
  let n = 1;
  while (used.has(n)) n += 1;
  return `CAM-${String(n).padStart(2, '0')}`;
}

const formatVideoSize = (bytes: number): string => {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
};

export const SettingsView: React.FC<SettingsViewProps> = ({ config, cameras, onSaveConfig, onAddCamera, onReplaceCamera, onDeleteCamera, authFetch }) => {
  const [formConfig, setFormConfig] = useState<SystemSettingsConfig>(config);
  const [activeTab, setActiveTab] = useState<'CAMERAS' | 'AI_CONFIG' | 'ALERT_RULES' | 'API_INTEGRATION' | 'SYSTEM_HEALTH'>('CAMERAS');
  const [saveStatus, setSaveStatus] = useState<{ kind: 'success' | 'error'; text: string } | null>(null);
  const [newCamId, setNewCamId] = useState(() => nextCameraId([]));
  const [newCamName, setNewCamName] = useState('');
  const [newCamSource, setNewCamSource] = useState('');
  const [newCamSourceType, setNewCamSourceType] = useState('video');
  const [newCamLocation, setNewCamLocation] = useState('');
  const [newCamType, setNewCamType] = useState('FIXED');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Replace modal state
  const [replaceModal, setReplaceModal] = useState<{ cameraId: string; currentSource: string } | null>(null);
  const [replaceSource, setReplaceSource] = useState('');
  const [replaceSourceType, setReplaceSourceType] = useState('video');
  const [isReplacing, setIsReplacing] = useState(false);

  // Delete confirmation state
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Video discovery state
  const [isVideoBrowserOpen, setIsVideoBrowserOpen] = useState(false);
  const [visibleVideos, setVisibleVideos] = useState<VideoFileEntry[]>([]);
  const [videoFolder, setVideoFolder] = useState('data/cameras;data');
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoverStatus, setDiscoverStatus] = useState<string | null>(null);

  const showStatus = (kind: 'success' | 'error', text: string) => {
    setSaveStatus({ kind, text });
    setTimeout(() => setSaveStatus(null), 4000);
  };

  const handleSave = () => {
    onSaveConfig?.(formConfig);
    showStatus('success', 'Settings updated and deployed.');
  };

  const refreshNextId = () => setNewCamId(nextCameraId(cameras));

  const handleAddCamera = async () => {
    if (!newCamName.trim() || !newCamSource.trim()) {
      showStatus('error', 'Name and source are required');
      return;
    }
    setIsSubmitting(true);
    const result = await onAddCamera?.({
      camera_id: newCamId.trim().toUpperCase(),
      name: newCamName.trim().toUpperCase(),
      source: newCamSource.trim(),
      source_type: newCamSourceType,
      location: newCamLocation.trim() || 'Unassigned',
      camera_type: newCamType,
    });
    setIsSubmitting(false);
    if (result?.success) {
      showStatus('success', `Camera ${newCamId.trim().toUpperCase()} registered.`);
      setNewCamName('');
      setNewCamSource('');
      setNewCamLocation('');
      refreshNextId();
    } else {
      showStatus('error', result?.message || 'Failed to register camera.');
    }
  };

  // Discover video files via the API (proxied through the Express BFF)
  const handleDiscoverVideos = async () => {
    if (!authFetch) return;
    setIsDiscovering(true);
    setDiscoverStatus(null);
    try {
      const folders = videoFolder.split(';').map((p) => p.trim()).filter(Boolean).join(';') || 'data/cameras;data';
      const qs = folders ? `?folder=${encodeURIComponent(folders)}` : '';
      const res = await authFetch(`/api/videos${qs}`);
      const data = await res.json();
      const list: VideoFileEntry[] = Array.isArray(data?.videos) ? data.videos : [];
      setVisibleVideos(list);
      if (list.length === 0) setDiscoverStatus(data?.message || 'No video files found.');
    } catch {
      setDiscoverStatus('Could not reach the backend to discover videos.');
    } finally {
      setIsDiscovering(false);
    }
  };

  const discoverAndOpen = () => {
    setIsVideoBrowserOpen(true);
    setVisibleVideos([]);
    setDiscoverStatus(null);
    handleDiscoverVideos();
  };

  const tabs = [
    { id: 'CAMERAS', label: `Cameras (${cameras.length})`, icon: 'videocam' },
    { id: 'AI_CONFIG', label: 'AI & Models', icon: 'neurology' },
    { id: 'ALERT_RULES', label: 'Alert Rules', icon: 'crisis_alert' },
    { id: 'API_INTEGRATION', label: 'API', icon: 'api' },
    { id: 'SYSTEM_HEALTH', label: 'Health', icon: 'memory' },
  ];

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">settings</span>
            System Configuration
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">Camera pool · AI models · Alert rules · Health</p>
        </div>
        {saveStatus && (
          <div className={`px-3 py-1 ${saveStatus.kind === 'error' ? 'bg-error-container border border-error/20 text-error' : 'bg-success-container border border-success/20 text-success'} text-[11px] font-semibold flex items-center gap-1.5 rounded-lg`}>
            <span className="material-symbols-outlined text-[14px]">{saveStatus.kind === 'error' ? 'error' : 'check_circle'}</span> {saveStatus.text}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-outline-variant bg-surface rounded-t-xl overflow-x-auto">
        {tabs.map((tab) => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id as any)} className={`px-4 py-2.5 text-[11px] font-bold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer whitespace-nowrap ${activeTab === tab.id ? 'border-primary text-primary bg-primary/5' : 'border-transparent text-on-surface-variant hover:text-on-surface'}`}>
            <span className="material-symbols-outlined text-[16px]">{tab.icon}</span> {tab.label}
          </button>
        ))}
      </div>

      {/* Tab: Cameras */}
      {activeTab === 'CAMERAS' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          <div className="lg:col-span-7 bg-surface border border-outline-variant rounded-xl p-5">
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3">Registered Cameras ({cameras.length})</span>
            <div className="divide-y divide-outline-variant/40 max-h-[500px] overflow-y-auto">
              {cameras.map((c) => (
                <div key={c.id} className="py-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-primary text-[18px]">videocam</span>
                    <div>
                      <div className="text-[11px] font-bold text-on-surface">{c.id} — <span className="text-primary">{c.name}</span></div>
                      <div className="text-[10px] text-on-surface-variant font-mono mt-0.5">{c.rtspUrl || 'No source'}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${c.status === 'ONLINE' ? 'bg-success-container text-success' : 'bg-warning-container text-warning'}`}>{c.status}</span>
                    <button onClick={() => { setReplaceModal({ cameraId: c.id, currentSource: c.rtspUrl || '' }); setReplaceSource(c.rtspUrl || ''); setReplaceSourceType('video'); }} className="px-2 py-1 text-[9px] font-bold bg-surface-container-high hover:bg-primary/20 text-on-surface-variant hover:text-primary rounded cursor-pointer transition-colors border border-outline-variant/50">Replace</button>
                    <button onClick={() => setDeleteConfirm(c.id)} className="px-2 py-1 text-[9px] font-bold bg-surface-container-high hover:bg-error/20 text-on-surface-variant hover:text-error rounded cursor-pointer transition-colors border border-outline-variant/50">Delete</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="lg:col-span-5 bg-surface border border-outline-variant rounded-xl p-5">
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3">Register Camera</span>
            <div className="space-y-3 text-[11px]">
              <div><label className="block text-on-surface-variant font-medium mb-1">CAMERA ID <span className="text-on-surface-variant/60">(auto — next free)</span></label><input type="text" value={newCamId} onChange={(e) => setNewCamId(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none" /></div>
              <div><label className="block text-on-surface-variant font-medium mb-1">NAME</label><input type="text" value={newCamName} onChange={(e) => setNewCamName(e.target.value)} placeholder="e.g. BOP NORTH GATE" className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none" /></div>
              <div><label className="block text-on-surface-variant font-medium mb-1">SOURCE TYPE</label>
                <select value={newCamSourceType} onChange={(e) => setNewCamSourceType(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none">
                  <option value="video">LOCAL VIDEO (MP4)</option>
                  <option value="rtsp">RTSP STREAM</option>
                  <option value="webcam">WEBCAM</option>
                </select>
              </div>
              <div><label className="block text-on-surface-variant font-medium mb-1">{newCamSourceType === 'rtsp' ? 'RTSP URL' : newCamSourceType === 'webcam' ? 'WEBCAM INDEX' : 'VIDEO FILE PATH'}</label>
                <input type="text" value={newCamSource} onChange={(e) => setNewCamSource(e.target.value)} placeholder={newCamSourceType === 'video' ? './data/cameras/cam-01.mp4' : newCamSourceType === 'rtsp' ? 'rtsp://192.168.1.101:554/live' : '0'} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-primary outline-none" />
                {newCamSourceType === 'video' && authFetch && (
                  <button onClick={discoverAndOpen} className="mt-2 w-full py-2 bg-surface-container-high hover:bg-primary/15 text-on-surface-variant hover:text-primary rounded-lg text-[10px] font-bold flex items-center justify-center gap-1.5 cursor-pointer transition-colors border border-outline-variant/50">
                    <span className="material-symbols-outlined text-[13px]">folder_open</span> SELECT FOLDER / BROWSE VIDEOS
                  </button>
                )}
              </div>
              <div><label className="block text-on-surface-variant font-medium mb-1">LOCATION</label><input type="text" value={newCamLocation} onChange={(e) => setNewCamLocation(e.target.value)} placeholder="e.g. North Outpost Main Gate" className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none" /></div>
              <div><label className="block text-on-surface-variant font-medium mb-1">CAMERA TYPE</label>
                <select value={newCamType} onChange={(e) => setNewCamType(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none">
                  <option value="FIXED">FIXED</option>
                  <option value="PTZ">PTZ</option>
                  <option value="THERMAL">THERMAL</option>
                  <option value="DAY_NIGHT">DAY/NIGHT</option>
                </select>
              </div>
            </div>
            <div className="pt-4 border-t border-outline-variant mt-4">
              <button onClick={handleAddCamera} disabled={isSubmitting} className="w-full py-2.5 bg-primary hover:bg-primary/90 text-on-primary rounded-xl text-[11px] font-bold flex items-center justify-center gap-1.5 cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed">
                <span className="material-symbols-outlined text-[14px]">{isSubmitting ? 'hourglass_top' : 'add'}</span> {isSubmitting ? 'REGISTERING...' : 'REGISTER CAMERA'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tab: AI Config */}
      {activeTab === 'AI_CONFIG' && (
        <div className="bg-surface border border-outline-variant rounded-xl p-5">
          <h2 className="text-[13px] font-bold text-on-surface tracking-wide mb-4 border-b border-outline-variant pb-3">YOLO &amp; Model Configuration</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[11px]">
            <div>
              <label className="block text-on-surface-variant font-medium mb-1">YOLO MODEL</label>
              <select value={formConfig.yoloModel} onChange={(e) => setFormConfig({ ...formConfig, yoloModel: e.target.value })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none">
                <option value="YOLOv8x-Custom-Border-V4">YOLOv8x Custom V4</option>
                <option value="YOLOv11-Border-Tactical">YOLOv11 Tactical</option>
                <option value="YOLOv8-Thermal-Night-IR">YOLOv8 Thermal IR</option>
              </select>
            </div>
            <div><label className="block text-on-surface-variant font-medium mb-1">OCR MODEL</label><input type="text" disabled value="EasyOCR (English)" className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface-variant outline-none opacity-80" /></div>
            <div>
              <div className="flex justify-between font-medium mb-1"><span>Confidence</span><span className="font-mono text-primary font-bold">{Math.round(formConfig.confidenceThreshold * 100)}%</span></div>
              <input type="range" min="0.40" max="0.95" step="0.05" value={formConfig.confidenceThreshold} onChange={(e) => setFormConfig({ ...formConfig, confidenceThreshold: parseFloat(e.target.value) })} className="w-full accent-primary" />
            </div>
            <div>
              <div className="flex justify-between font-medium mb-1"><span>OCR Score</span><span className="font-mono text-primary font-bold">{Math.round(formConfig.ocrThreshold * 100)}%</span></div>
              <input type="range" min="0.50" max="0.95" step="0.05" value={formConfig.ocrThreshold} onChange={(e) => setFormConfig({ ...formConfig, ocrThreshold: parseFloat(e.target.value) })} className="w-full accent-primary" />
            </div>
          </div>
          <div className="pt-4 border-t border-outline-variant mt-4 flex justify-end">
            <button onClick={handleSave} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold cursor-pointer transition-colors">SAVE AI CONFIG</button>
          </div>
        </div>
      )}

      {/* Tab: Alert Rules */}
      {activeTab === 'ALERT_RULES' && (
        <div className="bg-surface border border-outline-variant rounded-xl p-5">
          <h2 className="text-[13px] font-bold text-on-surface tracking-wide mb-4 border-b border-outline-variant pb-3">Alert Thresholds &amp; Curfew</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-[11px]">
            <div><label className="block text-on-surface-variant font-medium mb-1">LOITER THRESHOLD (s)</label><input type="number" value={formConfig.loiteringThresholdSec} onChange={(e) => setFormConfig({ ...formConfig, loiteringThresholdSec: parseInt(e.target.value) || 30 })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none" /></div>
            <div><label className="block text-on-surface-variant font-medium mb-1">INTRUSION SENSITIVITY (1-10)</label><input type="number" min="1" max="10" value={formConfig.intrusionSensitivity} onChange={(e) => setFormConfig({ ...formConfig, intrusionSensitivity: parseInt(e.target.value) || 9 })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none" /></div>
            <div><label className="block text-on-surface-variant font-medium mb-1">NIGHT START (UTC)</label><input type="text" value={formConfig.nightHoursStart} onChange={(e) => setFormConfig({ ...formConfig, nightHoursStart: e.target.value })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none" /></div>
            <div><label className="block text-on-surface-variant font-medium mb-1">NIGHT END (UTC)</label><input type="text" value={formConfig.nightHoursEnd} onChange={(e) => setFormConfig({ ...formConfig, nightHoursEnd: e.target.value })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none" /></div>
          </div>
          <div className="pt-4 border-t border-outline-variant mt-4 flex justify-end">
            <button onClick={handleSave} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold cursor-pointer transition-colors">SAVE RULES</button>
          </div>
        </div>
      )}

      {/* Tab: API */}
      {activeTab === 'API_INTEGRATION' && (
        <div className="bg-surface border border-outline-variant rounded-xl p-5">
          <h2 className="text-[13px] font-bold text-on-surface tracking-wide mb-4 border-b border-outline-variant pb-3">C2 API Integration</h2>
          <div className="space-y-3 text-[11px]">
            <div><label className="block text-on-surface-variant font-medium mb-1">API ENDPOINT</label><input type="text" value={formConfig.apiBaseUrl} onChange={(e) => setFormConfig({ ...formConfig, apiBaseUrl: e.target.value })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-primary font-bold outline-none" /></div>
            <div><label className="block text-on-surface-variant font-medium mb-1">BEARER TOKEN</label><input type="password" value={formConfig.apiAuthToken} onChange={(e) => setFormConfig({ ...formConfig, apiAuthToken: e.target.value })} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-on-surface outline-none" /></div>
          </div>
          <div className="pt-4 border-t border-outline-variant mt-4 flex justify-end">
            <button onClick={handleSave} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold cursor-pointer transition-colors">SAVE ENDPOINT</button>
          </div>
        </div>
      )}

      {/* Tab: System Health */}
      {activeTab === 'SYSTEM_HEALTH' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          <div className="bg-surface border border-outline-variant p-5 rounded-xl">
            <span className="text-[11px] text-on-surface-variant block mb-1">GPU VRAM</span>
            <div className="text-2xl font-bold text-on-surface-variant font-mono">— <span className="text-sm font-normal text-on-surface-variant">No data</span></div>
          </div>
          <div className="bg-surface border border-outline-variant p-5 rounded-xl">
            <span className="text-[11px] text-on-surface-variant block mb-1">INFERENCE FPS</span>
            <div className="text-2xl font-bold text-on-surface-variant font-mono">— <span className="text-sm font-normal text-on-surface-variant">No data</span></div>
          </div>
          <div className="bg-surface border border-outline-variant p-5 rounded-xl">
            <span className="text-[11px] text-on-surface-variant block mb-1">STORAGE</span>
            <div className="text-2xl font-bold text-on-surface-variant font-mono">— <span className="text-sm font-normal text-on-surface-variant">No data</span></div>
          </div>
        </div>
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
                {replaceSourceType === 'video' && authFetch && (
                  <button onClick={discoverAndOpen} className="mt-2 w-full py-2 bg-surface-container-high hover:bg-primary/15 text-on-surface-variant hover:text-primary rounded-lg text-[10px] font-bold flex items-center justify-center gap-1.5 cursor-pointer transition-colors border border-outline-variant/50">
                    <span className="material-symbols-outlined text-[13px]">folder_open</span> SELECT FOLDER / BROWSE VIDEOS
                  </button>
                )}
              </div>
            </div>
            <div className="px-5 py-3 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setReplaceModal(null)} className="px-4 py-2 text-[11px] font-semibold text-on-surface-variant hover:text-on-surface rounded-lg cursor-pointer transition-colors">Cancel</button>
              <button onClick={async () => {
                if (!replaceModal || !replaceSource.trim()) return;
                setIsReplacing(true);
                const result = await onReplaceCamera?.(replaceModal.cameraId, replaceSource.trim(), replaceSourceType);
                setIsReplacing(false);
                if (result?.success) {
                  showStatus('success', `Source for ${replaceModal.cameraId} replaced.`);
                  setReplaceModal(null);
                } else {
                  showStatus('error', result?.message || 'Failed to replace source.');
                }
              }} disabled={!replaceSource.trim() || isReplacing} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed">{isReplacing ? 'Replacing...' : 'Replace Source'}</button>
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
              <button onClick={async () => {
                if (!deleteConfirm) return;
                setIsDeleting(true);
                const result = await onDeleteCamera?.(deleteConfirm);
                setIsDeleting(false);
                if (result?.success) {
                  showStatus('success', `Camera ${deleteConfirm} deleted.`);
                  setDeleteConfirm(null);
                  refreshNextId();
                } else {
                  showStatus('error', result?.message || 'Failed to delete camera.');
                }
              }} disabled={isDeleting} className="px-4 py-2 bg-error hover:bg-error/90 text-on-error rounded-lg text-[11px] font-bold cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed">{isDeleting ? 'Deleting...' : 'Delete Camera'}</button>
            </div>
          </div>
        </div>,
        document.body
      )}

      {/* ═══ VIDEO BROWSER MODAL ═══ */}
      {isVideoBrowserOpen && createPortal(
        <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-on-surface/50 backdrop-blur-sm" onClick={() => setIsVideoBrowserOpen(false)}>
          <div className="bg-surface border border-outline-variant rounded-xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="px-5 py-4 border-b border-outline-variant bg-surface-container-low">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-primary text-[18px]">folder_open</span>
                  <h3 className="text-[13px] font-bold text-on-surface">Select Video File</h3>
                </div>
                <button onClick={() => setIsVideoBrowserOpen(false)} className="p-1 rounded hover:bg-surface-container-high cursor-pointer">
                  <span className="material-symbols-outlined text-[18px] text-on-surface-variant">close</span>
                </button>
              </div>
            </div>
            <div className="px-5 py-3 border-b border-outline-variant flex items-center gap-2">
              <input type="text" value={videoFolder} onChange={(e) => setVideoFolder(e.target.value)} placeholder="data/cameras;data" className="flex-1 bg-surface-container-low border border-outline-variant rounded-lg p-2 font-mono text-[11px] text-on-surface outline-none" />
              <button onClick={handleDiscoverVideos} disabled={isDiscovering} className="px-3 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[10px] font-bold cursor-pointer transition-colors disabled:opacity-50 whitespace-nowrap">
                {isDiscovering ? 'SCANNING...' : 'SCAN FOLDER'}
              </button>
            </div>
            <div className="max-h-[300px] overflow-y-auto">
              {isDiscovering && (
                <div className="px-5 py-6 text-center text-[11px] text-on-surface-variant">Scanning for video files...</div>
              )}
              {!isDiscovering && discoverStatus && visibleVideos.length === 0 && (
                <div className="px-5 py-6 text-center text-[11px] text-on-surface-variant">{discoverStatus}</div>
              )}
              {!isDiscovering && visibleVideos.map((v) => (
                <button
                  key={v.path}
                  onClick={() => {
                    if (replaceModal) setReplaceSource(v.path);
                    else setNewCamSource(v.path);
                    setIsVideoBrowserOpen(false);
                    showStatus('success', `Selected ${v.name}`);
                  }}
                  className="w-full px-5 py-3 flex items-center gap-3 hover:bg-primary/10 transition-colors cursor-pointer border-b border-outline-variant/30 text-left"
                >
                  <span className="material-symbols-outlined text-[18px] text-primary">movie</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] font-bold text-on-surface truncate">{v.name}</div>
                    <div className="text-[10px] text-on-surface-variant font-mono truncate">{v.path}</div>
                  </div>
                  <span className="text-[10px] text-on-surface-variant font-mono whitespace-nowrap">{formatVideoSize(v.size_bytes)}</span>
                </button>
              ))}
            </div>
            <div className="px-5 py-3 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setIsVideoBrowserOpen(false)} className="px-4 py-2 text-[11px] font-semibold text-on-surface-variant hover:text-on-surface rounded-lg cursor-pointer transition-colors">Close</button>
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
};
