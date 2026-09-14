# IBVAP — Team Architecture

## System Overview

IBVAP is a three-tier architecture: **React Frontend** → **Express BFF** → **FastAPI AI Service** → **PostgreSQL Database**.

```
┌─────────────────────────────────────────────────────────┐
│                    React Frontend                        │
│              (TypeScript, Vite, port 3000)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │Dashboard │ │Cameras   │ │Events    │ │ANPR/Face  │  │
│  └──────────┘ └──────────┘ └──────────┘ └───────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP / WebSocket
┌───────────────────────┴─────────────────────────────────┐
│                   Express BFF                            │
│            (Node.js, TypeScript, port 3000)              │
│  ┌──────────────┐ ┌───────────────┐ ┌────────────────┐  │
│  │API Proxy     │ │WebSocket      │ │Auth Bridge     │  │
│  │→ FastAPI     │ │→ AI Alerts    │ │→ JWT verify    │  │
│  └──────────────┘ └───────────────┘ └────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP / WebSocket
┌───────────────────────┴─────────────────────────────────┐
│                  FastAPI AI Service                       │
│               (Python, port 8000)                         │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │                  AI Pipeline                         │ │
│  │  Video → YOLO → ByteTrack → Context → Events → Risk│ │
│  └─────────────────────────────────────────────────────┘ │
│                                                           │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │ANPR     │ │Face Det. │ │Evidence  │ │Blockchain   │ │
│  │(EasyOCR)│ │(YuNet)   │ │+ SHA-256 │ │(LocalLedger)│ │
│  └─────────┘ └──────────┘ └──────────┘ └─────────────┘ │
│                                                           │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐ │
│  │Camera   │ │Sync      │ │Network   │ │Auth/RBAC    │ │
│  │Manager  │ │(Offline) │ │Health    │ │(JWT/bcrypt) │ │
│  └─────────┘ └──────────┘ └──────────┘ └─────────────┘ │
└───────────────────────┬─────────────────────────────────┘
                        │ asyncpg (SQLAlchemy 2.0)
┌───────────────────────┴─────────────────────────────────┐
│               PostgreSQL (Supabase)                       │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌───────┐ │
│  │cameras │ │zones   │ │events  │ │evidence│ │users  │ │
│  └────────┘ └────────┘ └────────┘ └────────┘ └───────┘ │
└─────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### React Frontend

**Location:** `frontend/src/`

| Component | Responsibility |
|-----------|---------------|
| Views | Page-level UI (Dashboard, Cameras, Events, ANPR, Reports) |
| Components | Reusable UI elements (overlays, headers, sidebars) |
| Hooks | Data fetching (`useAiAlerts`, `useAiCameraStream`) |
| Contexts | Auth state management (`AuthContext`) |
| Types | Shared TypeScript interfaces (`types.ts`) |

**Rules:**
- No backend secrets in frontend code
- No `VITE_*` variables for passwords/tokens
- All API calls go through Express BFF or direct to FastAPI

### Express BFF

**Location:** `backend/express/`

| File | Responsibility |
|------|---------------|
| `server.ts` | HTTP server, API proxy to FastAPI, WebSocket bridge |
| `auth.ts` | JWT verification middleware |

**Rules:**
- No business logic — proxy only
- WebSocket forwards AI alerts from FastAPI to frontend clients
- Authentication verification delegated to FastAPI

### FastAPI AI Service

**Location:** `backend/ai/`

| Module | Responsibility |
|--------|---------------|
| `main.py` | FastAPI app, route registration, startup/shutdown |
| `config.py` | All environment variable configuration |
| `pipeline.py` | Core pipeline: detection → tracking → context → events → risk |
| `camera/` | Camera lifecycle management, per-camera pipelines |
| `detection/` | YOLO v8 inference wrapper |
| `tracking/` | ByteTrack multi-object tracking |
| `context/` | ContextEngine: dwell, loiter, fence, direction, repeated entry |
| `events/` | EventEngine: virtual fence, intrusion, behavior analysis |
| `risk/` | RiskEngine: deterministic 0–100 scoring |
| `anpr/` | License plate detection, OCR, stabilization |
| `face/` | Face detection (YuNet, NOT recognition) |
| `evidence/` | Evidence capture, SHA-256 fingerprinting |
| `blockchain/` | LocalLedger tamper-evident chain |
| `sync/` | Store-and-forward queue, central server sync |
| `network/` | Network health state machine |
| `auth/` | JWT handling, password hashing, RBAC |
| `db/` | SQLAlchemy sessions, repository pattern |
| `alembic/` | Database migration scripts |

### Database (PostgreSQL)

**Tables:** cameras, zones, events, evidence, users, sync_queue, blockchain_ledger, etc.

**Access pattern:** Repository pattern via SQLAlchemy 2.0 async sessions.

## Data Flow

```
1. Video Frame
   ↓
2. YOLO Detection (person, car, motorcycle, etc.)
   ↓
3. ByteTrack (assign/maintain track IDs)
   ↓
4. ContextEngine (per-track: dwell, loiter, fence, direction)
   ↓
5. EventEngine (generate security events: intrusion, loitering)
   ↓
6. RiskEngine (score 0–100, classify severity)
   ↓
7. Alert Deduplication (CREATE / ESCALATE / UPDATE)
   ↓
8. Evidence Capture (snapshot + metadata + SHA-256)
   ↓
9. Optional: Blockchain Anchor (LocalLedger record)
   ↓
10. WebSocket Push → Frontend Dashboard
    ↓
11. Optional: Store-and-Forward → Central Server (when connected)
```

## Where to Add New Features

| Feature Type | Location | Notes |
|-------------|----------|-------|
| New frontend view | `frontend/src/views/` | Add route in `App.tsx` |
| New UI component | `frontend/src/components/` | Reusable, no business logic |
| New React hook | `frontend/src/hooks/` | Data fetching / state |
| New API endpoint | `backend/ai/main.py` | Register route |
| New AI behavior | `backend/ai/context/` or `backend/ai/events/` | Extend existing engines |
| New detection class | `backend/ai/config.py` `RELEVANT_CLASSES` | Add to COCO class list |
| New database table | `backend/ai/alembic/versions/` | Create migration |
| New repository | `backend/ai/db/repositories/` | Follow existing pattern |
| New test | `backend/ai/tests/` | Follow existing patterns |
| New script | `scripts/` | Document in README |
| New documentation | `docs/` | Cross-link from README |

## Security Boundaries

| Boundary | Implementation |
|----------|---------------|
| Frontend ↔ Backend | HTTP only, JWT in Authorization header |
| Backend ↔ Database | SQLAlchemy async, connection pooling |
| Backend ↔ Central Server | Optional TLS, edge node tokens |
| Evidence integrity | SHA-256 fingerprinting |
| Trust chain | LocalLedger blockchain (tamper-evident) |
| Authentication | JWT (python-jose), bcrypt password hashing |
| Authorization | RBAC: ADMIN / OPERATOR / VIEWER |
