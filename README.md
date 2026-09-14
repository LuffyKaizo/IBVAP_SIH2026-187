# IBVAP — Intelligent Border Video Analytics Platform

**SIH2026-187** | Smart India Hackathon 2026

---

## Overview

IBVAP transforms existing IP-based CCTV infrastructure into an intelligent border surveillance network. The platform performs real-time video analytics using AI-powered detection, tracking, context analysis, and risk scoring to identify security threats at border checkpoints and sensitive areas.

## Problem

Manual monitoring of multiple CCTV feeds is error-prone, cognitively overwhelming, and cannot scale to the volume of cameras deployed at national borders. Threats go undetected until after incidents occur.

## Solution

IBVAP provides:

- **Real-time AI detection** — YOLO object detection with ByteTrack multi-object tracking
- **Context-aware intelligence** — dwell time, loitering, fence proximity, direction analysis, repeated entry detection
- **Dynamic risk scoring** — deterministic 0–100 risk engine with severity classification (LOW/MEDIUM/HIGH/CRITICAL)
- **Automated alerting** — deduplication, escalation, and lifecycle management for security events
- **Evidence integrity** — SHA-256 fingerprinting and local blockchain ledger for tamper-evident records
- **Offline resilience** — store-and-forward synchronization with SD/NVR footage recovery
- **ANPR** — automatic number plate recognition for vehicle identification
- **Face detection** — real-time face detection for person tracking (NOT facial recognition)
- **Cybersecurity** — JWT authentication, role-based access control, secure edge communication

## Architecture

```
Video Feed (RTSP/File)
    → YOLO v8 Detection
    → ByteTrack Multi-Object Tracking
    → ContextEngine (dwell, loiter, fence, direction, repeated entry)
    → EventEngine (virtual fence, intrusion, behavior analysis)
    → RiskEngine (0–100 scoring, severity classification)
    → Alert Deduplication & Escalation
    → Evidence Capture + SHA-256 Fingerprint
    → Local Blockchain Ledger (tamper-evident record)
    → Store-and-Forward Sync (when connected)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| AI / ML | Python 3.12, YOLO v8 (Ultralytics), ByteTrack, OpenCV, EasyOCR, PyTorch |
| Backend API | Python, FastAPI, SQLAlchemy 2.0 (async), Alembic |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Tremor |
| BFF / WebSocket | Node.js, Express, TypeScript |
| Database | PostgreSQL (Supabase), asyncpg |
| Authentication | JWT (python-jose), bcrypt, RBAC |
| Blockchain | Local ledger prototype (SHA-256 anchored) |

## Repository Structure

```
SIH2026-187/
├── frontend/              React + TypeScript + Vite frontend
├── backend/
│   ├── ai/                FastAPI AI service (detection, tracking, events, evidence)
│   └── express/           Express BFF (proxy, WebSocket, auth bridge)
├── data/                  Test videos and ANPR/face test images
├── models/                Model weights directory
├── scripts/               Database bootstrap and admin utilities
├── docs/                  Project documentation
├── .env.example           Environment configuration template
└── yolov8n.pt             YOLO v8 nano model (baseline, tracked)
```

See [`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md) for full details.

## Quick Start

```bash
# Clone
git clone <repository-url>
cd SIH2026-187

# Python environment
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\ai\requirements.txt

# Node dependencies
npm install

# Environment
copy .env.example .env
# Edit .env with your DATABASE_URL and SECRET_KEY

# Database (requires Supabase/PostgreSQL)
alembic upgrade head
python scripts\ensure_admin.py

# Start AI backend (port 8000)
set PYTHONPATH=backend
python -m ai.main

# Start frontend (port 3000, separate terminal)
npm run dev
```

See [`docs/TEAM_SETUP.md`](docs/TEAM_SETUP.md) for complete setup instructions.

## Environment Variables

All configuration is via environment variables. See [`.env.example`](.env.example) for the complete list.

