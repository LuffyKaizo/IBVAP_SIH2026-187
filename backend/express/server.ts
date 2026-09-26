import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';
import { createServer as createViteServer } from 'vite';
import { GoogleGenAI } from '@google/genai';
import { verifyToken, requireRole } from './auth';
import {
  INITIAL_CAMERAS,
  INITIAL_VIRTUAL_ZONES,
  INITIAL_DIAGNOSTICS,
  INITIAL_SETTINGS_CONFIG,
} from '../../frontend/src/mockData.ts';
import {
  CameraFeed,
  BorderAlert,
  AnprRecord,
  VirtualZone,
  SuspiciousEventItem,
  SurveillanceReportItem,
  SystemSettingsConfig,
} from '../../frontend/src/types.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load .env from project root (same file the Python backend uses)
dotenv.config({ path: path.resolve(__dirname, '../../.env') });

// In-memory data stores — start with only camera/zone/config from mockData;
// alerts, ANPR, reports, suspicious events start EMPTY (real data only)
let camerasStore: CameraFeed[] = [...INITIAL_CAMERAS];
let alertsStore: BorderAlert[] = [];
let anprRecordsStore: AnprRecord[] = [];
let zonesStore: VirtualZone[] = [...INITIAL_VIRTUAL_ZONES];
let suspiciousEventsStore: SuspiciousEventItem[] = [];
let reportsStore: SurveillanceReportItem[] = [];
let settingsStore: SystemSettingsConfig = { ...INITIAL_SETTINGS_CONFIG };

