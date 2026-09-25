export type AlertSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'INFO' | 'NORMAL';

export type CameraStatus = 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'RECONNECTING' | 'SYNCHRONIZING';

export type ObjectClass = 'person' | 'vehicle' | 'face' | 'license_plate';

export interface BoundingBox {
  x: number; // percentage 0-100
  y: number; // percentage 0-100
  w: number; // percentage 0-100
  h: number; // percentage 0-100
}

export interface TrackedDetection {
  id: string;
  trackId: string; // e.g. "#17"
  classType: ObjectClass;
  confidence: number; // 0-100
  bbox: BoundingBox;
  direction: string; // e.g. "North-East", "Towards Fence", "Stationary"
  zone: string; // e.g. "Restricted Zone 1", "Buffer Sector B"
  status: 'Moving' | 'Loitering' | 'Stationary' | 'Crossing';
  speedKmh?: number;
  plateNumber?: string;
  isThreat?: boolean;
}

export interface CameraFeed {
  id: string; // e.g. "CAM-01"
  name: string; // e.g. "BOP NORTH"
  sector: string; // e.g. "Sector Alpha - Post 4"
  rtspUrl: string; // e.g. "rtsp://192.168.1.101:554/live/ch0"
  location: string; // e.g. "North Perimeter Gate"
  coordinates: string; // e.g. "34.0522° N, 118.2437° W"
  fps: number;
  resolution: string; // e.g. "1080p @ 30fps"
  bitrate: string; // e.g. "4.2 Mbps"
  status: CameraStatus;
  isNightMode: boolean;
  ptzSupport: boolean;
  videoPosterUrl: string;
  detections: TrackedDetection[];
  activeAlertCount: number;
}

export interface BorderAlert {
  id: string; // e.g. "ALT-8821"
  timestamp: string; // e.g. "02:14:37 UTC"
  timeAgo?: string;
  cameraId: string;
  cameraName: string;
  eventType: 'BORDER_INTRUSION' | 'NIGHT_MOVEMENT' | 'RESTRICTED_ZONE_VEHICLE' | 'LOITERING' | 'REPEATED_CROSSING' | 'STOPPED_VEHICLE' | 'SUSPICIOUS_ACTIVITY';
  title: string;
  /** Exact operator-facing incident sentence (AI alerts), e.g.
   * "Person #2 entered Intrusion Zone 'Gate 3 Restricted Area' on CAM-05." */
  message?: string;
  severity: AlertSeverity;
  trackId: string;
  confidence: number;
  evidenceChecklist: string[];
  reason: string;
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED';
  zone: string;
  snapshotUrl?: string;
  source?: 'AI' | 'SYSTEM' | 'OPERATOR';
  riskScore?: number;
  riskSeverity?: string;
  riskFactors?: { factor: string; points: number }[];
  dwellSeconds?: number;
  loitering?: boolean;
  fenceProximity?: boolean;
  direction?: string;
  repeatedEntry?: boolean;
}

export interface AnprRecord {
  id: string;
  timestamp: string;
  plateNumber: string;
  vehicleType: 'Sedan' | 'SUV' | 'Truck' | 'Motorcycle' | 'Pickup' | 'Van';
  confidence: number;
  cameraId: string;
  cameraName: string;
  status: 'WHITELIST' | 'WATCHLIST' | 'UNREGISTERED';
  direction: 'Incoming' | 'Outgoing' | 'Restricted Zone';
  snapshotUrl?: string;
  /** AI-origin markers (mock records never set these). */
  ai?: boolean;
  /** Plate text is a format-validated correction of raw OCR (inferred). */
  corrected?: boolean;
  /** Raw OCR reading preserved for traceability (pre-correction). */
  rawPlateText?: string;
}

export interface VirtualZone {
  id: string;
  name: string;
  cameraId: string;
  type: 'POLYGON_ZONE' | 'TRIPWIRE_LINE';
  coordinates: { x: number; y: number }[]; // percentage 0-100
  severity: AlertSeverity;
  rule: 'RESTRICTED_ENTRY' | 'RESTRICTED_EXIT' | 'BI_DIRECTIONAL' | 'LOITERING_ONLY';
  loiteringThresholdSec: number;
  isActive: boolean;
  color: string;
}

export interface SuspiciousEventItem {
  id: string;
  eventType: string;
  trackId: string;
  cameraId: string;
  cameraName: string;
  durationSec: number;
  zone: string;
  riskLevel: AlertSeverity;
  timestamp: string;
  details: string;
  evidenceTags: string[];
}

