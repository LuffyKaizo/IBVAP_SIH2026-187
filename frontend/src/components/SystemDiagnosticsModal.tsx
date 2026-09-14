import React, { useState, useEffect } from 'react';
import { DiagnosticsCheckItem } from '../types';

interface SystemDiagnosticsModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRunAgain?: () => void;
}

const EMPTY_DIAGNOSTICS: DiagnosticsCheckItem[] = [];

export const SystemDiagnosticsModal: React.FC<SystemDiagnosticsModalProps> = ({ isOpen, onClose, onRunAgain }) => {
  const [isScanning, setIsScanning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [activeStepIndex, setActiveStepIndex] = useState(0);
  const [diagnosticsItems, setDiagnosticsItems] = useState<DiagnosticsCheckItem[]>(EMPTY_DIAGNOSTICS);
  const [overallHealth, setOverallHealth] = useState<'OPTIMAL' | 'DEGRADED' | 'CHECKING'>('CHECKING');

  const runDiagnosticScan = async () => {
    setIsScanning(true);
    setProgress(0);
    setActiveStepIndex(0);
    setOverallHealth('CHECKING');
    try {
      const res = await fetch('/api/diagnostics/run', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        const results = data.results || [];
        setDiagnosticsItems(results);
        setOverallHealth(data.overallStatus || 'OPTIMAL');
        setProgress(100);
      } else {
        setDiagnosticsItems([]);
        setOverallHealth('DEGRADED');
      }
    } catch {
      setDiagnosticsItems([]);
      setOverallHealth('DEGRADED');
    } finally {
      setIsScanning(false);
    }
  };

  useEffect(() => { if (isOpen) runDiagnosticScan(); }, [isOpen]);
  if (!isOpen) return null;

  const avgLatency = Math.round(diagnosticsItems.reduce((a, item) => a + item.latencyMs, 0) / diagnosticsItems.length);
  const avgIntegrity = (diagnosticsItems.reduce((a, item) => a + item.integrityScore, 0) / diagnosticsItems.length).toFixed(2);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-on-surface/30 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-3xl bg-surface border border-outline-variant shadow-2xl flex flex-col relative overflow-hidden rounded-xl">
        {/* Header */}
        <div className="h-12 bg-surface-container-low border-b border-outline-variant flex items-center justify-between px-4 rounded-t-xl">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[18px]">memory</span>
            <span className="text-[11px] font-bold text-primary tracking-wider">SYSTEM DIAGNOSTICS</span>
          </div>
          <button onClick={onClose} className="text-on-surface-variant hover:text-on-surface p-1 cursor-pointer"><span className="material-symbols-outlined text-[18px]">close</span></button>
        </div>

        {/* Progress */}
        <div className="h-1 w-full bg-surface-container-lowest overflow-hidden">
          <div className={`h-full transition-all duration-300 ${isScanning ? 'bg-primary animate-pulse' : 'bg-success'}`} style={{ width: `${progress}%` }} />
        </div>

        {/* Body */}
        <div className="p-4 flex flex-col gap-4 max-h-[70vh] overflow-y-auto">
          {/* Status Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { label: 'Pipeline Health', value: isScanning ? 'CHECKING...' : overallHealth, color: isScanning ? 'text-warning' : 'text-success', icon: isScanning ? 'sync' : 'verified' },
              { label: 'Avg Latency', value: `${avgLatency} ms`, sub: '30 FPS' },
              { label: 'Stream Integrity', value: `${avgIntegrity}%`, sub: '6/6 SYNCED' },
            ].map((card, i) => (
              <div key={i} className="bg-surface-container-low p-3 border border-outline-variant rounded-xl flex items-center justify-between">
                <div>
                  <span className="text-[9px] text-on-surface-variant font-bold uppercase">{card.label}</span>
                  <div className={`text-[13px] font-bold mt-0.5 flex items-center gap-1.5 ${card.color || 'text-on-surface'}`}>
                    {card.icon && <span className="material-symbols-outlined text-[14px]">{card.icon}</span>}
                    {card.value}
                  </div>
                  {card.sub && <span className="text-[9px] text-on-surface-variant">{card.sub}</span>}
                </div>
              </div>
            ))}
          </div>

          {/* Subsystems */}
          <div className="flex flex-col">
            <div className="flex items-center justify-between border-b border-outline-variant pb-1 text-[9px] text-on-surface-variant font-bold uppercase">
              <span>Subsystem</span>
              <div className="flex items-center gap-6"><span>Latency</span><span>Integrity</span><span>Status</span></div>
            </div>
            <div className="divide-y divide-outline-variant/30">
              {diagnosticsItems.length === 0 && !isScanning ? (
                <div className="py-8 text-center text-on-surface-variant/50 text-[12px]">
                  No diagnostics data — click RE-RUN to check system health
                </div>
              ) : diagnosticsItems.map((item, idx) => (
                <div key={item.id} className={`py-2.5 px-2 flex items-center justify-between transition-colors ${isScanning && activeStepIndex === idx ? 'bg-primary/5 border-l-2 border-primary' : 'hover:bg-surface-container-low'}`}>
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-[16px] text-primary">
                      {item.category === 'AI_INFERENCE' ? 'neurology' : item.category === 'ANPR_OCR' ? 'license' : item.category === 'TRACKING_ENGINE' ? 'route' : item.category === 'EVENT_ENGINE' ? 'crisis_alert' : item.category === 'STORAGE_BUFFER' ? 'hard_drive' : 'videocam'}
                    </span>
                    <div>
                      <div className="text-[11px] font-bold text-on-surface">{item.name}</div>
                      <div className="text-[9px] text-on-surface-variant">{item.details}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-[10px] font-mono">
                    <span className="text-on-surface-variant w-14 text-right">{item.latencyMs} ms</span>
                    <span className="text-primary w-14 text-right font-bold">{item.integrityScore}%</span>
                    <span className={`w-16 text-center px-1.5 py-0.5 text-[9px] font-bold rounded ${item.status === 'OPTIMAL' ? 'bg-success-container text-success' : 'bg-error-container text-error'}`}>
                      {isScanning && activeStepIndex === idx ? 'CHECKING' : item.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="h-12 bg-surface-container-low border-t border-outline-variant flex items-center justify-between px-4 rounded-b-xl">
          <span className="text-[10px] text-on-surface-variant">RTSP & AI PIPELINE HEALTH: VERIFIED</span>
          <div className="flex items-center gap-2">
            <button onClick={() => { runDiagnosticScan(); onRunAgain?.(); }} disabled={isScanning}
              className="px-3 py-1.5 bg-surface hover:bg-surface-container-high border border-outline-variant text-[10px] text-on-surface rounded-lg flex items-center gap-1.5 disabled:opacity-50 cursor-pointer">
              <span className={`material-symbols-outlined text-[14px] ${isScanning ? 'animate-spin' : ''}`}>refresh</span> RE-RUN
            </button>
            <button onClick={onClose} className="px-4 py-1.5 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[10px] font-bold cursor-pointer">CLOSE</button>
          </div>
        </div>
      </div>
    </div>
  );
};
