import {
  CameraFeed,
  BorderAlert,
  AnprRecord,
  VirtualZone,
  SuspiciousEventItem,
  HourlySurveillanceActivity,
  DashboardKpiStats,
  DiagnosticsCheckItem,
  SurveillanceReportItem,
  SystemSettingsConfig,
} from './types';

export const INITIAL_CAMERAS: CameraFeed[] = [];

export const INITIAL_ALERTS: BorderAlert[] = [];

export const INITIAL_ANPR_RECORDS: AnprRecord[] = [];

export const INITIAL_VIRTUAL_ZONES: VirtualZone[] = [];

export const INITIAL_SUSPICIOUS_EVENTS: SuspiciousEventItem[] = [];

export const INITIAL_24H_SURVEILLANCE_ACTIVITY: HourlySurveillanceActivity[] = [
  { hour: '00:00', hourNum: 0, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '01:00', hourNum: 1, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '02:00', hourNum: 2, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '03:00', hourNum: 3, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '04:00', hourNum: 4, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '05:00', hourNum: 5, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '06:00', hourNum: 6, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '07:00', hourNum: 7, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '08:00', hourNum: 8, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '09:00', hourNum: 9, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '10:00', hourNum: 10, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '11:00', hourNum: 11, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '12:00', hourNum: 12, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '13:00', hourNum: 13, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '14:00', hourNum: 14, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '15:00', hourNum: 15, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '16:00', hourNum: 16, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '17:00', hourNum: 17, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '18:00', hourNum: 18, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '19:00', hourNum: 19, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '20:00', hourNum: 20, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '21:00', hourNum: 21, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '22:00', hourNum: 22, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
  { hour: '23:00', hourNum: 23, peopleCount: 0, vehicleCount: 0, alertsCount: 0, anprHits: 0, intrusionBreaches: 0, nightActivityIndex: 0, totalDensity: 0 },
];

export const INITIAL_KPI_STATS: DashboardKpiStats = {
  activeCameras: 0,
  totalCameras: 0,
  peopleDetected: 0,
  vehiclesDetected: 0,
  activeAlerts: 0,
  anprEvents: 0,
  intrusionEvents: 0,
  systemHealthPercent: 0,
  alertsBySeverity: {
    critical: 0,
    high: 0,
    medium: 0,
    info: 0,
  },
};

export const INITIAL_DIAGNOSTICS: DiagnosticsCheckItem[] = [];

export const INITIAL_REPORTS: SurveillanceReportItem[] = [];

export const INITIAL_SETTINGS_CONFIG: SystemSettingsConfig = {
  yoloModel: 'yolov8n',
  confidenceThreshold: 0.45,
  trackingMatchIntervalMs: 30,
  ocrThreshold: 0.85,
  faceDetectionEnabled: true,
  intrusionSensitivity: 9,
  loiteringThresholdSec: 30,
  nightHoursStart: '22:00',
  nightHoursEnd: '05:00',
  rtspBufferSizeMb: 2048,
  apiBaseUrl: '',
  apiAuthToken: '',
};

// Aliases for seamless component exports
export const INITIAL_HOURLY_ACTIVITY = INITIAL_24H_SURVEILLANCE_ACTIVITY;
export const INITIAL_SYSTEM_CONFIG = INITIAL_SETTINGS_CONFIG;
export const INITIAL_DASHBOARD_STATS = INITIAL_KPI_STATS;

export const INITIAL_SYSTEM_NODES: [] = [];

