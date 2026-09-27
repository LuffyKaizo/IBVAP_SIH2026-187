import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export interface EvidenceArtifactRow {
  id: string;
  evidenceType?: string;
  sha256Hash?: string;
  integrityStatus?: string;
  fileSize?: number;
  timestamp?: string | null;
  mimeType?: string;
  metadata?: Record<string, unknown> | null;
}

export interface EvidenceSlot {
  row: EvidenceArtifactRow | null;
  url: string;
}

export interface EvidenceSetState {
  state: 'LOADING' | 'READY' | 'UNAVAILABLE';
  original?: EvidenceSlot;
  annotated?: EvidenceSlot;
  target?: EvidenceSlot;
}

type Mode = 'ORIGINAL' | 'TARGET' | 'ANNOTATED' | 'PERSPECTIVE';

interface EvidenceViewerProps {
  set: EvidenceSetState;
  bbox?: { x1: number; y1: number; x2: number; y2: number };
  frameWidth?: number;
  frameHeight?: number;
  cameraName: string;
  timestamp: string;
}

const MODE_LABEL: Record<Mode, string> = {
  ORIGINAL: 'ORIGINAL SCENE',
  TARGET: 'TARGET CROP',
  ANNOTATED: 'ANNOTATED FRAME',
  PERSPECTIVE: 'PERSPECTIVE 3D',
};

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Evidence dossier viewer: renders the 3-artifact evidence set
 * (original / target crop / annotated frame) with object-fit: contain so
 * aspect ratio is never distorted, plus a perspective/isometric mode,
 * source-frame bbox overlay, zoom/pan/rotate/tilt controls and a
 * per-artifact chain-of-custody metadata panel. */
