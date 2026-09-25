import { useState, useCallback, useRef } from "react";
import type { AiTrackingMetadata, AiAlert, BorderAlert } from "../types";

/**
 * Converts AI-generated alerts from the WebSocket metadata
 * into the existing BorderAlert format used by EventIntelligenceView.
 * Handles deduplication and preserves operator actions (acknowledge/resolve).
 */
export function useAiAlerts() {
  const [aiAlerts, setAiAlerts] = useState<Record<string, BorderAlert>>({});
  const operatorActionsRef = useRef<Record<string, "ACKNOWLEDGED" | "RESOLVED">>({});

  const processMetadata = useCallback((metadata: AiTrackingMetadata) => {
    const incoming: AiAlert[] = metadata.alerts || [];
    setAiAlerts((prev) => {
      const next: Record<string, BorderAlert> = { ...prev };
      const activeIds = new Set(incoming.map((a) => a.id));

      for (const aiAlert of incoming) {
        const opStatus = operatorActionsRef.current[aiAlert.id];
        next[aiAlert.id] = {
          id: aiAlert.id,
          timestamp: formatTimestamp(aiAlert.timestamp),
          cameraId: aiAlert.cameraId,
          cameraName: aiAlert.cameraName,
          eventType: mapEventType(aiAlert.eventType),
          title: aiAlert.title,
          message: aiAlert.message,
          severity: aiAlert.severity as BorderAlert["severity"],
          trackId: aiAlert.trackId,
          confidence: aiAlert.confidence,
          zone: aiAlert.zone,
          reason: aiAlert.reason,
          evidenceChecklist: aiAlert.evidenceChecklist,
          status: (opStatus || aiAlert.status) as BorderAlert["status"],
          source: "AI",
          riskScore: aiAlert.riskScore,
          riskSeverity: aiAlert.riskSeverity,
          riskFactors: aiAlert.riskFactors,
          dwellSeconds: aiAlert.dwellSeconds,
          loitering: aiAlert.loitering,
          fenceProximity: aiAlert.fenceProximity,
          direction: aiAlert.direction,
          repeatedEntry: aiAlert.repeatedEntry,
        };
      }

      // Resolve alerts no longer in the incoming set
      const ids = Object.keys(next);
      for (let i = 0; i < ids.length; i++) {
        const id = ids[i];
        const alert: BorderAlert = next[id];
        if (alert.source === "AI" && !activeIds.has(id)) {
          const opStatus = operatorActionsRef.current[id];
          if (opStatus) {
            alert.status = opStatus;
          } else {
            const s: string = alert.status;
            if (s === "ACTIVE" || s === "DETECTED") {
              alert.status = "RESOLVED";
            }
          }
        }
      }

      return next;
    });
  }, []);

  const handleAction = useCallback((id: string, action: "ACKNOWLEDGE" | "RESOLVE") => {
    const mapped: "ACKNOWLEDGED" | "RESOLVED" = action === "ACKNOWLEDGE" ? "ACKNOWLEDGED" : "RESOLVED";
    operatorActionsRef.current[id] = mapped;
    setAiAlerts((prev) => {
      const alert: BorderAlert | undefined = prev[id];
      if (!alert) return prev;
      return { ...prev, [id]: { ...alert, status: mapped } };
    });
  }, []);

  const clearAlerts = useCallback(() => {
    setAiAlerts((prev) => {
      const next: Record<string, BorderAlert> = {};
      const entries: [string, BorderAlert][] = Object.entries(prev) as [string, BorderAlert][];
      for (let i = 0; i < entries.length; i++) {
        const [id, alert] = entries[i];
        const s: string = alert.status;
        if (s === "ACTIVE" || s === "DETECTED") {
          next[id] = { ...alert, status: "RESOLVED" };
        } else {
          next[id] = alert;
        }
      }
      return next;
    });
  }, []);

  const alertArray: BorderAlert[] = Object.values(aiAlerts);
  const activeCount = alertArray.filter(
    (a) => a.status === "ACTIVE"
  ).length;

  return {
    aiAlerts: alertArray,
    processMetadata,
    handleAction,
    clearAlerts,
    activeAiAlertCount: activeCount,
  };
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toISOString().substring(11, 19) + " UTC";
  } catch {
    return iso;
  }
}

function mapEventType(aiType: string): BorderAlert["eventType"] {
  const typeMap: Record<string, BorderAlert["eventType"]> = {
    BORDER_INTRUSION: "BORDER_INTRUSION",
    RESTRICTED_ZONE_VEHICLE: "RESTRICTED_ZONE_VEHICLE",
    LOITERING: "LOITERING",
    NIGHT_MOVEMENT: "NIGHT_MOVEMENT",
    SUSPICIOUS_ACTIVITY: "SUSPICIOUS_ACTIVITY",
  };
  return typeMap[aiType] || "BORDER_INTRUSION";
}
