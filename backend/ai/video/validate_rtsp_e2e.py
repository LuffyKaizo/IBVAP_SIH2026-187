"""End-to-end validation: full IBVAP pipeline consuming the local RTSP stream.

Runs ProcessingPipeline against rtsp://127.0.0.1:8554/test through the REAL
capture layer, exercising: capture -> YOLO -> ByteTrack -> face -> ANPR ->
events -> metadata (with camera health block).

Run: python -m ai.video.validate_rtsp_e2e   (requires the local RTSP server)
"""

import sys
import os
import time
import json
import socket

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

RTSP_URL = "rtsp://127.0.0.1:8554/test"


def server_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8554), timeout=0.5):
            return True
    except OSError:
        return False


def main():
    if not server_up():
        print("SKIP: local RTSP server not running on 8554")
        return 1
    from ai.pipeline import ProcessingPipeline

    print("=== IBVAP E2E over RTSP ===")
    pipe = ProcessingPipeline(camera_id="CAM-RTSP-TEST")
    pipe.configure(video_source=RTSP_URL, video_source_type="rtsp")
    if not pipe.start():
        print("FAIL: pipeline did not start")
        return 1

    t0 = time.time()
    last_report = 0.0
    json_ok = True
    meta_seen = 0
    camera_blocks = 0
    statuses = set()
    detections_total = 0
    faces_total = 0
    try:
        while time.time() - t0 < 25:
            time.sleep(1.0)
            st = pipe.state.get_status()
            md = pipe.state.get_latest_metadata()
            if md is not None:
                meta_seen += 1
                json.dumps(md)  # raises if not serializable
                cam = md.get("camera")
                if cam:
                    camera_blocks += 1
                    statuses.add(cam.get("status"))
                    detections_total = max(detections_total, len(md.get("detections", [])))
                    faces_total += len(md.get("faces", []))
            if time.time() - last_report >= 5:
                last_report = time.time()
                cam = st.get("camera", {})
                print(f"[{time.time()-t0:5.1f}s] status={cam.get('status','?'):12s} "
                      f"connected={st.get('video_connected')} procFps={st.get('processing_fps')} "
                      f"srcFps={cam.get('measuredSourceFps')} recon={cam.get('reconnectCount')} "
                      f"err={cam.get('lastError')}")
    finally:
        pipe.stop()

    print("\n=== E2E RESULTS ===")
    print(f"metadata messages (JSON-serializable): {meta_seen}")
    print(f"messages carrying camera block:        {camera_blocks}")
    print(f"camera statuses observed:              {sorted(statuses)}")
    print(f"max concurrent detections:             {detections_total}")
    print(f"face detections (frames summed):       {faces_total}")
    ok = meta_seen > 10 and camera_blocks > 10 and json_ok
    print("E2E:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
