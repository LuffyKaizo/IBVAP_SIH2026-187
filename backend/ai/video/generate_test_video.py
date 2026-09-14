"""Generate a synthetic test MP4 for IBVAP video capture testing."""

import cv2
import numpy as np
from pathlib import Path


def generate_test_video(
    output_path: str = "./data/test.mp4",
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    duration_sec: int = 10,
) -> str:
    """Generate a synthetic border surveillance test video."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output), fourcc, fps, (width, height))

    if not writer.isOpened():
        raise RuntimeError(f"Failed to open VideoWriter for {output_path}")

    total_frames = fps * duration_sec
    print(f"[IBVAP-GEN] Generating {duration_sec}s test video @ {width}x{height} {fps}fps")

    for i in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (20, 25, 30)

        x = int((i / total_frames) * (width - 100))
        y = int(height * 0.4 + 20 * np.sin(i / 15.0))
        cv2.rectangle(frame, (x, y), (x + 60, y + 120), (0, 180, 220), 2)

        vx = int(width - (i / total_frames) * (width - 80))
        vy = int(height * 0.65)
        cv2.rectangle(frame, (vx, vy), (vx + 100, vy + 50), (0, 200, 160), 2)

        text = f"Frame {i+1}/{total_frames}"
        cv2.putText(frame, text, (20, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (200, 200, 200), 2)

        sec = i / fps
        ts = f"{int(sec//60):02d}:{sec%60:05.2f}"
        cv2.putText(frame, ts, (width - 160, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 200, 150), 2)

        cv2.line(frame, (0, int(height * 0.3)), (width, int(height * 0.3)), (80, 80, 80), 1)
        cv2.putText(frame, "SECTOR WEST - TEST", (20, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 100, 120), 1)

        writer.write(frame)

    writer.release()
    abs_path = str(output.resolve())
    size_kb = output.stat().st_size / 1024
    print(f"[IBVAP-GEN] Video generated: {abs_path}")
    print(f"[IBVAP-GEN] Size: {size_kb:.1f} KB")
    return abs_path


if __name__ == "__main__":
    generate_test_video()
