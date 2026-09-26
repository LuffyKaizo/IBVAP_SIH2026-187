# IBVAP AI Models

All AI model files used by IBVAP are stored under this directory.
Paths are resolved project-relative (from source files), never absolute
personal paths. Models can be overridden via environment variables:

- `MODEL_PATH` — vehicle detector (default: `models/vehicle/yolov8n.pt`)
- `PLATE_MODEL_PATH` — license-plate detector (default: `models/license_plate/license_plate_detector.pt`)

## Model inventory

Model:
yolov8n.pt

Purpose:
Vehicle detection

Status:
ACTIVE

---

Model:
license_plate_detector.pt

Purpose:
License-plate detection (README-based YOLOv8 model, single class `license_plate`)

Status:
ACTIVE

---

Model:
best.pt

Purpose:
Previous experimental license-plate detector

Status:
PRESERVED FOR ROLLBACK / NOT ACTIVE

---

Model:
face_detection_yunet_2023mar.onnx

Purpose:
Face detection (YuNet, OpenCV FaceDetectorYN — detection only)

Status:
ACTIVE

## Notes

- SHA-256 of the active plate detector `models/license_plate/license_plate_detector.pt`:
  `8EC3B254A6C87610F037A90957462CAFA11A9C03224E33A28C6A1D1AC2AC51B0`
  (Ultralytics YOLOv8 detection, single class `license_plate`, 3.01M params).
  This is the exact checkpoint documented by the project README — the
  upstream repository copy and the linked Google Drive file
  (`1Zmf5ynaTFhmln2z7Qvv-tgjkWQYQ9Zdw`) are byte-identical to this file.
  Verified standalone (full-frame flow from the README) and integrated
  (per-vehicle ROI) on real video: detections with sensible boxes/confidence
  on GPU (CUDA).
- The previous experimental plate detector is preserved unchanged for
  rollback: `models/license_plate/best.pt`
  (SHA-256 `1C1EBEE2A1DD54701F612A24D3300734618EE829A7980A6B23602511C786B032`).
  It is **not loaded at runtime**; to roll back, set `PLATE_MODEL_PATH` to it.
- Legacy copies of `yolov8n.pt` remain at their historical locations
  (repository root, `backend/`, `backend/ai/`) because existing test
  utilities reference them. They are byte-identical to
  `models/vehicle/yolov8n.pt` (SHA-256 `F59B3D833E2FF32E194B5BB8E08D211DC7C5BDF144B90D2C8412C47CCFC83B36`)
  and the runtime no longer loads them (runtime uses `MODEL_PATH`).
