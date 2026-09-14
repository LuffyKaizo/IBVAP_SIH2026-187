# IBVAP — Repository Structure

## Directory Layout

```
SIH2026-187/
├── .env.example                    Environment variable template
├── .gitignore                      Git ignore rules
├── CONTRIBUTING.md                 Contribution guidelines
├── README.md                       Project overview and quick start
├── package.json                    Node.js dependencies and scripts
├── package-lock.json               npm lockfile
├── bun.lock                        Bun lockfile
├── index.html                      Vite entry HTML
├── tsconfig.json                   TypeScript configuration
├── vite.config.ts                  Vite build configuration
├── yolov8n.pt                      YOLO v8 nano model (baseline, tracked)
│
├── frontend/                       React + TypeScript frontend
│   ├── src/
│   │   ├── App.tsx                 Root component with routing
│   │   ├── main.tsx                Entry point
│   │   ├── types.ts                Shared TypeScript types
│   │   ├── components/             Reusable UI components
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── AIBoundingBoxOverlay.tsx   Detection/tracking overlay
│   │   │   ├── AIFaceOverlay.tsx          Face detection overlay
│   │   │   └── ...
│   │   ├── views/                  Page-level components
│   │   │   ├── LoginView.tsx
│   │   │   ├── CommandDashboardView.tsx
│   │   │   ├── CamerasMonitoringView.tsx
│   │   │   ├── EventIntelligenceView.tsx
│   │   │   ├── AnprView.tsx
│   │   │   ├── ReportsView.tsx
│   │   │   └── ...
│   │   ├── hooks/                  Custom React hooks
│   │   │   ├── useAiAlerts.ts
│   │   │   └── useAiCameraStream.ts
│   │   ├── contexts/               React context providers
│   │   │   └── AuthContext.tsx
│   │   └── vite-env.d.ts          Vite type declarations
│   └── ...
│
├── backend/
│   ├── express/                    Express BFF (Backend-for-Frontend)
│   │   ├── server.ts               Express server, API proxy, WebSocket bridge
│   │   └── auth.ts                 JWT verification middleware
│   │
│   └── ai/                         FastAPI AI service
│       ├── main.py                 FastAPI application entry point
│       ├── config.py               Centralized environment configuration
│       ├── pipeline.py             Main AI pipeline (detection → tracking → events)
│       ├── requirements.txt        Python dependencies
│       ├── alembic.ini             Alembic migration configuration
│       │
│       ├── alembic/                Database migrations
│       │   └── versions/           Individual migration scripts
│       │
│       ├── anpr/                   Automatic Number Plate Recognition
│       │   ├── detector.py         Plate detection
│       │   ├── ocr.py              OCR engine (EasyOCR)
│       │   ├── stabilizer.py       Temporal plate stabilization
│       │   └── formatter.py        Format validation
│       │
│       ├── auth/                   Authentication & RBAC
│       │   ├── jwt_handler.py      JWT token creation/verification
│       │   ├── passwords.py        Password hashing (bcrypt)
│       │   └── rbac.py             Role-based access control
│       │
│       ├── blockchain/             Trust layer
│       │   ├── ledger.py           LocalLedger (tamper-evident chain)
│       │   └── service.py          BlockchainService
│       │
│       ├── camera/                 Camera management
│       │   ├── manager.py          CameraManager (lifecycle, state)
│       │   └── pipeline.py         Per-camera processing pipeline
│       │
│       ├── context/                Context intelligence
│       │   └── engine.py           ContextEngine (dwell, loiter, fence, direction)
│       │
│       ├── db/                     Database layer
│       │   ├── session.py          SQLAlchemy async session
│       │   └── repositories/       Data access objects
│       │       ├── camera_repo.py
│       │       ├── event_repo.py
│       │       ├── evidence_repo.py
│       │       └── user_repo.py
│       │
│       ├── detection/              YOLO detection
│       │   └── yolo_detector.py    YOLO v8 inference wrapper
│       │
│       ├── edge/                   Edge node security
│       │   ├── token_manager.py    Edge JWT token management
│       │   └── auth.py             Edge authentication
│       │
│       ├── events/                 Event engine
│       │   ├── engine.py           EventEngine (virtual fence, intrusion)
│       │   └── behavior.py         BehaviorEngine (loitering, night movement)
│       │
│       ├── evidence/               Evidence management
│       │   ├── manager.py          EvidenceManager
│       │   └── sha256.py           SHA-256 fingerprinting
│       │
│       ├── face/                   Face detection
│       │   ├── detector.py         YuNet face detector
│       │   └── models/             ONNX model files
│       │
│       ├── network/                Network health
│       │   └── health.py           NetworkHealthMonitor state machine
│       │
│       ├── risk/                   Risk scoring
│       │   └── engine.py           RiskEngine (deterministic 0–100)
│       │
│       ├── sync/                   Store-and-forward
│       │   ├── client.py           Central server sync client
│       │   └── queue.py            Offline event queue
│       │
│       ├── tracking/               Object tracking
│       │   └── bytetrack.py        ByteTrack integration
│       │
│       ├── video/                  Video capture
│       │   ├── capture.py          VideoCapture (file/RTSP/webcam)
│       │   └── rtsp.py             RTSP ingestion with reconnection
│       │
│       ├── data/                   Runtime data (gitignored)
│       │   └── evidence/           Captured evidence files
│       │
│       └── tests/                  Python test suite
│           ├── conftest.py         Shared test fixtures
│           ├── test_auth.py        Authentication tests
│           ├── test_evidence.py    Evidence management tests
│           ├── test_sync.py        Sync tests
│           ├── test_context_risk.py  Context + Risk engine tests
│           └── ...
│
├── data/                           Test data
│   ├── surveillance_test.mp4       Primary demo video (tracked)
│   ├── test.mp4                    Secondary test video (tracked)
│   ├── anpr_test/                  ANPR test plate images
│   └── face_validation/            Face detection test images
│
├── models/                         Model weights directory
│
├── scripts/                        Utility scripts
│   ├── ensure_admin.py             Bootstrap admin user
│   ├── reset_admin_password.py     Reset admin password
│   └── check_db.py                 Database connectivity check
│
├── docs/                           Documentation
│   ├── TEAM_SETUP.md               Complete team setup guide
│   ├── TEAM_ARCHITECTURE.md        System architecture
│   ├── REPOSITORY_STRUCTURE.md     This file
│   ├── CONTEXT_RISK_INTELLIGENCE.md  Context/Risk engine docs
│   ├── SIH2026-187_TRACEABILITY.md   Requirement traceability
│   ├── GITHUB_READINESS_REPORT.md  Repository readiness report
│   └── FINAL_SCREENING_*.md        Screening phase reports
│
└── .github/                        GitHub configuration
    ├── CODEOWNERS                  Code ownership
    ├── pull_request_template.md    PR template
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   └── feature_request.md
    └── workflows/
        └── ci.yml                  CI pipeline
```

