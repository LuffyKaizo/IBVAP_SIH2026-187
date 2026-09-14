import { useState, useCallback, useRef } from "react";
import type { AiTrackingMetadata, AiAnprRecord, AnprRecord } from "../types";

/**
 * Converts AI-generated ANPR records from the WebSocket metadata
 * into the existing AnprRecord format used by AnprView.
 * Handles deduplication by trackId + plateText.
 */
export function useAiAnpr() {
  const [aiAnprRecords, setAiAnprRecords] = useState<Record<string, AnprRecord>>({});
  const seenRef = useRef<Set<string>>(new Set());

  const processMetadata = useCallback((metadata: AiTrackingMetadata) => {
    const incoming: AiAnprRecord[] = metadata.anpr || [];
    if (incoming.length === 0) return;

    setAiAnprRecords((prev) => {
      const next = { ...prev };

      for (const aiRec of incoming) {
        // Only surface meaningful records: a real plate reading exists and
        // the plate is not a low-quality/uncertain detection.
        if (!aiRec.plateText) continue;

        // Dedup by trackId + plateText
        const dedupKey = `${aiRec.trackId}:${aiRec.plateText}`;
        if (seenRef.current.has(dedupKey)) {
          // Update existing record
          if (next[aiRec.id]) {
            next[aiRec.id] = {
              ...next[aiRec.id],
              confidence: Math.round(aiRec.ocrConfidence || aiRec.plateConfidence),
            };
          }
          continue;
        }

        seenRef.current.add(dedupKey);

        // Convert AiAnprRecord to AnprRecord format
        const vehicleTypeMap: Record<string, AnprRecord["vehicleType"]> = {
          car: "Sedan",
          truck: "Truck",
          bus: "Van",
          motorcycle: "Motorcycle",
          bicycle: "Motorcycle",
        };

        const statusMap: Record<string, AnprRecord["status"]> = {
          CONFIRMED: "WATCHLIST",
          RECOGNIZED: "UNREGISTERED",
          DETECTED: "UNREGISTERED",
          UNREADABLE: "UNREGISTERED",
        };

        const timestamp = aiRec.timestamp
          ? new Date(aiRec.timestamp).toISOString().substring(11, 19) + " UTC"
          : new Date().toISOString().substring(11, 19) + " UTC";

        const camNames: Record<string, string> = {
          "CAM-01": "BOP NORTH MAIN GATE",
          "CAM-02": "BORDER ROAD SECTOR 3",
          "CAM-03": "CHECK POST VEHICLE LANE",
        };

        const rec: AnprRecord = {
          id: aiRec.id,
          timestamp,
          plateNumber: aiRec.plateText,
          vehicleType: vehicleTypeMap[aiRec.vehicleClass] || "Sedan",
          confidence: Math.round(aiRec.ocrConfidence || aiRec.plateConfidence),
          cameraId: aiRec.cameraId,
          cameraName: camNames[aiRec.cameraId] || aiRec.cameraId,
          status: statusMap[aiRec.status] || "UNREGISTERED",
          direction: "Restricted Zone",
          // AI markers: an inferred/corrected plate is never presented as
          // raw OCR - AnprView renders a distinct "AI.CORR" chip.
          ai: true,
          corrected: aiRec.corrected === true,
          rawPlateText: aiRec.rawOcrText || undefined,
        };

        next[aiRec.id] = rec;
      }

      return next;
    });
  }, []);

  const aiAnprArray: AnprRecord[] = Object.values(aiAnprRecords);

  return {
    aiAnprRecords: aiAnprArray,
    processMetadata,
  };
}
