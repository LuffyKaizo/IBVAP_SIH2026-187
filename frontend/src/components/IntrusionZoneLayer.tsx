import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { VirtualZone } from '../types';

export interface ZonePoint { x: number; y: number } // normalized 0-1 frame coords

export interface ZoneEditorState {
  mode: 'create' | 'edit';
  zoneId: string | null;
  name: string;
  points: ZonePoint[];
  isActive: boolean;
}

interface UseIntrusionZoneOptions {
  cameraId: string;
  zones: VirtualZone[];
  onSaveZone: (zone: VirtualZone) => void;
  onDeleteZone: (id: string) => void;
}

export interface IntrusionZoneController {
  cameraZones: VirtualZone[];
  selectedZoneId: string | null;
  editing: ZoneEditorState | null;
  menuPos: { x: number; y: number } | null;
  error: string | null;
  openMenu: (e: React.MouseEvent) => void;
  closeMenu: () => void;
  startCreate: () => void;
  startEdit: (zoneId: string) => void;
  toggleEnabled: (zoneId: string) => void;
  removeZone: (zoneId: string) => void;
  selectZone: (zoneId: string) => void;
  setEditing: React.Dispatch<React.SetStateAction<ZoneEditorState | null>>;
  addPoint: (p: ZonePoint) => void;
  movePoint: (idx: number, p: ZonePoint) => void;
  removePoint: (idx: number) => void;
  insertEdgePoint: (afterIdx: number) => void;
  renameEditing: (name: string) => void;
  saveEditing: () => void;
  cancelEditing: () => void;
}

const colorForSeverity = (sev: string): string =>
  sev === 'CRITICAL' ? '#ef4444' : sev === 'HIGH' ? '#f97316' : '#eab308';

const generateZoneId = (existing: VirtualZone[]): string => {
  for (let attempt = 0; attempt < 8; attempt++) {
    const rnd = crypto.getRandomValues(new Uint8Array(3));
    const hex = Array.from(rnd).map((b) => b.toString(16).padStart(2, '0')).join('');
    const id = `ZONE-${hex.toUpperCase()}`;
    if (!existing.some((z) => z.id === id)) return id;
  }
  return `ZONE-${Date.now().toString(36).toUpperCase()}`;
};

