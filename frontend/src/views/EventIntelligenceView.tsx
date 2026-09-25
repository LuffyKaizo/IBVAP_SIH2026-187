import React, { useEffect, useRef, useState } from 'react';
import { BorderAlert, SuspiciousEventItem } from '../types';
import { useAuth } from '../contexts/AuthContext';

const AI_SERVICE_URL = (import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8000');

/** AI alerts are id'd "ALT-AI-<eventId>"; the evidence API is keyed by the raw eventId. */
const eventIdFromAlertId = (id: string): string | null =>
  id.startsWith('ALT-AI-') ? id.slice('ALT-AI-'.length) : null;

/** Blob URL cache for alert-card thumbnails (eventId -> object URL). */
const thumbCache = new Map<string, string>();

/** Small target-crop thumbnail for an alert card. Fetches the event's
 * evidence, preferring the annotated TARGET_CROP, and caches the blob URL.
 * Skips non-AI alerts and renders nothing when no evidence exists. */
const AlertEvidenceThumb: React.FC<{ alert: BorderAlert; index: number }> = ({ alert, index }) => {
  const [url, setUrl] = useState<string | null>(() => thumbCache.get(alert.id) || null);
  const { getAuthHeaders } = useAuth();

  useEffect(() => {
    if (url || index >= 40) return;
    const eventId = eventIdFromAlertId(alert.id);
    if (!eventId) return;
    let cancelled = false;
    (async () => {
      try {
        const headers = getAuthHeaders();
        const listRes = await fetch(
          `${AI_SERVICE_URL}/evidence?event_id=${encodeURIComponent(eventId)}&limit=5`,
          { headers },
        );
        if (!listRes.ok) return;
        const list = await listRes.json();
        const items: { id?: string; evidenceType?: string }[] = list?.evidence || [];
        const chosen = items.find((e) => e.evidenceType === 'TARGET_CROP') || items[0];
        if (!chosen?.id) return;
        const fileRes = await fetch(
          `${AI_SERVICE_URL}/evidence/${encodeURIComponent(chosen.id)}/file`,
          { headers },
        );
        if (!fileRes.ok) return;
        const blob = await fileRes.blob();
        const objectUrl = URL.createObjectURL(blob);
        thumbCache.set(alert.id, objectUrl);
        if (!cancelled) setUrl(objectUrl);
      } catch {
        /* thumbnail is best-effort */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [alert.id, index, url, getAuthHeaders]);

  if (!url) return null;
  return (
    <img
      src={url}
      alt=""
      data-testid="alert-evidence-thumb"
      className="w-11 h-7 object-cover rounded border border-outline-variant shrink-0"
    />
  );
};

interface EventIntelligenceViewProps {
  alerts: BorderAlert[];
  suspiciousEvents: SuspiciousEventItem[];
  selectedAlertId?: string;
  onSelectAlert: (id: string) => void;
  onActionAlert?: (id: string, action: 'ACKNOWLEDGE' | 'RESOLVE') => void;
  onSelectCamera?: (cameraId: string) => void;
}

export const EventIntelligenceView: React.FC<EventIntelligenceViewProps> = ({
  alerts,
  suspiciousEvents,
  selectedAlertId,
  onSelectAlert,
  onActionAlert,
  onSelectCamera,
}) => {
  const [filterSeverity, setFilterSeverity] = useState<'ALL' | 'CRITICAL' | 'HIGH' | 'MEDIUM'>('ALL');
  const [activeTab, setActiveTab] = useState<'INCIDENTS' | 'RULES' | 'NIGHT_CURFEW'>('INCIDENTS');
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [sirenActive, setSirenActive] = useState(false);
  const [evidence, setEvidence] = useState<{
    state: 'LOADING' | 'READY' | 'UNAVAILABLE';
    url: string | null;
    kind: 'TARGET_CROP' | 'SNAPSHOT' | null;
  }>({ state: 'LOADING', url: null, kind: null });

  const { getAuthHeaders } = useAuth();
  const sirenAudioRef = useRef<HTMLAudioElement | null>(null);
  const chimeAudioRef = useRef<HTMLAudioElement | null>(null);
  const sirenTimerRef = useRef<number | null>(null);

  const filteredAlerts = alerts.filter((a) => filterSeverity === 'ALL' || a.severity === filterSeverity);
  const activeAlert = alerts.find((a) => a.id === selectedAlertId) || filteredAlerts[0] || alerts[0];
  const activeAlertId = activeAlert?.id;
  const activeSnapshotUrl = activeAlert?.snapshotUrl;

  // Resolve the evidence snapshot for the selected incident through the existing
  // GET /evidence (event_id filter) + GET /evidence/{id}/file APIs.
  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    setEvidence({ state: 'LOADING', url: null, kind: null });

    const load = async () => {
      try {
        if (!activeAlertId) {
          setEvidence({ state: 'UNAVAILABLE', url: null, kind: null });
          return;
        }
        if (activeSnapshotUrl) {
          // Alerts that already carry a snapshot URL (system/mock sources) use it directly.
          setEvidence({ state: 'READY', url: activeSnapshotUrl, kind: null });
          return;
        }
        const eventId = eventIdFromAlertId(activeAlertId);
        if (!eventId) {
          setEvidence({ state: 'UNAVAILABLE', url: null, kind: null });
          return;
        }
        const headers = getAuthHeaders();
        const listRes = await fetch(
          `${AI_SERVICE_URL}/evidence?event_id=${encodeURIComponent(eventId)}&limit=5`,
          { headers },
        );
        if (!listRes.ok) throw new Error(`evidence list ${listRes.status}`);
        const list = await listRes.json();
        // Primary evidence is the annotated TARGET_CROP (red box + labels are
        // baked into the pixels); fall back to the full-scene snapshot.
        const items: { id?: string; evidenceType?: string }[] = list?.evidence || [];
        const chosen = items.find((e) => e.evidenceType === 'TARGET_CROP') || items[0];
        const evidenceId: string | undefined = chosen?.id;
        if (!evidenceId) {
          if (!cancelled) setEvidence({ state: 'UNAVAILABLE', url: null, kind: null });
          return;
        }
        const fileRes = await fetch(
          `${AI_SERVICE_URL}/evidence/${encodeURIComponent(evidenceId)}/file`,
          { headers },
        );
        if (!fileRes.ok) throw new Error(`evidence file ${fileRes.status}`);
        const blob = await fileRes.blob();
        createdUrl = URL.createObjectURL(blob);
        if (!cancelled) {
          setEvidence({
            state: 'READY',
            url: createdUrl,
            kind: chosen?.evidenceType === 'TARGET_CROP' ? 'TARGET_CROP' : 'SNAPSHOT',
          });
        }
      } catch {
        if (!cancelled) setEvidence({ state: 'UNAVAILABLE', url: null, kind: null });
      }
    };

    void load();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [activeAlertId, activeSnapshotUrl, getAuthHeaders]);

  const stopSiren = () => {
    const audio = sirenAudioRef.current;
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    if (sirenTimerRef.current !== null) {
      window.clearTimeout(sirenTimerRef.current);
      sirenTimerRef.current = null;
    }
    setSirenActive(false);
  };

  // Stop the siren whenever the operator switches to a different incident.
  useEffect(() => {
    stopSiren();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeAlertId]);

  // Release all audio resources on unmount.
  useEffect(() => {
    return () => {
      for (const ref of [sirenAudioRef, chimeAudioRef]) {
        const audio = ref.current;
        if (audio) {
          audio.pause();
          audio.currentTime = 0;
          ref.current = null;
        }
      }
      if (sirenTimerRef.current !== null) {
        window.clearTimeout(sirenTimerRef.current);
        sirenTimerRef.current = null;
      }
    };
  }, []);

  const playDispatchChime = () => {
    try {
      let audio = chimeAudioRef.current;
      if (!audio) {
        audio = new Audio('/audio/dispatch-chime.wav');
        audio.volume = 0.6;
        chimeAudioRef.current = audio;
      }
      audio.currentTime = 0;
      void audio.play().catch(() => { /* ignore playback rejection */ });
    } catch { /* audio unsupported */ }
  };

  const handleDispatchPatrol = () => {
    setActionNotice(`Patrol dispatched to ${activeAlert.cameraName}`);
    setTimeout(() => setActionNotice(null), 3500);
    playDispatchChime();
  };

  const handleToggleSiren = () => {
    try {
      let audio = sirenAudioRef.current;
      if (!audio) {
        audio = new Audio('/audio/siren.wav');
        audio.loop = true;
        audio.volume = 0.7;
        sirenAudioRef.current = audio;
      }
      if (sirenActive) {
        stopSiren();
        return;
      }
      void audio.play().then(() => {
        setSirenActive(true);
        // Controlled lifecycle: auto-stop after a short burst.
        if (sirenTimerRef.current !== null) window.clearTimeout(sirenTimerRef.current);
        sirenTimerRef.current = window.setTimeout(() => stopSiren(), 10000);
      }).catch(() => setSirenActive(false));
    } catch { /* audio unsupported */ }
  };

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-error text-xl">crisis_alert</span>
            Alerts &amp; Incident Command
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">Detect → Verify → Respond</p>
        </div>
        {actionNotice && (
          <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
            <span className="material-symbols-outlined text-[14px]">notifications_active</span>
            {actionNotice}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-outline-variant bg-surface rounded-t-xl overflow-x-auto">
        {[
          { id: 'INCIDENTS', label: `Active Alerts (${alerts.length})`, icon: 'crisis_alert' },
          { id: 'RULES', label: 'Detection Rules (6)', icon: 'rule' },
          { id: 'NIGHT_CURFEW', label: 'Night Curfew', icon: 'nightlight' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-4 py-2.5 text-[11px] font-bold flex items-center gap-1.5 border-b-2 transition-all cursor-pointer whitespace-nowrap ${
              activeTab === tab.id
                ? 'border-primary text-primary bg-primary/5'
                : 'border-transparent text-on-surface-variant hover:text-on-surface'
            }`}
          >
            <span className="material-symbols-outlined text-[16px]">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab 1: Incidents */}
      {activeTab === 'INCIDENTS' && (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[11px] text-on-surface-variant font-medium mr-1">Filter:</span>
            {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM'] as const).map((sev) => (
              <button
                key={sev}
                onClick={() => setFilterSeverity(sev)}
                className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-colors cursor-pointer ${
                  filterSeverity === sev ? 'bg-primary text-on-primary' : 'bg-surface border border-outline-variant text-on-surface-variant hover:text-on-surface'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* Alert List */}
            <div className="lg:col-span-5 flex flex-col gap-2.5">
              {filteredAlerts.map((alert, idx) => {
                const isSelected = alert.id === activeAlert.id;
                const isCrit = alert.severity === 'CRITICAL';
                const isHigh = alert.severity === 'HIGH';
                return (
                  <button
                    key={alert.id}
                    onClick={() => onSelectAlert(alert.id)}
                    className={`w-full p-3 rounded-xl border-l-4 transition-all cursor-pointer text-left flex flex-col gap-1.5 ${
                      isSelected
                        ? 'bg-primary/10 border-primary shadow-sm'
                        : 'bg-surface hover:bg-surface-container-low border-outline-variant/60'
                    } ${isCrit ? 'border-l-error' : isHigh ? 'border-l-warning' : 'border-l-outline'} border border-outline-variant/50`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${isCrit ? 'bg-error text-on-error' : isHigh ? 'bg-warning text-on-warning' : 'bg-surface-container-high text-on-surface-variant'}`}>
                          {alert.severity}
                        </span>
                        <span className="font-mono text-[11px] font-bold text-on-surface">{alert.id}</span>
                      </div>
                      <span className="font-mono text-[10px] text-on-surface-variant">{alert.timestamp}</span>
                    </div>
                    <div className="text-[13px] font-semibold text-on-surface">{alert.title}</div>
                    {alert.message && (
                      <div className="text-[11px] text-on-surface-variant leading-snug" data-testid="alert-message">
                        {alert.message}
                      </div>
                    )}
                    <div className="text-[11px] text-on-surface-variant flex items-center justify-between gap-2">
                      <span className="truncate">{alert.cameraId} · {alert.cameraName}</span>
                      <span className="flex items-center gap-2 shrink-0">
                        <span className="font-mono text-primary font-semibold">{alert.trackId}</span>
                        <AlertEvidenceThumb alert={alert} index={idx} />
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Dossier */}
            {activeAlert && (
              <div className="lg:col-span-7 bg-surface border border-outline-variant rounded-xl p-5 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between border-b border-outline-variant pb-3 mb-4">
                    <h2 className="text-[13px] font-bold text-on-surface tracking-wide">Evidence Dossier · {activeAlert.id}</h2>
                    <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${activeAlert.status === 'ACTIVE' ? 'bg-error-container text-on-error-container' : 'bg-success-container text-success'}`}>
                      {activeAlert.status}
                    </span>
                  </div>

                  {/* Incident Details */}
                  <div className="bg-surface-container-low rounded-lg p-3.5 border border-outline-variant mb-4">
                    <span className="text-[10px] font-bold text-primary uppercase tracking-wider block mb-2">Incident Details</span>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-2 text-[11px]">
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Severity</span>
                        <span className={`inline-block text-[10px] font-bold px-2 py-0.5 rounded mt-0.5 ${
                          activeAlert.severity === 'CRITICAL' ? 'bg-error text-on-error' :
                          activeAlert.severity === 'HIGH' ? 'bg-warning text-on-warning' :
                          'bg-surface-container-high text-on-surface-variant'
                        }`}>{activeAlert.severity}</span>
                      </div>
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Incident ID</span>
                        <span className="font-mono font-semibold text-on-surface">{activeAlert.id}</span>
                      </div>
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Type</span>
                        <span className="font-semibold text-on-surface">{activeAlert.eventType.replace(/_/g, ' ')}</span>
                      </div>
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Camera</span>
                        <span className="font-semibold text-on-surface">{activeAlert.cameraId} · {activeAlert.cameraName}</span>
                      </div>
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Zone / Location</span>
                        <span className="font-semibold text-on-surface">{activeAlert.zone}</span>
                      </div>
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Detected At</span>
                        <span className="font-mono text-on-surface">{activeAlert.timestamp}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-4 mt-2.5 pt-2.5 border-t border-outline-variant/40 text-[10px] text-on-surface-variant">
                      <span className="flex items-center gap-1">
                        <span className="text-[9px] font-semibold uppercase tracking-wider">Track</span>
                        <span className="font-mono font-bold text-on-surface">{activeAlert.trackId}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <span className="material-symbols-outlined text-[13px]">my_location</span>
                        Confidence <span className="font-mono font-bold text-on-surface">{activeAlert.confidence}%</span>
                      </span>
                    </div>
                  </div>

                  {/* Incident message (exact operator-facing alert sentence) */}
                  {activeAlert.message && (
                    <div
                      className="bg-error-container/40 border border-error/30 rounded-lg px-3 py-2 mb-4 text-[12px] font-semibold text-on-surface flex items-start gap-2"
                      data-testid="dossier-message"
                    >
                      <span className="material-symbols-outlined text-error text-[15px] mt-0.5">warning</span>
                      <span>{activeAlert.message}</span>
                    </div>
                  )}

                  {/* Response controls */}
                  <div className="flex flex-wrap items-center gap-2 pb-4 mb-4 border-b border-outline-variant">
                    <button onClick={handleDispatchPatrol} className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold flex items-center justify-center gap-1.5 cursor-pointer">
                      <span className="material-symbols-outlined text-[14px]">local_police</span> Dispatch Patrol
                    </button>
                    <button
                      onClick={handleToggleSiren}
                      aria-pressed={sirenActive}
                      className={`px-3 py-1.5 rounded-lg text-[11px] font-bold flex items-center justify-center gap-1.5 cursor-pointer transition-colors ${
                        sirenActive
                          ? 'bg-error text-on-error'
                          : 'bg-surface hover:bg-surface-container-high border border-error text-error'
                      }`}
                    >
                      <span className="material-symbols-outlined text-[14px]">{sirenActive ? 'volume_off' : 'volume_up'}</span>
                      {sirenActive ? 'Stop Siren' : 'Sound Siren'}
                    </button>
                    {onActionAlert && activeAlert.status === 'ACTIVE' && (
                      <button onClick={() => onActionAlert(activeAlert.id, 'ACKNOWLEDGE')} className="px-3 py-1.5 bg-surface hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface font-semibold rounded-lg cursor-pointer flex items-center justify-center gap-1.5">
                        <span className="material-symbols-outlined text-[14px]">check</span>
                        Acknowledge
                      </button>
                    )}
                  </div>

                  {/* Snapshot */}
                  <div className="relative w-full aspect-video bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant mb-4 select-none">
                    {evidence.state === 'READY' && evidence.url ? (
                      <>
                        <img
                          src={evidence.url}
                          alt={evidence.kind === 'TARGET_CROP' ? 'Target crop evidence' : 'Incident snapshot'}
                          className="w-full h-full object-cover opacity-90"
                          onError={() => setEvidence({ state: 'UNAVAILABLE', url: null, kind: null })}
                        />
                        {/* No fake CSS bounding box — the red box + labels are
                            baked into TARGET_CROP images by the AI pipeline. */}
                        <div className="absolute bottom-2 left-2 flex items-center gap-1.5">
                          {evidence.kind === 'TARGET_CROP' && (
                            <span className="bg-error px-2 py-0.5 rounded text-[9px] font-mono font-bold text-on-error" data-testid="evidence-target-crop-badge">
                              TARGET CROP
                            </span>
                          )}
                          <span className="bg-on-surface/80 px-2 py-0.5 rounded text-[10px] text-surface font-mono">
                            {activeAlert.cameraName} · {activeAlert.timestamp}
                          </span>
                        </div>
                      </>
                    ) : evidence.state === 'LOADING' ? (
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-on-surface-variant">
                        <span className="material-symbols-outlined text-[28px] animate-spin">progress_activity</span>
                        <span className="text-[11px]">Loading evidence snapshot…</span>
                      </div>
                    ) : (
                      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-on-surface-variant px-4 text-center">
                        <span className="material-symbols-outlined text-[32px] opacity-60">image_not_supported</span>
                        <span className="text-[11px] font-bold uppercase tracking-wider">No evidence snapshot captured</span>
                        <span className="text-[10px] font-mono">{activeAlert.cameraName} · {activeAlert.timestamp}</span>
                      </div>
                    )}
                  </div>

                  {/* Reason */}
                  <div className="bg-surface-container-low rounded-lg p-3.5 border border-outline-variant mb-3 text-[11px]">
                    <span className="text-primary font-bold block mb-1">TRIGGER REASON:</span>
                    <p className="text-on-surface leading-relaxed">{activeAlert.reason}</p>
                  </div>

                  {/* Risk Score + Context */}
                  {(activeAlert.riskScore !== undefined && activeAlert.riskScore > 0) && (
                    <div className="bg-surface-container-low rounded-lg p-3.5 border border-outline-variant mb-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-bold text-primary uppercase tracking-wider">Risk Assessment</span>
                        <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                          activeAlert.riskSeverity === 'CRITICAL' ? 'bg-error text-on-error' :
                          activeAlert.riskSeverity === 'HIGH' ? 'bg-warning text-on-warning' :
                          activeAlert.riskSeverity === 'MEDIUM' ? 'bg-surface-container-high text-on-surface' :
                          'bg-surface-container-high text-on-surface-variant'
                        }`}>
                          {activeAlert.riskSeverity || activeAlert.severity}
                          <span className="ml-1.5 opacity-75">({activeAlert.riskScore})</span>
                        </span>
                      </div>
                      {activeAlert.riskFactors && activeAlert.riskFactors.length > 0 && (
                        <div className="space-y-1 text-[11px]">
                          {activeAlert.riskFactors.map((f, idx) => (
                            <div key={idx} className="flex items-center gap-2 text-on-surface">
                              <span className="text-success font-mono font-bold">+{f.points}</span>
                              <span>{f.factor}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="flex flex-wrap gap-3 mt-2 pt-2 border-t border-outline-variant/40 text-[10px] text-on-surface-variant">
                        {activeAlert.direction && activeAlert.direction !== 'UNKNOWN' && (
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[12px]">navigation</span>
                            {activeAlert.direction.replace(/_/g, ' ')}
                          </span>
                        )}
                        {(activeAlert.dwellSeconds !== undefined && activeAlert.dwellSeconds > 0) && (
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[12px]">timer</span>
                            Dwell: {activeAlert.dwellSeconds.toFixed(0)}s
                          </span>
                        )}
                        {activeAlert.loitering && (
                          <span className="flex items-center gap-1 text-warning">
                            <span className="material-symbols-outlined text-[12px]">hourglass_bottom</span>
                            Loitering
                          </span>
                        )}
                        {activeAlert.fenceProximity && (
                          <span className="flex items-center gap-1">
                            <span className="material-symbols-outlined text-[12px]">fence</span>
                            Near Fence
                          </span>
                        )}
                        {activeAlert.repeatedEntry && (
                          <span className="flex items-center gap-1 text-error">
                            <span className="material-symbols-outlined text-[12px]">replay</span>
                            Repeated Entry
                          </span>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Evidence Checklist */}
                  <div className="bg-surface-container-low rounded-lg p-3.5 border border-outline-variant">
                    <span className="text-[10px] font-bold text-primary uppercase tracking-wider block mb-2">Verification Checklist</span>
                    <div className="space-y-1.5 text-[11px] text-on-surface">
                      {activeAlert.evidenceChecklist.map((item, idx) => (
                        <div key={idx} className="flex items-start gap-2">
                          <span className="material-symbols-outlined text-success text-[14px] shrink-0 mt-0.5">check_circle</span>
                          <span>{item}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Rules */}
      {activeTab === 'RULES' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[
            { title: 'Restricted-Zone Entry', icon: 'fence', severity: 'CRITICAL', desc: 'Fires when object centroid intersects a restricted polygon.', trigger: 'Centroid Ingress' },
            { title: 'Loitering Dwell', icon: 'timer', severity: 'MEDIUM', desc: 'Fires when entity remains in buffer area beyond threshold.', trigger: 'Dwell exceeded' },
            { title: 'Unauthorized Vehicle', icon: 'no_crash', severity: 'HIGH', desc: 'Flags vehicles in non-designated lanes or after curfew.', trigger: 'ANPR Miss' },
            { title: 'Person Convergence', icon: 'group_work', severity: 'HIGH', desc: 'Flags multiple track IDs approaching within proximity threshold.', trigger: 'Proximity threshold' },
            { title: 'Night Perimeter Motion', icon: 'nightlight', severity: 'CRITICAL', desc: 'Amplified motion filter during curfew hours.', trigger: 'Curfew + Motion' },
            { title: 'Watchlist Plate Match', icon: 'warning', severity: 'CRITICAL', desc: 'Fires when OCR matches active blacklist entry.', trigger: 'Exact Match' },
          ].map((rule, idx) => (
            <div key={idx} className="bg-surface border border-outline-variant rounded-xl p-4 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="material-symbols-outlined text-primary text-[20px]">{rule.icon}</span>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${rule.severity === 'CRITICAL' ? 'bg-error-container text-on-error-container' : rule.severity === 'HIGH' ? 'bg-warning-container text-on-warning-container' : 'bg-surface-container-high text-on-surface-variant'}`}>
                    {rule.severity}
                  </span>
                </div>
                <h3 className="text-[13px] font-bold text-on-surface">{rule.title}</h3>
                <p className="text-[11px] text-on-surface-variant mt-1.5 leading-relaxed">{rule.desc}</p>
              </div>
              <div className="mt-3 pt-2 border-t border-outline-variant/40 text-[10px] font-mono text-primary">Trigger: {rule.trigger}</div>
            </div>
          ))}
        </div>
      )}

      {/* Tab 3: Night Curfew */}
      {activeTab === 'NIGHT_CURFEW' && (
        <div className="bg-surface border border-outline-variant rounded-xl p-5 flex flex-col gap-4">
          <div className="flex items-center justify-between border-b border-outline-variant pb-3">
            <div>
              <h2 className="text-[15px] font-bold text-on-surface">Night Curfew Surveillance Engine</h2>
              <p className="text-[11px] text-on-surface-variant mt-0.5">Configurable curfew hours</p>
            </div>
            <span className="text-[11px] font-bold text-on-surface-variant flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-on-surface-variant" /> NOT CONFIGURED
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
              <span className="text-[11px] text-on-surface-variant">Sensor Amplification</span>
              <div className="text-xl font-bold text-on-surface-variant mt-1">—</div>
              <span className="text-[10px] text-on-surface-variant">No data</span>
            </div>
            <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
              <span className="text-[11px] text-on-surface-variant">Curfew Breaches</span>
              <div className="text-xl font-bold text-on-surface-variant mt-1">0</div>
              <span className="text-[10px] text-on-surface-variant">No data</span>
            </div>
            <div className="bg-surface-container-low p-4 rounded-xl border border-outline-variant">
              <span className="text-[11px] text-on-surface-variant">Thermal IR</span>
              <div className="text-xl font-bold text-on-surface-variant mt-1">—</div>
              <span className="text-[10px] text-on-surface-variant">No data</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