export interface HourlySurveillanceActivity {
  hour: string; // "00:00", "01:00", ...
  hourNum: number;
  peopleCount: number;
  vehicleCount: number;
  alertsCount: number;
  anprHits: number;
  intrusionBreaches: number;
  nightActivityIndex: number; // 0-100
  totalDensity: number; // 0-100
}

export interface DashboardKpiStats {
  activeCameras: number;
  totalCameras: number;
  peopleDetected: number;
  vehiclesDetected: number;
  activeAlerts: number;
  anprEvents: number;
  intrusionEvents: number;
  systemHealthPercent: number;
  alertsBySeverity: {
    critical: number;
    high: number;
    medium: number;
    info: number;
  };
}

export interface DiagnosticsCheckItem {
  id: string;
  name: string;
  category: 'VIDEO_STREAM' | 'AI_INFERENCE' | 'TRACKING_ENGINE' | 'ANPR_OCR' | 'EVENT_ENGINE' | 'STORAGE_BUFFER';
  status: 'OPTIMAL' | 'DEGRADED' | 'CHECKING' | 'FAULT';
  latencyMs: number;
  throughput: string;
  integrityScore: number;
  details: string;
}

export interface SurveillanceReportItem {
  id: string;
  title: string;
  type: 'DAILY_SURVEILLANCE' | 'INCIDENT_DOSSIER' | 'INTRUSION_BREACH' | 'ANPR_TRAFFIC' | 'CAMERA_HEALTH';
  date: string;
  camera: string;
  severity: AlertSeverity;
  evidence: string[];
  summary: string;
  analystNotes: string;
  generatedBy: string;
}

export interface SystemSettingsConfig {
  yoloModel: string;
  confidenceThreshold: number;
  trackingMatchIntervalMs: number;
  ocrThreshold: number;
  faceDetectionEnabled: boolean;
  intrusionSensitivity: number;
  loiteringThresholdSec: number;
  nightHoursStart: string;
  nightHoursEnd: string;
  rtspBufferSizeMb: number;
  apiBaseUrl: string;
  apiAuthToken: string;
}

export type IbvapDashboardStats = DashboardKpiStats;

export interface SystemNode {
  id: string;
  name: string;
  status: string;
  pingMs: number;
  load: number;
}



export interface AiTrackedObject {
  track_id: number;
  class_id: number;
  class_name: string;
  confidence: number;
  bbox: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  };
}

export interface AiTrackingMetadata {
  camera_id: string;
  timestamp: string;
  source: string;
  frame_width: number;
  frame_height: number;
  detections: AiTrackedObject[];
  active_tracks: number;
  inference_time_ms: number;
  alerts: AiAlert[];
  anpr?: AiAnprRecord[];
  faces?: AiFaceDetection[];
  /** Whether AI processing is currently enabled on this camera. */
  ai_enabled?: boolean;
  /** Capture-layer health (RTSP/CCTV), present when the pipeline runs. */
  camera?: AiCameraHealth;
  track_context?: TrackContext[];
  /** Active security events (incl. zone intrusion) from the AI event engine. */
  events?: AiSecurityEvent[];
}

/** Serialized SecurityEvent from the backend event engine (pipeline metadata). */
export interface AiSecurityEvent {
  event_id: string;
  event_type: string;
  severity: string;
  camera_id: string;
  zone_id: string;
  zone_name: string;
  track_id: number;
  object_class: string;
  timestamp: string;
  confidence: number;
  bbox: {
    x1: number;
    y1: number;
    x2: number;
    y2: number;
  };
  status: 'DETECTED' | 'ACTIVE' | 'RESOLVED';
}

export interface TrackContext {
  track_id: number;
  object_class: string;
  dwell_seconds: number;
  loitering: boolean;
  fence_proximity: boolean;
  distance_to_fence: number;
  direction: string;
  repeated_entry: boolean;
  entry_count: number;
}

/** Camera/ingestion health reported by the AI capture layer. */
export interface AiCameraHealth {
  connected: boolean;
  sourceType: string;
  source: string; // credential-masked
  status: 'CONNECTED' | 'CONNECTING' | 'RECONNECTING' | 'STALE' | 'DISCONNECTED' | 'STOPPED' | 'ERROR';
  fps: number;
  measuredSourceFps: number;
  frameWidth: number;
  frameHeight: number;
  lastFrameTimestamp: number | null;
  reconnectCount: number;
  lastError: string | null;
  /** SD-card sync state: IDLE | SYNCING | COMPLETED | FAILED */
  syncState?: string;
  /** Pending footage count on SD card */
  pendingFootageCount?: number;
}