export function useIntrusionZoneController(opts: UseIntrusionZoneOptions): IntrusionZoneController {
  const { cameraId, zones, onSaveZone, onDeleteZone } = opts;
  const [editing, setEditing] = useState<ZoneEditorState | null>(null);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cameraZones = zones.filter((z) => z.cameraId === cameraId);

  const openMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setEditing(null);
    setError(null);
    if (cameraZones.length === 0) {
      // No zone yet: context/left click on control enters create mode directly
      setMenuPos(null);
      setSelectedZoneId(null);
      setEditing({
        mode: 'create', zoneId: null, name: `ZONE ${cameraId} 1`,
        points: [], isActive: true,
      });
      return;
    }
    const x = Math.min(e.clientX, window.innerWidth - 230);
    const y = Math.min(e.clientY, window.innerHeight - 300);
    setMenuPos({ x: Math.max(8, x), y: Math.max(8, y) });
  }, [cameraId, cameraZones.length]);

  const closeMenu = useCallback(() => setMenuPos(null), []);

  const startCreate = useCallback(() => {
    setMenuPos(null);
    setError(null);
    setEditing({
      mode: 'create', zoneId: null, name: `ZONE ${cameraId} ${cameraZones.length + 1}`,
      points: [], isActive: true,
    });
  }, [cameraId, cameraZones.length]);

  const startEdit = useCallback((zoneId: string) => {
    const zone = zones.find((z) => z.id === zoneId && z.cameraId === cameraId);
    if (!zone) return;
    setMenuPos(null);
    setError(null);
    setSelectedZoneId(zoneId);
    setEditing({
      mode: 'edit',
      zoneId: zone.id,
      name: zone.name,
      points: zone.coordinates.map((c) => ({ x: c.x / 100, y: c.y / 100 })),
      isActive: zone.isActive,
    });
  }, [zones, cameraId]);

  const toggleEnabled = useCallback((zoneId: string) => {
    const zone = zones.find((z) => z.id === zoneId && z.cameraId === cameraId);
    if (!zone) return;
    setMenuPos(null);
    setEditing(null);
    onSaveZone({ ...zone, isActive: !zone.isActive });
  }, [zones, cameraId, onSaveZone]);

  const removeZone = useCallback((zoneId: string) => {
    const zone = zones.find((z) => z.id === zoneId);
    if (!zone) return;
    const ok = window.confirm(`Delete zone "${zone.name}" on ${zone.cameraId}? This cannot be undone.`);
    if (!ok) return;
    setMenuPos(null);
    setEditing((prev) => (prev && prev.zoneId === zoneId ? null : prev));
    setSelectedZoneId((prev) => (prev === zoneId ? null : prev));
    onDeleteZone(zoneId);
  }, [zones, onDeleteZone]);

  const selectZone = useCallback((zoneId: string) => {
    setSelectedZoneId(zoneId);
  }, []);

  const addPoint = useCallback((p: ZonePoint) => {
    setEditing((prev) => (prev ? { ...prev, points: [...prev.points, p] } : prev));
  }, []);

  const movePoint = useCallback((idx: number, p: ZonePoint) => {
    setEditing((prev) => {
      if (!prev || idx < 0 || idx >= prev.points.length) return prev;
      const points = [...prev.points];
      points[idx] = p;
      return { ...prev, points };
    });
  }, []);

  const removePoint = useCallback((idx: number) => {
    setEditing((prev) => {
      if (!prev || prev.points.length <= 3) return prev;
      const points = prev.points.filter((_, i) => i !== idx);
      return { ...prev, points };
    });
  }, []);

  const insertEdgePoint = useCallback((afterIdx: number) => {
    setEditing((prev) => {
      if (!prev || prev.points.length < 3) return prev;
      const nextIdx = (afterIdx + 1) % prev.points.length;
      const a = prev.points[afterIdx];
      const b = prev.points[nextIdx];
      const mid: ZonePoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const points = [...prev.points];
      points.splice(afterIdx + 1, 0, mid);
      return { ...prev, points };
    });
  }, []);

  const renameEditing = useCallback((name: string) => {
    setEditing((prev) => (prev ? { ...prev, name } : prev));
  }, []);

  const cancelEditing = useCallback(() => {
    setEditing(null);
    setError(null);
  }, []);

  // Read current draft from a ref so side effects stay out of the state updater.
  const editingRef = useRef<ZoneEditorState | null>(null);
  editingRef.current = editing;

  const saveEditing = useCallback(() => {
    const prev = editingRef.current;
    if (!prev) return;
    if (prev.points.length < 3) {
      setError('Minimum 3 points required');
      return;
    }
    const name = prev.name.trim() || (prev.zoneId ? 'ZONE' : `ZONE ${cameraId}`);
    if (prev.mode === 'create') {
      const zone: VirtualZone = {
        id: generateZoneId(zones),
        name,
        cameraId,
        type: 'POLYGON_ZONE',
        coordinates: prev.points.map((p) => ({ x: +(p.x * 100).toFixed(4), y: +(p.y * 100).toFixed(4) })),
        severity: 'CRITICAL',
        rule: 'RESTRICTED_ENTRY',
        loiteringThresholdSec: 30,
        isActive: true,
        color: colorForSeverity('CRITICAL'),
      };
      onSaveZone(zone);
      setSelectedZoneId(zone.id);
    } else {
      const existing = zones.find((z) => z.id === prev.zoneId);
      if (existing) {
        onSaveZone({
          ...existing,
          name,
          coordinates: prev.points.map((p) => ({ x: +(p.x * 100).toFixed(4), y: +(p.y * 100).toFixed(4) })),
        });
      }
    }
    setError(null);
    setEditing(null);
  }, [cameraId, zones, onSaveZone]);

  useEffect(() => {
    if (!menuPos) return;
    const handler = () => setMenuPos(null);
    window.addEventListener('click', handler);
    window.addEventListener('resize', handler);
    return () => {
      window.removeEventListener('click', handler);
      window.removeEventListener('resize', handler);
    };
  }, [menuPos]);

  return {
    cameraZones, selectedZoneId, editing, menuPos, error,
    openMenu, closeMenu, startCreate, startEdit, toggleEnabled, removeZone,
    selectZone, setEditing, addPoint, movePoint, removePoint, insertEdgePoint,
    renameEditing, saveEditing, cancelEditing,
  };
}

// ─── Display-only polygons (dashboard / non-interactive reuse) ───────────────

export const ZonePolygons: React.FC<{ zones: VirtualZone[]; dim?: boolean }> = ({ zones, dim }) => (
  <svg
    className="absolute inset-0 w-full h-full"
    viewBox="0 0 100 100"
    preserveAspectRatio="none"
    style={{ pointerEvents: 'none', opacity: dim ? 0.5 : 1 }}
    aria-hidden
  >
    {zones.map((z) => {
      const pts = z.coordinates.map((c) => `${c.x},${c.y}`).join(' ');
      const stroke = z.isActive ? z.color : '#64748B';
      return (
        <polygon
          key={z.id}
          points={pts}
          fill={`${stroke}${z.isActive ? '26' : '14'}`}
          stroke={stroke}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
          strokeDasharray={z.isActive ? undefined : '6 4'}
        />
      );
    })}
  </svg>
);

