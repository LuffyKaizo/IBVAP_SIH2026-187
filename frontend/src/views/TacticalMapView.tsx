import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';

const AI_SERVICE_URL = (import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8000');

const MAP_W = 1000;
const MAP_H = 640;
const PAD = 56;
const M_PER_DEG = 111320;

type LatLon = { lat: number; lon: number };

type CameraGeo = {
  cameraId: string | null;
  name: string | null;
  lat: number | null;
  lon: number | null;
  headingDeg: number;
  fovDeg: number;
  rangeM: number;
  placed: boolean;
  cone: LatLon[];
};

type ZeroLine = { id: string; name: string; cameraId?: string | null; points: LatLon[] };
type BufferZone = { id: string; name: string; cameraId?: string | null; polygon: LatLon[]; bufferM?: number | null };

type Overview = {
  cameras: CameraGeo[];
  zeroLines: ZeroLine[];
  bufferZones: BufferZone[];
  updatedAt?: string;
};

type Selected =
  | { kind: 'camera'; id: string }
  | { kind: 'line'; id: string }
  | { kind: 'zone'; id: string }
  | null;

type DrawMode = 'line' | 'zone' | null;
type EditTarget = { kind: 'line' | 'zone'; id: string } | null;

const EMPTY_OVERVIEW: Overview = { cameras: [], zeroLines: [], bufferZones: [] };

const fmt = (n: number | null | undefined, digits = 6): string =>
  n == null || Number.isNaN(n) ? '' : String(Number(n.toFixed(digits)));
const num = (s: string, fallback: number): number => {
  const v = parseFloat(s);
  return Number.isFinite(v) ? v : fallback;
};

function boundsOf(ov: Overview) {
  const pts: LatLon[] = [];
  for (const c of ov.cameras) if (c.placed && c.lat != null && c.lon != null) pts.push({ lat: c.lat, lon: c.lon });
  for (const l of ov.zeroLines) pts.push(...l.points);
  for (const z of ov.bufferZones) pts.push(...z.polygon);
  if (pts.length === 0) return { latMin: 26.85, latMax: 26.97, lonMin: 73.77, lonMax: 73.94 };
  let latMin = Infinity, latMax = -Infinity, lonMin = Infinity, lonMax = -Infinity;
  for (const p of pts) {
    latMin = Math.min(latMin, p.lat); latMax = Math.max(latMax, p.lat);
    lonMin = Math.min(lonMin, p.lon); lonMax = Math.max(lonMax, p.lon);
  }
  const latPad = Math.max((latMax - latMin) * 0.18, 0.004);
  const lonPad = Math.max((lonMax - lonMin) * 0.18, 0.004);
  return { latMin: latMin - latPad, latMax: latMax + latPad, lonMin: lonMin - lonPad, lonMax: lonMax + lonPad };
}

export const TacticalMapView: React.FC = () => {
  const { getAuthHeaders, user } = useAuth();
  const canEdit = user?.role === 'ADMIN' || user?.role === 'OPERATOR';

  const [overview, setOverview] = useState<Overview>(EMPTY_OVERVIEW);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const [layers, setLayers] = useState({ cameras: true, cones: true, lines: true, zones: true });
  const [selected, setSelected] = useState<Selected>(null);
  const [drawMode, setDrawMode] = useState<DrawMode>(null);
  const [editTarget, setEditTarget] = useState<EditTarget>(null);
  const [draftPoints, setDraftPoints] = useState<LatLon[]>([]);
  const [draftName, setDraftName] = useState('');
  const [placeMode, setPlaceMode] = useState(false);

  const [camForm, setCamForm] = useState({ lat: '', lon: '', heading: '0', fov: '60', range: '250' });

  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragCameraRef = useRef<string | null>(null);
  const suppressClickRef = useRef(false);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showNotice = useCallback((kind: 'ok' | 'err', text: string) => {
    if (noticeTimer.current) clearTimeout(noticeTimer.current);
    setNotice({ kind, text });
    noticeTimer.current = setTimeout(() => setNotice(null), 5000);
  }, []);

  const loadOverview = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const res = await fetch(`${AI_SERVICE_URL}/tactical/overview`, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error(`Tactical overview failed (HTTP ${res.status})`);
      const data: Overview = await res.json();
      setOverview({
        cameras: data.cameras || [],
        zeroLines: data.zeroLines || [],
        bufferZones: data.bufferZones || [],
        updatedAt: data.updatedAt,
      });
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Failed to load tactical overview');
    } finally {
      setLoading(false);
    }
  }, [getAuthHeaders]);

  useEffect(() => { void loadOverview(); }, [loadOverview]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setDrawMode(null); setEditTarget(null); setDraftPoints([]); setDraftName('');
        setPlaceMode(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const bounds = useMemo(() => boundsOf(overview), [overview]);

  const proj = useMemo(() => {
    const lat0 = (bounds.latMin + bounds.latMax) / 2;
    const mPerLon = Math.cos((lat0 * Math.PI) / 180) * M_PER_DEG;
    const wM = Math.max((bounds.lonMax - bounds.lonMin) * mPerLon, 1);
    const hM = Math.max((bounds.latMax - bounds.latMin) * M_PER_DEG, 1);
    const scale = Math.min((MAP_W - 2 * PAD) / wM, (MAP_H - 2 * PAD) / hM);
    const offX = (MAP_W - wM * scale) / 2;
    const offY = (MAP_H - hM * scale) / 2;
    return {
      toXY: (p: LatLon) => ({
        x: offX + (p.lon - bounds.lonMin) * mPerLon * scale,
        y: MAP_H - offY - (p.lat - bounds.latMin) * M_PER_DEG * scale,
      }),
      toLatLon: (x: number, y: number): LatLon => ({
        lon: bounds.lonMin + (x - offX) / (mPerLon * scale),
        lat: bounds.latMin + (MAP_H - offY - y) / (M_PER_DEG * scale),
      }),
    };
  }, [bounds]);

  const clientToView = useCallback((e: { clientX: number; clientY: number }) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }, []);

  // ── API mutations ───────────────────────────────────────────────────

  const api = useCallback(async (method: string, path: string, body?: unknown) => {
    const res = await fetch(`${AI_SERVICE_URL}${path}`, {
      method,
      headers: { ...getAuthHeaders(), ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = await res.json();
        if (typeof data?.detail === 'string') detail = data.detail;
        else if (data?.detail?.message) detail = `${data.detail.message}: ${(data.detail.issues || []).join(', ')}`;
      } catch { /* keep status */ }
      throw new Error(detail);
    }
    return res.json();
  }, [getAuthHeaders]);

  const handleSaveCamera = useCallback(async () => {
    if (!selected || selected.kind !== 'camera' || !selected.id) return;
    const lat = num(camForm.lat, NaN);
    const lon = num(camForm.lon, NaN);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      showNotice('err', 'Latitude and longitude are required');
      return;
    }
    setSaving(true);
    try {
      const updated = await api('PUT', `/tactical/cameras/${encodeURIComponent(selected.id)}/geo`, {
        lat, lon,
        headingDeg: num(camForm.heading, 0),
        fovDeg: num(camForm.fov, 60),
        rangeM: num(camForm.range, 250),
      });
      setOverview((ov) => ({
        ...ov,
        cameras: ov.cameras.map((c) => (c.cameraId === selected.id ? { ...c, ...updated } : c)),
      }));
      showNotice('ok', `Camera ${selected.id} placement saved`);
    } catch (e) {
      showNotice('err', e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [selected, camForm, api, showNotice]);

  const startDraw = useCallback((mode: 'line' | 'zone', target: EditTarget = null, seed?: LatLon[], seedName?: string) => {
    if (!canEdit) return;
    setDrawMode(mode);
    setEditTarget(target);
    setDraftPoints(seed ? [...seed] : []);
    setDraftName(seedName ?? '');
    setSelected(null);
    setPlaceMode(false);
  }, [canEdit]);

  const finishDraw = useCallback(async () => {
    if (!drawMode) return;
    const minPts = drawMode === 'line' ? 2 : 3;
    if (draftPoints.length < minPts) {
      showNotice('err', `Need at least ${minPts} points`);
      return;
    }
    const name = draftName.trim() || (editTarget ? '' : drawMode === 'line' ? 'Zero Line' : 'Buffer Zone');
    if (!name) {
      showNotice('err', 'Name is required');
      return;
    }
    setSaving(true);
    try {
      if (drawMode === 'line') {
        const path = editTarget && editTarget.kind === 'line'
          ? `/tactical/zero-lines/${encodeURIComponent(editTarget.id)}`
          : '/tactical/zero-lines';
        const row = await api(editTarget ? 'PUT' : 'POST', path, { name, points: draftPoints });
        setOverview((ov) => ({
          ...ov,
          zeroLines: editTarget
            ? ov.zeroLines.map((z) => (z.id === row.id ? row : z))
            : [...ov.zeroLines, row],
        }));
        showNotice('ok', editTarget ? 'Zero Line updated' : 'Zero Line created');
      } else {
        const path = editTarget && editTarget.kind === 'zone'
          ? `/tactical/buffer-zones/${encodeURIComponent(editTarget.id)}`
          : '/tactical/buffer-zones';
        const row = await api(editTarget ? 'PUT' : 'POST', path, { name, polygon: draftPoints });
        setOverview((ov) => ({
          ...ov,
          bufferZones: editTarget
            ? ov.bufferZones.map((z) => (z.id === row.id ? row : z))
            : [...ov.bufferZones, row],
        }));
        showNotice('ok', editTarget ? 'Buffer Zone updated' : 'Buffer Zone created');
      }
      setDrawMode(null); setEditTarget(null); setDraftPoints([]); setDraftName('');
    } catch (e) {
      showNotice('err', e instanceof Error ? e.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [drawMode, editTarget, draftPoints, draftName, api, showNotice]);

  const handleDelete = useCallback(async () => {
    if (!selected || selected.kind === 'camera' || !canEdit) return;
    const isLine = selected.kind === 'line';
    const path = isLine
      ? `/tactical/zero-lines/${encodeURIComponent(selected.id)}`
      : `/tactical/buffer-zones/${encodeURIComponent(selected.id)}`;
    setSaving(true);
    try {
      await api('DELETE', path);
      setOverview((ov) => (isLine
        ? { ...ov, zeroLines: ov.zeroLines.filter((z) => z.id !== selected.id) }
        : { ...ov, bufferZones: ov.bufferZones.filter((z) => z.id !== selected.id) }));
      setSelected(null);
      showNotice('ok', isLine ? 'Zero Line deleted' : 'Buffer Zone deleted');
    } catch (e) {
      showNotice('err', e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setSaving(false);
    }
  }, [selected, canEdit, api, showNotice]);

  // ── pointer interactions ────────────────────────────────────────────

  const onNodePointerDown = useCallback((e: React.PointerEvent, cam: CameraGeo) => {
    if (!canEdit) return;
    e.stopPropagation();
    dragCameraRef.current = cam.cameraId;
    if (cam.cameraId) {
      setSelected({ kind: 'camera', id: cam.cameraId });
      setCamForm({
        lat: fmt(cam.lat), lon: fmt(cam.lon),
        heading: fmt(cam.headingDeg, 1), fov: fmt(cam.fovDeg, 1), range: fmt(cam.rangeM, 0),
      });
    }
  }, [canEdit]);

  const onSvgPointerMove = useCallback((e: React.PointerEvent) => {
    const id = dragCameraRef.current;
    if (!id) return;
    const { x, y } = clientToView(e);
    const p = proj.toLatLon(x, y);
    suppressClickRef.current = true;
    setCamForm((f) => ({ ...f, lat: fmt(p.lat), lon: fmt(p.lon) }));
    setOverview((ov) => ({
      ...ov,
      cameras: ov.cameras.map((c) => (c.cameraId === id ? { ...c, lat: p.lat, lon: p.lon } : c)),
    }));
  }, [clientToView, proj]);

  const onSvgPointerUp = useCallback(() => {
    dragCameraRef.current = null;
    setTimeout(() => { suppressClickRef.current = false; }, 0);
  }, []);

  const onSvgClick = useCallback((e: React.MouseEvent) => {
    // Node/feature clicks handle their own selection — never deselect here.
    const target = e.target as Element | null;
    if (target?.closest?.('[data-node],[data-feature]')) return;
    if (suppressClickRef.current) return;
    const { x, y } = clientToView(e);
    const p = proj.toLatLon(x, y);
    if (placeMode) {
      setCamForm((f) => ({ ...f, lat: fmt(p.lat), lon: fmt(p.lon) }));
      setPlaceMode(false);
      showNotice('ok', 'Position picked — press Save to apply');
      return;
    }
    if (drawMode) {
      setDraftPoints((pts) => [...pts, p]);
      return;
    }
    setSelected(null);
  }, [clientToView, proj, placeMode, drawMode, showNotice]);

  const selectCamera = useCallback((cam: CameraGeo) => {
    if (!cam.cameraId) return;
    setSelected({ kind: 'camera', id: cam.cameraId });
    setCamForm({
      lat: fmt(cam.lat), lon: fmt(cam.lon),
      heading: fmt(cam.headingDeg, 1), fov: fmt(cam.fovDeg, 1), range: fmt(cam.rangeM, 0),
    });
  }, []);

  // ── derived render data ─────────────────────────────────────────────

  const placedCameras = overview.cameras.filter((c) => c.placed && c.lat != null && c.lon != null);
  const unplaced = overview.cameras.filter((c) => !c.placed);

  const linePath = (pts: LatLon[], close = false) => {
    if (pts.length === 0) return '';
    const d = pts.map((p, i) => {
      const { x, y } = proj.toXY(p);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return close ? `${d} Z` : d;
  };

  const selectedLine = selected?.kind === 'line' ? overview.zeroLines.find((z) => z.id === selected.id) : undefined;
  const selectedZone = selected?.kind === 'zone' ? overview.bufferZones.find((z) => z.id === selected.id) : undefined;
  const selectedCam = selected?.kind === 'camera' ? overview.cameras.find((c) => c.cameraId === selected.id) : undefined;

  const gridLines = useMemo(() => {
    const lines: { x1: number; y1: number; x2: number; y2: number; label: string }[] = [];
    const steps = 6;
    for (let i = 0; i <= steps; i++) {
      const lon = bounds.lonMin + ((bounds.lonMax - bounds.lonMin) * i) / steps;
      const a = proj.toXY({ lat: bounds.latMin, lon });
      const b = proj.toXY({ lat: bounds.latMax, lon });
      lines.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, label: `${lon.toFixed(3)}°E` });
      const lat = bounds.latMin + ((bounds.latMax - bounds.latMin) * i) / steps;
      const c = proj.toXY({ lat, lon: bounds.lonMin });
      const d = proj.toXY({ lat, lon: bounds.lonMax });
      lines.push({ x1: c.x, y1: c.y, x2: d.x, y2: d.y, label: `${lat.toFixed(3)}°N` });
    }
    return lines;
  }, [bounds, proj]);

  const layerChip = (key: keyof typeof layers, label: string) => (
    <button
      key={key}
      data-testid={`tactical-layer-${key}`}
      onClick={() => setLayers((l) => ({ ...l, [key]: !l[key] }))}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border cursor-pointer transition-colors ${
        layers[key]
          ? 'bg-primary/10 border-primary/40 text-primary'
          : 'bg-surface-container-high border-outline-variant text-on-surface-variant/60'
      }`}
    >
      <span className="material-symbols-outlined text-[13px]">
        {layers[key] ? 'visibility' : 'visibility_off'}
      </span>
      {label}
    </button>
  );

  const inputCls = 'w-full bg-surface-container-high border border-outline-variant rounded-md px-2 py-1.5 text-[12px] text-on-surface outline-none focus:border-primary/50';

  return (
    <div className="flex-1 flex flex-col h-[calc(100vh-3.5rem)]" data-testid="tactical-map">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-outline-variant bg-surface-container-low">
        <span className="material-symbols-outlined text-primary text-[20px] mr-1">map</span>
        <span className="text-[13px] font-bold text-on-surface tracking-wide mr-2">TACTICAL MAP — BORDER SECTOR</span>
        {layerChip('cameras', 'Cameras')}
        {layerChip('cones', 'Coverage')}
        {layerChip('lines', 'Zero Line')}
        {layerChip('zones', 'Buffer Zone')}
        <div className="flex-1" />
        {canEdit && !drawMode && (
          <>
            <button
              data-testid="tactical-draw-line"
              onClick={() => startDraw('line')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-error/10 text-error border border-error/30 cursor-pointer hover:bg-error/15 transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">timeline</span>
              Draw Zero Line
            </button>
            <button
              data-testid="tactical-draw-zone"
              onClick={() => startDraw('zone')}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-tertiary/10 text-tertiary border border-tertiary/30 cursor-pointer hover:bg-tertiary/15 transition-colors"
            >
              <span className="material-symbols-outlined text-[14px]">select_all</span>
              Draw Buffer Zone
            </button>
          </>
        )}
        <button
          data-testid="tactical-refresh"
          onClick={() => void loadOverview()}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-surface-container-high border border-outline-variant text-on-surface-variant cursor-pointer hover:text-on-surface transition-colors"
        >
          <span className={`material-symbols-outlined text-[14px] ${loading ? 'animate-spin' : ''}`}>refresh</span>
          Refresh
        </button>
      </div>

      {/* Drawing toolbar */}
      {drawMode && (
        <div className="flex flex-wrap items-center gap-3 px-4 py-2 bg-primary/5 border-b border-primary/20">
          <span className="text-[11px] font-semibold text-primary">
            {editTarget ? 'Editing' : 'Drawing'} {drawMode === 'line' ? 'Zero Line' : 'Buffer Zone'} — click the map to add points
            ({draftPoints.length}{drawMode === 'zone' ? ', min 3' : ', min 2'})
          </span>
          <input
            className={`${inputCls} w-48`}
            placeholder="Name"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            data-testid="tactical-draft-name"
          />
          <button
            onClick={() => setDraftPoints((p) => p.slice(0, -1))}
            disabled={draftPoints.length === 0}
            className="px-2.5 py-1 rounded-md text-[11px] bg-surface-container-high border border-outline-variant text-on-surface-variant disabled:opacity-40 cursor-pointer"
          >
            Undo point
          </button>
          <div className="flex-1" />
          <button
            data-testid="tactical-cancel-draw"
            onClick={() => { setDrawMode(null); setEditTarget(null); setDraftPoints([]); setDraftName(''); }}
            className="px-3 py-1.5 rounded-md text-[11px] font-semibold text-on-surface-variant border border-outline-variant cursor-pointer hover:bg-surface-container-high"
          >
            Cancel
          </button>
          <button
            data-testid="tactical-finish-draw"
            onClick={() => void finishDraw()}
            disabled={saving}
            className="px-3 py-1.5 rounded-md text-[11px] font-semibold bg-primary text-on-primary cursor-pointer disabled:opacity-50"
          >
            {saving ? 'Saving…' : editTarget ? 'Update' : 'Create'}
          </button>
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* Map */}
        <div className="flex-1 relative bg-surface-container-lowest min-w-0">
          {loadError && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-error">
              <span className="material-symbols-outlined text-[32px]">error</span>
              <span className="text-[13px] font-medium">{loadError}</span>
              <button onClick={() => void loadOverview()} className="px-3 py-1.5 text-[12px] rounded-md border border-error/40 cursor-pointer">Retry</button>
            </div>
          )}
          {!loadError && loading && overview.cameras.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-[13px]">Loading tactical layer…</div>
          )}
          {!loadError && (
            <svg
              ref={svgRef}
              viewBox={`0 0 ${MAP_W} ${MAP_H}`}
              className="w-full h-full block cursor-crosshair select-none"
              onClick={onSvgClick}
              onPointerMove={onSvgPointerMove}
              onPointerUp={onSvgPointerUp}
              data-testid="tactical-svg"
            >
              <rect x="0" y="0" width={MAP_W} height={MAP_H} fill="transparent" />
              {/* Grid */}
              {gridLines.map((g, i) => (
                <g key={i}>
                  <line x1={g.x1} y1={g.y1} x2={g.x2} y2={g.y2} stroke="currentColor" className="text-on-surface-variant/10" strokeWidth={0.5} />
                </g>
              ))}
              {/* Buffer zones */}
              {layers.zones && overview.bufferZones.map((z) => (
                <path
                  key={z.id}
                  d={linePath(z.polygon, true)}
                  fill={selected?.kind === 'zone' && selected.id === z.id ? 'rgba(245,158,11,0.28)' : 'rgba(245,158,11,0.14)'}
                  stroke="#f59e0b"
                  strokeWidth={2}
                  strokeDasharray="6 3"
                  className="cursor-pointer"
                  data-feature="1"
                  onClick={(e) => { e.stopPropagation(); if (!drawMode) setSelected({ kind: 'zone', id: z.id }); }}
                  data-testid={`tactical-zone-${z.id}`}
                />
              ))}
              {/* Zero lines */}
              {layers.lines && overview.zeroLines.map((z) => (
                <path
                  key={z.id}
                  d={linePath(z.points)}
                  fill="none"
                  stroke="#ef4444"
                  strokeWidth={selected?.kind === 'line' && selected.id === z.id ? 4 : 2.5}
                  strokeDasharray="10 6"
                  strokeLinecap="round"
                  className="cursor-pointer"
                  data-feature="1"
                  onClick={(e) => { e.stopPropagation(); if (!drawMode) setSelected({ kind: 'line', id: z.id }); }}
                  data-testid={`tactical-line-${z.id}`}
                />
              ))}
              {/* Coverage cones */}
              {layers.cones && placedCameras.map((c) => (
                <path
                  key={`cone-${c.cameraId}`}
                  d={linePath(c.cone, true)}
                  fill="rgba(34,197,94,0.14)"
                  stroke="rgba(34,197,94,0.55)"
                  strokeWidth={1}
                />
              ))}
              {/* Camera nodes */}
              {layers.cameras && placedCameras.map((c) => {
                const { x, y } = proj.toXY({ lat: c.lat as number, lon: c.lon as number });
                const headingRad = ((c.headingDeg - 90) * Math.PI) / 180;
                const tick = 14;
                const isSel = selected?.kind === 'camera' && selected.id === c.cameraId;
                return (
                  <g
                    key={c.cameraId}
                    data-node="1"
                    onPointerDown={(e) => onNodePointerDown(e, c)}
                    onClick={(e) => { e.stopPropagation(); if (!suppressClickRef.current && !drawMode) selectCamera(c); }}
                    className={canEdit ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'}
                    data-testid={`tactical-node-${c.cameraId}`}
                  >
                    <circle cx={x} cy={y} r={isSel ? 11 : 8} fill={isSel ? '#22c55e' : '#16a34a'} stroke="#ffffff" strokeWidth={2} />
                    <line
                      x1={x} y1={y}
                      x2={x + Math.cos(headingRad) * tick} y2={y + Math.sin(headingRad) * tick}
                      stroke="#22c55e" strokeWidth={2.5} strokeLinecap="round"
                    />
                    <text x={x + 12} y={y - 8} fontSize={11} fontWeight={600} className="fill-on-surface">
                      {c.name || c.cameraId}
                    </text>
                  </g>
                );
              })}
              {/* Draft geometry */}
              {drawMode && draftPoints.length > 0 && (
                <g>
                  <path
                    d={linePath(draftPoints, drawMode === 'zone' && draftPoints.length > 2)}
                    fill={drawMode === 'zone' && draftPoints.length > 2 ? 'rgba(139,92,246,0.18)' : 'none'}
                    stroke="#8b5cf6"
                    strokeWidth={2.5}
                    strokeDasharray="7 4"
                  />
                  {draftPoints.map((p, i) => {
                    const { x, y } = proj.toXY(p);
                    return <circle key={i} cx={x} cy={y} r={4} fill="#8b5cf6" stroke="#fff" strokeWidth={1.5} />;
                  })}
                </g>
              )}
              {/* Legend */}
              <g transform={`translate(12, ${MAP_H - 86})`}>
                <rect x="0" y="0" width="168" height="74" rx="6" fill="rgba(0,0,0,0.45)" />
                <line x1="10" y1="16" x2="34" y2="16" stroke="#ef4444" strokeWidth="2.5" strokeDasharray="8 5" />
                <text x="42" y="20" fontSize="10" className="fill-white">Zero Line</text>
                <rect x="10" y="27" width="24" height="10" fill="rgba(245,158,11,0.3)" stroke="#f59e0b" strokeDasharray="4 2" />
                <text x="42" y="36" fontSize="10" className="fill-white">Buffer Exclusion</text>
                <path d="M10,56 L34,46 L34,66 Z" fill="rgba(34,197,94,0.3)" stroke="#22c55e" />
                <text x="42" y="58" fontSize="10" className="fill-white">Coverage cone</text>
              </g>
            </svg>
          )}
          {/* Notice toast */}
          {notice && (
            <div
              data-testid="tactical-notice"
              className={`absolute top-3 left-1/2 -translate-x-1/2 px-4 py-2 rounded-lg text-[12px] font-semibold shadow-lg border ${
                notice.kind === 'ok'
                  ? 'bg-primary/15 border-primary/40 text-primary'
                  : 'bg-error/15 border-error/40 text-error'
              }`}
            >
              {notice.text}
            </div>
          )}
        </div>

        {/* Side panel */}
        <div className="w-[300px] border-l border-outline-variant bg-surface-container-low overflow-y-auto p-3 flex flex-col gap-3">
          {selectedCam && (
            <div className="rounded-lg border border-outline-variant bg-surface p-3 flex flex-col gap-2" data-testid="tactical-camera-panel">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-primary">videocam</span>
                <span className="text-[13px] font-bold text-on-surface">{selectedCam.name || selectedCam.cameraId}</span>
              </div>
              <label className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Latitude</label>
              <input className={inputCls} value={camForm.lat} onChange={(e) => setCamForm((f) => ({ ...f, lat: e.target.value }))} data-testid="tactical-lat" />
              <label className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Longitude</label>
              <input className={inputCls} value={camForm.lon} onChange={(e) => setCamForm((f) => ({ ...f, lon: e.target.value }))} data-testid="tactical-lon" />
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Heading°</label>
                  <input className={inputCls} value={camForm.heading} onChange={(e) => setCamForm((f) => ({ ...f, heading: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">FOV°</label>
                  <input className={inputCls} value={camForm.fov} onChange={(e) => setCamForm((f) => ({ ...f, fov: e.target.value }))} />
                </div>
                <div>
                  <label className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Range m</label>
                  <input className={inputCls} value={camForm.range} onChange={(e) => setCamForm((f) => ({ ...f, range: e.target.value }))} />
                </div>
              </div>
              <div className="flex gap-2 mt-1">
                <button
                  data-testid="tactical-save-camera"
                  onClick={() => void handleSaveCamera()}
                  disabled={saving || !canEdit}
                  className="flex-1 py-1.5 rounded-md text-[12px] font-semibold bg-primary text-on-primary cursor-pointer disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save placement'}
                </button>
                <button
                  onClick={() => setPlaceMode(true)}
                  disabled={!canEdit}
                  className="px-2 py-1.5 rounded-md text-[11px] border border-outline-variant text-on-surface-variant cursor-pointer disabled:opacity-50"
                  title="Pick position on map"
                >
                  <span className="material-symbols-outlined text-[14px]">my_location</span>
                </button>
              </div>
              {placeMode && (
                <span className="text-[11px] text-primary font-medium">Click the map to set position…</span>
              )}
            </div>
          )}

          {selectedLine && (
            <div className="rounded-lg border border-error/30 bg-error/5 p-3 flex flex-col gap-2" data-testid="tactical-line-panel">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-error">timeline</span>
                <span className="text-[13px] font-bold text-on-surface">{selectedLine.name}</span>
              </div>
              <span className="text-[11px] text-on-surface-variant">Zero Line · {selectedLine.points.length} points · {selectedLine.id}</span>
              <div className="flex gap-2">
                <button
                  onClick={() => canEdit && startDraw('line', { kind: 'line', id: selectedLine.id }, selectedLine.points, selectedLine.name)}
                  disabled={!canEdit}
                  className="flex-1 py-1.5 rounded-md text-[11px] font-semibold border border-outline-variant text-on-surface cursor-pointer disabled:opacity-50"
                >
                  Edit points
                </button>
                <button
                  data-testid="tactical-delete"
                  onClick={() => void handleDelete()}
                  disabled={saving || !canEdit}
                  className="flex-1 py-1.5 rounded-md text-[11px] font-semibold bg-error/15 text-error border border-error/30 cursor-pointer disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </div>
          )}

          {selectedZone && (
            <div className="rounded-lg border border-tertiary/30 bg-tertiary/5 p-3 flex flex-col gap-2" data-testid="tactical-zone-panel">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[16px] text-tertiary">select_all</span>
                <span className="text-[13px] font-bold text-on-surface">{selectedZone.name}</span>
              </div>
              <span className="text-[11px] text-on-surface-variant">
                Buffer Exclusion Zone · {selectedZone.polygon.length} vertices
                {selectedZone.bufferM != null ? ` · ${selectedZone.bufferM} m` : ''} · {selectedZone.id}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => canEdit && startDraw('zone', { kind: 'zone', id: selectedZone.id }, selectedZone.polygon, selectedZone.name)}
                  disabled={!canEdit}
                  className="flex-1 py-1.5 rounded-md text-[11px] font-semibold border border-outline-variant text-on-surface cursor-pointer disabled:opacity-50"
                >
                  Edit vertices
                </button>
                <button
                  data-testid="tactical-delete"
                  onClick={() => void handleDelete()}
                  disabled={saving || !canEdit}
                  className="flex-1 py-1.5 rounded-md text-[11px] font-semibold bg-error/15 text-error border border-error/30 cursor-pointer disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </div>
          )}

          {unplaced.length > 0 && (
            <div className="rounded-lg border border-outline-variant bg-surface p-3 flex flex-col gap-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Unplaced cameras</span>
              {unplaced.map((c) => (
                <div key={c.cameraId} className="flex items-center justify-between gap-2">
                  <span className="text-[12px] text-on-surface truncate">{c.name || c.cameraId}</span>
                  <button
                    onClick={() => { selectCamera(c); setPlaceMode(true); }}
                    disabled={!canEdit}
                    className="px-2 py-1 rounded text-[10px] font-semibold bg-primary/10 text-primary border border-primary/30 cursor-pointer disabled:opacity-50"
                  >
                    Place
                  </button>
                </div>
              ))}
            </div>
          )}

          {!selectedCam && !selectedLine && !selectedZone && (
            <div className="rounded-lg border border-outline-variant bg-surface p-3">
              <span className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">How to use</span>
              <ul className="mt-2 space-y-1.5 text-[11px] text-on-surface-variant list-disc pl-4">
                <li>Click a camera node to edit its placement, heading, FOV and range — or drag it.</li>
                <li>Draw a Zero Line / Buffer Zone on the map, then edit or delete it from its panel.</li>
                <li>Toggle layers with the chips above.</li>
              </ul>
            </div>
          )}

          <div className="mt-auto text-[10px] text-on-surface-variant/60 pt-2">
            {overview.updatedAt ? `Last sync ${new Date(overview.updatedAt).toLocaleTimeString()}` : ''}
            {!canEdit && ' · read-only role'}
          </div>
        </div>
      </div>
    </div>
  );
};

export default TacticalMapView;