export interface AiAlert {
  id: string;
  timestamp: string;
  cameraId: string;
  cameraName: string;
  eventType: string;
  title: string;
  /** Exact operator-facing incident sentence (absent on non-intrusion events). */
  message?: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'INFO';
  trackId: string;
  confidence: number;
  zone: string;
  reason: string;
  evidenceChecklist: string[];
  status: 'ACTIVE' | 'ACKNOWLEDGED' | 'RESOLVED';
  source: 'AI' | 'SYSTEM' | 'OPERATOR';
  riskScore?: number;
  riskSeverity?: string;
  riskFactors?: { factor: string; points: number }[];
  dwellSeconds?: number;
  loitering?: boolean;
  fenceProximity?: boolean;
  direction?: string;
  repeatedEntry?: boolean;
}


export interface AiAnprRecord {
  id: string;
  trackId: number;
  cameraId: string;
  vehicleClass: string;
  plateText: string | null;
  plateConfidence: number;
  ocrConfidence: number | null;
  vehicleBbox: { x1: number; y1: number; x2: number; y2: number };
  plateBbox?: { x1: number; y1: number; x2: number; y2: number } | null;
  status: 'DETECTED' | 'RECOGNIZED' | 'CONFIRMED' | 'UNREADABLE';
  timestamp: string;
  source: 'AI';
  /** Traceability / correction metadata (additive, may be absent). */
  rawOcrText?: string | null;
  corrected?: boolean;
  formatStatus?: 'VALID' | 'INVALID' | 'UNCERTAIN' | null;
  observationCount?: number | null;
}

export interface AiCameraStatus {
  camera_id: string;
  video_connected: boolean;
  ai_processing: boolean;
  processing_fps: number;
  source_fps: number;
  resolution: string;
  frames_processed: number;
  total_detections: number;
  websocket_clients: number;
  /** Capture-layer health (present when a capture session exists). */
  camera?: AiCameraHealth;
}

/** AI face DETECTION record (no recognition / no identity). */
export interface AiFaceDetection {
  id: string;
  personTrackId: number | null;
  confidence: number;
  bbox: { x1: number; y1: number; x2: number; y2: number }; // normalized 0..1
  timestamp: string;
  source: 'AI';
}

// --- Network Health (Section 13) ---

export type NetworkHealthState = 'CONNECTED' | 'DEGRADED' | 'OFFLINE' | 'RECOVERING';

export interface NetworkHealthStatus {
  state: NetworkHealthState;
  central_reachable: boolean;
  latency_ms: number;
  average_latency_ms: number;
  min_latency_ms: number;
  max_latency_ms: number;
  consecutive_failures: number;
  consecutive_successes: number;
  last_success_at: string | null;
  last_failure_at: string | null;
  offline_since: string | null;
  recovery_started_at: string | null;
  checks_performed: number;
  sync_pending: number;
  sync_failed: number;
}

// --- Blockchain Trust Layer (Pre-Section 15A Retrofit) ---

export type AnchorStatus = 'PENDING' | 'CONFIRMED' | 'FAILED';

export type VerificationStatus =
  | 'VERIFIED'
  | 'DATABASE_HASH_MISMATCH'
  | 'BLOCKCHAIN_HASH_MISMATCH'
  | 'EVIDENCE_TAMPERED'
  | 'ANCHOR_NOT_FOUND'
  | 'BLOCKCHAIN_UNAVAILABLE'
  | 'VERIFICATION_FAILED';

export interface BlockchainAnchor {
  anchorId: string;
  evidenceId: string;
  sha256Hash: string;
  recordHash: string;
  txHash: string;
  blockNumber: number;
  previousHash: string;
  status: AnchorStatus;
  confirmationTimeMs: number;
  createdAt: string;
  confirmedAt: string | null;
}

export interface BlockchainVerificationResult {
  evidence_id: string;
  verified: boolean;
  status: VerificationStatus;
  local_hash: string;
  chain_hash: string;
  anchor_id: string;
}

export interface BlockchainStats {
  total_anchors: number;
  confirmed: number;
  pending: number;
  failed: number;
  avg_confirmation_ms: number;
}

export interface BlockchainHealth {
  healthy: boolean;
  enabled: boolean;
}