async function startServer() {
  const app = express();
  const PORT = 3000;

  app.use(express.json({ limit: '50mb' }));
  app.use(express.urlencoded({ extended: true, limit: '50mb' }));

  // --- IBVAP Auth Routes ---

  // Healthcheck (public)
  app.get('/api/health', (_req, res) => {
    res.json({
      status: 'ok',
      platform: 'IBVAP - Intelligent Border Video Analytics Platform',
      version: '4.2.0-PROD',
      time: new Date().toISOString(),
    });
  });

  // Login (public - handled by Python backend via proxy, but also available here)
  app.post('/api/auth/login', express.json(), async (req, res) => {
    try {
      const { email, password } = req.body;
      if (!email || !password) {
        return res.status(400).json({ detail: 'Email and password required' });
      }
      // Forward to Python AI service auth endpoint
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch (err) {
      res.status(502).json({ detail: 'Auth service unavailable' });
    }
  });

  // Screening-mode auto-login (public — only when SCREENING_MODE=true)
  app.post('/api/auth/screening-login', express.json(), async (_req, res) => {
    if (process.env.SCREENING_MODE !== 'true') {
      return res.status(404).json({ detail: 'Screening mode not enabled' });
    }
    try {
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/auth/screening-login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch (err) {
      res.status(502).json({ detail: 'Auth service unavailable' });
    }
  });

  // Get current user (authenticated)
  app.get('/api/auth/me', verifyToken, (req, res) => {
    res.json({
      user_id: req.user!.user_id,
      email: req.user!.email,
      role: req.user!.role,
    });
  });

  // --- IBVAP Protected API Routes ---

  const AI_URL = process.env.AI_SERVICE_URL || 'http://localhost:8000';

  // Helper: proxy request to Python AI backend, forwarding auth header
  async function proxyToAI(reqPath: string, req: express.Request, res: express.Response) {
    try {
      const resp = await fetch(AI_URL + reqPath, {
        method: req.method,
        headers: {
          'Content-Type': 'application/json',
          ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
        },
        body: req.method !== 'GET' && req.method !== 'HEAD' ? JSON.stringify(req.body) : undefined,
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch (err) {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  }

  // System overview status — proxy to FastAPI
  app.get('/api/status', verifyToken, (req, res) => {
    proxyToAI('/status', req, res);
  });

  // KPI Dashboard Stats — combine Express in-memory stores with AI backend counts
  app.get('/api/dashboard/stats', verifyToken, async (_req, res) => {
    try {
      // Get real camera count from FastAPI
      const camResp = await fetch(AI_URL + '/cameras', {
        headers: { Authorization: _req.headers.authorization || '' },
      });
      const camData = camResp.ok ? await camResp.json() : [];
      const cameras = Array.isArray(camData) ? camData : [];

      // Get alerts from Express in-memory store
      const activeAlerts = alertsStore.filter(a => a.status === 'ACTIVE').length;

      res.json({
        activeCameras: cameras.filter((c: any) => c.status === 'ONLINE' || c.enabled !== false).length,
        totalCameras: cameras.length,
        peopleDetected: 0,
        vehiclesDetected: 0,
        activeAlerts,
        anprEvents: anprRecordsStore.length,
        intrusionEvents: alertsStore.filter(a => a.eventType === 'BORDER_INTRUSION').length,
        systemHealthPercent: 0,
        alertsBySeverity: { critical: 0, high: 0, medium: 0, info: 0 },
      });
    } catch {
      // Fallback to Express stores
      const activeAlerts = alertsStore.filter(a => a.status === 'ACTIVE').length;
      res.json({
        activeCameras: camerasStore.filter(c => c.status === 'ONLINE').length,
        totalCameras: camerasStore.length,
        peopleDetected: 0,
        vehiclesDetected: 0,
        activeAlerts,
        anprEvents: anprRecordsStore.length,
        intrusionEvents: alertsStore.filter(a => a.eventType === 'BORDER_INTRUSION').length,
        systemHealthPercent: 0,
        alertsBySeverity: { critical: 0, high: 0, medium: 0, info: 0 },
      });
    }
  });

  // Discover video files on disk for camera source registration — proxy to FastAPI
  app.get('/api/videos', verifyToken, async (req, res) => {
    const folder = typeof req.query.folder === 'string' ? req.query.folder : undefined;
    const qs = folder ? `?folder=${encodeURIComponent(folder)}` : '';
    try {
      const resp = await fetch(AI_URL + '/videos' + qs, {
        headers: { Authorization: req.headers.authorization || '' },
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  });

  // Camera feeds list — proxy to FastAPI for real camera data
  app.get('/api/cameras', verifyToken, async (req, res) => {
    try {
      const resp = await fetch(AI_URL + '/cameras', {
        headers: { Authorization: req.headers.authorization || '' },
      });
      const data = await resp.json();
      // FastAPI returns list of camera info dicts — normalize for frontend
      if (Array.isArray(data)) {
        const normalized = data.map((cam: any) => ({
          id: cam.camera_id || cam.id || 'CAM-01',
          name: cam.name || cam.camera_id || 'Unknown Camera',
          sector: cam.sector || 'Border Sector',
          rtspUrl: cam.source || cam.rtspUrl || '',
          sourceType: cam.source_type || cam.sourceType || 'rtsp',
          location: cam.location || '',
          coordinates: cam.coordinates || '0.0000 N, 0.0000 W',
          fps: cam.fps || 30,
          resolution: cam.resolution || '1080p',
          bitrate: cam.bitrate || '4.0 Mbps',
          status: cam.enabled !== false ? 'ONLINE' : 'OFFLINE',
          isNightMode: false,
          ptzSupport: cam.camera_type === 'PTZ',
          videoPosterUrl: '',
          activeAlertCount: 0,
          detections: [],
        }));
        res.json(normalized);
      } else {
        res.json(camerasStore);
      }
    } catch (err) {
      res.json(camerasStore);
    }
  });

  // Single Camera feed — proxy to FastAPI
  app.get('/api/cameras/:id', verifyToken, async (req, res) => {
    try {
      const { id } = req.params;
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/cameras/${id}`, {
        headers: { Authorization: req.headers.authorization || '' },
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  });

  // Register a new camera — proxy to FastAPI (ADMIN only)
  app.post('/api/cameras', verifyToken, requireRole('ADMIN'), async (req, res) => {
    try {
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/cameras`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
        },
        body: JSON.stringify(req.body),
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  });

  // Update camera — proxy to FastAPI (ADMIN only)
  app.patch('/api/cameras/:id', verifyToken, requireRole('ADMIN'), async (req, res) => {
    try {
      const { id } = req.params;
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/cameras/${id}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
        },
        body: JSON.stringify(req.body),
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  });

  // Delete camera — proxy to FastAPI (ADMIN only)
  app.delete('/api/cameras/:id', verifyToken, requireRole('ADMIN'), async (req, res) => {
    try {
      const { id } = req.params;
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/cameras/${id}`, {
        method: 'DELETE',
        headers: { Authorization: req.headers.authorization || '' },
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  });

  // Toggle AI processing for a camera (ADMIN only — proxy to FastAPI)
  app.post('/api/cameras/:id/ai-toggle', verifyToken, requireRole('ADMIN'), async (req, res) => {
    try {
      const { id } = req.params;
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/cameras/${id}/ai-toggle`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
        },
        body: JSON.stringify(req.body),
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch (err) {
      res.status(502).json({ detail: 'AI backend unavailable' });
    }
  });

  // Alerts list & filtered query — proxy to FastAPI for real persisted events
  app.get('/api/alerts', verifyToken, async (req, res) => {
    try {
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const qs = new URLSearchParams();
      if (req.query.severity) qs.set('severity', String(req.query.severity));
      if (req.query.camera) qs.set('camera', String(req.query.camera));
      qs.set('limit', '200');
      const resp = await fetch(`${aiUrl}/alerts?${qs.toString()}`, {
        headers: {
          ...(req.headers.authorization ? { Authorization: req.headers.authorization } : {}),
        },
      });
      if (!resp.ok) throw new Error(`AI service responded ${resp.status}`);
      const data = await resp.json();
      const alerts = Array.isArray(data?.alerts) ? data.alerts : [];
      res.json(alerts);
    } catch {
      // AI backend unavailable — fall back to the in-memory store
      res.json(alertsStore);
    }
  });

  // Acknowledge or resolve an alert (ADMIN, OPERATOR)
  app.post('/api/alerts/:id/action', verifyToken, requireRole('ADMIN', 'OPERATOR'), (req, res) => {
    const { id } = req.params;
    const { action } = req.body; // 'ACKNOWLEDGE' | 'RESOLVE' | 'DISMISS'
    const alertIndex = alertsStore.findIndex(a => a.id.toLowerCase() === id.toLowerCase());

    if (alertIndex !== -1) {
      alertsStore[alertIndex].status = action === 'RESOLVE' ? 'RESOLVED' : 'ACKNOWLEDGED';
      return res.json({ success: true, alert: alertsStore[alertIndex] });
    }
    res.status(404).json({ error: 'Alert not found' });
  });

  // ANPR Records
  app.get('/api/anpr', verifyToken, (req, res) => {
    const search = ((req.query.search as string) || '').toLowerCase();
    const status = (req.query.status as string) || 'ALL';

    let filtered = anprRecordsStore.filter(record => {
      if (search) {
        const matches =
          record.plateNumber.toLowerCase().includes(search) ||
          record.vehicleType.toLowerCase().includes(search) ||
          record.cameraName.toLowerCase().includes(search);
        if (!matches) return false;
      }
      if (status !== 'ALL') {
        if (record.status.toLowerCase() !== status.toLowerCase()) return false;
      }
      return true;
    });

    res.json({
      records: filtered,
      total: filtered.length,
      watchlistCount: anprRecordsStore.filter(r => r.status === 'WATCHLIST').length,
    });
  });

  // Add ANPR Record / Manual Vehicle Scan (ADMIN, OPERATOR)
  app.post('/api/anpr/scan', verifyToken, requireRole('ADMIN', 'OPERATOR'), (req, res) => {
    const { plateNumber, vehicleType, cameraId, confidence } = req.body;
    if (!plateNumber) {
      return res.status(400).json({ error: 'plateNumber is required' });
    }
    const newRecord: AnprRecord = {
      id: `ANPR-${Date.now()}`,
      timestamp: new Date().toISOString().substring(11, 19) + ' UTC',
      plateNumber: plateNumber.toUpperCase(),
      vehicleType: vehicleType || 'Unknown',
      confidence: confidence || 0,
      cameraId: cameraId || 'CAM-01',
      cameraName: camerasStore.find(c => c.id === cameraId)?.name || 'Unknown Camera',
      status: 'UNREGISTERED',
      direction: 'Restricted Zone',
      snapshotUrl: '',
    };
    anprRecordsStore.unshift(newRecord);
    res.json({ success: true, record: newRecord });
  });

  // Virtual Zones — proxy to FastAPI for real zone data
  app.get('/api/zones', verifyToken, async (req, res) => {
    try {
      const resp = await fetch(AI_URL + '/zones', {
        headers: { Authorization: req.headers.authorization || '' },
      });
      const data = await resp.json();
      // FastAPI returns { zones: [...] } format
      if (data && Array.isArray(data.zones)) {
        res.json(data);
      } else {
        res.json(zonesStore);
      }
    } catch {
      res.json(zonesStore);
    }
  });

  // Save / Update Virtual Zone (ADMIN, OPERATOR)
  // Proxies to FastAPI /zones (upsert) so zones persist in the database and
  // the live AI pipelines pick them up. In-memory store is a fallback only
  // when the AI backend is unreachable.
  app.post('/api/zones', verifyToken, requireRole('ADMIN', 'OPERATOR'), async (req, res) => {
    try {
      const resp = await fetch(AI_URL + '/zones', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: req.headers.authorization || '',
        },
        body: JSON.stringify(req.body),
      });
      const data = await resp.json().catch(() => ({}));
      res.status(resp.status).json(data);
      return;
    } catch {
      // Fallback: AI backend unreachable — keep legacy in-memory behavior
    }
    const newZone: VirtualZone = {
      id: req.body.id || `ZONE-${Date.now().toString(36).toUpperCase()}`,
      name: req.body.name || `CUSTOM_ZONE_${zonesStore.length + 1}`,
      cameraId: req.body.cameraId || req.body.camera_id || 'CAM-04',
      type: req.body.type || req.body.zone_type || 'POLYGON_ZONE',
      coordinates: req.body.coordinates || (req.body.points || []).map((p: any) => ({ x: p.x * 100, y: p.y * 100 })),
      severity: req.body.severity || 'HIGH',
      rule: req.body.rule || 'RESTRICTED_ENTRY',
      loiteringThresholdSec: req.body.loiteringThresholdSec || 20,
      isActive: req.body.enabled !== false,
      color: req.body.severity === 'CRITICAL' ? '#ef4444' : req.body.severity === 'HIGH' ? '#f97316' : '#eab308',
    };
    zonesStore.push(newZone);
    res.json({ success: true, zone: newZone });
  });

  // Delete Virtual Zone (ADMIN, OPERATOR) — proxied so the live pipeline
  // stops evaluating the deleted zone immediately.
  app.delete('/api/zones/:id', verifyToken, requireRole('ADMIN', 'OPERATOR'), async (req, res) => {
    const id = String(req.params.id || '');
    try {
      const resp = await fetch(AI_URL + '/zones/' + encodeURIComponent(id), {
        method: 'DELETE',
        headers: { Authorization: req.headers.authorization || '' },
      });
      const data = await resp.json().catch(() => ({}));
      res.status(resp.status).json(data);
      return;
    } catch {
      // Fallback: AI backend unreachable — legacy in-memory behavior
    }
    zonesStore = zonesStore.filter(z => z.id !== id);
    res.json({ success: true });
  });

  // Suspicious Events & Night Monitoring
  app.get('/api/events/suspicious', verifyToken, (_req, res) => {
    res.json(suspiciousEventsStore);
  });

  // 24-Hour Surveillance Density & Activity Analytics — empty until live data arrives
  app.get('/api/analytics/activity', verifyToken, (_req, res) => {
    res.json({
      hourly: Array.from({ length: 24 }, (_, i) => ({
        hour: `${String(i).padStart(2, '0')}:00`,
        peopleCount: 0,
        vehicleCount: 0,
        alerts: 0,
        anprHits: 0,
        intrusionBreaches: 0,
        nightActivityIndex: 0,
        density: 0,
      })),
      summary: {
        peakHour: null,
        peakDensity: 0,
        totalPeopleCount: 0,
        totalVehicleCount: 0,
        totalAlerts: 0,
        activeNightCurfew: '22:00 - 05:00 UTC',
      },
    });
  });

  // Surveillance Reports
  app.get('/api/reports', verifyToken, (_req, res) => {
    res.json(reportsStore);
  });

  // Generate Report (ADMIN, OPERATOR)
  app.post('/api/reports/generate', verifyToken, requireRole('ADMIN', 'OPERATOR'), (req, res) => {
    const { title, type, camera, analystNotes } = req.body;
    const newReport: SurveillanceReportItem = {
      id: `REP-2026-${String(reportsStore.length + 1).padStart(3, '0')}`,
      title: title || 'Border Video Analytics Incident Report',
      type: type || 'INCIDENT_DOSSIER',
      date: new Date().toISOString().replace('T', ' ').substring(0, 16) + ' UTC',
      camera: camera || 'CAM-04 (SECTOR WEST FENCE LINE)',
      severity: 'HIGH',
      evidence: [
        'Automated YOLOv8 object bounding boxes verified',
        'ByteTrack persistent ID trajectory recorded',
        'Virtual perimeter breach verified with 95% confidence',
      ],
      summary: 'Automated video analytics report generated by IBVAP intelligence engine.',
      analystNotes: analystNotes || 'Command review completed. Sector patrols notified.',
      generatedBy: 'COMMAND_OFFICER_01',
    };
    reportsStore.unshift(newReport);
    res.json({ success: true, report: newReport });
  });

  // System Diagnostics Run (ADMIN, OPERATOR)
  app.post('/api/diagnostics/run', verifyToken, requireRole('ADMIN', 'OPERATOR'), (_req, res) => {
    const results = INITIAL_DIAGNOSTICS.map(item => ({
      ...item,
    }));

    res.json({
      success: true,
      executionTimestamp: new Date().toISOString(),
      overallStatus: 'OPTIMAL',
      totalSubsystemsChecked: results.length,
      averageLatencyMs: Math.round(results.reduce((acc, r) => acc + r.latencyMs, 0) / results.length),
      results,
    });
  });

  // Settings Configuration
  app.get('/api/settings', verifyToken, (_req, res) => {
    res.json(settingsStore);
  });

  app.post('/api/settings', verifyToken, requireRole('ADMIN'), (req, res) => {
    settingsStore = { ...settingsStore, ...req.body };
    res.json({ success: true, settings: settingsStore });
  });

  // Interactive Live Demo Simulation Trigger (ADMIN, OPERATOR)
  app.post('/api/demo/simulate-step', verifyToken, requireRole('ADMIN', 'OPERATOR'), (req, res) => {
    const { step } = req.body;
    let message = 'Demo step executed — connect to AI backend for real detections';

    res.json({
      success: true,
      message,
      alertsCount: alertsStore.length,
      anprCount: anprRecordsStore.length,
    });
  });

  // AI Multimodal Surveillance Frame Ingestion
  app.post('/api/analyze-frame', verifyToken, async (req, res) => {
    try {
      const { fileData, cameraName } = req.body;
      let detections: any[] = [];

      // If Gemini API is available and image data is provided, analyze with Gemini
      if (process.env.GEMINI_API_KEY && fileData && fileData.startsWith('data:image')) {
        try {
          const ai = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
          const base64Data = fileData.split(',')[1];
          const mimeType = fileData.split(';')[0].split(':')[1] || 'image/jpeg';

          const response = await ai.models.generateContent({
            model: 'gemini-2.5-flash',
            contents: [
              {
                role: 'user',
                parts: [
                  {
                    text: `Analyze this CCTV surveillance video frame for the IBVAP Intelligent Border Surveillance system.
                     Return a JSON object with:
                     - peopleCount: number
                     - vehicleCount: number
                     - detectedObjects: array of { id: string, trackId: string (e.g. "#17"), classType: "person" | "vehicle", confidence: number (70-99), x: number (0-80), y: number (0-80), w: number (10-40), h: number (10-50), isThreat: boolean, direction: string, zone: string }
                     - securityAlert: { required: boolean, severity: "CRITICAL" | "HIGH" | "MEDIUM", title: string, reason: string }
                     Format strictly as valid JSON.`,
                  },
                  {
                    inlineData: {
                      mimeType: mimeType,
                      data: base64Data,
                    },
                  },
                ],
              },
            ],
          });

          const textResult = response.text || '';
          const jsonMatch = textResult.match(/\{[\s\S]*\}/);
          if (jsonMatch) {
            const parsed = JSON.parse(jsonMatch[0]);
            if (Array.isArray(parsed.detectedObjects) && parsed.detectedObjects.length > 0) {
              detections = parsed.detectedObjects.map((d: any, i: number) => ({
                id: d.id || `DET-AI-0${i + 1}`,
                trackId: d.trackId || `#${Math.floor(10 + i * 7)}`,
                classType: d.classType || 'person',
                confidence: d.confidence || 93,
                bbox: { x: d.x || 30 + i * 20, y: d.y || 30 + i * 15, w: d.w || 15, h: d.h || 35 },
                direction: d.direction || 'North-East',
                zone: d.zone || 'Perimeter Buffer',
                status: 'Moving',
                isThreat: d.isThreat !== undefined ? d.isThreat : true,
              }));
            }
          }
        } catch (geminiErr) {
          console.warn('Gemini vision frame analysis warning (using fallback):', geminiErr);
        }
      }

      res.json({
        success: true,
        camera: cameraName || 'CAM-04 SECTOR WEST',
        timestamp: new Date().toISOString(),
        detections,
      });
    } catch (err) {
      console.error('Frame analysis error:', err);
      res.status(500).json({ error: 'Failed to analyze frame' });
    }
  });

  // --- IBVAP Network Health Proxy Routes ---

  app.get('/api/network/status', verifyToken, async (req, res) => {
    try {
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/network/status`, {
        headers: { 'Authorization': req.headers.authorization || '' },
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch (err) {
      res.status(502).json({ detail: 'Network health service unavailable' });
    }
  });

  app.post('/api/network/check', verifyToken, requireRole('ADMIN', 'OPERATOR'), async (req, res) => {
    try {
      const aiUrl = process.env.AI_SERVICE_URL || 'http://localhost:8000';
      const resp = await fetch(`${aiUrl}/network/check`, {
        method: 'POST',
        headers: { 'Authorization': req.headers.authorization || '' },
      });
      const data = await resp.json();
      res.status(resp.status).json(data);
    } catch (err) {
      res.status(502).json({ detail: 'Network health service unavailable' });
    }
  });

  // Vite Middleware for development vs Static serving for production
  if (process.env.NODE_ENV !== 'production') {
    const frontendRoot = path.resolve(__dirname, '../../frontend');
    const vite = await createViteServer({
      root: frontendRoot,
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'frontend', 'dist');
    app.use(express.static(distPath));
    app.get('*', (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`[IBVAP SERVER] Intelligent Border Video Analytics Platform running on http://0.0.0.0:${PORT}`);
  });
}

startServer();
