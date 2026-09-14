import React from "react";
import type { AiFaceDetection } from "../types";

interface AIFaceOverlayProps {
  faces: AiFaceDetection[];
}

/**
 * Minimal face bounding-box overlay for the existing camera view.
 * Detection only — boxes show FACE, optional person track, confidence.
 * Uses normalized coordinates (0..1) from the AI metadata.
 */
export const AIFaceOverlay: React.FC<AIFaceOverlayProps> = ({ faces }) => {
  if (!faces || faces.length === 0) return null;

  return (
    <>
      {faces.map((face, idx) => {
        const left = face.bbox.x1 * 100;
        const top = face.bbox.y1 * 100;
        const width = (face.bbox.x2 - face.bbox.x1) * 100;
        const height = (face.bbox.y2 - face.bbox.y1) * 100;
        const confidence = Math.round(face.confidence * 100);

        return (
          <div
            key={`ai-face-${face.id}-${idx}`}
            style={{
              position: "absolute",
              left: `${left}%`,
              top: `${top}%`,
              width: `${Math.max(width, 1.2)}%`,
              height: `${Math.max(height, 2.2)}%`,
              border: "2px solid #B8860B",
              backgroundColor: "rgba(184,134,11,0.10)",
              transition: "all 0.15s ease-out",
              pointerEvents: "none",
            }}
          >
            <div
              style={{
                position: "absolute",
                bottom: "-16px",
                left: "-2px",
                padding: "1px 4px",
                fontSize: "8px",
                fontFamily: "JetBrains Mono, monospace",
                fontWeight: 700,
                whiteSpace: "nowrap",
                borderRadius: "2px",
                backgroundColor: "#B8860B",
                color: "#1a1a1a",
                lineHeight: "14px",
              }}
            >
              FACE{face.personTrackId != null ? ` #${face.personTrackId}` : ""} {confidence}%
            </div>
          </div>
        );
      })}
    </>
  );
};