## Ownership Boundaries

| Directory | Owner | Scope |
|-----------|-------|-------|
| `frontend/src/` | Frontend team | UI components, views, hooks, contexts |
| `backend/express/` | Full-stack | BFF proxy, WebSocket bridge, auth middleware |
| `backend/ai/` | AI/Backend team | Detection, tracking, events, evidence, blockchain |
| `backend/ai/context/` | AI team | ContextEngine intelligence |
| `backend/ai/risk/` | AI team | RiskEngine scoring |
| `backend/ai/anpr/` | AI team | License plate recognition |
| `backend/ai/face/` | AI team | Face detection |
| `scripts/` | DevOps/Backend | Database bootstrap, admin utilities |
| `docs/` | All | Project documentation |
| `.github/` | DevOps | CI, templates, collaboration |

## Key Files

| File | Purpose |
|------|---------|
| `.env.example` | Environment variable reference (copy to `.env`) |
| `package.json` | Node dependencies, `npm run dev`, `npm run build` |
| `backend/ai/requirements.txt` | Python dependencies |
| `backend/ai/config.py` | All environment variable definitions |
| `backend/ai/main.py` | FastAPI application entry |
| `backend/ai/pipeline.py` | Core AI pipeline |
| `backend/express/server.ts` | Express BFF entry |
| `vite.config.ts` | Vite build configuration |
| `yolov8n.pt` | YOLO v8 baseline model (6.2 MB, tracked) |
