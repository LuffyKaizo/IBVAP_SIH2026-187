import { useState, useEffect, useRef, useCallback } from "react";
import type { AiTrackingMetadata, AiCameraStatus } from "../types";

const AI_SERVICE_URL = import.meta.env.VITE_AI_SERVICE_URL || "http://localhost:8000";

export interface UseAiCameraStreamResult {
  metadata: AiTrackingMetadata | null;
  status: AiCameraStatus | null;
  isConnected: boolean;
  videoUrl: string;
  connect: (cameraId: string, token?: string) => void;
  disconnect: () => void;
}

export function useAiCameraStream(): UseAiCameraStreamResult {
  const [metadata, setMetadata] = useState<AiTrackingMetadata | null>(null);
  const [status, setStatus] = useState<AiCameraStatus | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [currentCameraId, setCurrentCameraId] = useState<string | null>(null);
  const [authToken, setAuthToken] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Refs to avoid stale closures in callbacks/timers
  const cameraIdRef = useRef<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const reconnectFnRef = useRef<((cameraId: string, token: string | null) => void) | null>(null);

  const videoUrl = currentCameraId
    ? AI_SERVICE_URL + "/video/stream/" + currentCameraId + (authToken ? "?token=" + authToken : "")
    : "";

  const cleanup = useCallback(() => {
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }
    if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
    if (statusTimerRef.current) { clearInterval(statusTimerRef.current); statusTimerRef.current = null; }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const cid = cameraIdRef.current;
      const token = tokenRef.current;
      const url = cid
        ? AI_SERVICE_URL + "/status?camera_id=" + cid
        : AI_SERVICE_URL + "/status";
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      const res = await fetch(url, { headers });
      if (res.ok) {
        const data = await res.json();
        if (data.pipeline) {
          setStatus({
            camera_id: data.pipeline.camera_id || cid || "",
            video_connected: data.pipeline.video_connected || false,
            ai_processing: data.pipeline.ai_processing || false,
            processing_fps: data.pipeline.processing_fps || 0,
            source_fps: data.pipeline.source_fps || 0,
            resolution: data.pipeline.resolution || "",
            frames_processed: data.pipeline.frames_processed || 0,
            total_detections: data.pipeline.total_detections || 0,
            websocket_clients: data.websocket_clients || 0,
            camera: data.pipeline.camera || undefined,
          });
        } else {
          setStatus(null);
        }
      }
    } catch { setStatus(null); }
  }, []);

  const connectInternal = useCallback((cameraId: string, token: string | null) => {
    cleanup();
    cameraIdRef.current = cameraId;
    tokenRef.current = token;
    setCurrentCameraId(cameraId);
    setMetadata(null);
    setIsConnected(false);

    const tokenParam = token || "";
    const wsUrl = AI_SERVICE_URL.replace("http://", "ws://").replace("https://", "wss://")
      + "/ws/cameras/" + cameraId + (tokenParam ? "?token=" + tokenParam : "");

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        fetchStatus();
        statusTimerRef.current = setInterval(fetchStatus, 3000);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data && data.camera_id) setMetadata(data);
        } catch { /* ignore */ }
      };

      ws.onclose = () => {
        setIsConnected(false);
        setMetadata(null);
        if (statusTimerRef.current) { clearInterval(statusTimerRef.current); statusTimerRef.current = null; }
        reconnectTimerRef.current = setTimeout(() => {
          if (reconnectFnRef.current) reconnectFnRef.current(cameraId, token);
        }, 3000);
      };

      ws.onerror = () => { setIsConnected(false); };
    } catch {
      reconnectTimerRef.current = setTimeout(() => {
        if (reconnectFnRef.current) reconnectFnRef.current(cameraId, token);
      }, 3000);
    }
  }, [cleanup, fetchStatus]);

  reconnectFnRef.current = connectInternal;

  const connect = useCallback((cameraId: string, token?: string) => {
    connectInternal(cameraId, token || null);
    setAuthToken(token || null);
  }, [connectInternal]);

  const disconnect = useCallback(() => {
    cleanup();
    cameraIdRef.current = null;
    tokenRef.current = null;
    setCurrentCameraId(null);
    setAuthToken(null);
    setMetadata(null);
    setStatus(null);
    setIsConnected(false);
  }, [cleanup]);

  useEffect(() => { return cleanup; }, [cleanup]);

  return { metadata, status, isConnected, videoUrl, connect, disconnect };
}
