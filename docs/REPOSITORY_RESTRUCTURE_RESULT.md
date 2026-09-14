# Repository Restructure Result

**Date:** 2026-09-13
**Git Checkpoint:** `5ec3d25` (pre-restructure commit)

## Final Directory Structure

```
netraksh-tactical-intelligence-sih/
├── .env
├── .env.example
├── .gitignore
├── README.md
├── metadata.json
├── package.json                    # Single root package.json
├── package-lock.json
├── bun.lock
│
├── certificates/
│   ├── auto.crt
│   └── auto.key
│
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── types.ts
│       ├── mockData.ts
│       ├── vite-env.d.ts
│       ├── components/  (11 files)
│       ├── contexts/    (1 file)
│       ├── hooks/       (3 files)
│       └── views/       (10 files)
│
├── backend/
│   ├── express/
│   │   ├── server.ts
│   │   └── auth.ts
│   └── ai/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── pipeline.py
│       ├── requirements.txt
│       ├── alembic.ini + alembic/
│       ├── anpr/ auth/ blockchain/ camera/ db/ detection/
│       ├── edge/ events/ evidence/ face/ network/ sync/
│       ├── tracking/ video/
│       ├── data/evidence/
│       └── tests/
│
├── data/
│   └── surveillance_test.mp4
│
├── models/
│   └── yolov8n.pt
│
├── scripts/
│   ├── check_db.py
│   ├── ensure_admin.py
│   └── reset_admin_password.py
│
├── docs/
├── assets/
│
└── debug/
    ├── diagnose_*.py  (4 files)
    ├── step1_*.py     (2 files)
    ├── step5_*.py     (4 files)
    ├── _write_pipeline.py
    ├── _gen_login.js
    ├── pipeline_result.txt
    ├── frames/
    └── .freebuff/
```

## Files Moved

| Source | Destination |
|--------|-------------|
| `index.html` | `frontend/index.html` |
| `tsconfig.json` | `frontend/tsconfig.json` |
| `vite.config.ts` | `frontend/vite.config.ts` |
| `src/*` | `frontend/src/*` |
| `server.ts` | `backend/express/server.ts` |
| `server/auth.ts` | `backend/express/auth.ts` |
| `ai/*` | `backend/ai/*` |
| `auto.crt`, `auto.key` | `certificates/` |
| `diagnose_*.py`, `step*.py` | `debug/` |
| `debug_frames/*` | `debug/frames/` |
| `.freebuff/` | `debug/.freebuff/` |

## Imports/Paths Changed

### `backend/express/server.ts`
- `'./server/auth'` → `'./auth'`
- `'./src/mockData.ts'` → `'../../frontend/src/mockData.ts'`
- `'./src/types.ts'` → `'../../frontend/src/types.ts'`
- Added `import { fileURLToPath } from 'url'` + `__dirname` polyfill
- Added `root: path.resolve(__dirname, '../../frontend')` to Vite server
- Dist path: `path.join(process.cwd(), 'frontend', 'dist')`

### `frontend/vite.config.ts`
- `'@': path.resolve(__dirname, '.')` → `'@': path.resolve(__dirname, './src')`

### `frontend/tsconfig.json`
- `"@/*": ["./*"]` → `"@/*": ["./src/*"]`

### `backend/ai/main.py`
- `.env` path: `.parent.parent` → `.parent.parent.parent`

### `scripts/*.py` (3 files)
- `sys.path.insert(0, root)` → `sys.path.insert(0, root / "backend")`

### `debug/*.py` (10 files)
- Added `sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backend'))`
- Updated video paths: `data/...` → `../data/...`
- Updated debug_frames: `debug_frames/` → `frames/`

### `package.json`
- `"dev": "tsx server.ts"` → `"dev": "tsx backend/express/server.ts"`
- `"build"` → `cd frontend && npx vite build && cd .. && npx esbuild backend/express/server.ts ...`
- `"lint"` → `cd frontend && npx tsc --noEmit`
- Added `"ai": "set PYTHONPATH=backend && python -m ai.main"`

### `.gitignore`
- `ai/` paths → `backend/ai/`
- Added `debug/frames/`, `debug/.freebuff/`

### Test files (7 files)
- `_project_root`: `parent.parent.parent` → `parent.parent.parent.parent`
- `TEST_MODEL` / `TEST_VIDEO`: added extra `..` for path resolution
- `mockData.ts` path: added `frontend/` segment

## Startup Commands

```bash
# Development
npm run dev          # Express + Vite on :3000
npm run ai           # FastAPI on :8000

# Production
npm run build        # Builds frontend + bundles Express
npm run start        # Node.js serves static frontend

# Tests
npm run lint         # TypeScript check
cd frontend && npx vite build  # Vite build
set PYTHONPATH=backend && python -m pytest backend/ai/  # Python tests
```

## Validation Results

| Check | Result |
|-------|--------|
| TypeScript | **PASS** (0 errors) |
| Vite build | **PASS** (901.95 KB JS, 54.21 KB CSS) |
| Express startup | **PASS** (port 3000, Vite middleware) |
| FastAPI startup | **PASS** (port 8000, DB connected) |
| Health check | **PASS** (`/api/health` returns OK) |
| Auth login | **PASS** (JWT issued, user returned) |
| Protected API | **PASS** (cameras, zones, dashboard) |
| Frontend serve | **PASS** (IBVAP HTML returned) |
| pytest | **PASS** (364 pass, 32 pre-existing, 0 new regressions) |

## Remaining Pre-existing Failures (32)
- `test_evidence.py` — 9 failures (DB FK constraint issues)
- `test_sync.py` — 23 failures (RuntimeError in async mock setup)

## No New Regressions
All 32 failures are the same pre-existing issues from before the restructure.
