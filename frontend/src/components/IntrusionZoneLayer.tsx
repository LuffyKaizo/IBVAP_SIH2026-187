import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { VirtualZone, AiSecurityEvent } from '../types';

export interface ZonePoint { x: number; y: number } // normalized 0-1 frame coords

/** Cumulative transform parameters shown by the editor's transform panel. */
export interface ZoneTransformParams {
  rotationDeg: number; // normalized to (-180, 180]; 360 -> 0, 380 -> 20
  skewDeg: number;     // horizontal shear (degrees)
  tiltDeg: number;     // vertical shear (degrees)
  perspPct: number;    // horizontal keystone (-60..60)
}

const IDENTITY_TRANSFORM: ZoneTransformParams = { rotationDeg: 0, skewDeg: 0, tiltDeg: 0, perspPct: 0 };

const isIdentityTransform = (t?: ZoneTransformParams): boolean =>
  !t || (t.rotationDeg === 0 && t.skewDeg === 0 && t.tiltDeg === 0 && t.perspPct === 0);

export interface ZoneEditorState {
  mode: 'create' | 'edit';
  zoneId: string | null;
  name: string;
  points: ZonePoint[];
  isActive: boolean;
  /** Shape as it was when this edit session began — Reset Transform restores it. */
  originPoints?: ZonePoint[];
  /** Cumulative transform values displayed by the transform panel. */
  transform?: ZoneTransformParams;
  /** Show the rotate / skew / tilt / perspective panel. */
  showTransform?: boolean;
}

interface UseIntrusionZoneOptions {
  cameraId: string;
  zones: VirtualZone[];
  onSaveZone: (zone: VirtualZone) => void;
  onDeleteZone: (id: string) => void;
  /** Live AI security events — powers the zone status panel intruder list. */
  events?: AiSecurityEvent[];
}

export interface ZoneIntruder {
  trackId: number;
  label: string;
  confidence: number;
  eventType: string;
}

export interface IntrusionZoneController {
  cameraZones: VirtualZone[];
  selectedZoneId: string | null;
  editing: ZoneEditorState | null;
  menuPos: { x: number; y: number } | null;
  statusPos: { x: number; y: number } | null;
  error: string | null;
  openMenu: (e: React.MouseEvent) => void;
  showMenuAt: (x: number, y: number) => void;
  closeMenu: () => void;
  openStatus: (e: React.MouseEvent) => void;
  closeStatus: () => void;
  startCreate: () => void;
  startEdit: (zoneId: string, opts?: { showTransform?: boolean }) => void;
  startTransform: (zoneId: string) => void;
  resetZoneTransform: (zoneId: string) => void;
  zoneIntruders: (zoneId: string) => ZoneIntruder[];
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

// ─── Perspective-aware transform math ────────────────────────────────────────
// Points live in normalized frame space (0-1 x, 0-1 y), but frames are not
// square — rotation/shear are computed in aspect-corrected space
// (u = x * aspect, v = y) so 45° actually LOOKS like 45° on screen.

const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));
const round4 = (v: number): number => +v.toFixed(4);

/** Normalize any degree value into (-180, 180]: 360 -> 0, 380 -> 20, 220 -> -140. */
const norm360 = (deg: number): number => {
  let d = deg % 360;
  if (d > 180) d -= 360;
  if (d <= -180) d += 360;
  return round4(d);
};

const polygonCentroid = (pts: ZonePoint[]): ZonePoint => {
  let sx = 0;
  let sy = 0;
  for (const p of pts) {
    sx += p.x;
    sy += p.y;
  }
  return { x: sx / pts.length, y: sy / pts.length };
};

type TransformOp = 'rotate' | 'skew' | 'tilt' | 'persp';

/**
 * Apply one incremental transform op to a polygon.
 *  - rotate: around the polygon centroid (aspect-corrected)
 *  - skew:   horizontal shear around the centroid (degrees)
 *  - tilt:   vertical shear around the centroid (degrees)
 *  - persp:  horizontal keystone — top/bottom width diverges (delta = -60..60)
 * Results are clamped to valid normalized coordinates (0-1).
 */