// ─── Manage menu (portal) ───────────────────────────────────────────────────

export const ZoneManageMenu: React.FC<{ controller: IntrusionZoneController }> = ({ controller }) => {
  const { menuPos, cameraZones, selectedZoneId, closeMenu, startCreate, startEdit, toggleEnabled, removeZone, selectZone } = controller;
  if (!menuPos) return null;
  const activeId = selectedZoneId || cameraZones[0]?.id || null;
  const activeZone = cameraZones.find((z) => z.id === activeId) || null;
  const menuItem = 'w-full px-3 py-2 text-left text-[11px] text-on-surface hover:bg-surface-container-high flex items-center gap-2 cursor-pointer transition-colors';

  return createPortal(
    <div
      className="fixed z-[10000]"
      style={{ left: menuPos.x, top: menuPos.y }}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
      data-testid="zone-manage-menu"
    >
      <div className="bg-surface border border-outline-variant rounded-xl shadow-xl py-1 min-w-[210px] overflow-hidden">
        <div className="px-3 py-2 border-b border-outline-variant/50 bg-surface-container-low flex items-center justify-between">
          <span className="text-[11px] font-bold text-primary font-mono">INTRUSION ZONES</span>
          <span className="text-[9px] text-on-surface-variant font-mono">{cameraZones.length}</span>
        </div>

        {cameraZones.length > 1 && (
          <div className="max-h-[130px] overflow-y-auto border-b border-outline-variant/50">
            {cameraZones.map((z) => (
              <button
                key={z.id}
                onClick={() => { selectZone(z.id); closeMenu(); startEdit(z.id); }}
                className={`w-full px-3 py-1.5 text-left text-[10px] flex items-center justify-between gap-2 cursor-pointer transition-colors hover:bg-surface-container-high ${
                  z.id === activeId ? 'text-primary font-bold' : 'text-on-surface'
                }`}
              >
                <span className="truncate">{z.name}</span>
                <span className={`px-1 rounded text-[8px] font-bold ${z.isActive ? 'bg-success-container text-success' : 'bg-surface-container-high text-on-surface-variant'}`}>
                  {z.isActive ? 'ON' : 'OFF'}
                </span>
              </button>
            ))}
          </div>
        )}

        {activeZone ? (
          <>
            <button className={menuItem} onClick={() => startEdit(activeZone.id)} data-testid="zone-menu-edit">
              <span className="material-symbols-outlined text-[14px]">edit</span> Edit / Reshape Zone
            </button>
            <button className={menuItem} onClick={() => toggleEnabled(activeZone.id)} data-testid="zone-menu-toggle">
              <span className="material-symbols-outlined text-[14px]">{activeZone.isActive ? 'visibility_off' : 'visibility'}</span>
              {activeZone.isActive ? 'Disable Zone' : 'Enable Zone'}
            </button>
            <button className={`${menuItem} text-error hover:text-error`} onClick={() => removeZone(activeZone.id)} data-testid="zone-menu-delete">
              <span className="material-symbols-outlined text-[14px]">delete</span> Delete Zone
            </button>
          </>
        ) : (
          <div className="px-3 py-2 text-[10px] text-on-surface-variant">No zones on this camera</div>
        )}

        <div className="border-t border-outline-variant/50 my-0.5" />
        <button className={menuItem} onClick={startCreate} data-testid="zone-menu-create">
          <span className="material-symbols-outlined text-[14px]">add</span> Create Zone
        </button>
      </div>
    </div>,
    document.body
  );
};

// ─── Button (place beside AI ON/OFF) ────────────────────────────────────────