**Critical variables:**
- `DATABASE_URL` — PostgreSQL connection string (required)
- `SECRET_KEY` — JWT signing key (required, generate a random 64+ char string)
- `ADMIN_PASSWORD` — Bootstrap admin password (required for scripts)
- `EDGE_NODE_SECRET` / `EDGE_TOKEN_SECRET` — Edge security tokens

## Authentication

- Default admin: `admin@ibvap.local` (email configured via `ADMIN_EMAIL`)
- Password: set via `ADMIN_PASSWORD` environment variable
- Roles: `ADMIN`, `OPERATOR`, `VIEWER`
- JWT tokens with configurable expiry

## AI Capabilities

### Detection & Tracking
- YOLO v8 nano model (6.2 MB, COCO pre-trained)
- ByteTrack multi-object tracking
- Configurable confidence thresholds and NMS

### Context Intelligence (ContextEngine)
- **Dwell time** — tracks how long objects remain in zones
- **Loitering detection** — identifies prolonged stationary behavior
- **Fence proximity** — measures distance to restricted boundaries
- **Direction analysis** — determines movement vectors
- **Repeated entry** — flags objects entering zones multiple times

### Risk Scoring (RiskEngine)
- Deterministic 0–100 scoring
- Factors: intrusion type, zone severity, loitering, dwell, fence proximity, repeated entry, night activity, confidence
- Severity: LOW / MEDIUM / HIGH / CRITICAL

### ANPR
- License plate detection and OCR via EasyOCR
- Temporal stabilization across frames
- Format validation and contextual correction

### Face Detection
- YuNet-based face detection (ONNX runtime)
- Person-track association
- **Detection only** — no facial recognition, no biometric identification

## Evidence & Integrity

- Captured evidence includes: frame snapshot, bounding box, event metadata, risk assessment
- Each evidence record receives a **SHA-256 fingerprint**
- Optional **local blockchain ledger** provides tamper-evident chaining of evidence records
- Evidence is stored off-chain; blockchain records fingerprints only

## Offline / Store-and-Forward

- When network is unavailable, events queue locally
- Automatic sync when connectivity resumes
- Exponential backoff retry strategy
- Configurable retention and cleanup

## Testing

```bash
# Python unit tests (no database required)
cd backend
set PYTHONPATH=ai
python -m pytest ai/tests/ -v

# TypeScript check
npx tsc --noEmit

# Build
npm run build
```

**Known pre-existing test failures:** 32 tests in `test_evidence.py` (9) and `test_sync.py` (23) have asyncio event loop deprecation issues on Python 3.12. These are pre-existing and unrelated to current development.

## Development Workflow

- Frontend: `npm run dev` (Vite dev server on port 3000)
- Backend: `set PYTHONPATH=backend && python -m ai.main` (FastAPI on port 8000)
- WebSocket: real-time AI alerts pushed to frontend via `/ws/ai-alerts`

## Security Rules

- **Never commit `.env`** — contains real credentials
- **Never commit private keys** (`*.key`, `*.pem`)
- **Never hardcode passwords** in source code
- **Rotate exposed credentials** if repository was previously public
- All evidence is SHA-256 fingerprinted for tamper detection

## Known Limitations

- **Face detection ≠ facial recognition** — IBVAP detects faces but does not identify individuals
- **Local blockchain** — prototype/tamper-evident record, not a distributed network
- **Demo video** — `data/surveillance_test.mp4` is a test clip; field validation with real border CCTV not performed in this repository
- **SD/local footage recovery** — prototype mode; physical SD card recovery from government hardware not tested
- **Stock YOLO model** — COCO pre-trained; custom border-surveillance fine-tuning not yet performed

## SIH2026-187 Traceability

See [`docs/SIH2026-187_TRACEABILITY.md`](docs/SIH2026-187_TRACEABILITY.md) for requirement mapping. The official SIH2026-187 problem statement document is not currently in this repository.

## License

Internal use for SIH2026-187 project submission.
