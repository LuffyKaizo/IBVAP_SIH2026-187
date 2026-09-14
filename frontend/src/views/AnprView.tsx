import React, { useState } from 'react';
import { AnprRecord } from '../types';

interface AnprViewProps {
  records: AnprRecord[];
  onAddRecord?: (record: AnprRecord) => void;
}

export const AnprView: React.FC<AnprViewProps> = ({ records, onAddRecord }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'WHITELIST' | 'WATCHLIST' | 'UNREGISTERED'>('ALL');
  const [selectedRecord, setSelectedRecord] = useState<AnprRecord | null>(
    records.length > 0 ? records[0] : null
  );
  const [simPlate, setSimPlate] = useState('');
  const [simType, setSimType] = useState<'SUV' | 'Sedan' | 'Truck' | 'Motorcycle' | 'Pickup'>('SUV');
  const [simCamera, setSimCamera] = useState('CAM-03');
  const [scanNotice, setScanNotice] = useState<string | null>(null);

  const filteredRecords = records.filter((rec) => {
    if (statusFilter !== 'ALL' && rec.status !== statusFilter) return false;
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      return rec.plateNumber.toLowerCase().includes(q) || rec.vehicleType.toLowerCase().includes(q) || rec.cameraId.toLowerCase().includes(q);
    }
    return true;
  });

  // Empty state — no ANPR records yet
  if (!selectedRecord) {
    return (
      <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
        <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
              <span className="material-symbols-outlined text-primary text-xl">directions_car</span>
              ANPR &amp; Vehicle Intelligence
            </h1>
            <p className="text-[12px] text-on-surface-variant mt-0.5">Automatic Number Plate Recognition · Watchlist Verification</p>
          </div>
        </div>
        <div className="bg-surface border border-outline-variant rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-[48px] text-on-surface-variant/40 block mb-3">directions_car</span>
          <p className="text-on-surface-variant text-sm">No ANPR records yet</p>
          <p className="text-on-surface-variant/60 text-[11px] mt-1">Vehicle plate detections will appear here once the AI pipeline detects them</p>
        </div>
      </div>
    );
  }

  const handleSimulateScan = () => {
    if (!simPlate.trim()) {
      setScanNotice('Enter a plate number');
      setTimeout(() => setScanNotice(null), 3000);
      return;
    }
    const newRec: AnprRecord = {
      id: `ANPR-${Date.now()}`,
      timestamp: new Date().toISOString().substring(11, 19) + ' UTC',
      plateNumber: simPlate.toUpperCase().trim(),
      vehicleType: simType,
      confidence: 0,
      cameraId: simCamera,
      cameraName: simCamera,
      status: 'UNREGISTERED',
      direction: 'Restricted Zone',
    };
    onAddRecord?.(newRec);
    setSelectedRecord(newRec);
    setScanNotice(`Plate captured: ${newRec.plateNumber} (UNREGISTERED — needs backend classification)`);
    setTimeout(() => setScanNotice(null), 3500);
  };

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">directions_car</span>
            ANPR &amp; Vehicle Intelligence
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">Automatic Number Plate Recognition · Watchlist Verification</p>
        </div>
        {scanNotice && (
          <div className="px-3 py-1 bg-success-container border border-success/20 text-success text-[11px] font-semibold flex items-center gap-1.5 rounded-lg">
            <span className="material-symbols-outlined text-[14px]">check_circle</span> {scanNotice}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* Left: Vehicle Inspector */}
        <div className="lg:col-span-7 bg-surface border border-outline-variant rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-outline-variant pb-3 mb-4">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Vehicle Inspector · {selectedRecord.id}</span>
              <span className={`text-[9px] font-bold px-2.5 py-0.5 rounded ${selectedRecord.status === 'WATCHLIST' ? 'bg-error text-on-error' : selectedRecord.status === 'WHITELIST' ? 'bg-success text-on-success' : 'bg-surface-container-high text-on-surface-variant'}`}>
                {selectedRecord.status}
              </span>
            </div>

            <div className="relative w-full aspect-[21/9] bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant mb-4 select-none">
              <img src={selectedRecord.snapshotUrl || ''} alt="Vehicle" className="w-full h-full object-cover opacity-90" />
              <div className="absolute left-[30%] top-[25%] w-[42%] h-[60%] border-2 border-tertiary bg-tertiary/10">
                <span className="absolute -top-[18px] left-0 bg-tertiary text-on-tertiary px-1.5 py-[2px] text-[8px] font-mono font-bold rounded">{selectedRecord.vehicleType} (YOLO: {Math.round(selectedRecord.confidence * 100)}%)</span>
              </div>
              <div className="absolute left-[44%] top-[62%] w-[16%] h-[16%] border-2 border-success bg-success/10">
                <span className="absolute -bottom-[18px] left-0 bg-success text-on-success px-1 py-[2px] text-[8px] font-mono font-bold rounded">OCR CROP</span>
              </div>
            </div>

            {/* Plate Display */}
            <div className="bg-surface-container-low rounded-xl p-4 border border-outline-variant flex flex-col sm:flex-row items-center justify-between gap-3">
              <div>
                <span className="text-[10px] text-on-surface-variant uppercase tracking-wider block">License Plate</span>
                <div className="flex items-center gap-2 flex-wrap mt-1">
                  <div className="font-mono text-2xl tracking-[0.15em] text-primary font-bold bg-primary-container px-4 py-1.5 rounded-lg border border-primary/20 inline-block">
                    {selectedRecord.plateNumber}
                  </div>
                  {selectedRecord.ai && (
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${selectedRecord.corrected ? 'bg-tertiary-container text-tertiary' : 'bg-surface-container-high text-on-surface-variant'}`}>
                      {selectedRecord.corrected ? 'AI·CORR' : 'AI'}
                    </span>
                  )}
                </div>
                {selectedRecord.corrected && selectedRecord.rawPlateText && (
                  <div className="text-[10px] text-on-surface-variant mt-1 flex items-center gap-1">
                    <span className="material-symbols-outlined text-[12px] text-tertiary">auto_fix</span>
                    corrected from raw OCR <span className="font-mono text-tertiary">{selectedRecord.rawPlateText}</span>
                  </div>
                )}
              </div>
              <div className="flex flex-col items-end text-[11px] space-y-1">
                <span className="text-on-surface-variant">Confidence: <strong className="text-success font-mono">{selectedRecord.confidence}%</strong></span>
                <span className="text-on-surface-variant">Vehicle: <strong className="text-on-surface">{selectedRecord.vehicleType}</strong></span>
                <span className="text-on-surface-variant">Camera: <strong className="text-on-surface">{selectedRecord.cameraId}</strong></span>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Scanner Simulator */}
        <div className="lg:col-span-5 bg-surface border border-outline-variant rounded-xl p-5 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-outline-variant pb-3 mb-3">
              <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">ANPR Test Scanner</span>
              <span className="text-[10px] text-primary font-mono font-semibold">TEST BENCH</span>
            </div>
            <p className="text-[11px] text-on-surface-variant mb-4 leading-relaxed">Test incoming vehicles to trigger OCR and watchlist verification.</p>
            <div className="space-y-3 text-[11px]">
              <div>
                <label className="block text-on-surface-variant font-medium mb-1">LICENSE PLATE</label>
                <input type="text" value={simPlate} onChange={(e) => setSimPlate(e.target.value.toUpperCase())} placeholder="Enter plate number"
                  className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 font-mono text-sm text-primary font-bold focus:border-primary outline-none" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-on-surface-variant font-medium mb-1">VEHICLE TYPE</label>
                  <select value={simType} onChange={(e) => setSimType(e.target.value as any)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none cursor-pointer">
                    <option value="SUV">SUV</option><option value="Sedan">Sedan</option><option value="Truck">Truck</option><option value="Pickup">Pickup</option><option value="Motorcycle">Motorcycle</option>
                  </select>
                </div>
                <div>
                  <label className="block text-on-surface-variant font-medium mb-1">CAMERA</label>
                  <select value={simCamera} onChange={(e) => setSimCamera(e.target.value)} className="w-full bg-surface-container-low border border-outline-variant rounded-lg p-2.5 text-on-surface outline-none cursor-pointer">
                    <option value="CAM-03">CAM-03</option><option value="CAM-01">CAM-01</option><option value="CAM-02">CAM-02</option>
                  </select>
                </div>
              </div>
            </div>
          </div>
          <div className="pt-4 border-t border-outline-variant mt-4">
            <button onClick={handleSimulateScan} className="w-full py-2.5 bg-primary hover:bg-primary/90 text-on-primary rounded-xl text-[11px] font-bold flex items-center justify-center gap-2 cursor-pointer transition-colors">
              <span className="material-symbols-outlined text-[16px]">scan</span> TRIGGER OCR SCAN
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-surface border border-outline-variant rounded-xl p-4 flex flex-col gap-3">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 border-b border-outline-variant pb-3">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-[18px]">table_chart</span>
            <span className="text-[11px] font-bold text-on-surface tracking-wide uppercase">Plate Events ({filteredRecords.length})</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 bg-surface-container-low border border-outline-variant rounded-lg px-2.5 py-1 text-[11px]">
              <span className="material-symbols-outlined text-[14px] text-on-surface-variant">search</span>
              <input type="text" value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} placeholder="Search plate..." className="bg-transparent border-none outline-none text-on-surface placeholder-on-surface-variant/50 w-28" />
            </div>
            {(['ALL', 'WHITELIST', 'WATCHLIST'] as const).map((st) => (
              <button key={st} onClick={() => setStatusFilter(st)} className={`px-2.5 py-1 rounded-lg text-[10px] font-semibold cursor-pointer transition-colors ${statusFilter === st ? 'bg-primary text-on-primary' : 'bg-surface-container-low border border-outline-variant text-on-surface-variant hover:text-on-surface'}`}>
                {st}
              </button>
            ))}
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-[11px] border-collapse">
            <thead>
              <tr className="border-b border-outline-variant/60 text-on-surface-variant font-medium">
                <th className="py-2 px-3">TIMESTAMP</th><th className="py-2 px-3">PLATE</th><th className="py-2 px-3">VEHICLE</th><th className="py-2 px-3">CAMERA</th><th className="py-2 px-3">CONFIDENCE</th><th className="py-2 px-3">STATUS</th><th className="py-2 px-3 text-right">ACTION</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant/30">
              {filteredRecords.map((rec) => (
                <tr key={rec.id} onClick={() => setSelectedRecord(rec)} className={`cursor-pointer transition-colors ${rec.id === selectedRecord.id ? 'bg-primary/5' : 'hover:bg-surface-container-low'}`}>
                  <td className="py-2 px-3 font-mono text-on-surface-variant">{rec.timestamp}</td>
                  <td className="py-2 px-3">
                    <span className="font-mono font-bold text-primary">{rec.plateNumber}</span>
                    {rec.ai && (
                      <span title={rec.corrected && rec.rawPlateText ? `raw OCR: ${rec.rawPlateText}` : 'AI source'} className={`ml-1.5 px-1.5 py-0.5 rounded text-[8px] font-bold align-middle ${rec.corrected ? 'bg-tertiary-container text-tertiary' : 'bg-surface-container-high text-on-surface-variant'}`}>
                        {rec.corrected ? 'AI·CORR' : 'AI'}
                      </span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-on-surface">{rec.vehicleType}</td>
                  <td className="py-2 px-3 text-on-surface-variant">{rec.cameraId}</td>
                  <td className="py-2 px-3 font-mono font-bold text-success">{rec.confidence}%</td>
                  <td className="py-2 px-3">
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${rec.status === 'WATCHLIST' ? 'bg-error-container text-on-error-container' : 'bg-success-container text-success'}`}>
                      {rec.status}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-right"><button onClick={(e) => { e.stopPropagation(); setSelectedRecord(rec); }} className="text-primary hover:underline font-semibold">Inspect</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