export const EvidenceViewer: React.FC<EvidenceViewerProps> = ({
  set,
  bbox,
  frameWidth,
  frameHeight,
  cameraName,
  timestamp,
}) => {
  const [mode, setMode] = useState<Mode>('ORIGINAL');
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [rotate, setRotate] = useState(0);
  const [tilt, setTilt] = useState(48);
  const [showBBox, setShowBBox] = useState(true);
  const [showMeta, setShowMeta] = useState(false);
  const dragRef = useRef<{ x: number; y: number; px: number; py: number } | null>(null);

  const slotFor = useCallback(
    (m: Mode): EvidenceSlot | undefined => {
      if (m === 'ORIGINAL') return set.original;
      if (m === 'TARGET') return set.target;
      if (m === 'ANNOTATED') return set.annotated;
      // Perspective renders the original scene (falls back to annotated).
      return set.original || set.annotated;
    },
    [set],
  );

  const availableModes = useMemo<Mode[]>(() => {
    const modes: Mode[] = [];
    if (set.original) modes.push('ORIGINAL');
    if (set.target) modes.push('TARGET');
    if (set.annotated) modes.push('ANNOTATED');
    if (set.original || set.annotated) modes.push('PERSPECTIVE');
    return modes;
  }, [set]);

  // Reset view state whenever the selected incident changes.
  useEffect(() => {
    const modes: Mode[] = [];
    if (set.original) modes.push('ORIGINAL');
    else if (set.target) modes.push('TARGET');
    else if (set.annotated) modes.push('ANNOTATED');
    if (modes.length > 0 && !modes.includes(mode) && mode !== 'PERSPECTIVE') {
      setMode(modes[0]);
    }
    if (set.state !== 'READY') setMode('ORIGINAL');
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setRotate(0);
    setTilt(48);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set.state, set.original?.url, set.target?.url, set.annotated?.url]);

  const activeSlot = slotFor(mode);
  const activeRow = activeSlot?.row ?? null;

  const resetView = () => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setRotate(0);
    setTilt(48);
  };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    setZoom((z) => clamp(z * factor, 1, 8));
  };

  const handlePointerDown = (e: React.PointerEvent) => {
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
  };
  const handlePointerMove = (e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d) return;
    setPan({ x: d.px + (e.clientX - d.x), y: d.py + (e.clientY - d.y) });
  };
  const handlePointerUp = () => {
    dragRef.current = null;
  };

  /** Bbox overlay as % of the displayed image (source-frame pixels only,
   * never normalized). On the target crop the stored frame-pixel bbox is
   * rebased onto the crop via the crop_rect kept in evidence metadata. */
  const overlayBox = useMemo(() => {
    if (!showBBox || !bbox || mode === 'ANNOTATED') return null;
    if (mode === 'ORIGINAL' || mode === 'PERSPECTIVE') {
      if (!frameWidth || !frameHeight) return null;
      return {
        left: (bbox.x1 / frameWidth) * 100,
        top: (bbox.y1 / frameHeight) * 100,
        width: ((bbox.x2 - bbox.x1) / frameWidth) * 100,
        height: ((bbox.y2 - bbox.y1) / frameHeight) * 100,
      };
    }
    if (mode === 'TARGET') {
      const rect = activeRow?.metadata?.crop_rect;
      if (!Array.isArray(rect) || rect.length !== 4) return null;
      const [rx1, ry1, rx2, ry2] = rect as number[];
      const cw = rx2 - rx1;
      const ch = ry2 - ry1;
      if (cw <= 0 || ch <= 0) return null;
      const left = clamp(((bbox.x1 - rx1) / cw) * 100, 0, 100);
      const top = clamp(((bbox.y1 - ry1) / ch) * 100, 0, 100);
      const right = clamp(((bbox.x2 - rx1) / cw) * 100, 0, 100);
      const bottom = clamp(((bbox.y2 - ry1) / ch) * 100, 0, 100);
      if (right <= left || bottom <= top) return null;
      return { left, top, width: right - left, height: bottom - top };
    }
    return null;
  }, [showBBox, bbox, mode, frameWidth, frameHeight, activeRow]);

  if (set.state === 'LOADING') {
    return (
      <div className="relative w-full aspect-video bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant mb-4 select-none">
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-on-surface-variant">
          <span className="material-symbols-outlined text-[28px] animate-spin">progress_activity</span>
          <span className="text-[11px]">Loading evidence set…</span>
        </div>
      </div>
    );
  }

  if (set.state === 'UNAVAILABLE' || !activeSlot) {
    return (
      <div className="relative w-full aspect-video bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant mb-4 select-none">
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 text-on-surface-variant px-4 text-center">
          <span className="material-symbols-outlined text-[32px] opacity-60">image_not_supported</span>
          <span className="text-[11px] font-bold uppercase tracking-wider">No evidence snapshot captured</span>
          <span className="text-[10px] font-mono">{cameraName} · {timestamp}</span>
        </div>
      </div>
    );
  }

  const isPerspective = mode === 'PERSPECTIVE';
  const transform = [
    `translate(${pan.x}px, ${pan.y}px)`,
    `scale(${zoom})`,
    isPerspective ? `rotateX(${tilt}deg) rotateZ(${rotate}deg)` : `rotate(${rotate}deg)`,
  ].join(' ');

  const meta = activeRow?.metadata || {};

  return (
    <div className="relative w-full aspect-video bg-surface-container-low rounded-lg overflow-hidden border border-outline-variant mb-4 select-none">
      {/* Toolbar */}
      <div className="absolute top-0 left-0 right-0 z-20 flex items-center justify-between gap-2 px-2 py-1.5 bg-on-surface/85 backdrop-blur-sm">
        <div className="flex items-center gap-1 overflow-x-auto">
          {availableModes.map((m) => (
            <button
              key={m}
              onClick={() => { setMode(m); resetView(); }}
              data-testid={`evidence-mode-${m}`}
              className={`px-2 py-1 rounded text-[9px] font-bold tracking-wide whitespace-nowrap cursor-pointer transition-colors ${
                mode === m ? 'bg-primary text-on-primary' : 'text-surface/80 hover:text-surface'
              }`}
            >
              {m === 'PERSPECTIVE' ? 'PERSPECTIVE' : m === 'ORIGINAL' ? 'ORIGINAL' : m === 'TARGET' ? 'TARGET' : 'ANNOTATED'}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={() => setZoom((z) => clamp(z / 1.15, 1, 8))}
            title="Zoom out"
            className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
          >
            <span className="material-symbols-outlined text-[15px]">zoom_out</span>
          </button>
          <span className="text-[9px] font-mono text-surface/80 w-9 text-center">{Math.round(zoom * 100)}%</span>
          <button
            onClick={() => setZoom((z) => clamp(z * 1.15, 1, 8))}
            title="Zoom in"
            className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
          >
            <span className="material-symbols-outlined text-[15px]">zoom_in</span>
          </button>
          {isPerspective && (
            <>
              <button
                onClick={() => setRotate((r) => r - 15)}
                title="Rotate left"
                className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[15px]">rotate_left</span>
              </button>
              <button
                onClick={() => setRotate((r) => r + 15)}
                title="Rotate right"
                className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[15px]">rotate_right</span>
              </button>
              <button
                onClick={() => setTilt((t) => clamp(t - 10, 0, 85))}
                title="Tilt down"
                className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[15px]">expand</span>
              </button>
              <button
                onClick={() => setTilt((t) => clamp(t + 10, 0, 85))}
                title="Tilt up"
                className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[15px]">compress</span>
              </button>
            </>
          )}
          <button
            onClick={() => setShowBBox((v) => !v)}
            title="Toggle target box"
            aria-pressed={showBBox}
            data-testid="evidence-bbox-toggle"
            className={`p-1 rounded cursor-pointer ${showBBox ? 'text-error' : 'text-surface/60 hover:text-surface'}`}
          >
            <span className="material-symbols-outlined text-[15px]">object_track</span>
          </button>
          <button
            onClick={() => setShowMeta((v) => !v)}
            title="Toggle metadata"
            aria-pressed={showMeta}
            data-testid="evidence-meta-toggle"
            className={`p-1 rounded cursor-pointer ${showMeta ? 'text-primary' : 'text-surface/60 hover:text-surface'}`}
          >
            <span className="material-symbols-outlined text-[15px]">info</span>
          </button>
          <button
            onClick={resetView}
            title="Reset view"
            className="p-1 rounded text-surface/80 hover:text-surface hover:bg-surface/20 cursor-pointer"
          >
            <span className="material-symbols-outlined text-[15px]">restart_alt</span>
          </button>
        </div>
      </div>

      {/* Image stage */}
      <div
        className="absolute inset-0 flex items-center justify-center pt-7 pb-6 px-2 overflow-hidden"
        style={isPerspective ? { perspective: '1400px' } : undefined}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        onDoubleClick={resetView}
        data-testid="evidence-stage"
      >
        <div
          className="relative max-w-full max-h-full"
          style={{ transform, transformStyle: 'preserve-3d', transition: dragRef.current ? 'none' : 'transform 120ms ease-out' }}
        >
          <img
            src={activeSlot.url}
            alt={MODE_LABEL[mode]}
            data-testid="evidence-image"
            draggable={false}
            className="block max-w-full max-h-[calc(100vh-2rem)] object-contain select-none"
            style={{ maxHeight: '100%' }}
          />
          {overlayBox && (
            <div
              data-testid="evidence-bbox-overlay"
              className="absolute border-2 border-error pointer-events-none"
              style={{
                left: `${overlayBox.left}%`,
                top: `${overlayBox.top}%`,
                width: `${overlayBox.width}%`,
                height: `${overlayBox.height}%`,
                boxShadow: '0 0 0 1px rgba(0,0,0,0.45)',
              }}
            />
          )}
        </div>
      </div>

      {/* Badges */}
      <div className="absolute bottom-2 left-2 z-10 flex items-center gap-1.5 pointer-events-none">
        <span
          className={`px-2 py-0.5 rounded text-[9px] font-mono font-bold ${
            mode === 'TARGET' ? 'bg-error text-on-error' : 'bg-on-surface/80 text-surface'
          }`}
          data-testid="evidence-mode-badge"
        >
          {MODE_LABEL[mode]}
        </span>
        <span className="bg-on-surface/80 px-2 py-0.5 rounded text-[10px] text-surface font-mono">
          {cameraName} · {timestamp}
        </span>
      </div>

      {/* Chain-of-custody metadata panel */}
      {showMeta && (
        <div
          className="absolute top-7 right-0 bottom-6 z-10 w-56 bg-surface/95 border-l border-t border-outline-variant overflow-y-auto p-2.5 flex flex-col gap-1.5"
          data-testid="evidence-meta-panel"
        >
          <span className="text-[9px] font-bold text-primary uppercase tracking-wider">
            Chain of Custody
          </span>
          <MetaRow label="Artifact" value={activeRow?.evidenceType || MODE_LABEL[mode]} />
          <MetaRow label="Evidence ID" value={activeRow?.id || '—'} />
          <MetaRow
            label="Integrity"
            value={activeRow?.integrityStatus || '—'}
            highlight={activeRow?.integrityStatus === 'VALID'}
          />
          <MetaRow label="SHA-256" value={activeRow?.sha256Hash || '—'} mono wrap />
          <MetaRow
            label="File Size"
            value={activeRow?.fileSize ? `${(activeRow.fileSize / 1024).toFixed(1)} KB` : '—'}
          />
          <MetaRow label="Captured" value={activeRow?.timestamp || timestamp} />
          <MetaRow
            label="Frame"
            value={
              (meta.frame_width && meta.frame_height)
                ? `${meta.frame_width} × ${meta.frame_height}`
                : (frameWidth && frameHeight) ? `${frameWidth} × ${frameHeight}` : '—'
            }
          />
          <MetaRow
            label="Target BBox"
            value={
              bbox ? `${bbox.x1}, ${bbox.y1} → ${bbox.x2}, ${bbox.y2}` : '—'
            }
            mono
          />
          <MetaRow
            label="Crop Rect"
            value={
              Array.isArray(meta.crop_rect) ? (meta.crop_rect as number[]).join(', ') : '—'
            }
            mono
          />
          <MetaRow
            label="FPS (src/proc)"
            value={
              (meta.source_fps !== undefined || meta.processing_fps !== undefined)
                ? `${meta.source_fps ?? '—'} / ${meta.processing_fps ?? '—'}`
                : '—'
            }
          />
          <MetaRow label="Object" value={(meta.object_class as string) || '—'} />
          <MetaRow
            label="Confidence"
            value={meta.confidence !== undefined ? `${Math.round((meta.confidence as number) * 100)}%` : '—'}
          />
        </div>
      )}
    </div>
  );
};

const MetaRow: React.FC<{ label: string; value: string; mono?: boolean; wrap?: boolean; highlight?: boolean }> = ({
  label,
  value,
  mono,
  wrap,
  highlight,
}) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-[8px] font-semibold text-on-surface-variant uppercase tracking-wider">{label}</span>
    <span
      className={`text-[10px] leading-snug ${mono ? 'font-mono' : 'font-semibold'} ${
        highlight ? 'text-success' : 'text-on-surface'
      } ${wrap ? 'break-all' : 'truncate'}`}
    >
      {value}
    </span>
  </div>
);

export default EvidenceViewer;
