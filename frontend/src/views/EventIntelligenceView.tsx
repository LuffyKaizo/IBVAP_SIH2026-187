import React, { useEffect, useRef, useState } from 'react';
import { BorderAlert, SuspiciousEventItem } from '../types';
import { useAuth } from '../contexts/AuthContext';
import EvidenceViewer, { EvidenceArtifactRow, EvidenceSetState, EvidenceSlot } from '../components/EvidenceViewer';

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
  const [filterSeverity, setFilterSeverity] = useState<'ALL' | 'CRITICAL' | 'MEDIUM' | 'LOW'>('ALL');
  const [activeTab, setActiveTab] = useState<'INCIDENTS' | 'RULES' | 'NIGHT_CURFEW'>('INCIDENTS');
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [sirenActive, setSirenActive] = useState(false);
  const [evidenceSet, setEvidenceSet] = useState<EvidenceSetState>({ state: 'LOADING' });
  const [flashId, setFlashId] = useState<string | null>(null);

  const { getAuthHeaders } = useAuth();
  const sirenAudioRef = useRef<HTMLAudioElement | null>(null);
  const chimeAudioRef = useRef<HTMLAudioElement | null>(null);
  const sirenTimerRef = useRef<number | null>(null);

  const filteredAlerts = alerts.filter((a) => {
    if (filterSeverity === 'ALL') return true;
    // Legacy rows may still carry HIGH — group them under the MEDIUM section.
    const sev = a.severity === 'HIGH' ? 'MEDIUM' : a.severity;
    return sev === filterSeverity;
  });
  const activeAlert = alerts.find((a) => a.id === selectedAlertId) || filteredAlerts[0] || alerts[0];
  const activeAlertId = activeAlert?.id;
  const activeSnapshotUrl = activeAlert?.snapshotUrl;

  // Load the full 3-artifact evidence set (original / annotated / target)
  // for the selected incident through GET /evidence/set/{eventId} — with a
  // fallback to the legacy list endpoint, then fetch each artifact's file.
  useEffect(() => {
    let cancelled = false;
    const createdUrls: string[] = [];
    setEvidenceSet({ state: 'LOADING' });

    const fetchRow = async (row: EvidenceArtifactRow): Promise<EvidenceSlot | null> => {
      if (!row?.id) return null;
      const res = await fetch(`${AI_SERVICE_URL}/evidence/${encodeURIComponent(row.id)}/file`, {
        headers: getAuthHeaders(),
      });
      if (!res.ok) return null;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      createdUrls.push(url);
      return { row, url };
    };

    const load = async () => {
      try {
        if (!activeAlertId) {
          setEvidenceSet({ state: 'UNAVAILABLE' });
          return;
        }
        if (activeSnapshotUrl) {
          // System/mock alerts carry a direct snapshot URL — single artifact.
          setEvidenceSet({ state: 'READY', original: { row: null, url: activeSnapshotUrl } });
          return;
        }
        const eventId = eventIdFromAlertId(activeAlertId);
        if (!eventId) {
          setEvidenceSet({ state: 'UNAVAILABLE' });
          return;
        }
        const headers = getAuthHeaders();

        let rows: EvidenceArtifactRow[] = [];
        try {
          const setRes = await fetch(
            `${AI_SERVICE_URL}/evidence/set/${encodeURIComponent(eventId)}`,
            { headers },
          );
          if (setRes.ok) {
            const data = await setRes.json();
            rows = [data.original, data.annotated, data.target].filter(Boolean);
          }
        } catch {
          /* fall through to legacy list */
        }
        if (rows.length === 0) {
          const listRes = await fetch(
            `${AI_SERVICE_URL}/evidence?event_id=${encodeURIComponent(eventId)}&limit=5`,
            { headers },
          );
          if (!listRes.ok) throw new Error(`evidence list ${listRes.status}`);
          const list = await listRes.json();
          rows = (list?.evidence || []).filter((e: EvidenceArtifactRow) => e?.id);
        }

        const slots = await Promise.all(rows.map(fetchRow));
        if (cancelled) return;
        const valid = slots.filter(Boolean) as EvidenceSlot[];
        if (valid.length === 0) {
          setEvidenceSet({ state: 'UNAVAILABLE' });
          return;
        }
        const find = (type: string) =>
          valid.find((s) => s.row?.evidenceType === type) || null;
        setEvidenceSet({
          state: 'READY',
          original: find('SNAPSHOT'),
          annotated: find('ANNOTATED'),
          target: find('TARGET_CROP'),
        });
      } catch {
        if (!cancelled) setEvidenceSet({ state: 'UNAVAILABLE' });
      }
    };

    void load();
    return () => {
      cancelled = true;
      for (const url of createdUrls) URL.revokeObjectURL(url);
    };
  }, [activeAlertId, activeSnapshotUrl, getAuthHeaders]);

  // Alert-click focus: scroll the selected alert card into view and flash it
  // (selectedAlertId can be set from anywhere via handleSelectAlert).
  useEffect(() => {
    if (!selectedAlertId) return;
    const el = document.getElementById(`alert-card-${selectedAlertId}`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setFlashId(selectedAlertId);
    const t = window.setTimeout(() => setFlashId(null), 1400);
    return () => window.clearTimeout(t);
  }, [selectedAlertId]);

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

  // Open the print-ready incident report (HTML with embedded evidence +
  // SHA-256). Fetched with auth headers, then opened as a blob URL so no
  // credentials leak into the URL.
  const handleOpenReport = async () => {
    try {
      const eventId = activeAlert ? eventIdFromAlertId(activeAlert.id) : null;
      if (!eventId) return;
      const res = await fetch(
        `${AI_SERVICE_URL}/reports/incidents/${encodeURIComponent(eventId)}`,
        { headers: getAuthHeaders() },
      );
      if (!res.ok) throw new Error(`report ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      setActionNotice('Incident report opened');
      setTimeout(() => setActionNotice(null), 3500);
    } catch {
      setActionNotice('Report unavailable for this incident');
      setTimeout(() => setActionNotice(null), 3500);
    }
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
            {(['ALL', 'CRITICAL', 'MEDIUM', 'LOW'] as const).map((sev) => (
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
                const isMed = alert.severity === 'HIGH' || alert.severity === 'MEDIUM';
                const severityLabel = alert.severity === 'HIGH' ? 'MEDIUM' : alert.severity;
                return (
                  <button
                    key={alert.id}
                    id={`alert-card-${alert.id}`}
                    data-testid={`alert-card-${alert.id}`}
                    onClick={() => onSelectAlert(alert.id)}
                    className={`w-full p-3 rounded-xl border-l-4 transition-all cursor-pointer text-left flex flex-col gap-1.5 ${
                      isSelected
                        ? 'bg-primary/10 border-primary shadow-sm'
                        : 'bg-surface hover:bg-surface-container-low border-outline-variant/60'
                    } ${flashId === alert.id ? 'ring-2 ring-primary ring-offset-1 ring-offset-surface' : ''} ${
                      isCrit ? 'border-l-error' : isMed ? 'border-l-warning' : 'border-l-outline'
                    } border border-outline-variant/50`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`text-[9px] font-bold px-2 py-0.5 rounded ${isCrit ? 'bg-error text-on-error' : isMed ? 'bg-warning text-on-warning' : 'bg-surface-container-high text-on-surface-variant'}`}>
                          {severityLabel}
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
                          activeAlert.severity === 'HIGH' || activeAlert.severity === 'MEDIUM' ? 'bg-warning text-on-warning' :
                          'bg-surface-container-high text-on-surface-variant'
                        }`}>{activeAlert.severity === 'HIGH' ? 'MEDIUM' : activeAlert.severity}</span>
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
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Object Type</span>
                        <span className="font-semibold text-on-surface capitalize" data-testid="alert-object-class">
                          {activeAlert.objectClass || (activeAlert.bbox ? 'Tracked target' : '—')}
                        </span>
                      </div>
                      <div>
                        <span className="block text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">FPS (source / analysis)</span>
                        <span className="font-mono text-on-surface">
                          {activeAlert.sourceFps ?? '—'} / {activeAlert.processingFps ?? '—'}
                        </span>
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
                      onClick={() => void handleOpenReport()}
                      data-testid="open-incident-report"
                      className="px-3 py-1.5 bg-surface hover:bg-surface-container-high border border-outline-variant rounded-lg text-[11px] font-bold flex items-center justify-center gap-1.5 cursor-pointer text-on-surface"
                    >
                      <span className="material-symbols-outlined text-[14px]">description</span> Incident Report
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

                  {/* Evidence viewer: original / target / annotated / perspective */}
                  <EvidenceViewer
                    set={evidenceSet}
                    bbox={activeAlert.bbox}
                    frameWidth={activeAlert.frameWidth}
                    frameHeight={activeAlert.frameHeight}
                    cameraName={activeAlert.cameraName}
                    timestamp={activeAlert.timestamp}
                  />

                  {/* Chain of custody (primary artifact: target > annotated > original) */}
                  {(() => {
                    const primary =
                      evidenceSet.target?.row || evidenceSet.annotated?.row || evidenceSet.original?.row;
                    if (!primary) return null;
                    return (
                      <div
                        className="bg-surface-container-low rounded-lg px-3 py-2 mb-4 border border-outline-variant flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[10px]"
                        data-testid="evidence-chain-of-custody"
                      >
                        <span className="flex items-center gap-1.5">
                          <span className="text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Integrity</span>
                          <span
                            className={`font-bold px-1.5 py-0.5 rounded ${
                              primary.integrityStatus === 'VALID'
                                ? 'bg-success-container text-success'
                                : 'bg-error-container text-on-error-container'
                            }`}
                          >
                            {primary.integrityStatus || 'UNKNOWN'}
                          </span>
                        </span>
                        <span className="flex items-center gap-1.5 min-w-0">
                          <span className="text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider shrink-0">SHA-256</span>
                          <span
                            className="font-mono text-on-surface truncate"
                            title={primary.sha256Hash || ''}
                            data-testid="evidence-sha256"
                          >
                            {primary.sha256Hash ? `${primary.sha256Hash.slice(0, 24)}…` : '—'}
                          </span>
                        </span>
                        <span className="flex items-center gap-1.5">
                          <span className="text-[9px] font-semibold text-on-surface-variant uppercase tracking-wider">Artifacts</span>
                          <span className="font-mono text-on-surface">
                            {[evidenceSet.original, evidenceSet.annotated, evidenceSet.target]
                              .filter(Boolean).length}/3
                          </span>
                        </span>
                      </div>
                    );
                  })()}

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
            { title: 'Loitering Dwell', icon: 'timer', severity: 'LOW', desc: 'Fires when entity remains in buffer area beyond threshold.', trigger: 'Dwell exceeded' },
            { title: 'Unauthorized Vehicle', icon: 'no_crash', severity: 'MEDIUM', desc: 'Flags vehicles in non-designated lanes or after curfew.', trigger: 'ANPR Miss' },
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
