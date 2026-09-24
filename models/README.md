# IBVAP AI Models

All AI model files used by IBVAP are stored under this directory.
Paths are resolved project-relative (from source files), never absolute
personal paths. Models can be overridden via environment variables:

- `MODEL_PATH` — vehicle detector (default: `models/vehicle/yolov8n.pt`)
- `PLATE_MODEL_PATH` — license-plate detector (default: `models/license_plate/best.pt`)

## Model inventory

Model:
yolov8n.pt

Purpose:
Vehicle detection

Status:
ACTIVE

---

Model:
best.pt

Purpose:
Experimental license-plate detection

Status:
ACTIVE FOR CURRENT EXPERIMENT

---

Model:
license_plate_detector.pt

Purpose:
Previous license-plate detector

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

- SHA-256 of the active plate detector `models/license_plate/best.pt`:
  `1C1EBEE2A1DD54701F612A24D3300734618EE829A7980A6B23602511C786B032`
  (Ultralytics YOLOv8 detection, single class `plate`, verified on real video).
- The previous plate detector is preserved unchanged for rollback:
  `models/license_plate/license_plate_detector.pt`
  (SHA-256 `8EC3B254A6C87610F037A90957462CAFA11A9C03224E33A28C6A1D1AC2AC51B0`).
  It is **not loaded at runtime** during this experiment.
- Legacy copies of `yolov8n.pt` remain at their historical locations
  (repository root, `backend/`, `backend/ai/`) because existing test
  utilities reference them. They are byte-identical to
  `models/vehicle/yolov8n.pt` (SHA-256 `F59B3D833E2FF32E194B5BB8E08D211DC7C5BDF144B90D2C8412C47CCFC83B36`)
  and the runtime no longer loads them (runtime uses `MODEL_PATH`).
- To roll back the experimental plate detector, restore
  `backend/ai/config.py` / `backend/ai/anpr/plate_detector.py`
  (see the integration commit) or set `PLATE_MODEL_PATH` to the old model.
