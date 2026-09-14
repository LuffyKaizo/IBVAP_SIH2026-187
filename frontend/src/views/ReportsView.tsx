import React, { useState } from 'react';
import { SurveillanceReportItem } from '../types';

interface ReportsViewProps {
  reports: SurveillanceReportItem[];
  onGenerateReport?: (report: Partial<SurveillanceReportItem>) => void;
}

export const ReportsView: React.FC<ReportsViewProps> = ({ reports, onGenerateReport }) => {
  const [selectedReport, setSelectedReport] = useState<SurveillanceReportItem | null>(
    reports.length > 0 ? reports[0] : null
  );
  const [reportTypeFilter, setReportTypeFilter] = useState<string>('ALL');
  const [newTitle, setNewTitle] = useState('');
  const [newType, setNewType] = useState<SurveillanceReportItem['type']>('INCIDENT_DOSSIER');
  const [newCamera, setNewCamera] = useState('');
  const [newNotes, setNewNotes] = useState('');
  const [reportNotice, setReportNotice] = useState<string | null>(null);

  const filteredReports = reports.filter((r) => reportTypeFilter === 'ALL' || r.type === reportTypeFilter);

  // Empty state — no reports generated yet
  if (!selectedReport) {
    return (
      <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
        <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-xl">description</span>
              Surveillance Reports
            </h1>
            <p className="text-[12px] text-on-surface-variant mt-0.5">Incident dossiers · Audit archive · Exportable reports</p>
          </div>
          {reportNotice && (
            <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
              <span className="material-symbols-outlined text-[14px]">check_circle</span> {reportNotice}
            </div>
          )}
        </div>
        <div className="bg-surface border border-outline-variant rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-[48px] text-on-surface-variant/40 block mb-3">description</span>
          <p className="text-on-surface-variant text-sm">No reports generated yet</p>
          <p className="text-on-surface-variant/60 text-[11px] mt-1">Surveillance reports will appear here once generated</p>
        </div>

        {/* Generate Form — still accessible on empty state */}
        <div className="bg-surface border border-outline-variant rounded-xl p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between border-b border-outline-variant pb-2">
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Generate New Report</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Title</label>
              <input type="text" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none" />
            </div>
            <div>
              <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Category</label>
              <select value={newType} onChange={(e) => setNewType(e.target.value as any)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none">
                <option value="INCIDENT_DOSSIER">Incident Dossier</option><option value="DAILY_SURVEILLANCE">Daily Surveillance</option><option value="ANPR_TRAFFIC">ANPR Traffic</option>
              </select>
            </div>
            <div>
              <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Camera</label>
              <input type="text" value={newCamera} onChange={(e) => setNewCamera(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none" />
            </div>
          </div>
          <div>
            <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Notes</label>
            <textarea rows={2} value={newNotes} onChange={(e) => setNewNotes(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none resize-none" />
          </div>
          <div className="flex justify-end">
            <button onClick={() => {
              if (!newTitle.trim()) {
                setReportNotice('Title is required');
                setTimeout(() => setReportNotice(null), 3000);
                return;
              }
              const report: SurveillanceReportItem = {
                id: `REP-2026-${String(reports.length + 1).padStart(3, '0')}`,
                title: newTitle,
                type: newType,
                date: new Date().toISOString().replace('T', ' ').substring(0, 16) + ' UTC',
                camera: newCamera || 'Not specified',
                severity: 'HIGH',
                evidence: [],
                summary: '',
                analystNotes: newNotes,
                generatedBy: 'OPERATOR',
              };
              onGenerateReport?.(report);
              setSelectedReport(report);
              setReportNotice(`Report "${report.title}" generated.`);
              setTimeout(() => setReportNotice(null), 4000);
            }} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold flex items-center gap-1.5 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">add_circle</span> GENERATE REPORT
            </button>
          </div>
        </div>
      </div>
    );
  }

  const handleGenerate = () => {
    if (!newTitle.trim()) {
      setReportNotice('Title is required');
      setTimeout(() => setReportNotice(null), 3000);
      return;
    }
    const report: SurveillanceReportItem = {
      id: `REP-2026-${String(reports.length + 1).padStart(3, '0')}`,
      title: newTitle,
      type: newType,
      date: new Date().toISOString().replace('T', ' ').substring(0, 16) + ' UTC',
      camera: newCamera || 'Not specified',
      severity: 'HIGH',
      evidence: [],
      summary: '',
      analystNotes: newNotes,
      generatedBy: 'OPERATOR',
    };
    onGenerateReport?.(report);
    setSelectedReport(report);
    setReportNotice(`Report "${report.title}" generated.`);
    setTimeout(() => setReportNotice(null), 4000);
  };

  const handleExport = () => {
    const severityColor = selectedReport.severity === 'CRITICAL' ? '#B84C4C' : selectedReport.severity === 'HIGH' ? '#B88735' : '#356B7A';
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>IBVAP Report — ${selectedReport.id}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Inter', sans-serif; background: #F1F4F2; color: #243238; padding: 40px; }
  .report { max-width: 800px; margin: 0 auto; background: #FCFDFC; border: 1px solid #D4DEDC; border-radius: 12px; overflow: hidden; }
  .header { background: #356B7A; color: white; padding: 32px 40px; }
  .header h1 { font-size: 13px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.8; margin-bottom: 8px; }
  .header h2 { font-size: 22px; font-weight: 700; line-height: 1.3; }
  .meta { display: flex; gap: 32px; padding: 20px 40px; background: #E7EEEC; border-bottom: 1px solid #D4DEDC; font-size: 12px; }
  .meta-item { display: flex; flex-direction: column; gap: 2px; }
  .meta-label { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #66757A; }
  .meta-value { font-family: 'JetBrains Mono', monospace; font-weight: 600; color: #243238; }
  .severity-badge { display: inline-block; padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 700; color: white; background: ${severityColor}; }
  .content { padding: 32px 40px; }
  .section { margin-bottom: 28px; }
  .section-title { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: #356B7A; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 2px solid #DDECEA; }
  .section p { font-size: 13px; line-height: 1.7; color: #243238; }
  .evidence-list { list-style: none; padding: 0; }
  .evidence-list li { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; border-bottom: 1px solid #D4DEDC; font-size: 13px; line-height: 1.5; }
  .evidence-list li:last-child { border-bottom: none; }
  .evidence-icon { color: #3E7655; font-weight: bold; flex-shrink: 0; margin-top: 2px; }
  .notes { background: #E7EEEC; padding: 16px 20px; border-radius: 8px; font-size: 13px; line-height: 1.7; color: #243238; }
  .footer { padding: 20px 40px; background: #E7EEEC; border-top: 1px solid #D4DEDC; display: flex; justify-content: space-between; align-items: center; font-size: 11px; color: #66757A; }
  .footer-left { display: flex; align-items: center; gap: 6px; }
  .footer-left span { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #3E7655; }
  @media print { body { padding: 0; background: white; } .report { border: none; border-radius: 0; } }
</style>
</head>
<body>
<div class="report">
  <div class="header">
    <h1>Intelligent Border Video Analytics Platform</h1>
    <h2>${selectedReport.title}</h2>
  </div>
  <div class="meta">
    <div class="meta-item"><span class="meta-label">Report ID</span><span class="meta-value">${selectedReport.id}</span></div>
    <div class="meta-item"><span class="meta-label">Date</span><span class="meta-value">${selectedReport.date}</span></div>
    <div class="meta-item"><span class="meta-label">Type</span><span class="meta-value">${selectedReport.type.replace('_', ' ')}</span></div>
    <div class="meta-item"><span class="meta-label">Severity</span><span class="meta-value"><span class="severity-badge">${selectedReport.severity}</span></span></div>
  </div>
  <div class="content">
    <div class="section">
      <div class="section-title">Incident Details</div>
      <div class="meta" style="padding: 16px 20px; background: #F1F4F2; border-radius: 8px; border: 1px solid #D4DEDC;">
        <div class="meta-item"><span class="meta-label">Camera / Location</span><span class="meta-value">${selectedReport.camera}</span></div>
        <div class="meta-item"><span class="meta-label">Analyst</span><span class="meta-value">${selectedReport.generatedBy}</span></div>
      </div>
    </div>
    <div class="section">
      <div class="section-title">Executive Summary</div>
      <p>${selectedReport.summary}</p>
    </div>
    <div class="section">
      <div class="section-title">Evidence Audit Trail</div>
      <ul class="evidence-list">
        ${selectedReport.evidence.map((e) => `<li><span class="evidence-icon">✓</span><span>${e}</span></li>`).join('\n        ')}
      </ul>
    </div>
    <div class="section">
      <div class="section-title">Analyst Notes</div>
      <div class="notes">${selectedReport.analystNotes}</div>
    </div>
  </div>
  <div class="footer">
    <div class="footer-left"><span></span> SHA-256 Verified · AES-256 Encrypted</div>
    <div>Generated by IBVAP · ${new Date().getFullYear()}</div>
  </div>
</div>
</body>
</html>`;
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${selectedReport.id}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">description</span>
            Surveillance Reports
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">Incident dossiers · Audit archive · Exportable reports</p>
        </div>
        {reportNotice && (
          <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
            <span className="material-symbols-outlined text-[14px]">check_circle</span> {reportNotice}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Report List */}
        <div className="lg:col-span-4 bg-surface border border-outline-variant rounded-xl flex flex-col">
          <div className="p-3 bg-surface-container-low border-b border-outline-variant flex items-center justify-between">
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Reports ({filteredReports.length})</span>
            <select value={reportTypeFilter} onChange={(e) => setReportTypeFilter(e.target.value)} className="bg-surface border border-outline-variant text-[10px] text-on-surface px-1.5 py-0.5 rounded outline-none cursor-pointer">
              <option value="ALL">ALL</option>
              <option value="DAILY_SURVEILLANCE">DAILY</option>
              <option value="INCIDENT_DOSSIER">INCIDENT</option>
              <option value="ANPR_TRAFFIC">ANPR</option>
            </select>
          </div>
          <div className="flex flex-col divide-y divide-outline-variant/40 overflow-y-auto max-h-[600px]">
            {filteredReports.map((rep) => (
              <button key={rep.id} onClick={() => setSelectedReport(rep)} className={`p-3 cursor-pointer transition-all text-left border-l-4 ${rep.id === selectedReport.id ? 'bg-primary/5 border-primary' : 'hover:bg-surface-container-low border-transparent'}`}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] text-primary font-bold">{rep.id}</span>
                  <span className="font-mono text-[9px] text-on-surface-variant">{rep.date.split(' ')[0]}</span>
                </div>
                <div className="text-[12px] font-bold text-on-surface mt-1">{rep.title}</div>
                <div className="text-[10px] text-on-surface-variant mt-0.5">{rep.camera}</div>
                <div className="flex items-center justify-between mt-1.5 pt-1 border-t border-outline-variant/30 text-[9px]">
                  <span className="text-primary font-bold">{rep.type.replace('_', ' ')}</span>
                  <span className="text-on-surface font-semibold">{rep.generatedBy}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Report Viewer */}
        <div className="lg:col-span-8 bg-surface border border-outline-variant rounded-xl p-5">
          <div className="border-b-2 border-primary pb-3 mb-4 flex items-start sm:items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-primary font-bold">{selectedReport.id}</span>
                <span className="text-[11px] text-on-surface-variant">· {selectedReport.date}</span>
              </div>
              <h2 className="text-[15px] font-bold text-on-surface mt-1">{selectedReport.title}</h2>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-bold px-2 py-0.5 border border-primary text-primary rounded">{selectedReport.type}</span>
              <span className={`text-[9px] font-bold px-2 py-0.5 border rounded ${selectedReport.severity === 'CRITICAL' ? 'border-error text-error bg-error-container' : 'border-warning text-warning bg-warning-container'}`}>
                {selectedReport.severity}
              </span>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 bg-surface-container-low p-3 border border-outline-variant rounded-lg mb-4 text-[11px]">
            <div><span className="text-on-surface-variant block text-[9px]">TARGET:</span><span className="text-on-surface font-bold">{selectedReport.camera}</span></div>
            <div><span className="text-on-surface-variant block text-[9px]">ANALYST:</span><span className="text-primary font-bold">{selectedReport.generatedBy}</span></div>
          </div>

          <div className="mb-4">
            <span className="text-[10px] font-bold text-primary uppercase block mb-1.5">Executive Summary</span>
            <p className="text-[12px] text-on-surface leading-relaxed bg-surface-container-low p-3 border border-outline-variant rounded-lg">{selectedReport.summary}</p>
          </div>

          <div className="mb-4">
            <span className="text-[10px] font-bold text-primary uppercase block mb-1.5">Evidence Audit Trail</span>
            <div className="space-y-1.5 bg-surface-container-low p-3 border border-outline-variant rounded-lg text-[11px] text-on-surface">
              {selectedReport.evidence.map((ev, i) => (
                <div key={i} className="flex items-start gap-2">
                  <span className="material-symbols-outlined text-success text-[14px] shrink-0 mt-0.5">check_circle</span>
                  <span>{ev}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="mb-4">
            <span className="text-[10px] font-bold text-primary uppercase block mb-1.5">Analyst Notes</span>
            <p className="text-[12px] text-on-surface-variant bg-surface-container-low p-3 border border-outline-variant rounded-lg leading-relaxed">{selectedReport.analystNotes}</p>
          </div>

          <div className="pt-4 border-t border-outline-variant flex items-center justify-between">
            <span className="text-[10px] text-on-surface-variant">SHA-256 VERIFIED</span>
            <button onClick={handleExport} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold flex items-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[14px]">download</span> DOWNLOAD REPORT
            </button>
          </div>
        </div>
      </div>

      {/* Generate Form */}
      <div className="bg-surface border border-outline-variant rounded-xl p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between border-b border-outline-variant pb-2">
          <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Generate New Report</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Title</label>
            <input type="text" value={newTitle} onChange={(e) => setNewTitle(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none" />
          </div>
          <div>
            <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Category</label>
            <select value={newType} onChange={(e) => setNewType(e.target.value as any)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none">
              <option value="INCIDENT_DOSSIER">Incident Dossier</option><option value="DAILY_SURVEILLANCE">Daily Surveillance</option><option value="ANPR_TRAFFIC">ANPR Traffic</option>
            </select>
          </div>
          <div>
            <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Camera</label>
            <input type="text" value={newCamera} onChange={(e) => setNewCamera(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none" />
          </div>
        </div>
        <div>
          <label className="block text-[9px] font-bold text-on-surface-variant mb-1 uppercase">Notes</label>
          <textarea rows={2} value={newNotes} onChange={(e) => setNewNotes(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant p-2 text-[11px] text-on-surface rounded-lg outline-none resize-none" />
        </div>
        <div className="flex justify-end">
          <button onClick={handleGenerate} className="px-4 py-2 bg-primary hover:bg-primary/90 text-on-primary rounded-lg text-[11px] font-bold flex items-center gap-1.5 cursor-pointer transition-colors">
            <span className="material-symbols-outlined text-[14px]">add_circle</span> GENERATE REPORT
          </button>
        </div>
      </div>
    </div>
  );
};
