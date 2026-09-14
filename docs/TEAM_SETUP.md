# IBVAP — Team Setup Guide

Complete setup instructions for Windows development environment.

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Git | Latest | Version control |
| Python | 3.12.x | AI backend |
| Node.js | 18+ LTS | Frontend + Express |
| npm | 10+ | Package management |

Optional:
- **FFmpeg** — only if processing video files outside the pipeline
- **CUDA toolkit** — only if GPU inference is desired

## 1. Clone Repository

```bash
git clone <repository-url>
cd SIH2026-187
```

## 2. Python Environment

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\ai\requirements.txt
```

**Key Python dependencies:**
- FastAPI, uvicorn (web framework)
- OpenCV, Ultralytics/YOLO, PyTorch (AI/CV)
- EasyOCR (license plate recognition)
- SQLAlchemy, asyncpg, Alembic (database)
- python-jose, bcrypt (authentication)

## 3. Node Dependencies

```bash
npm install
```

## 4. Environment Configuration

```bash
copy .env.example .env
```

Edit `.env` and configure at minimum:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (Supabase) |
| `SECRET_KEY` | Yes | JWT signing key (generate 64+ random chars) |
| `ADMIN_PASSWORD` | Yes | Password for admin bootstrap scripts |
| `EDGE_NODE_SECRET` | Yes | Edge node authentication secret |
| `EDGE_TOKEN_SECRET` | Yes | Edge JWT signing secret |
| `ADMIN_EMAIL` | No | Default: `admin@ibvap.local` |
| `SYNC_ENABLED` | No | Default: `false` (standalone mode) |
| `BLOCKCHAIN_ENABLED` | No | Default: `false` |

**Generate a SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Security warnings:**
- Never commit `.env` to version control
- Never share real credentials in chat/email
- If the repository was previously public, rotate all exposed credentials

## 5. Database Setup (Supabase)

### Option A: Supabase Cloud (Recommended)

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. Copy the connection string from Settings → Database → Connection string → URI
3. Set `DATABASE_URL` in `.env` with the connection string
4. Ensure `sslmode=require` is in the URL

### Option B: Local PostgreSQL

1. Install PostgreSQL 14+
2. Create database: `createdb netraksh_db`
3. Set `DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/netraksh_db`

### Run Migrations

```bash
cd backend
alembic upgrade head
```

This creates all required tables (cameras, zones, events, evidence, users, etc.).

### Bootstrap Admin User

```bash
python scripts\ensure_admin.py
```

This creates `admin@ibvap.local` with the password from `ADMIN_PASSWORD` in `.env`.

## 6. Start the Application

### AI Backend (FastAPI — port 8000)

Open a terminal:

```bash
cd SIH2026-187
.venv\Scripts\activate
set PYTHONPATH=backend
python -m ai.main
```

**Important:** The `PYTHONPATH=backend` is required so Python can find the `ai` package.

The FastAPI server starts on `http://localhost:8000`.

Verify: `curl http://localhost:8000/api/health`

### Frontend + Express BFF (port 3000)

Open a **second terminal**:

```bash
cd SIH2026-187
npm run dev
```

The Vite dev server starts on `http://localhost:3000`.

## 7. Ports & Endpoints

| Service | Port | URL |
|---------|------|-----|
| Frontend (Vite) | 3000 | `http://localhost:3000` |
| AI Backend (FastAPI) | 8000 | `http://localhost:8000` |
| WebSocket alerts | 8000 | `ws://localhost:8000/ws/ai-alerts` |

## 8. Demo Workflow

### Login

1. Open `http://localhost:3000`
2. Enter `admin@ibvap.local` and the password from `ADMIN_PASSWORD`
3. Click Login

### Camera Setup

1. Navigate to Cameras
2. Add a camera with video source: `./data/surveillance_test.mp4`
3. Start the camera — AI processing begins automatically

### What Happens

1. **YOLO** detects objects (person, car, motorcycle, bus, truck)
2. **ByteTrack** assigns consistent track IDs across frames
3. **ContextEngine** analyzes behavior (dwell, loiter, direction, etc.)
4. **EventEngine** generates security events (virtual fence, intrusion)
5. **RiskEngine** assigns 0–100 risk score with severity
6. **Evidence** is captured with SHA-256 fingerprint
7. **WebSocket** pushes real-time alerts to the frontend dashboard

### Verify Evidence

```bash
curl http://localhost:8000/api/evidence?limit=5
```

Each record includes `sha256Hash` for integrity verification.

### Verify Blockchain (if enabled)

Set `BLOCKCHAIN_ENABLED=true` in `.env`, restart backend, then:

```bash
curl http://localhost:8000/api/blockchain/status
```

## 9. AI Subsystems

### ANPR (Automatic Number Plate Recognition)

- Enabled by default (`ANPR_ENABLED=true`)
- Uses EasyOCR for plate OCR
- Detects plates on vehicles, validates format, stabilizes across frames
- Test images: `data/anpr_test/`

### Face Detection

- Enabled by default (`FACE_DETECTION_ENABLED=true`)
- Uses YuNet ONNX model for face detection
- Associates detected faces with tracked persons
- **Detection only** — no facial recognition

### Context Engine

- Analyzes tracked object behavior per frame
- Computes: dwell time, loitering, fence proximity, direction, repeated entry
- Configurable thresholds via environment variables

### Risk Engine

- Deterministic scoring (no ML/randomness)
- Factors weighted by zone severity, behavior, and context
- Output: score (0–100), severity (LOW/MEDIUM/HIGH/CRITICAL), contributing factors

## 10. Testing

### Python Tests

```bash
cd backend
set PYTHONPATH=ai
python -m pytest ai/tests/ -v
```

**Unit tests (no database required):** ~21 test files covering detection, tracking, events, context, risk, evidence, blockchain, sync, network health, ANPR, face detection.

**Integration tests (require Supabase):** `test_auth.py`, `test_section9_final.py`, `test_db_diag.py`, `test_db_diag2.py` — these will fail without a live database.

**Known pre-existing failures:** 32 tests in `test_evidence.py` (9) and `test_sync.py` (23) have Python 3.12 asyncio event loop deprecation issues.

### TypeScript Check

```bash
npx tsc --noEmit
```

### Build

```bash
npm run build
```

## 11. Troubleshooting

### "ModuleNotFoundError: No module named 'ai'"
→ Ensure `PYTHONPATH=backend` is set before running Python commands.

### "DATABASE_URL not set"
→ Copy `.env.example` to `.env` and fill in `DATABASE_URL`.

### "SECRET_KEY not set"
→ Generate one: `python -c "import secrets; print(secrets.token_hex(32))"` and add to `.env`.

### Frontend shows "Connection refused"
→ Ensure the AI backend is running on port 8000 in a separate terminal.

### WebSocket not connecting
→ Verify `VITE_AI_SERVICE_URL` or that the Express BFF proxy is configured correctly.

### EasyOCR import error
→ Run: `pip install easyocr` (may take several minutes for first-time model download).

### Video not playing
→ Verify `data/surveillance_test.mp4` exists. For RTSP sources, ensure network connectivity.

## 12. Security Reminders

- **Never commit `.env`** — it contains real database credentials and secrets
- **Never hardcode passwords** in source code
- **Rotate credentials** if the repository was previously exposed publicly
- **Use strong secrets** for `SECRET_KEY`, `EDGE_NODE_SECRET`, `EDGE_TOKEN_SECRET`
- All `.key` and `.pem` files are gitignored — never track private keys
