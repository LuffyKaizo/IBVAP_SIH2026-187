import React, { useState } from 'react';
import { CameraFeed, BorderAlert, AnprRecord } from '../types';
import { NavPath } from './Sidebar';

interface CommandPaletteModalProps {
  isOpen: boolean;
  onClose: () => void;
  cameras?: CameraFeed[];
  alerts?: BorderAlert[];
  anprRecords?: AnprRecord[];
  onSelectCamera?: (cameraId: string) => void;
  onSelectAlert?: (alertId: string) => void;
  onNavigate?: (path: NavPath) => void;
}

export const CommandPaletteModal: React.FC<CommandPaletteModalProps> = ({
  isOpen, onClose, cameras = [], alerts = [], anprRecords = [], onSelectCamera, onSelectAlert, onNavigate,
}) => {
  const [query, setQuery] = useState('');
  if (!isOpen) return null;
  const q = query.toLowerCase().trim();

  const filteredCameras = cameras.filter((c) => c.id.toLowerCase().includes(q) || c.name.toLowerCase().includes(q));
  const filteredAlerts = alerts.filter((a) => a.id.toLowerCase().includes(q) || a.title.toLowerCase().includes(q));
  const filteredPlates = anprRecords.filter((p) => p.plateNumber.toLowerCase().includes(q));

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-on-surface/30 backdrop-blur-sm p-4 animate-in fade-in duration-150">
      <div className="w-full max-w-2xl bg-surface border border-outline-variant shadow-2xl flex flex-col relative overflow-hidden rounded-xl">
        <div className="h-10 bg-surface-container-low border-b border-outline-variant flex items-center justify-between px-4 rounded-t-xl">
          <span className="text-[11px] font-bold text-primary flex items-center gap-2">
            <span className="material-symbols-outlined text-[14px]">terminal</span> IBVAP COMMAND PALETTE [CTRL+K]
          </span>
          <button onClick={onClose} className="text-on-surface-variant hover:text-on-surface cursor-pointer"><span className="material-symbols-outlined text-[16px]">close</span></button>
        </div>
        <div className="p-4 border-b border-outline-variant flex items-center gap-3 bg-surface">
          <span className="material-symbols-outlined text-primary text-[18px]">search</span>
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search cameras, plates, alerts..."
            className="w-full bg-transparent border-none outline-none text-[13px] text-on-surface placeholder-on-surface-variant/50 font-medium" />
        </div>
        <div className="p-2 bg-surface-container-low border-b border-outline-variant flex gap-1.5 flex-wrap">
          {[
            { p: 'command-dashboard', l: 'DASHBOARD' }, { p: 'cameras', l: 'CAMERAS' }, { p: 'ai-analytics', l: 'AI' },
            { p: 'anpr', l: 'ANPR' }, { p: 'intrusion-zones', l: 'ZONES' }, { p: 'event-intelligence', l: 'ALERTS' },
            { p: 'analytics', l: 'ANALYTICS' }, { p: 'reports', l: 'REPORTS' }, { p: 'settings', l: 'SETTINGS' },
          ].map((btn) => (
            <button key={btn.p} onClick={() => { onNavigate?.(btn.p as NavPath); onClose(); }}
              className="px-2 py-0.5 bg-surface-container-high hover:bg-primary/10 hover:text-primary border border-outline-variant text-[9px] text-on-surface font-bold cursor-pointer rounded transition-colors">
              {btn.l}
            </button>
          ))}
        </div>
        <div className="max-h-80 overflow-y-auto divide-y divide-outline-variant/30">
          {filteredAlerts.length > 0 && (
            <div>
              <div className="px-3 py-1 bg-surface-container-low text-[9px] font-bold text-error tracking-wider uppercase">Alerts ({filteredAlerts.length})</div>
              {filteredAlerts.map((a) => (
                <div key={a.id} onClick={() => { onSelectAlert?.(a.id); onNavigate?.('event-intelligence'); onClose(); }}
                  className="p-3 hover:bg-error-container/20 cursor-pointer flex items-center justify-between transition-colors">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-error text-[16px]">crisis_alert</span>
                    <div>
                      <div className="text-[12px] text-on-surface font-bold">{a.title}</div>
                      <div className="text-[10px] text-on-surface-variant">{a.id} · {a.cameraId}</div>
                    </div>
                  </div>
                  <span className="text-[9px] font-bold px-2 py-0.5 border border-error text-error bg-error-container rounded">{a.severity}</span>
                </div>
              ))}
            </div>
          )}
          {filteredCameras.length > 0 && (
            <div>
              <div className="px-3 py-1 bg-surface-container-low text-[9px] font-bold text-primary tracking-wider uppercase">Cameras ({filteredCameras.length})</div>
              {filteredCameras.map((c) => (
                <div key={c.id} onClick={() => { onSelectCamera?.(c.id); onNavigate?.('cameras'); onClose(); }}
                  className="p-3 hover:bg-primary/5 cursor-pointer flex items-center justify-between transition-colors">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-primary text-[16px]">videocam</span>
                    <div>
                      <div className="text-[12px] font-bold"><span className="text-primary">{c.id}</span> - <span className="text-on-surface">{c.name}</span></div>
                      <div className="text-[10px] text-on-surface-variant">{c.detections.length} detections</div>
                    </div>
                  </div>
                  <span className="text-[9px] text-success bg-success-container px-2 py-0.5 rounded">{c.status}</span>
                </div>
              ))}
            </div>
          )}
          {filteredPlates.length > 0 && (
            <div>
              <div className="px-3 py-1 bg-surface-container-low text-[9px] font-bold text-tertiary tracking-wider uppercase">Plates ({filteredPlates.length})</div>
              {filteredPlates.map((p) => (
                <div key={p.id} onClick={() => { onNavigate?.('anpr'); onClose(); }}
                  className="p-3 hover:bg-tertiary/5 cursor-pointer flex items-center justify-between transition-colors">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-tertiary text-[16px]">directions_car</span>
                    <div>
                      <div className="text-[12px] font-bold text-on-surface font-mono">{p.plateNumber}</div>
                      <div className="text-[10px] text-on-surface-variant">{p.vehicleType} · {p.cameraId}</div>
                    </div>
                  </div>
                  <span className={`text-[9px] font-bold px-2 py-0.5 border rounded ${p.status === 'WATCHLIST' ? 'border-error text-error bg-error-container' : 'border-success text-success bg-success-container'}`}>{p.status}</span>
                </div>
              ))}
            </div>
          )}
          {filteredAlerts.length === 0 && filteredCameras.length === 0 && filteredPlates.length === 0 && (
            <div className="p-4 text-center text-[11px] text-on-surface-variant">No matching results</div>
          )}
        </div>
      </div>
    </div>
  );
};
