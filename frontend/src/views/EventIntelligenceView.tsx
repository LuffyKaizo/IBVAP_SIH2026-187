import React, { useState } from 'react';
import { BorderAlert, SuspiciousEventItem } from '../types';

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

  const filteredAlerts = alerts.filter((a) => filterSeverity === 'ALL' || a.severity === filterSeverity);
  const activeAlert = alerts.find((a) => a.id === selectedAlertId) || filteredAlerts[0] || alerts[0];

  const handleDispatchPatrol = () => {
    setActionNotice(`Patrol dispatched to ${activeAlert.cameraName}`);
    setTimeout(() => setActionNotice(null), 3500);
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
              {filteredAlerts.map((alert) => {
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
                    <div className="text-[11px] text-on-surface-variant flex items-center justify-between">
                      <span>{alert.cameraId} · {alert.cameraName}</span>
                      <span className="font-mono text-primary font-semibold">{alert.trackId}</span>
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

                  {/* Snapshot */}
                  <div className="relative w-full aspect-video bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant mb-4 select-none">
                    <img src={activeAlert.snapshotUrl || ''} alt="Incident" className="w-full h-full object-cover opacity-90" />
                    <div className="absolute left-[38%] top-[25%] w-[22%] h-[55%] border-2 border-error bg-error/10">
                      <span className="absolute -top-[18px] left-0 text-[9px] font-mono font-bold text-on-error bg-error px-1.5 py-[2px] rounded">
                        TARGET {activeAlert.trackId} ({activeAlert.confidence}%)
                      </span>
                    </div>
                    <div className="absolute bottom-2 left-2 bg-on-surface/80 px-2 py-0.5 rounded text-[10px] text-surface font-mono">
                      {activeAlert.cameraName} · {activeAlert.timestamp}
                    </div>
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

                {/* Actions */}
                <div className="pt-4 mt-4 border-t border-outline-variant flex flex-wrap items-center gap-2">
                  <button onClick={handleDispatchPatrol} className="px-3 py-1.5 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold flex items-center justify-center gap-1.5 cursor-pointer">
                    <span className="material-symbols-outlined text-[14px]">local_police</span> Dispatch Patrol
                  </button>
                  <button className="px-3 py-1.5 bg-surface hover:bg-surface-container-high border border-error text-error rounded-lg text-[11px] font-bold flex items-center justify-center gap-1.5 cursor-pointer">
                    <span className="material-symbols-outlined text-[14px]">volume_up</span> Sound Siren
                  </button>
                  {onActionAlert && activeAlert.status === 'ACTIVE' && (
                    <button onClick={() => onActionAlert(activeAlert.id, 'ACKNOWLEDGE')} className="px-3 py-1.5 bg-surface hover:bg-surface-container-high border border-outline-variant text-[11px] text-on-surface font-semibold rounded-lg cursor-pointer flex items-center justify-center gap-1.5">
                      <span className="material-symbols-outlined text-[14px]">check</span>
                      Acknowledge
                    </button>
                  )}
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
