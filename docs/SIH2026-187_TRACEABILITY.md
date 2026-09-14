# SIH2026-187 — Requirement Traceability

## Status

**Official SIH2026-187 problem statement / requirements document is not currently present in this repository.**

The traceability matrix below will be populated after the official document is added to `docs/requirements/SIH2026-187.<ext>`.

Do not invent requirement statements. Only map actual official requirements when available.

---

## Placeholder Mapping

The following areas are implemented in IBVAP and likely correspond to SIH2026-187 requirements. This mapping is provisional and must be verified against the official problem statement.

| Requirement Area | IBVAP Module | Status | Verification |
|-----------------|--------------|--------|-------------|
| Border surveillance analytics | AI Pipeline, Camera Management | Implemented | Runtime validated |
| Real-time video processing | YOLO + ByteTrack tracking | Implemented | Runtime validated |
| Threat detection & alerting | ContextEngine + RiskEngine + EventEngine | Implemented | Runtime validated, 26 unit tests |
| Evidence management | Evidence subsystem + SHA-256 fingerprints | Implemented | Runtime validated, 50+ evidence records |
| Trust chain / integrity | LocalLedger blockchain prototype | Implemented | Runtime validated |
| Offline resilience | Store-and-forward, SD/NVR recovery | Implemented | Unit tested |
| ANPR (license plate recognition) | ANPR subsystem (EasyOCR) | Implemented | Runtime validated |
| Face detection | YuNet face detector | Implemented | Detection only — NOT recognition |
| Cybersecurity | JWT auth, RBAC, edge tokens, TLS | Implemented | Unit tested |
| Multi-camera support | CameraManager with per-camera isolation | Implemented | Runtime validated |
| Network health monitoring | NetworkHealthMonitor state machine | Implemented | Unit tested |

---

## Action Required

1. Obtain the official SIH2026-187 problem statement document.
2. Place it in `docs/requirements/SIH2026-187.<ext>`.
3. Populate this traceability matrix with exact requirement IDs.
4. Map each requirement to specific implementation files and test evidence.
5. Identify any gaps between official requirements and current implementation.

---

## Known Limitations (Must Be Disclosed)

- **Face detection only**: IBVAP performs face detection (bounding boxes), NOT facial recognition. No biometric identification.
- **Local blockchain prototype**: The `LocalLedger` is a tamper-evident record store, not a distributed blockchain network.
- **Demo video**: `data/surveillance_test.mp4` is a synthetic/test clip. Field validation with real border CCTV footage has not been performed in this repository.
- **SD/local footage recovery**: Implemented as prototype/demo mode. Physical SD card recovery from government CCTV hardware has not been tested.
