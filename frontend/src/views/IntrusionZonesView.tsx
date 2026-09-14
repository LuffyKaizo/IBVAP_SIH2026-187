import React, { useState } from 'react';
import { VirtualZone, CameraFeed, BorderAlert } from '../types';

interface IntrusionZonesViewProps {
  zones: VirtualZone[];
  cameras: CameraFeed[];
  alerts: BorderAlert[];
  onSaveZone?: (zone: VirtualZone) => void;
  onDeleteZone?: (id: string) => void;
  onNavigateAlerts?: () => void;
}

export const IntrusionZonesView: React.FC<IntrusionZonesViewProps> = ({
  zones,
  cameras,
  alerts,
  onSaveZone,
  onDeleteZone,
  onNavigateAlerts,
}) => {
  const [activeTab, setActiveTab] = useState<'MONITORING' | 'CONFIG'>('MONITORING');
  const [selectedCameraId, setSelectedCameraId] = useState<string>('CAM-04');
  const [selectedZoneId, setSelectedZoneId] = useState<string>(zones[0]?.id || 'ZONE-01');
  const [zoneName, setZoneName] = useState('PERIMETER_FENCE_SECTOR_05');
  const [zoneType, setZoneType] = useState<'POLYGON_ZONE' | 'TRIPWIRE_LINE'>('POLYGON_ZONE');
  const [zoneSeverity, setZoneSeverity] = useState<'CRITICAL' | 'HIGH' | 'MEDIUM'>('CRITICAL');
  const [zoneRule, setZoneRule] = useState<'RESTRICTED_ENTRY' | 'RESTRICTED_EXIT' | 'BI_DIRECTIONAL' | 'LOITERING_ONLY'>('RESTRICTED_ENTRY');
  const [loiterThreshold, setLoiterThreshold] = useState<number>(20);
  const [notice, setNotice] = useState<string | null>(null);

  const activeCamera = cameras.find((c) => c.id === selectedCameraId) || cameras[0];
  const activeZone = zones.find((z) => z.id === selectedZoneId) || zones[0];

  const handleCreateZone = () => {
    const newZone: VirtualZone = {
      id: `ZONE-0${zones.length + 1}`,
      name: zoneName.trim().toUpperCase(),
      cameraId: selectedCameraId,
      type: zoneType,
      coordinates: zoneType === 'POLYGON_ZONE' ? [{ x: 20, y: 30 }, { x: 80, y: 30 }, { x: 80, y: 70 }, { x: 20, y: 70 }] : [{ x: 10, y: 50 }, { x: 90, y: 50 }],
      severity: zoneSeverity,
      rule: zoneRule,
      loiteringThresholdSec: loiterThreshold,
      isActive: true,
      color: zoneSeverity === 'CRITICAL' ? '#B84C4C' : zoneSeverity === 'HIGH' ? '#B88735' : '#356B7A',
    };
    onSaveZone?.(newZone);
    setSelectedZoneId(newZone.id);
    setNotice(`Zone "${newZone.name}" configured and active.`);
    setTimeout(() => setNotice(null), 3500);
  };

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">fence</span>
            Zones &amp; Virtual Fencing
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">Geofencing · Tripwire detection · Loitering management</p>
        </div>
        {notice && (
          <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
            <span className="material-symbols-outlined text-[14px]">check_circle</span> {notice}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-outline-variant bg-surface rounded-t-xl">
        <button onClick={() => setActiveTab('MONITORING')} className={`px-4 py-2.5 text-[11px] font-bold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${activeTab === 'MONITORING' ? 'border-primary text-primary bg-primary/5' : 'border-transparent text-on-surface-variant hover:text-on-surface'}`}>
          <span className="material-symbols-outlined text-[16px]">visibility</span> Zone Monitoring
        </button>
        <button onClick={() => setActiveTab('CONFIG')} className={`px-4 py-2.5 text-[11px] font-bold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${activeTab === 'CONFIG' ? 'border-primary text-primary bg-primary/5' : 'border-transparent text-on-surface-variant hover:text-on-surface'}`}>
          <span className="material-symbols-outlined text-[16px]">edit</span> Zone Configuration
        </button>
      </div>

      {/* Tab 1: Monitoring */}
      {activeTab === 'MONITORING' && (
        <div className="flex flex-col gap-5">
          {/* Breach Banner - only shows when there are ACTIVE critical/high alerts */}
          {alerts.filter((a) => a.status === 'ACTIVE' && (a.severity === 'CRITICAL' || a.severity === 'HIGH')).length > 0 ? (
            alerts
              .filter((a) => a.status === 'ACTIVE' && (a.severity === 'CRITICAL' || a.severity === 'HIGH'))
              .slice(0, 1)
              .map((breach) => (
                <div key={breach.id} className="p-4 rounded-xl border border-error/30 bg-error-container/30 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-error text-xl">warning</span>
                    <div>
                      <div className="text-[12px] font-bold text-error">BREACH IN PROGRESS · {breach.cameraId} ({breach.zone})</div>
                      <div className="text-[11px] text-on-surface-variant">{breach.title} at {breach.timestamp}</div>
                    </div>
                  </div>
                  {onNavigateAlerts && (
                    <button onClick={onNavigateAlerts} className="px-3 py-1.5 bg-error text-on-error rounded-lg text-[11px] font-bold flex items-center gap-1 cursor-pointer">
                      <span>View Incident</span><span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                    </button>
                  )}
                </div>
              ))
          ) : (
            <div className="p-4 rounded-xl border border-outline-variant/30 bg-surface-container/30 flex items-center gap-3">
              <span className="material-symbols-outlined text-on-surface-variant/50 text-xl">check_circle</span>
              <div className="text-[12px] text-on-surface-variant">No active breach — all zones secure</div>
            </div>
          )}

          {/* Zone Status Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {zones.slice(0, 3).map((z) => {
              const hasActiveBreach = alerts.some(
                (a) => a.status === 'ACTIVE' && a.zone === z.name && (a.severity === 'CRITICAL' || a.severity === 'HIGH')
              );
              return (
                <div key={z.id} className="bg-surface border border-outline-variant p-4 rounded-xl">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-bold text-on-surface">{z.name}</span>
                    <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${hasActiveBreach ? 'bg-error-container text-on-error-container' : 'bg-success-container text-success'}`}>
                      {hasActiveBreach ? 'BREACH' : 'SECURE'}
                    </span>
                  </div>
                  <div className="text-[11px] text-on-surface-variant space-y-0.5">
                    <div>Camera: <span className="text-on-surface font-medium">{z.cameraId}</span></div>
                    <div>Rule: <span className="text-on-surface font-medium">{z.rule}</span></div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Live Camera Feed */}
          <div className="bg-surface border border-outline-variant rounded-xl p-4">
            <div className="flex items-center justify-between border-b border-outline-variant pb-3 mb-3">
              <div className="flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                <span className="text-[11px] font-bold text-primary font-mono">{activeCamera.id} — {activeCamera.name}</span>
              </div>
              <select value={selectedCameraId} onChange={(e) => setSelectedCameraId(e.target.value)} className="bg-surface-container-low border border-outline-variant rounded-lg text-[11px] text-on-surface px-2.5 py-1 outline-none cursor-pointer">
                {cameras.map((c) => (<option key={c.id} value={c.id}>{c.id}</option>))}
              </select>
            </div>
            <div className="relative w-full aspect-video bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant select-none">
              {activeCamera.videoPosterUrl ? (
                <img src={activeCamera.videoPosterUrl} alt={activeCamera.name} className="w-full h-full object-cover opacity-90" />
              ) : (
                <div className="w-full h-full flex items-center justify-center bg-surface-container text-on-surface-variant text-sm">No preview available</div>
              )}
              {/* Dynamic zone overlays from backend coordinates */}
              {zones
                .filter((z) => z.cameraId === activeCamera.id && z.coordinates && z.coordinates.length >= 2)
                .map((z) => {
                  if (z.type === 'TRIPWIRE_LINE') {
                    const p1 = z.coordinates[0];
                    const p2 = z.coordinates[z.coordinates.length - 1];
                    return (
                      <div key={z.id} className="absolute inset-0 pointer-events-none">
                        <div
                          className="absolute border-t-2 border-dashed"
                          style={{
                            left: `${Math.min(p1.x, p2.x)}%`,
                            top: `${Math.min(p1.y, p2.y)}%`,
                            width: `${Math.abs(p2.x - p1.x)}%`,
                            height: 0,
                            borderColor: z.severity === 'CRITICAL' ? '#B84C4C' : '#B88735',
                          }}
                        />
                        <span
                          className="absolute text-[9px] font-mono font-bold px-1.5 py-[2px] rounded"
                          style={{
                            left: `${Math.min(p1.x, p2.x)}%`,
                            top: `${Math.min(p1.y, p2.y) - 3}%`,
                            color: '#fff',
                            backgroundColor: z.severity === 'CRITICAL' ? '#B84C4C' : '#B88735',
                          }}
                        >
                          TRIPWIRE: {z.name}
                        </span>
                      </div>
                    );
                  }
                  // POLYGON_ZONE
                  const xs = z.coordinates.map((c) => c.x);
                  const ys = z.coordinates.map((c) => c.y);
                  const minX = Math.min(...xs);
                  const minY = Math.min(...ys);
                  const maxX = Math.max(...xs);
                  const maxY = Math.max(...ys);
                  const hasActiveBreach = alerts.some(
                    (a) => a.status === 'ACTIVE' && a.zone === z.name
                  );
                  return (
                    <div key={z.id} className="absolute pointer-events-none" style={{
                      left: `${minX}%`, top: `${minY}%`,
                      width: `${maxX - minX}%`, height: `${maxY - minY}%`,
                      borderWidth: 2,
                      borderColor: z.severity === 'CRITICAL' ? '#B84C4C' : z.severity === 'HIGH' ? '#B88735' : '#356B7A',
                      backgroundColor: hasActiveBreach
                        ? (z.severity === 'CRITICAL' ? 'rgba(184,76,76,0.15)' : 'rgba(184,135,53,0.15)')
                        : (z.severity === 'CRITICAL' ? 'rgba(184,76,76,0.05)' : 'rgba(184,135,53,0.05)'),
                    }}>
                      <span className="absolute -top-[18px] left-0 text-[9px] font-mono font-bold px-1.5 py-[2px] rounded"
                        style={{ color: '#fff', backgroundColor: z.severity === 'CRITICAL' ? '#B84C4C' : '#B88735' }}>
                        {z.name}
                      </span>
                      {hasActiveBreach && (
                        <span className="absolute text-[9px] font-mono font-bold px-1.5 py-[2px] rounded"
                          style={{ left: '50%', top: '50%', transform: 'translate(-50%,-50%)', color: '#fff', backgroundColor: '#B84C4C' }}>
                          BREACH DETECTED
                        </span>
                      )}
                    </div>
                  );
                })}
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: Config */}
      {activeTab === 'CONFIG' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
          {/* Zone List */}
          <div className="lg:col-span-7 bg-surface border border-outline-variant rounded-xl p-5">
            <div className="flex items-center justify-between border-b border-outline-variant pb-3 mb-4">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Configured Zones ({zones.length})</span>
            </div>
            <div className="space-y-2">
              {zones.map((z) => (
                <button key={z.id} onClick={() => setSelectedZoneId(z.id)} className={`w-full p-3 rounded-lg border transition-all cursor-pointer text-left flex items-center justify-between ${selectedZoneId === z.id ? 'bg-primary/10 border-primary' : 'bg-surface-container-low hover:bg-surface-container-high border-outline-variant'}`}>
                  <div>
                    <div className="text-[12px] font-bold text-on-surface">{z.name}</div>
                    <div className="text-[10px] text-on-surface-variant">{z.cameraId} · {z.type} · {z.rule}</div>
                  </div>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${z.severity === 'CRITICAL' ? 'bg-error-container text-on-error-container' : z.severity === 'HIGH' ? 'bg-warning-container text-on-warning-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                    {z.severity}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Create Zone Form */}
          <div className="lg:col-span-5 bg-surface border border-outline-variant rounded-xl p-5">
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase block mb-3">Define New Zone</span>
            <div className="space-y-3 text-[11px]">
              <div>
                <label className="block text-on-surface-variant font-medium mb-1">ZONE IDENTIFIER</label>
                <input type="text" value={zoneName} onChange={(e) => setZoneName(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-primary font-bold outline-none" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-on-surface-variant font-medium mb-1">GEOMETRY</label>
                  <select value={zoneType} onChange={(e) => setZoneType(e.target.value as any)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none cursor-pointer">
                    <option value="POLYGON_ZONE">Polygon</option><option value="TRIPWIRE_LINE">Tripwire</option>
                  </select>
                </div>
                <div>
                  <label className="block text-on-surface-variant font-medium mb-1">SEVERITY</label>
                  <select value={zoneSeverity} onChange={(e) => setZoneSeverity(e.target.value as any)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none cursor-pointer">
                    <option value="CRITICAL">Critical</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option>
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-on-surface-variant font-medium mb-1">RULE</label>
                <select value={zoneRule} onChange={(e) => setZoneRule(e.target.value as any)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none cursor-pointer">
                  <option value="RESTRICTED_ENTRY">Restricted Entry</option><option value="RESTRICTED_EXIT">Restricted Exit</option><option value="BI_DIRECTIONAL">Bi-Directional</option><option value="LOITERING_ONLY">Loitering Only</option>
                </select>
              </div>
              <div>
                <div className="flex justify-between mb-1">
                  <span className="text-on-surface-variant font-medium">Loiter Threshold</span>
                  <span className="font-mono text-primary font-bold">{loiterThreshold}s</span>
                </div>
                <input type="range" min="5" max="60" step="5" value={loiterThreshold} onChange={(e) => setLoiterThreshold(parseInt(e.target.value))} className="w-full accent-primary" />
              </div>
            </div>
            <div className="pt-4 border-t border-outline-variant mt-4">
              <button onClick={handleCreateZone} className="w-full py-2.5 bg-primary hover:bg-primary/90 text-on-primary rounded-xl text-[11px] font-bold flex items-center justify-center gap-2 cursor-pointer transition-colors">
                <span className="material-symbols-outlined text-[16px]">add_circle</span> SAVE &amp; APPLY ZONE
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
