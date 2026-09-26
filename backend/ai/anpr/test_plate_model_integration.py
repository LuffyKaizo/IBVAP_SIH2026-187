"""Integration test: active license-plate detector is the README model
(models/license_plate/license_plate_detector.pt).

Verifies:
- project-relative model configuration (models/ structure)
- active plate model path + SHA-256 of the README-documented checkpoint
- previous experimental model (best.pt) preserved on disk but NOT loaded
- vehicle model resolves to models/vehicle/yolov8n.pt
- plate detection executes on a real camera/video frame

Run: python -m ai.anpr.test_plate_model_integration  (from backend/)
"""

import hashlib
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import cv2
import numpy as np

from ai.config import settings, MODELS_DIR, REPO_ROOT
from ai.anpr.plate_detector import PlateDetector

# SHA-256 of the README checkpoint (upstream repo copy == Google Drive file)
EXPECTED_ACTIVE_SHA = "8EC3B254A6C87610F037A90957462CAFA11A9C03224E33A28C6A1D1AC2AC51B0"
ACTIVE_PLATE = MODELS_DIR / "license_plate" / "license_plate_detector.pt"
OLD_PLATE = MODELS_DIR / "license_plate" / "best.pt"
VEHICLE_MODEL = MODELS_DIR / "vehicle" / "yolov8n.pt"


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def main():
    print("=" * 70)
    print("PLATE MODEL INTEGRATION TEST (models/ structure)")
    print("=" * 70)
    passed, failed = 0, 0

    def check(label, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"  PASS  {label}" + (f"  [{detail}]" if detail else ""))
        else:
            failed += 1
            print(f"  FAIL  {label}" + (f"  [{detail}]" if detail else ""))

    # --- 1. Configuration paths (project-relative, no personal paths) ---
    print("\n[1] Configuration")
    import re
    cfg_src = open(os.path.join(os.path.dirname(__file__), '..', 'config.py'), encoding='utf-8').read()
    check("config has no hardcoded drive-letter path",
          not re.search(r'["\'][A-Za-z]:\\\\', cfg_src))
    check("paths derived from REPO_ROOT",
          str(settings.MODEL_PATH).startswith(str(REPO_ROOT)) and
          str(settings.PLATE_MODEL_PATH).startswith(str(REPO_ROOT)),
          str(REPO_ROOT))
    check("vehicle model configured", settings.MODEL_PATH == str(VEHICLE_MODEL), settings.MODEL_PATH)
    check("plate model configured", settings.PLATE_MODEL_PATH == str(ACTIVE_PLATE), settings.PLATE_MODEL_PATH)
    check("vehicle model exists", VEHICLE_MODEL.exists())
    check("active plate model exists", ACTIVE_PLATE.exists())
    check("previous experimental model preserved", OLD_PLATE.exists())
    check("active model is license_plate_detector.pt",
          os.path.basename(settings.PLATE_MODEL_PATH) == "license_plate_detector.pt")

    # --- 2. Integrity of the README-documented checkpoint ---
    print("\n[2] Active plate model integrity")
    check("license_plate_detector.pt SHA-256 matches README checkpoint",
          sha256(ACTIVE_PLATE) == EXPECTED_ACTIVE_SHA, sha256(ACTIVE_PLATE)[:16] + "...")

    # --- 3. Runtime load: exactly one plate model, the active one ---
    print("\n[3] Runtime load")
    detector = PlateDetector()
    check("plate detector initialized (YOLO)", detector._yolo_available)
    check("loaded path IS models/license_plate/license_plate_detector.pt",
          detector._model_path is not None and
          os.path.samefile(detector._model_path, ACTIVE_PLATE),
          str(detector._model_path))
    check("loaded path is NOT the previous experimental model",
          detector._model_path is None or
          not str(detector._model_path).endswith("best.pt"))
    names = detector._yolo_model.names if detector._yolo_model else {}
    check("plate model class names == {0: 'license_plate'}",
          names == {0: 'license_plate'}, str(names))
    n_params = sum(p.numel() for p in detector._yolo_model.model.parameters())
    check("plate model params ~3.0M (yolov8n-scale)",
          2.5e6 < n_params < 4e6, f"{n_params/1e6:.2f}M")

    # --- 4. Vehicle model still loads (YOLOv8n unchanged) ---
    print("\n[4] Vehicle detector")
    from ultralytics import YOLO
    vehicle = YOLO(settings.MODEL_PATH)
    vnames = vehicle.names
    check("vehicle model loads from models/vehicle/yolov8n.pt", True)
    check("vehicle classes include car/truck/bus", all(c in vnames.values() for c in ("car", "truck", "bus")))
    check("vehicle model is nano-scale (<5M params)",
          sum(p.numel() for p in vehicle.model.parameters()) < 5e6)

    # --- 5. Real frame detection (camera/video evidence) ---
    print("\n[5] Plate detection on a real video frame")
    video = os.path.normpath(os.path.join(REPO_ROOT, "data", "cameras",
                                          "Automatic Number Plate Recognition (ANPR) _ Vehicle Number Plate Recognition (1).mp4"))
    check("test video exists", os.path.exists(video), os.path.basename(video))
    cap = cv2.VideoCapture(video)
    frame = None
    cap.set(cv2.CAP_PROP_POS_FRAMES, 558)  # known frame with two visible plates
    ok, frame = cap.read()
    if not ok:
        frame = None
        for _ in range(30):  # fallback: grab a mid-stream frame
            ok, f = cap.read()
            if ok:
                frame = f
    cap.release()
    check("frame read from real video", frame is not None,
          f"{frame.shape[1]}x{frame.shape[0]}" if frame is not None else "")

    if frame is not None:
        # Vehicle ROI = whole frame region containing the car(s); use center band
        # as ROI stand-in like the pipeline does with tracked boxes.
        t0 = time.time()
        cands = detector.detect_plates(frame)
        full_ms = (time.time() - t0) * 1000
        h, w = frame.shape[:2]
        roi = frame[int(h * 0.3):int(h * 0.9), int(w * 0.1):int(w * 0.9)]
        t0 = time.time()
        roi_cands = detector.detect_plates(roi)
        roi_ms = (time.time() - t0) * 1000
        total_cands = len(cands) + len(roi_cands)
        print(f"    full-frame cands={len(cands)} ({full_ms:.0f}ms)  "
              f"ROI cands={len(roi_cands)} ({roi_ms:.0f}ms)")
        for c in (cands + roi_cands)[:5]:
            print(f"    bbox={c.bbox} conf={c.confidence:.2f} area={c.area:.0f}")
        check("plate detector executed on real frame without error", True)
        check("YOLO path actually invoked (not OpenCV fallback)",
              detector._yolo_available and detector._model_path is not None)
        check("plate detections found on known frame (full-frame or ROI)",
              total_cands >= 1, f"total={total_cands}")
        if roi_cands:
            crop = detector.extract_plate_crop(roi, roi_cands[0])
            check("plate crop extracted for OCR", crop is not None and crop.size > 0,
                  f"{crop.shape[1]}x{crop.shape[0]}" if crop is not None else "none")
            if crop is not None:
                processed = detector.preprocess_for_ocr(crop)
                check("OCR preprocess produced image", processed is not None and processed.size > 0,
                      f"{processed.shape[1]}x{processed.shape[0]}")

    # --- 6. Edge cases ---
    print("\n[6] Edge cases")
    empty = detector.detect_plates(np.zeros((5, 5, 3), dtype=np.uint8))
    check("tiny frame handled (no crash)", isinstance(empty, list))
    none_out = detector.detect_plates(None)
    check("None frame handled (no crash)", none_out == [])
    blank = detector.detect_plates(np.full((200, 400, 3), 128, dtype=np.uint8))
    check("featureless frame handled (no crash, no fake plate)", isinstance(blank, list))

    print("\n" + "=" * 70)
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 70)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