export function transformZonePoints(
  points: ZonePoint[],
  aspect: number,
  op: TransformOp,
  delta: number,
): ZonePoint[] {
  if (points.length === 0 || !delta) return points.map((p) => ({ ...p }));
  const a = aspect > 0 && Number.isFinite(aspect) ? aspect : 16 / 9;
  const c = polygonCentroid(points);
  const cx = c.x * a;
  const cy = c.y;
  const rad = (delta * Math.PI) / 180;
  const tanK = Math.tan(rad);

  let spanY = 0;
  if (op === 'persp') {
    let minY = Infinity;
    let maxY = -Infinity;
    for (const p of points) {
      if (p.y < minY) minY = p.y;
      if (p.y > maxY) maxY = p.y;
    }
    spanY = Math.max(0.05, maxY - minY);
  }

  return points.map((p0) => {
    const px = p0.x * a;
    const py = p0.y;
    let qx: number;
    let qy: number;
    if (op === 'rotate') {
      const cos = Math.cos(rad);
      const sin = Math.sin(rad);
      qx = cx + (px - cx) * cos - (py - cy) * sin;
      qy = cy + (px - cx) * sin + (py - cy) * cos;
    } else if (op === 'skew') {
      qx = px + (py - cy) * tanK;
      qy = py;
    } else if (op === 'tilt') {
      qx = px;
      qy = py + (px - cx) * tanK;
    } else {
      // Keystone: horizontal scale varies linearly with distance from center
      const t = Math.max(-0.9, Math.min(0.9, delta / 100));
      qx = cx + (px - cx) * (1 + (t * 2 * (py - cy)) / spanY);
      qy = py;
    }
    return { x: round4(clamp01(qx / a)), y: round4(clamp01(qy)) };
  });
}