export const IntrusionZoneButton: React.FC<{
  controller: IntrusionZoneController;
  compact?: boolean;
}> = ({ controller, compact }) => {
  const { cameraZones, editing, openMenu } = controller;
  const hasZones = cameraZones.length > 0;
  const active = editing !== null;
  const sizeCls = compact
    ? 'px-1.5 py-0.5 rounded text-[8px] gap-0.5'
    : 'px-3 py-1.5 rounded-lg border text-[11px] gap-1.5';
  const colorCls = active
    ? 'bg-primary-container text-primary border-primary/30'
    : 'bg-surface hover:bg-surface-container-high border-outline-variant text-on-surface';
  return (
    <button
      onClick={(e) => { e.stopPropagation(); openMenu(e); }}
      onContextMenu={(e) => openMenu(e)}
      title="Intrusion Zone"
      data-testid="intrusion-zone-button"
      className={`font-semibold flex items-center cursor-pointer transition-colors whitespace-nowrap border ${sizeCls} ${colorCls}`}
    >
      <span className={`material-symbols-outlined ${compact ? 'text-[10px]' : 'text-[14px]'}`}>fence</span> Intrusion Zone
      {hasZones && (
        <span className={`px-1 rounded text-[8px] font-bold ${active ? 'bg-primary text-on-primary' : 'bg-primary-container text-primary'}`}>
          {cameraZones.length}
        </span>
      )}
    </button>
  );
};

// ─── Layer: display polygons + interactive editor (lives in video container) ─

