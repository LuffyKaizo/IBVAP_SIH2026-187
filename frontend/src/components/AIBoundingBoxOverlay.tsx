import React from "react";
import type { AiTrackedObject, TrackContext } from "../types";

interface AIBoundingBoxOverlayProps {
  detections: AiTrackedObject[];
  trackContext?: TrackContext[];
}

const CLASS_COLORS: Record<string, { border: string; bg: string; label: string }> = {
  person: { border: "#356B7A", bg: "rgba(53,107,122,0.12)", label: "PERSON" },
  car: { border: "#4C8B8B", bg: "rgba(76,139,139,0.12)", label: "CAR" },
  motorcycle: { border: "#4C8B8B", bg: "rgba(76,139,139,0.12)", label: "MOTORCYCLE" },
  bus: { border: "#4C8B8B", bg: "rgba(76,139,139,0.12)", label: "BUS" },
  truck: { border: "#4C8B8B", bg: "rgba(76,139,139,0.12)", label: "TRUCK" },
};

const DEFAULT_COLOR = { border: "#356B7A", bg: "rgba(53,107,122,0.12)", label: "OBJECT" };

export const AIBoundingBoxOverlay: React.FC<AIBoundingBoxOverlayProps> = ({ detections, trackContext }) => {
  if (!detections || detections.length === 0) return null;

  const ctxMap = new Map<number, TrackContext>();
  if (trackContext) {
    for (const tc of trackContext) {
      ctxMap.set(tc.track_id, tc);
    }
  }

  return (
    <>
      {detections.map((det, idx) => {
        const color = CLASS_COLORS[det.class_name] || DEFAULT_COLOR;
        const left = det.bbox.x1 * 100;
        const top = det.bbox.y1 * 100;
        const width = (det.bbox.x2 - det.bbox.x1) * 100;
        const height = (det.bbox.y2 - det.bbox.y1) * 100;
        const confidence = Math.round(det.confidence * 100);
        const ctx = ctxMap.get(det.track_id);
        const hasContext = ctx && (ctx.direction !== 'UNKNOWN' || ctx.loitering || ctx.fence_proximity || ctx.dwell_seconds > 0);
        const contextLabel = ctx ? (
          ctx.loitering ? 'Loitering' :
          ctx.fence_proximity ? 'Near Fence' :
          ctx.direction !== 'UNKNOWN' ? ctx.direction.replace(/_/g, ' ') :
          ctx.dwell_seconds > 0 ? `Dwell ${ctx.dwell_seconds.toFixed(0)}s` :
          null
        ) : null;

        return (
          <div
            key={`ai-det-${det.track_id}-${idx}`}
            style={{
              position: "absolute",
              left: `${left}%`,
              top: `${top}%`,
              width: `${width}%`,
              height: `${height}%`,
              border: `2px solid ${color.border}`,
              backgroundColor: color.bg,
              transition: "all 0.15s ease-out",
              pointerEvents: "none",
            }}
          >
            {/* Label */}
            <div
              style={{
                position: "absolute",
                top: "-20px",
                left: 0,
                padding: "2px 6px",
                fontSize: "10px",
                fontFamily: "JetBrains Mono, monospace",
                fontWeight: 700,
                whiteSpace: "nowrap",
                borderRadius: "3px",
                backgroundColor: color.border,
                color: "#fff",
                lineHeight: "14px",
              }}
            >
              {color.label} #{det.track_id} | {confidence}%
            </div>
            {/* Context sublabel */}
            {hasContext && contextLabel && (
              <div
                style={{
                  position: "absolute",
                  top: "-34px",
                  left: 0,
                  padding: "1px 5px",
                  fontSize: "9px",
                  fontFamily: "JetBrains Mono, monospace",
                  fontWeight: 600,
                  whiteSpace: "nowrap",
                  borderRadius: "3px",
                  backgroundColor: "rgba(0,0,0,0.7)",
                  color: ctx.loitering ? "#FFB74D" : ctx.fence_proximity ? "#EF5350" : "#B0BEC5",
                  lineHeight: "12px",
                }}
              >
                {contextLabel}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
};