export function useIntrusionZoneController(opts: UseIntrusionZoneOptions): IntrusionZoneController {
  const { cameraId, zones, onSaveZone, onDeleteZone } = opts;
  const [editing, setEditing] = useState<ZoneEditorState | null>(null);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const [statusPos, setStatusPos] = useState<{ x: number; y: number } | null>(null);
  const [selectedZoneId, setSelectedZoneId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Per-session original shape per zone id — Reset Transform restores this. */
  const originsRef = useRef<Record<string, ZonePoint[]>>({});
  /** Cumulative transform params per zone id — survive save + reopen in-session. */
  const transformsRef = useRef<Record<string, ZoneTransformParams>>({});

  const cameraZones = zones.filter((z) => z.cameraId === cameraId);

  const zoneIntruders = useCallback((zoneId: string): ZoneIntruder[] => {
    const out: ZoneIntruder[] = [];
    for (const ev of opts.events || []) {
      if (ev.zone_id !== zoneId) continue;
      if (ev.status === 'RESOLVED') continue;
      if (ev.event_type !== 'PERSON_INTRUSION' && ev.event_type !== 'VEHICLE_INTRUSION') continue;
      const raw = ev.object_class || (ev.event_type === 'PERSON_INTRUSION' ? 'person' : 'target');
      const cls = raw.charAt(0).toUpperCase() + raw.slice(1);
      out.push({
        trackId: ev.track_id,
        label: `${cls} #${ev.track_id}`,
        confidence: Math.round((ev.confidence || 0) * 100),
        eventType: ev.event_type,
      });
    }
    return out;
  }, [opts.events]);

  const showMenuAt = useCallback((clientX: number, clientY: number) => {
    setStatusPos(null);
    if (cameraZones.length === 0) return;
    const x = Math.min(clientX, window.innerWidth - 230);
    const y = Math.min(clientY, window.innerHeight - 300);
    setMenuPos({ x: Math.max(8, x), y: Math.max(8, y) });
  }, [cameraZones.length]);

  const openMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setEditing(null);
    setError(null);
    if (cameraZones.length === 0) {
      // No zone yet: context/left click on control enters create mode directly
      setMenuPos(null);
      setStatusPos(null);
      setSelectedZoneId(null);
      setEditing({
        mode: 'create', zoneId: null, name: `ZONE ${cameraId} 1`,
        points: [], isActive: true,
      });
      return;
    }
    showMenuAt(e.clientX, e.clientY);
  }, [cameraId, cameraZones.length, showMenuAt]);

  const closeMenu = useCallback(() => setMenuPos(null), []);

  const openStatus = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setMenuPos(null);
    setEditing(null);
    setError(null);
    if (cameraZones.length === 0) return;
    const x = Math.min(e.clientX, window.innerWidth - 260);
    const y = Math.min(e.clientY, window.innerHeight - 260);
    setStatusPos({ x: Math.max(8, x), y: Math.max(8, y) });
  }, [cameraZones.length]);

  const closeStatus = useCallback(() => setStatusPos(null), []);

  const startCreate = useCallback(() => {
    setMenuPos(null);
    setError(null);
    setEditing({
      mode: 'create', zoneId: null, name: `ZONE ${cameraId} ${cameraZones.length + 1}`,
      points: [], isActive: true,
    });
  }, [cameraId, cameraZones.length]);

  const startEdit = useCallback((zoneId: string, editOpts?: { showTransform?: boolean }) => {
    const zone = zones.find((z) => z.id === zoneId && z.cameraId === cameraId);
    if (!zone) return;
    setMenuPos(null);
    setStatusPos(null);
    setError(null);
    setSelectedZoneId(zoneId);
    const points = zone.coordinates.map((c) => ({ x: c.x / 100, y: c.y / 100 }));
    // Remember the original (pre-transform) shape once per zone per session so
    // "Reset Transform" can restore it later — even after save/reopen.
    if (!originsRef.current[zoneId]) {
      originsRef.current[zoneId] = points.map((p) => ({ ...p }));
    }
    const origin = originsRef.current[zoneId].map((p) => ({ ...p }));
    const savedT = transformsRef.current[zoneId];
    setEditing({
      mode: 'edit',
      zoneId: zone.id,
      name: zone.name,
      points,
      isActive: zone.isActive,
      originPoints: origin,
      transform: savedT ? { ...savedT } : { ...IDENTITY_TRANSFORM },
      showTransform: editOpts?.showTransform || false,
    });
  }, [zones, cameraId]);

  const startTransform = useCallback((zoneId: string) => {
    startEdit(zoneId, { showTransform: true });
  }, [startEdit]);

  const resetZoneTransform = useCallback((zoneId: string) => {
    const origin = originsRef.current[zoneId];
    if (!origin || origin.length < 3) {
      setError('No original shape saved for this zone yet');
      return;
    }
    setMenuPos(null);
    setStatusPos(null);
    setSelectedZoneId(zoneId);
    const zone = zones.find((z) => z.id === zoneId);
    transformsRef.current[zoneId] = { ...IDENTITY_TRANSFORM };
    setEditing({
      mode: 'edit',
      zoneId,
      name: zone?.name ?? 'ZONE',
      points: origin.map((p) => ({ ...p })),
      isActive: zone?.isActive ?? true,
      originPoints: origin.map((p) => ({ ...p })),
      transform: { ...IDENTITY_TRANSFORM },
      showTransform: true,
    });
  }, [zones]);

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
      const newId = generateZoneId(zones);
      const zone: VirtualZone = {
        id: newId,
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
      setSelectedZoneId(newId);
      // Plain (untransformed) saves become the new Reset origin; transformed
      // saves keep the pre-transform baseline so rotation stays undoable.
      originsRef.current[newId] = isIdentityTransform(prev.transform)
        ? prev.points.map((p) => ({ ...p }))
        : (prev.originPoints ?? prev.points.map((p) => ({ ...p })));
      transformsRef.current[newId] = { ...(prev.transform ?? IDENTITY_TRANSFORM) };
    } else {
      const existing = zones.find((z) => z.id === prev.zoneId);
      if (existing) {
        onSaveZone({
          ...existing,
          name,
          coordinates: prev.points.map((p) => ({ x: +(p.x * 100).toFixed(4), y: +(p.y * 100).toFixed(4) })),
        });
        originsRef.current[existing.id] = isIdentityTransform(prev.transform)
          ? prev.points.map((p) => ({ ...p }))
          : (prev.originPoints ?? prev.points.map((p) => ({ ...p })));
        transformsRef.current[existing.id] = { ...(prev.transform ?? IDENTITY_TRANSFORM) };
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

  useEffect(() => {
    if (!statusPos) return;
    const handler = () => setStatusPos(null);
    window.addEventListener('click', handler);
    window.addEventListener('resize', handler);
    return () => {
      window.removeEventListener('click', handler);
      window.removeEventListener('resize', handler);
    };
  }, [statusPos]);

  return {
    cameraZones, selectedZoneId, editing, menuPos, statusPos, error,
    openMenu, showMenuAt, closeMenu, openStatus, closeStatus,
    startCreate, startEdit, startTransform, resetZoneTransform, zoneIntruders,
    toggleEnabled, removeZone, selectZone, setEditing, addPoint, movePoint,
    removePoint, insertEdgePoint, renameEditing, saveEditing, cancelEditing,
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
  const { menuPos, cameraZones, selectedZoneId, closeMenu, startCreate, startEdit, startTransform, resetZoneTransform, toggleEnabled, removeZone, selectZone } = controller;
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
            <button className={menuItem} onClick={() => startTransform(activeZone.id)} data-testid="zone-menu-rotate">
              <span className="material-symbols-outlined text-[14px]">rotate_right</span> Transform / Perspective
            </button>
            <button className={menuItem} onClick={() => resetZoneTransform(activeZone.id)} data-testid="zone-menu-reset">
              <span className="material-symbols-outlined text-[14px]">restart_alt</span> Reset Transform
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
  const { cameraZones, editing, openMenu, openStatus } = controller;
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
      onClick={(e) => { e.stopPropagation(); if (hasZones) openStatus(e); else openMenu(e); }}
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

// ─── Zone status panel (portal): one-click health view for the active zone ──

export const ZoneStatusPanel: React.FC<{ controller: IntrusionZoneController }> = ({ controller }) => {
  const {
    statusPos, cameraZones, selectedZoneId, zoneIntruders,
    startEdit, startCreate, closeStatus, showMenuAt, selectZone,
  } = controller;
  if (!statusPos) return null;
  const activeId = selectedZoneId || cameraZones[0]?.id || null;
  const activeZone = cameraZones.find((z) => z.id === activeId) || cameraZones[0] || null;
  const intruders = activeZone ? zoneIntruders(activeZone.id) : [];
  const btn = 'px-2 py-1 rounded border border-outline-variant text-[10px] font-semibold text-on-surface hover:bg-surface-container-high cursor-pointer flex items-center gap-1 justify-center';

  return createPortal(
    <div
      className="fixed z-[10000] w-[248px]"
      style={{ left: statusPos.x, top: statusPos.y }}
      onClick={(e) => e.stopPropagation()}
      onContextMenu={(e) => e.stopPropagation()}
      data-testid="zone-status-panel"
    >
      <div className="bg-surface border border-outline-variant rounded-xl shadow-2xl overflow-hidden">
        <div className="px-3 py-2 border-b border-outline-variant/50 bg-surface-container-low flex items-center justify-between">
          <span className="text-[11px] font-bold text-primary font-mono">ZONE STATUS</span>
          <button
            onClick={closeStatus}
            data-testid="zone-status-close"
            className="text-[11px] text-on-surface-variant hover:text-on-surface cursor-pointer leading-none"
            title="Close"
          >
            ✕
          </button>
        </div>

        {cameraZones.length > 1 && (
          <div className="flex gap-1 px-2 py-1.5 border-b border-outline-variant/50 overflow-x-auto">
            {cameraZones.map((z) => (
              <button
                key={`chip-${z.id}`}
                onClick={() => selectZone(z.id)}
                data-testid="zone-status-chip"
                className={`px-1.5 py-0.5 rounded text-[8px] font-mono font-bold whitespace-nowrap cursor-pointer border ${
                  z.id === activeZone?.id
                    ? 'bg-primary-container text-primary border-primary/30'
                    : 'bg-surface-container-low text-on-surface-variant border-outline-variant hover:text-on-surface'
                }`}
              >
                {z.name}
              </button>
            ))}
          </div>
        )}

        {activeZone ? (
          <div className="px-3 py-2 flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <span
                className="text-[11px] font-bold font-mono truncate text-on-surface"
                data-testid="zone-status-name"
                title={activeZone.name}
              >
                {activeZone.name}
              </span>
              <span
                className={`px-1.5 py-0.5 rounded text-[8px] font-bold font-mono ${
                  activeZone.isActive ? 'bg-success-container text-success' : 'bg-surface-container-high text-on-surface-variant'
                }`}
              >
                {activeZone.isActive ? 'ENABLED' : 'DISABLED'}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={`text-[22px] font-bold font-mono leading-none ${intruders.length > 0 ? 'text-error' : 'text-success'}`}
                data-testid="zone-status-intruders"
              >
                {intruders.length}
              </span>
              <span className="text-[9px] font-mono text-on-surface-variant">
                {intruders.length === 1 ? 'INTRUDER' : 'INTRUDERS'}
              </span>
            </div>

            {intruders.length > 0 && (
              <div className="flex flex-col gap-1 max-h-[110px] overflow-y-auto">
                {intruders.map((it) => (
                  <div
                    key={`${it.eventType}-${it.trackId}`}
                    className="flex items-center justify-between bg-error-container/60 rounded px-1.5 py-1"
                    data-testid="zone-status-intruder-row"
                  >
                    <span className="text-[9px] font-mono font-bold text-error truncate">{it.label}</span>
                    <span className="text-[9px] font-mono text-error font-bold">{it.confidence}%</span>
                  </div>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-1.5 pt-1 border-t border-outline-variant/50">
              <button className={btn} onClick={() => startEdit(activeZone.id)} data-testid="zone-status-edit">
                <span className="material-symbols-outlined text-[12px]">edit</span> Edit
              </button>
              <button
                className={btn}
                onClick={() => { closeStatus(); showMenuAt(statusPos.x, statusPos.y); }}
                data-testid="zone-status-manage"
              >
                <span className="material-symbols-outlined text-[12px]">tune</span> Manage
              </button>
              <button className={btn} onClick={() => { closeStatus(); startCreate(); }} data-testid="zone-status-create">
                <span className="material-symbols-outlined text-[12px]">add</span> New Zone
              </button>
              <button className={btn} onClick={closeStatus} data-testid="zone-status-dismiss">
                <span className="material-symbols-outlined text-[12px]">close</span> Close
              </button>
            </div>
          </div>
        ) : (
          <div className="px-3 py-2 text-[10px] text-on-surface-variant">No zones on this camera</div>
        )}
      </div>
    </div>,
    document.body
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
  /** Whole-zone interior drag: start point + pre-drag shape snapshot. */
  const shapeDragRef = useRef<{ startX: number; startY: number; start: ZonePoint; startPoints: ZonePoint[] } | null>(null);
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
  const tParams = editing.transform ?? IDENTITY_TRANSFORM;

  const frameAspect = (): number => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (rect && rect.height > 0 && rect.width > 0) return rect.width / rect.height;
    return 16 / 9;
  };

  const handleRootClick = (e: React.MouseEvent) => {
    if (didDragRef.current) { didDragRef.current = false; return; }
    e.stopPropagation();
    addPoint(toNorm(e.clientX, e.clientY));
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (dragIdxRef.current !== null) {
      didDragRef.current = true;
      movePoint(dragIdxRef.current, toNorm(e.clientX, e.clientY));
      forceRender((n) => n + 1);
      return;
    }
    const sd = shapeDragRef.current;
    if (!sd) return;
    const rect = containerRef.current?.getBoundingClientRect();
    const movedPx = rect ? Math.hypot(e.clientX - sd.startX, e.clientY - sd.startY) : 0;
    if (movedPx > 3) didDragRef.current = true;
    if (!didDragRef.current) return; // suppress zone move until >3px so a plain click still adds a point
    const cur = toNorm(e.clientX, e.clientY);
    const dx = cur.x - sd.start.x;
    const dy = cur.y - sd.start.y;
    setEditing((prev) => (prev
      ? {
          ...prev,
          points: sd.startPoints.map((p) => ({
            x: clamp01(+(p.x + dx).toFixed(4)),
            y: clamp01(+(p.y + dy).toFixed(4)),
          })),
        }
      : prev));
    forceRender((n) => n + 1);
  };

  const endDrag = () => {
    dragIdxRef.current = null;
    shapeDragRef.current = null;
  };

  // ── Transform ops (rotate / skew / tilt / perspective) ───────────────────
  const applyRotation = (absDeg: number) => setEditing((prev) => {
    if (!prev) return prev;
    const curT = prev.transform ?? IDENTITY_TRANSFORM;
    const target = norm360(absDeg);
    const delta = round4(target - curT.rotationDeg);
    if (prev.points.length < 3 || delta === 0) {
      return { ...prev, transform: { ...curT, rotationDeg: target } };
    }
    return {
      ...prev,
      points: transformZonePoints(prev.points, frameAspect(), 'rotate', delta),
      transform: { ...curT, rotationDeg: target },
    };
  });

  const applyShear = (field: 'skewDeg' | 'tiltDeg', absVal: number) => setEditing((prev) => {
    if (!prev) return prev;
    const curT = prev.transform ?? IDENTITY_TRANSFORM;
    const target = round4(absVal);
    const delta = round4(target - curT[field]);
    if (prev.points.length < 3 || delta === 0) {
      return { ...prev, transform: { ...curT, [field]: target } };
    }
    return {
      ...prev,
      points: transformZonePoints(prev.points, frameAspect(), field === 'skewDeg' ? 'skew' : 'tilt', delta),
      transform: { ...curT, [field]: target },
    };
  });

  const applyPerspective = (absPct: number) => setEditing((prev) => {
    if (!prev) return prev;
    const curT = prev.transform ?? IDENTITY_TRANSFORM;
    const target = Math.max(-60, Math.min(60, round4(absPct)));
    const delta = round4(target - curT.perspPct);
    if (prev.points.length < 3 || delta === 0) {
      return { ...prev, transform: { ...curT, perspPct: target } };
    }
    return {
      ...prev,
      points: transformZonePoints(prev.points, frameAspect(), 'persp', delta),
      transform: { ...curT, perspPct: target },
    };
  });

  const resetTransformInPanel = () => setEditing((prev) => {
    if (!prev) return prev;
    const origin = prev.originPoints;
    if (!origin || origin.length < 3) {
      return { ...prev, transform: { ...IDENTITY_TRANSFORM } };
    }
    return {
      ...prev,
      points: origin.map((p) => ({ ...p })),
      transform: { ...IDENTITY_TRANSFORM },
    };
  });

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
            style={{ pointerEvents: points.length >= 3 ? 'auto' : 'none', cursor: points.length >= 3 ? 'move' : 'default' }}
            onPointerDown={(e) => {
              if (points.length < 3) return;
              e.stopPropagation();
              e.preventDefault();
              didDragRef.current = false;
              shapeDragRef.current = {
                startX: e.clientX,
                startY: e.clientY,
                start: toNorm(e.clientX, e.clientY),
                startPoints: points.map((p) => ({ ...p })),
              };
              (e.target as SVGElement).setPointerCapture(e.pointerId);
            }}
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
        {/* Transform panel (rotate / skew / tilt / perspective) — floats above toolbar */}
        {editing.showTransform && (
          <div
            className="absolute bottom-full left-0 right-0 sm:right-auto sm:w-[320px] mb-1 bg-surface border border-outline-variant rounded-xl p-2.5 flex flex-col gap-2 shadow-2xl z-10"
            style={{ cursor: 'default' }}
            onClick={(e) => e.stopPropagation()}
            onPointerDown={(e) => e.stopPropagation()}
            onContextMenu={(e) => { e.preventDefault(); e.stopPropagation(); }}
            data-testid="zone-transform-panel"
          >
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-bold font-mono text-primary">TRANSFORM ZONE</span>
              <button
                onClick={() => setEditing((prev) => (prev ? { ...prev, showTransform: false } : prev))}
                data-testid="zone-transform-close"
                className="text-[11px] text-on-surface-variant hover:text-on-surface cursor-pointer leading-none"
                title="Close"
              >
                ✕
              </button>
            </div>

            {/* Rotation: numeric input is authoritative and always absolute */}
            <label className="flex items-center gap-2 text-[9px] font-mono text-on-surface-variant">
              <span className="w-14">ROTATE°</span>
              <input
                type="number"
                min={-180}
                max={180}
                step={1}
                value={tParams.rotationDeg}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  if (!Number.isNaN(v)) applyRotation(v);
                }}
                data-testid="zone-rotation-input"
                className="bg-surface-container-low border border-outline-variant rounded px-1.5 py-0.5 text-[10px] font-mono text-on-surface w-16 outline-none focus:border-primary"
              />
              <input
                type="range"
                min={-180}
                max={180}
                step={1}
                value={tParams.rotationDeg}
                onChange={(e) => applyRotation(parseFloat(e.target.value))}
                className="flex-1 accent-[#7C8CF8] cursor-pointer"
                data-testid="zone-rotation-slider"
                title="Rotate zone"
              />
            </label>

            <label className="flex items-center gap-2 text-[9px] font-mono text-on-surface-variant">
              <span className="w-14">SKEW°</span>
              <input
                type="range"
                min={-45}
                max={45}
                step={1}
                value={tParams.skewDeg}
                onChange={(e) => applyShear('skewDeg', parseFloat(e.target.value))}
                className="flex-1 accent-[#7C8CF8] cursor-pointer"
                data-testid="zone-skew-slider"
                title="Skew (horizontal shear)"
              />
              <span className="w-8 text-right text-on-surface">{tParams.skewDeg}</span>
            </label>

            <label className="flex items-center gap-2 text-[9px] font-mono text-on-surface-variant">
              <span className="w-14">TILT°</span>
              <input
                type="range"
                min={-45}
                max={45}
                step={1}
                value={tParams.tiltDeg}
                onChange={(e) => applyShear('tiltDeg', parseFloat(e.target.value))}
                className="flex-1 accent-[#7C8CF8] cursor-pointer"
                data-testid="zone-tilt-slider"
                title="Tilt (vertical shear)"
              />
              <span className="w-8 text-right text-on-surface">{tParams.tiltDeg}</span>
            </label>

            <label className="flex items-center gap-2 text-[9px] font-mono text-on-surface-variant">
              <span className="w-14">PERSP%</span>
              <input
                type="range"
                min={-60}
                max={60}
                step={5}
                value={tParams.perspPct}
                onChange={(e) => applyPerspective(parseFloat(e.target.value))}
                className="flex-1 accent-[#7C8CF8] cursor-pointer"
                data-testid="zone-perspective-slider"
                title="Perspective (keystone)"
              />
              <span className="w-8 text-right text-on-surface">{tParams.perspPct}</span>
            </label>

            <button
              onClick={resetTransformInPanel}
              disabled={!editing.originPoints || editing.originPoints.length < 3}
              data-testid="zone-reset-transform"
              className="w-full px-2 py-1 rounded border border-outline-variant text-[10px] font-semibold text-on-surface hover:bg-surface-container-high disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center justify-center gap-1"
            >
              <span className="material-symbols-outlined text-[12px]">restart_alt</span>
              Reset to Origin
            </button>
            <span className="text-[8px] text-on-surface-variant font-mono leading-tight">
              Origin = shape when editing began · Reset survives save + reopen
            </span>
          </div>
        )}

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
            onClick={() => setEditing((prev) => (prev
              ? {
                  ...prev,
                  showTransform: !prev.showTransform,
                  originPoints: prev.originPoints ?? prev.points.map((p) => ({ ...p })),
                  transform: prev.transform ?? { ...IDENTITY_TRANSFORM },
                }
              : prev))}
            data-testid="zone-transform-toggle"
            className="px-2.5 py-1 rounded border border-outline-variant text-[10px] font-semibold text-on-surface hover:bg-surface-container-high cursor-pointer flex items-center gap-1"
            title="Rotate / skew / tilt / perspective"
          >
            <span className="material-symbols-outlined text-[12px]">3d_rotation</span>
            Transform
          </button>
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
