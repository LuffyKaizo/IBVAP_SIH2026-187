import { useState, useEffect, useRef } from 'react';
import { useAuth } from '../contexts/AuthContext';

const AI_BASE = (import.meta.env.VITE_AI_SERVICE_URL || 'http://localhost:8000') as string;

export interface AiGpuInfo {
  torch_cuda_available: boolean;
  torch_device: string | null;
  utilization_pct: number | null;
  memory_used_mb: number | null;
  memory_total_mb: number | null;
  temperature_c: number | null;
}

export interface AiServiceStatus {
  device: string;
  yolo_loaded: boolean;
  gpu: AiGpuInfo | null;
  processing_fps: number | null;
  source_fps: number | null;
}

/**
 * Polls the AI service `/status` endpoint for live GPU + device + pipeline FPS
 * numbers (the same payload `GET /status` returns: `gpu`, `device`,
 * `pipeline.processing_fps`). Returns null until the first successful
 * response, and null again while the backend is unreachable — callers render
 * their "No data" placeholder in both cases.
 */
export function useAiStatus(pollMs = 5000): AiServiceStatus | null {
  const { getAuthHeaders } = useAuth();
  const [status, setStatus] = useState<AiServiceStatus | null>(null);
  const headersRef = useRef<Record<string, string>>({});
  headersRef.current = getAuthHeaders();

  useEffect(() => {
    let alive = true;

    const tick = async () => {
      try {
        const resp = await fetch(AI_BASE + '/status', { headers: headersRef.current });
        if (!resp.ok) {
          if (alive) setStatus(null);
          return;
        }
        const data = await resp.json();
        if (!alive) return;
        const pipe = data.pipeline || {};
        setStatus({
          device: data.device || '',
          yolo_loaded: !!data.yolo_loaded,
          gpu:
            data.gpu && typeof data.gpu.torch_cuda_available === 'boolean'
              ? (data.gpu as AiGpuInfo)
              : null,
          processing_fps: typeof pipe.processing_fps === 'number' ? pipe.processing_fps : null,
          source_fps: typeof pipe.source_fps === 'number' ? pipe.source_fps : null,
        });
      } catch {
        if (alive) setStatus(null);
      }
    };

    tick();
    const timer = window.setInterval(tick, pollMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [pollMs]);

  return status;
}
