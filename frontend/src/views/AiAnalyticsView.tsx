import React, { useState } from 'react';

export const AiAnalyticsView: React.FC = () => {
  const [viewMode, setViewMode] = useState<'OPERATOR' | 'ENGINEERING'>('OPERATOR');
  const [selectedPipelineStep, setSelectedPipelineStep] = useState<number>(1);
  const [confidenceThreshold, setConfidenceThreshold] = useState<number>(0.75);
  const [iouThreshold, setIouThreshold] = useState<number>(0.45);
  const [trackingBuffer, setTrackingBuffer] = useState<number>(30);
  const [ocrMinScore, setOcrMinScore] = useState<number>(0.85);

  const operatorPipeline = [
    { title: 'Video Ingestion', desc: 'RTSP multi-channel streaming', icon: 'videocam', status: '—' },
    { title: 'Object Detection', desc: 'YOLO neural model identifying targets', icon: 'neurology', status: '—' },
    { title: 'Object Tracking', desc: 'ByteTrack persistent target IDs', icon: 'route', status: '—' },
    { title: 'Spatial Analysis', desc: 'Virtual fence & tripwire checking', icon: 'fence', status: '—' },
    { title: 'Alert Generation', desc: 'Threat dispatch to console', icon: 'crisis_alert', status: '—' },
  ];

  const engineeringSteps = [
    { id: 0, title: 'RTSP INGESTION', framework: 'FFmpeg + OpenCV', throughput: '—', latency: '—', desc: 'Frame ingestion pipeline.' },
    { id: 1, title: 'YOLO DETECTION', framework: 'YOLOv8', throughput: '—', latency: '—', desc: 'Convolutional backbone with bounding box estimation.' },
    { id: 2, title: 'BYTETRACK', framework: 'Kalman + Hungarian', throughput: '—', latency: '—', desc: 'Persistent trajectory history and speed estimation.' },
    { id: 3, title: 'PADDLEOCR ANPR', framework: 'DBNet + CRNN', throughput: '—', latency: '—', desc: 'Plate crop, dewarping, character recognition.' },
    { id: 4, title: 'SPATIAL ENGINE', framework: 'Shapely Ray-Caster', throughput: '—', latency: '—', desc: 'Polygon containment and tripwire crossing.' },
  ];

  return (
    <div className="flex flex-col w-full p-4 md:p-6 gap-5 select-none max-w-7xl mx-auto">
      {/* Header */}
      <div className="bg-surface border border-outline-variant p-4 rounded-xl flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-on-surface tracking-tight flex items-center gap-2">
            <span className="material-symbols-outlined text-primary text-xl">neurology</span>
            AI Analytics &amp; Pipeline
          </h1>
          <p className="text-[12px] text-on-surface-variant mt-0.5">Computer Vision · YOLO · ByteTrack · EasyOCR</p>
        </div>
        <div className="flex items-center bg-surface-container-low border border-outline-variant rounded-lg p-1">
          <button onClick={() => setViewMode('OPERATOR')} className={`px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all cursor-pointer flex items-center gap-1.5 ${viewMode === 'OPERATOR' ? 'bg-primary text-on-primary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'}`}>
            <span className="material-symbols-outlined text-[14px]">visibility</span> OPERATOR
          </button>
          <button onClick={() => setViewMode('ENGINEERING')} className={`px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all cursor-pointer flex items-center gap-1.5 ${viewMode === 'ENGINEERING' ? 'bg-primary text-on-primary shadow-sm' : 'text-on-surface-variant hover:text-on-surface'}`}>
            <span className="material-symbols-outlined text-[14px]">terminal</span> ENGINEERING
          </button>
        </div>
      </div>

      {/* Operator View */}
      {viewMode === 'OPERATOR' && (
        <div className="flex flex-col gap-5">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {[
              { label: 'AI Engine', value: '—', color: 'text-on-surface-variant', icon: 'help' },
              { label: 'Detection', value: 'YOLO', color: 'text-on-surface', sub: 'Human · Vehicle' },
              { label: 'Tracking', value: 'ByteTrack', color: 'text-on-surface', sub: 'Active IDs' },
              { label: 'Avg Confidence', value: '—', color: 'text-on-surface-variant' },
              { label: 'Inference Latency', value: '—', color: 'text-on-surface-variant' },
            ].map((kpi, i) => (
              <div key={i} className="bg-surface border border-outline-variant p-3.5 rounded-xl">
                <span className="text-[10px] text-on-surface-variant font-medium">{kpi.label}</span>
                <div className={`text-lg font-bold mt-1 flex items-center gap-1.5 ${kpi.color}`}>
                  {kpi.icon && <span className="material-symbols-outlined text-[16px]">{kpi.icon}</span>}
                  {kpi.value}
                </div>
                {kpi.sub && <span className="text-[10px] text-primary font-medium">{kpi.sub}</span>}
              </div>
            ))}
          </div>

          {/* Pipeline */}
          <div className="bg-surface border border-outline-variant rounded-xl p-5">
            <div className="flex items-center justify-between border-b border-outline-variant pb-2 mb-4">
              <h2 className="text-[13px] font-bold text-on-surface tracking-wide">AI Inference Pipeline</h2>
              <span className="text-[10px] text-on-surface-variant font-semibold flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-on-surface-variant" /> NOT STARTED</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
              {operatorPipeline.map((step, idx) => (
                <div key={idx} className="bg-surface-container-low rounded-xl border border-outline-variant p-3.5">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-mono font-bold text-primary">0{idx + 1}</span>
                    <span className="material-symbols-outlined text-primary text-[18px]">{step.icon}</span>
                  </div>
                  <h3 className="text-[12px] font-bold text-on-surface">{step.title}</h3>
                  <p className="text-[10px] text-on-surface-variant mt-1 leading-relaxed">{step.desc}</p>
                  <div className="mt-2 pt-2 border-t border-outline-variant/40 flex items-center justify-between text-[9px]">
                    <span className="text-on-surface-variant">Status</span>
                    <span className="text-success font-bold">{step.status}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Capabilities */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {[
              { icon: 'person_search', title: 'Human Detection & Tracking', desc: 'Identifies people across borders with unique track IDs, speed, and direction vectors.' },
              { icon: 'directions_car', title: 'Vehicle & ANPR', desc: 'Classifies vehicles and reads plates via EasyOCR with temporal stabilization.' },
              { icon: 'fence', title: 'Virtual Fencing', desc: 'Tripwires, loitering dwell times, and restricted polygon boundaries in real time.' },
            ].map((cap, i) => (
              <div key={i} className="bg-surface border border-outline-variant rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="material-symbols-outlined text-primary">{cap.icon}</span>
                  <h3 className="text-[12px] font-bold text-on-surface">{cap.title}</h3>
                </div>
                <p className="text-[11px] text-on-surface-variant leading-relaxed">{cap.desc}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Engineering View */}
      {viewMode === 'ENGINEERING' && (
        <div className="flex flex-col gap-5">
          {/* Tech Stack */}
          <div className="bg-surface border border-outline-variant rounded-xl p-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-bold text-on-surface-variant mr-2">STACK:</span>
                    {['Python 3.12', 'PyTorch 2.14 CPU', 'YOLOv8n', 'ByteTrack', 'EasyOCR', 'OpenCV'].map((pill) => (
              <span key={pill} className="px-2 py-0.5 rounded-lg border border-outline-variant text-[10px] font-mono font-bold text-on-surface bg-surface-container-low">{pill}</span>
            ))}
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
            {/* Pipeline Stages */}
            <div className="lg:col-span-7 bg-surface border border-outline-variant rounded-xl p-5">
              <h2 className="text-[13px] font-bold text-on-surface tracking-wide mb-4 border-b border-outline-variant pb-3">Pipeline Stage Inspection</h2>
              <div className="space-y-2 mb-4">
                {engineeringSteps.map((step, idx) => (
                  <button key={step.id} onClick={() => setSelectedPipelineStep(idx)} className={`w-full p-3 rounded-lg border transition-all cursor-pointer text-left flex items-center justify-between ${selectedPipelineStep === idx ? 'bg-primary/10 border-primary' : 'bg-surface-container-low hover:bg-surface-container-high border-outline-variant'}`}>
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-[11px] font-bold text-primary">0{idx + 1}</span>
                      <div>
                        <div className="text-[11px] font-bold text-on-surface">{step.title}</div>
                        <div className="text-[10px] text-on-surface-variant font-mono">{step.framework}</div>
                      </div>
                    </div>
                    <span className="font-mono text-[11px] text-primary font-bold">{step.latency}</span>
                  </button>
                ))}
              </div>
              <div className="p-3 bg-surface-container-low rounded-lg border border-outline-variant text-[11px]">
                <span className="text-primary font-bold block mb-1">Architecture:</span>
                <p className="text-on-surface leading-relaxed">{engineeringSteps[selectedPipelineStep].desc}</p>
              </div>
            </div>

            {/* Tuning Sliders */}
            <div className="lg:col-span-5 bg-surface border border-outline-variant rounded-xl p-5">
              <h2 className="text-[13px] font-bold text-on-surface tracking-wide mb-4 border-b border-outline-variant pb-3">Hyperparameter Tuning</h2>
              <div className="space-y-4 text-[11px]">
                {[
                  { label: 'Confidence Threshold', value: confidenceThreshold, set: setConfidenceThreshold, min: 0.3, max: 0.95, step: 0.05 },
                  { label: 'NMS IoU Threshold', value: iouThreshold, set: setIouThreshold, min: 0.2, max: 0.8, step: 0.05 },
                  { label: 'ByteTrack Buffer', value: trackingBuffer, set: (v: number) => setTrackingBuffer(v), min: 10, max: 90, step: 5 },
                   { label: 'OCR Min Score', value: ocrMinScore, set: setOcrMinScore, min: 0.6, max: 0.95, step: 0.05 },
                ].map((slider, i) => (
                  <div key={i}>
                    <div className="flex justify-between mb-1">
                      <span className="text-on-surface font-medium">{slider.label}</span>
                      <span className="font-mono text-primary font-bold">{typeof slider.value === 'number' && slider.value < 1 ? slider.value.toFixed(2) : slider.value}{slider.label.includes('Buffer') ? ' Frames' : ''}</span>
                    </div>
                    <input type="range" min={slider.min} max={slider.max} step={slider.step} value={slider.value} onChange={(e) => slider.set(parseFloat(e.target.value))} className="w-full accent-primary" />
                  </div>
                ))}
              </div>
              <div className="p-3 bg-surface-container-low rounded-lg border border-outline-variant mt-4 text-[10px] text-on-surface-variant flex items-center justify-between">
                <span>GPU: No data</span>
                <span className="text-on-surface-variant">Status unknown</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