export const IntrusionZoneLayer: React.FC<{ controller: IntrusionZoneController }> = ({ controller }) => {
  const {
    cameraZones, editing, selectedZoneId, error,
    setEditing, addPoint, movePoint, removePoint, insertEdgePoint,
    renameEditing, saveEditing, cancelEditing, openMenu, selectZone, startEdit,
  } = controller;

  const containerRef = useRef<HTMLDivElement>(null);
  const dragIdxRef = useRef<number | null>(null);
  const didDragRef = useRef(false);
  const [, forceRender] = useState(0);

  const toNorm = useCallback((clientX: number, clientY: number): ZonePoint => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return { x: 0, y: 0 };
    return {
      x: Math.min(1, Math.max(0, +((clientX - rect.left) / rect.width).toFixed(4))),
      y: Math.min(1, Math.max(0, +((clientY - rect.top) / rect.height).toFixed(4))),
    };
  }, []);

  if (!editing) {
    // Display mode: zones beneath detection boxes (render before AIBoundingBoxOverlay)
    return (
      <div
        ref={containerRef}
        className="absolute inset-0"
        style={{ pointerEvents: 'none' }}
        data-testid="zone-layer"
      >
        <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          {cameraZones.map((z) => {
            const pts = z.coordinates.map((c) => `${c.x},${c.y}`).join(' ');
            const selected = z.id === selectedZoneId;
            const stroke = z.isActive ? z.color : '#64748B';
            return (
              <polygon
                key={z.id}
                data-testid="zone-polygon"
                data-zone-id={z.id}
                points={pts}
                fill={`${stroke}${z.isActive ? (selected ? '38' : '26') : '14'}`}
                stroke={stroke}
                strokeWidth={selected ? 2 : 1.2}
                vectorEffect="non-scaling-stroke"
                strokeDasharray={z.isActive ? undefined : '6 4'}
                style={{ pointerEvents: 'auto' }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  selectZone(z.id);
                  openMenu(e);
                }}
              />
            );
          })}
        </svg>
        {cameraZones.map((z) => {
          if (z.coordinates.length === 0) return null;
          const top = z.coordinates.reduce((a, b) => (b.y < a.y ? b : a), z.coordinates[0]);
          return (
            <div
              key={`lbl-${z.id}`}
              className="absolute"
              style={{
                left: `${top.x}%`,
                top: `${top.y}%`,
                transform: 'translate(-50%, -150%)',
                pointerEvents: 'none',
              }}
            >
              <span
                className="px-1.5 py-0.5 rounded text-[8px] font-bold font-mono whitespace-nowrap border"
                style={{
                  backgroundColor: 'rgba(10,14,18,0.85)',
                  borderColor: z.isActive ? z.color : '#64748B',
                  color: z.isActive ? z.color : '#94A3B8',
                }}
              >
                {z.name.toUpperCase()}{z.isActive ? '' : ' · DISABLED'}
              </span>
            </div>
          );
        })}
      </div>
    );
  }

  // Editor mode
  const points = editing.points;
  const draftPts = points.map((p) => `${p.x * 100},${p.y * 100}`).join(' ');

  const handleRootClick = (e: React.MouseEvent) => {
    if (didDragRef.current) { didDragRef.current = false; return; }
    e.stopPropagation();
    addPoint(toNorm(e.clientX, e.clientY));
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (dragIdxRef.current === null) return;
    didDragRef.current = true;
    movePoint(dragIdxRef.current, toNorm(e.clientX, e.clientY));
    forceRender((n) => n + 1);
  };

  const endDrag = () => { dragIdxRef.current = null; };

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 z-30"
      data-testid="zone-editor"
      style={{ cursor: 'crosshair' }}
      onClick={handleRootClick}
      onPointerMove={handlePointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); }}
    >
      {/* Existing zones dimmed while editing */}
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ pointerEvents: 'none', opacity: 0.45 }}>
        {cameraZones
          .filter((z) => z.id !== editing.zoneId)
          .map((z) => (
            <polygon
              key={z.id}
              points={z.coordinates.map((c) => `${c.x},${c.y}`).join(' ')}
              fill={`${z.isActive ? z.color : '#64748B'}26`}
              stroke={z.isActive ? z.color : '#64748B'}
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
              strokeDasharray={z.isActive ? undefined : '6 4'}
            />
          ))}
      </svg>

      {/* Draft polygon + edges */}
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ pointerEvents: 'none' }}>
        {points.length >= 2 && (
          <polygon
            points={draftPts}
            fill={points.length >= 3 ? 'rgba(124,140,248,0.16)' : 'transparent'}
            stroke="#7C8CF8"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            strokeDasharray={points.length >= 3 ? undefined : '5 4'}
          />
        )}
        <g style={{ pointerEvents: 'auto' }}>
          {points.map((p, i) => {
            const nx = points[(i + 1) % points.length];
            if (points.length < 3 && i === points.length - 1) return null;
            return (
              <line
                key={`edge-${i}`}
                x1={p.x * 100} y1={p.y * 100} x2={nx.x * 100} y2={nx.y * 100}
                stroke="transparent" strokeWidth={12}
                vectorEffect="non-scaling-stroke"
                style={{ pointerEvents: 'stroke', cursor: 'copy' }}
                onClick={(e) => { e.stopPropagation(); }}
                onDoubleClick={(e) => { e.stopPropagation(); insertEdgePoint(i); }}
              />
            );
          })}
        </g>
      </svg>

      {/* Vertex handles */}
      {points.map((p, i) => (
        <div
          key={`vtx-${i}`}
          data-testid="zone-vertex"
          onPointerDown={(e) => {
            e.stopPropagation();
            e.preventDefault();
            didDragRef.current = false;
            (e.target as HTMLElement).setPointerCapture(e.pointerId);
            dragIdxRef.current = i;
          }}
          onDoubleClick={(e) => { e.stopPropagation(); removePoint(i); }}
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            left: `${p.x * 100}%`,
            top: `${p.y * 100}%`,
            width: '12px',
            height: '12px',
            marginLeft: '-6px',
            marginTop: '-6px',
            borderRadius: '50%',
            background: '#fff',
            border: '2px solid #7C8CF8',
            cursor: 'grab',
            pointerEvents: 'auto',
            boxShadow: '0 0 4px rgba(0,0,0,0.6)',
          }}
          title="Drag to move · Double-click to remove"
        />
      ))}

      {/* Editor toolbar */}
      <div
        className="absolute bottom-0 left-0 right-0 px-2 py-1.5 flex items-center gap-2 flex-wrap border-t border-[#1E2A32]"
        style={{ background: 'rgba(10,14,18,0.94)', cursor: 'default' }}
        onClick={(e) => e.stopPropagation()}
        onPointerDown={(e) => e.stopPropagation()}
      >
        <input
          value={editing.name}
          onChange={(e) => renameEditing(e.target.value)}
          placeholder="Zone name"
          data-testid="zone-name-input"
          className="bg-surface-container-low border border-outline-variant rounded px-2 py-1 text-[10px] font-mono text-on-surface w-36 outline-none focus:border-primary"
        />
        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold font-mono ${points.length >= 3 ? 'bg-success-container text-success' : 'bg-error-container text-error'}`}>
          {points.length} PTS
        </span>
        <span className="text-[9px] text-on-surface-variant font-mono hidden md:inline">
          Click to add · Drag dots · Dbl-click dot=remove · Dbl-click edge=insert
        </span>
        {error && <span className="text-[9px] font-bold text-error" data-testid="zone-editor-error">{error}</span>}
        <div className="flex items-center gap-1.5 ml-auto">
          <button
            onClick={cancelEditing}
            data-testid="zone-cancel"
            className="px-2.5 py-1 rounded border border-outline-variant text-[10px] font-semibold text-on-surface hover:bg-surface-container-high cursor-pointer"
          >
            Cancel
          </button>
          <button
            onClick={saveEditing}
            disabled={points.length < 3}
            data-testid="zone-save"
            className="px-2.5 py-1 rounded bg-primary text-on-primary text-[10px] font-bold disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            Save Zone
          </button>
        </div>
      </div>
    </div>
  );
};
