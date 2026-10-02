"""IBVAP AI Service - FastAPI with multi-camera management, video stream and WebSocket."""

import time
import asyncio
import os
import uuid
import cv2
import numpy as np
from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root before any config imports
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from ai.config import is_production, settings
from ai.detection.yolo_detector import YoloDetector
from ai.camera.config import CameraConfig
from ai.camera.manager import CameraManager
from ai.db.session import init_db, close_db, get_db_session, is_available
from ai.db.repositories import (
    CameraRepository, ZoneRepository, EventRepository,
    AlertRepository, AnprRepository, AuditRepository, UserRepository,
    EvidenceRepository, SyncQueueRepository,
)
from ai.evidence.store import LocalFileEvidenceStore
from ai.evidence.capture import EvidenceCapture
from ai.evidence.routes import router as evidence_router, init_evidence_routes
from ai.reports.routes import router as reports_router, init_report_routes
from ai.tactical.routes import router as tactical_router, init_tactical_routes
from ai.sync.client import CentralSyncClient
from ai.sync.manager import SyncManager
from ai.sync.routes import router as sync_router, init_sync_routes
from ai.network.health import NetworkHealthManager
from ai.network.routes import router as network_router, init_network_routes
from ai.auth.routes import router as auth_router, bootstrap_admin
from ai.auth.deps import get_current_user, require_permission, get_user_from_token_query
from ai.auth.models import Permission, UserContext
from ai.edge.registry import EdgeNodeRepository
from ai.edge.auth import EdgeTokenManager, AuthRateLimiter, bootstrap_edge_node
from ai.edge.deps import init_edge_deps
from ai.edge.routes import router as edge_router, init_edge_routes
from ai.blockchain.repository import BlockchainAnchorRepository
from ai.blockchain.local_ledger import LocalLedger
from ai.blockchain.service import BlockchainService
from ai.blockchain.routes import router as blockchain_router, init_blockchain_routes

detector = YoloDetector()
camera_manager = None
start_time = 0.0
ws_clients = set()

# Repository instances (set during startup)
_camera_repo = None
_zone_repo = None
_event_repo = None
_alert_repo = None
_anpr_repo = None
_audit_repo = None
_user_repo = None


# Legacy auto-created default zone (pre-fix): covered ~80% of the frame, which
# made every ground point "inside" — all objects rendered red. Zones are now
# operator-created on demand (spec: create when needed, empty list otherwise).
_LEGACY_DEFAULT_ZONE_NAME = "Restricted Border Area"
_LEGACY_DEFAULT_ZONE_POINTS = [
    {"x": 0.10, "y": 0.20},
    {"x": 0.90, "y": 0.20},
    {"x": 0.90, "y": 0.90},
    {"x": 0.10, "y": 0.90},
]
# Replacement geometry: a bottom border strip (visible, editable, disable-able)
_LEGACY_DEFAULT_ZONE_STRIP = [
    {"x": 0.10, "y": 0.80},
    {"x": 0.90, "y": 0.80},
    {"x": 0.90, "y": 0.95},
    {"x": 0.10, "y": 0.95},
]


def _build_default_zones(camera_id: str):
    """No implicit zones for a camera — operators define zones on demand."""
    return []


def _is_legacy_default_zone(zone) -> bool:
    """True for the untouched auto-created full-frame default rectangle."""
    pts = getattr(zone, "points", None) or (
        zone.get("points") if isinstance(zone, dict) else None
    )
    name = getattr(zone, "name", None) or (
        zone.get("name") if isinstance(zone, dict) else ""
    )
    if name != _LEGACY_DEFAULT_ZONE_NAME or not pts or len(pts) != 4:
        return False
    try:
        for p, expected in zip(pts, _LEGACY_DEFAULT_ZONE_POINTS):
            px = p.get("x") if isinstance(p, dict) else float(p["x"])
            py = p.get("y") if isinstance(p, dict) else float(p["y"])
            if abs(float(px) - expected["x"]) > 1e-6 or abs(float(py) - expected["y"]) > 1e-6:
                return False
        return True
    except Exception:
        return False


def _build_seed_camera() -> CameraConfig:
    """Build CAM-01 from environment config for DB seeding."""
    return CameraConfig(
        camera_id="CAM-01",
        name="BOP NORTH MAIN GATE",
        location="North Outpost Main Gate",
        source=settings.VIDEO_SOURCE,
        source_type=settings.VIDEO_SOURCE_TYPE,
        camera_type="FIXED",
        enabled=True,
    )


@asynccontextmanager
async def lifespan(app):
    global start_time, camera_manager, _camera_repo, _zone_repo
    global _event_repo, _alert_repo, _anpr_repo, _audit_repo, _user_repo
    global _blockchain_service

    _blockchain_service = None
    start_time = time.time()

    # --- Production deployment safety: fail fast, never degrade silently ---
    if is_production():
        missing = [
            name for name in ("SECRET_KEY", "DATABASE_URL", "ADMIN_EMAIL", "ADMIN_PASSWORD")
            if not str(getattr(settings, name, "") or "").strip()
        ]
        if missing:
            raise RuntimeError(
                "Production startup aborted — missing required environment "
                "variables: %s" % ", ".join(missing)
            )
        db_url = settings.DATABASE_URL
        db_scheme = db_url.split(":", 1)[0]
        if db_scheme not in (
            "postgresql", "postgres", "postgresql+asyncpg", "postgres+asyncpg",
            "sqlite", "sqlite+aiosqlite",
        ):
            raise RuntimeError(
                "Production startup aborted — DATABASE_URL must be a "
                "PostgreSQL or SQLite connection string in production, "
                "got scheme %r" % db_scheme
            )
        if db_scheme.startswith("sqlite") and ":memory:" in db_url:
            raise RuntimeError(
                "Production startup aborted — in-memory SQLite is not "
                "allowed in production; use a file on persistent storage "
                "(e.g. sqlite+aiosqlite:////var/data/ibvap.db)."
            )
        if os.getenv("DEV_AUTH_BYPASS", "false").lower() == "true":
            raise RuntimeError(
                "Production startup aborted — DEV_AUTH_BYPASS must not be "
                "enabled in production."
            )
        if not settings.EVIDENCE_DIR or not os.path.isabs(settings.EVIDENCE_DIR):
            raise RuntimeError(
                "Production startup aborted — EVIDENCE_DIR must be an absolute "
                "path on persistent storage (e.g. /var/data/evidence); the "
                "container filesystem is ephemeral."
            )

    detector.load()

    # Initialize database (creates engine + session factory, no held session)
    db_ok = await init_db(settings.DATABASE_URL)
    if is_production() and not db_ok:
        raise RuntimeError(
            "Production startup aborted — Database connection failed "
            "(DATABASE_URL). Persistence is mandatory in production; the "
            "no-database fallback is not allowed."
        )
    if db_ok:
        _camera_repo = CameraRepository()
        _zone_repo = ZoneRepository()
        _event_repo = EventRepository()
        _alert_repo = AlertRepository()
        _anpr_repo = AnprRepository()
        _audit_repo = AuditRepository()
        _user_repo = UserRepository()
        _evidence_repo = EvidenceRepository()

        # Bootstrap admin user if no users exist
        await bootstrap_admin(_user_repo)

    # Evidence subsystem (works without DB for local-only storage)
    _evidence_dir = settings.EVIDENCE_DIR or None
    _evidence_store = LocalFileEvidenceStore(base_dir=_evidence_dir)

    # Blockchain trust layer — must be created BEFORE EvidenceCapture
    # so that auto-anchoring works in the capture path.
    _blockchain_anchor_repo = BlockchainAnchorRepository() if db_ok else None
    _blockchain_ledger = None
    if settings.BLOCKCHAIN_ENABLED:
        if settings.BLOCKCHAIN_LEDGER_TYPE == "local":
            _blockchain_ledger = LocalLedger(
                anchor_repo=_blockchain_anchor_repo,
                simulated_latency_ms=settings.BLOCKCHAIN_LOCAL_LATENCY_MS,
            )
        else:
            print("[STARTUP] WARNING: Unknown BLOCKCHAIN_LEDGER_TYPE=%s, blockchain disabled" % settings.BLOCKCHAIN_LEDGER_TYPE)

        if _blockchain_ledger:
            _blockchain_service = BlockchainService(
                ledger=_blockchain_ledger,
                evidence_repo=_evidence_repo if db_ok else None,
                evidence_store=_evidence_store,
                audit_repo=_audit_repo if db_ok else None,
                sync_repo=None,
                anchor_repo=_blockchain_anchor_repo,
            )
            print("[STARTUP] Blockchain trust layer enabled (type=%s, policy=%s)" % (
                settings.BLOCKCHAIN_LEDGER_TYPE, settings.BLOCKCHAIN_ANCHOR_POLICY,
            ))
    else:
        print("[STARTUP] Blockchain trust layer disabled (BLOCKCHAIN_ENABLED=false)")

    # EvidenceCapture now receives the real BlockchainService (not None)
    _evidence_capture = EvidenceCapture(
        store=_evidence_store,
        evidence_repo=_evidence_repo if db_ok else None,
        audit_repo=_audit_repo if db_ok else None,
        snapshot_quality=settings.EVIDENCE_SNAPSHOT_QUALITY,
        blockchain_service=_blockchain_service,
    )
    init_evidence_routes(
        _evidence_repo if db_ok else None,
        _evidence_store,
        _evidence_capture,
        _blockchain_service,
    )
    init_report_routes(
        _event_repo if db_ok else None,
        _alert_repo if db_ok else None,
        _evidence_repo if db_ok else None,
        _evidence_store,
    )
    # Tactical geospatial layer (PART 10): idempotent runtime schema —
    # no auto-migration and no create_all (alembic 008 is schema-as-code).
    _tactical_repo = None
    if db_ok:
        from ai.tactical.repository import TacticalRepository
        _tactical_repo = TacticalRepository()
        if await _tactical_repo.ensure_schema():
            print("[STARTUP] Tactical geospatial tables ready")
        else:
            print("[STARTUP] WARNING: tactical schema creation failed")
    init_tactical_routes(_tactical_repo, _camera_repo if db_ok else None)
    print("[STARTUP] Evidence subsystem initialized (dir=%s)" % _evidence_store._base_dir)

    # Sync subsystem (store-and-forward to central server)
    _sync_repo = SyncQueueRepository() if db_ok else None

    # Edge node identity & authentication (Section 14)
    _edge_node_repo = EdgeNodeRepository() if db_ok else None
    _edge_token_manager = None
    _edge_rate_limiter = None
    if settings.EDGE_NODE_ID and settings.EDGE_NODE_SECRET and settings.EDGE_TOKEN_SECRET:
        if _edge_node_repo:
            await bootstrap_edge_node(
                _edge_node_repo,
                settings.EDGE_NODE_ID,
                settings.EDGE_NODE_SECRET,
            )
        _edge_token_manager = EdgeTokenManager(
            token_secret=settings.EDGE_TOKEN_SECRET,
            token_ttl=settings.EDGE_TOKEN_TTL_SECONDS,
            issuer=settings.EDGE_TOKEN_ISSUER,
            node_registry=_edge_node_repo,
            audit_repo=_audit_repo if db_ok else None,
            last_seen_interval=settings.EDGE_LAST_SEEN_UPDATE_SECONDS,
        )
        _edge_rate_limiter = AuthRateLimiter(
            max_failures=settings.EDGE_AUTH_RATE_LIMIT_MAX,
            window_sec=settings.EDGE_AUTH_RATE_LIMIT_WINDOW_SEC,
        )
        init_edge_deps(_edge_token_manager)
        init_edge_routes(_edge_token_manager, _edge_rate_limiter)
        print("[STARTUP] Edge auth enabled (node=%s, ttl=%ds)" % (
            settings.EDGE_NODE_ID, settings.EDGE_TOKEN_TTL_SECONDS,
        ))
    else:
        print("[STARTUP] Edge auth disabled (EDGE_NODE_ID/EDGE_NODE_SECRET/EDGE_TOKEN_SECRET not set)")

    # Warn if central URL uses HTTP (not HTTPS)
    if settings.CENTRAL_API_URL.startswith("http://") and "localhost" not in settings.CENTRAL_API_URL:
        print("[STARTUP] WARNING: CENTRAL_API_URL uses HTTP, not HTTPS. Transport encryption is not in use.")

    _central_client = CentralSyncClient(
        base_url=settings.CENTRAL_API_URL,
        api_key=settings.CENTRAL_API_KEY,
        timeout=settings.SYNC_REQUEST_TIMEOUT_SEC,
        verify_tls=settings.CENTRAL_VERIFY_TLS,
        ca_bundle=settings.CENTRAL_CA_BUNDLE,
        edge_token_manager=_edge_token_manager,
    )

    # Network health monitor (observes CentralSyncClient, drives SyncManager state)
    _network_health = NetworkHealthManager(
        central_client=_central_client,
        audit_repo=_audit_repo if db_ok else None,
    )
    init_network_routes(_network_health, _sync_repo)

    _sync_manager = SyncManager(
        sync_repo=_sync_repo,
        evidence_store=_evidence_store,
        audit_repo=_audit_repo if db_ok else None,
        central_client=_central_client,
        network_health=_network_health,
    )
    init_sync_routes(_sync_manager, _sync_repo)

    # Initialize blockchain routes (service already created before EvidenceCapture)
    if _blockchain_service:
        init_blockchain_routes(_blockchain_service)

    # Create CameraManager with optional DB persistence
    camera_manager = CameraManager(
        model_path=settings.MODEL_PATH,
        camera_repo=_camera_repo,
        audit_repo=_audit_repo,
        event_repo=_event_repo,
        alert_repo=_alert_repo,
        anpr_repo=_anpr_repo,
        evidence_capture=_evidence_capture,
        sync_manager=_sync_manager,
    )

    # Load cameras from database or seed from env
    if db_ok and _camera_repo:
        cameras = await _camera_repo.list_all()
        if cameras:
            for cam_config in cameras:
                # Load zones from database for this camera
                cam_zones = []
                if _zone_repo:
                    cam_zones = await _zone_repo.list_for_camera(cam_config.camera_id)
                # Root-cause fix: the legacy auto-created default zone covered
                # ~80% of the frame, so every ground point evaluated "inside"
                # (all objects rendered red). Shrink any untouched default zone
                # to a bottom border strip; operator zones are left untouched.
                for z in cam_zones:
                    if _is_legacy_default_zone(z):
                        try:
                            if _zone_repo:
                                await _zone_repo.update(z.id, points=list(_LEGACY_DEFAULT_ZONE_STRIP))
                            z.points = [dict(p) for p in _LEGACY_DEFAULT_ZONE_STRIP]
                            print("[STARTUP] Normalized legacy default zone %s (%s)"
                                  % (z.id, cam_config.camera_id))
                        except Exception as exc:
                            print("[STARTUP] Zone normalize failed for %s: %s" % (z.id, exc))
                if not cam_zones:
                    cam_zones = _build_default_zones(cam_config.camera_id)
                await camera_manager.register_camera(
                    cam_config, auto_start=cam_config.enabled, zones=cam_zones
                )
            print("[STARTUP] Loaded %d cameras from database" % len(cameras))
        elif settings.VIDEO_SOURCE:
            seed_cam = _build_seed_camera()
            await _camera_repo.create(seed_cam)
            await camera_manager.register_camera(seed_cam, auto_start=True)
            print("[STARTUP] Seeded CAM-01 from env config (database was empty)")
        else:
            print("[STARTUP] No cameras in database and no VIDEO_SOURCE configured")
    else:
        cam01 = _build_seed_camera()
        camera_manager._sync_register_camera(cam01, auto_start=True)
        print("[STARTUP] Registered CAM-01 in-memory (no database)")

    # Start background workers
    await _network_health.start()
    await _sync_manager.start()

    yield

    # Shutdown: stop network health first, then sync, then cameras, then DB
    await _network_health.stop()
    await _sync_manager.stop()
    if camera_manager:
        camera_manager.shutdown_all()
    await close_db()


app = FastAPI(title="IBVAP AI Service", version="0.3.0", lifespan=lifespan)

# CORS - locked down to allowed origins
_allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth routes
app.include_router(auth_router)

# Evidence routes
app.include_router(evidence_router)
app.include_router(reports_router)
app.include_router(tactical_router)

# Sync routes
app.include_router(sync_router)

# Network health routes
app.include_router(network_router)

# Edge node auth routes (Section 14)
app.include_router(edge_router)

# Blockchain trust layer routes (Pre-Section 15A Retrofit)
app.include_router(blockchain_router)


# ──────────────────────────────────────────────────────────────────
# Health & Status (public)
# ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    uptime = round(time.time() - start_time, 1) if start_time else 0
    agg = camera_manager.get_aggregate_status() if camera_manager else {}
    return {
        "status": "ok" if detector.is_loaded else "degraded",
        "service": "ibvap-ai",
        "version": "0.3.0",
        "yolo_available": detector.is_loaded,
        "device": settings.get_device(),
        "uptime_seconds": uptime,
        "cameras": agg,
    }


@app.get("/status")
async def service_status(
    camera_id: Optional[str] = Query(None),
    _user: UserContext = Depends(require_permission(Permission.CAMERA_READ)),
):
    """Service status. If camera_id is given, return that camera's status."""
    if camera_id and camera_manager:
        pipeline = camera_manager.get_pipeline(camera_id)
        if pipeline:
            return {
                "service": "ibvap-ai",
                "status": "running",
                "yolo_loaded": detector.is_loaded,
                "device": settings.get_device(),
                "pipeline": pipeline.get_status(),
                "websocket_clients": len(ws_clients),
            }
        return {
            "service": "ibvap-ai",
            "status": "running",
            "yolo_loaded": detector.is_loaded,
            "device": settings.get_device(),
            "pipeline": {},
            "websocket_clients": len(ws_clients),
        }
    # Aggregate status
    agg = camera_manager.get_aggregate_status() if camera_manager else {}
    first_pipeline_status = {}
    if camera_manager:
        for cid in camera_manager._pipelines:
            p = camera_manager.get_pipeline(cid)
            if p and p.is_running:
                first_pipeline_status = p.get_status()
                break
    return {
        "service": "ibvap-ai",
        "status": "running",
        "yolo_loaded": detector.is_loaded,
        "device": settings.get_device(),
        "pipeline": first_pipeline_status,
        "cameras": agg,
        "websocket_clients": len(ws_clients),
    }


# ──────────────────────────────────────────────────────────────────
# Camera Management REST API
# ──────────────────────────────────────────────────────────────────

class CameraCreateRequest(BaseModel):
    camera_id: str
    name: str
    location: str
    source: str
    source_type: str = "rtsp"
    camera_type: str = "FIXED"
    enabled: bool = True

class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    source: Optional[str] = None
    source_type: Optional[str] = None
    camera_type: Optional[str] = None
    enabled: Optional[bool] = None


@app.get("/cameras")
async def list_cameras(
    _user: UserContext = Depends(require_permission(Permission.CAMERA_READ)),
):
    if camera_manager is None:
        return []
    return camera_manager.list_cameras()


@app.get("/cameras/{camera_id}")
async def get_camera(
    camera_id: str,
    _user: UserContext = Depends(require_permission(Permission.CAMERA_READ)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    info = camera_manager.get_camera(camera_id)
    if info is None:
        return {"error": "Camera not found: %s" % camera_id}
    return info


@app.post("/cameras")
async def register_camera(
    req: CameraCreateRequest,
    user: UserContext = Depends(require_permission(Permission.CAMERA_WRITE)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    try:
        config = CameraConfig(
            camera_id=req.camera_id,
            name=req.name,
            location=req.location,
            source=req.source,
            source_type=req.source_type,
            camera_type=req.camera_type,
            enabled=req.enabled,
        )
        info = await camera_manager.register_camera(
            config,
            auto_start=req.enabled,
            zones=_build_default_zones(req.camera_id),
            actor=user.user_id,
        )
        return {"success": True, "camera": info}
    except ValueError as e:
        return {"error": str(e)}


@app.patch("/cameras/{camera_id}")
async def update_camera(
    camera_id: str,
    req: CameraUpdateRequest,
    user: UserContext = Depends(require_permission(Permission.CAMERA_WRITE)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    fields = {k: v for k, v in req.dict().items() if v is not None}
    if not fields:
        return {"error": "No fields to update"}
    info = await camera_manager.update_camera(camera_id, actor=user.user_id, **fields)
    if info is None:
        return {"error": "Camera not found: %s" % camera_id}
    return {"success": True, "camera": info}


@app.delete("/cameras/{camera_id}")
async def delete_camera(
    camera_id: str,
    user: UserContext = Depends(require_permission(Permission.CAMERA_WRITE)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    removed = await camera_manager.unregister_camera(camera_id, actor=user.user_id)
    if not removed:
        return {"error": "Camera not found: %s" % camera_id}
    return {"success": True, "camera_id": camera_id}


@app.post("/cameras/{camera_id}/start")
async def start_camera(
    camera_id: str,
    user: UserContext = Depends(require_permission(Permission.CAMERA_CONTROL)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    return await camera_manager.start_camera(camera_id, actor=user.user_id)


@app.post("/cameras/{camera_id}/stop")
async def stop_camera(
    camera_id: str,
    user: UserContext = Depends(require_permission(Permission.CAMERA_CONTROL)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    return await camera_manager.stop_camera(camera_id, actor=user.user_id)


@app.post("/cameras/{camera_id}/restart")
async def restart_camera(
    camera_id: str,
    user: UserContext = Depends(require_permission(Permission.CAMERA_CONTROL)),
):
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    return await camera_manager.restart_camera(camera_id, actor=user.user_id)


@app.post("/cameras/{camera_id}/sync-footage")
async def sync_camera_footage(
    camera_id: str,
    user: UserContext = Depends(require_permission(Permission.CAMERA_CONTROL)),
):
    """Trigger SD-card footage retrieval for a reconnected camera."""
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    return await camera_manager.trigger_footage_sync(camera_id)


class CameraAiToggleRequest(BaseModel):
    ai_enabled: bool


@app.post("/cameras/{camera_id}/ai-toggle")
async def toggle_camera_ai(
    camera_id: str,
    req: CameraAiToggleRequest,
    user: UserContext = Depends(require_permission(Permission.CAMERA_CONTROL)),
):
    """Toggle AI processing for a specific camera without stopping video capture."""
    if camera_manager is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Camera manager not initialized"},
        )
    pipeline = camera_manager.get_pipeline(camera_id)
    if pipeline is None:
        return JSONResponse(
            status_code=404,
            content={"error": "Camera not found: %s" % camera_id},
        )
    pipeline.set_ai_enabled(req.ai_enabled)
    status = pipeline.get_status()
    return {
        "camera_id": camera_id,
        "ai_enabled": req.ai_enabled,
        "video_connected": status.get("video_connected", False),
        "ai_processing": status.get("ai_processing", False),
        "running": pipeline.is_running,
    }


@app.get("/cameras/{camera_id}/footage")
async def get_camera_footage(
    camera_id: str,
    user: UserContext = Depends(require_permission(Permission.CAMERA_READ)),
):
    """Get SD-card footage status for a camera."""
    if camera_manager is None:
        return {"error": "Camera manager not initialized"}
    svc = camera_manager.get_footage_service(camera_id)
    if not svc:
        return {"camera_id": camera_id, "footage": [], "summary": None}
    return {
        "camera_id": camera_id,
        "footage": [f.to_dict() for f in svc.get_all()],
        "summary": svc.get_status_summary(),
        "sync_state": camera_manager.get_sync_state(camera_id),
    }


_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v", ".flv"}


@app.get("/videos")
async def list_video_files(
    folder: Optional[str] = Query(None),
    _user: UserContext = Depends(require_permission(Permission.CAMERA_READ)),
):
    """Discover video files on disk for camera source registration.

    If `folder` is given (relative to the project root or absolute), scan only that
    folder recursively. Otherwise scan the default media folders (data/cameras, data).
    Returns entries with the project-root-relative path usable as a camera source.
    """
    default_folders = ["data/cameras", "data"]
    if folder and folder.strip():
        folders = [p.strip() for p in folder.split(";") if p.strip()]
    else:
        folders = list(default_folders)

    # main.py is at backend/ai/main.py → 3 levels up = project root
    # (backend CWD is `backend/`, but video files live at project root `data/`)
    project_root = Path(__file__).resolve().parent.parent.parent
    found = []
    seen = set()
    for raw in folders:
        p = Path(raw)
        if not p.is_absolute():
            p = project_root / p
        if not p.exists() or not p.is_dir():
            continue
        for f in sorted(p.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix.lower() not in _VIDEO_EXTENSIONS:
                continue
            try:
                rel = f.resolve().relative_to(project_root).as_posix()
                if not rel.startswith("./"):
                    rel = "./" + rel
            except ValueError:
                rel = str(f)
            if rel in seen:
                continue
            seen.add(rel)
            found.append({
                "path": rel,
                "name": f.name,
                "folder": str(f.parent).replace(str(project_root), ".").replace("\\", "/"),
                "size_bytes": f.stat().st_size,
                "extension": f.suffix.lower(),
            })
    if not found:
        return {"videos": [], "folders": folders, "message": "No video files found in: " + ", ".join(folders)}
    return {"videos": found, "folders": folders}


# ──────────────────────────────────────────────────────────────────
# MJPEG Video Stream (token via query param)
# ──────────────────────────────────────────────────────────────────

_BOUNDARY = b"--frame" + bytes([13, 10]) + b"Content-Type: image/jpeg" + bytes([13, 10]) + bytes([13, 10])
_END = bytes([13, 10])


def _placeholder_frame(text="Waiting for video..."):
    ph = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(ph, text, (40, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 2)
    return ph


@app.get("/video/stream")
@app.get("/video/stream/{camera_id}")
async def video_stream(
    camera_id: Optional[str] = None,
    _user: UserContext = Depends(get_user_from_token_query),
):
    """MJPEG stream. Token required via query parameter."""
    def generate():
        while True:
            frame = None
            if camera_manager:
                if camera_id:
                    pipeline = camera_manager.get_pipeline(camera_id)
                    if pipeline:
                        frame = pipeline.get_frame()
                else:
                    for cid in camera_manager._pipelines:
                        p = camera_manager.get_pipeline(cid)
                        if p and p.is_running:
                            frame = p.get_frame()
                            break
            if frame is None:
                frame = _placeholder_frame()
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                yield _BOUNDARY + buf.tobytes() + _END
            time.sleep(1.0 / settings.INFERENCE_FPS)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ──────────────────────────────────────────────────────────────────
# WebSocket - camera-specific metadata streaming (token via query)
# ──────────────────────────────────────────────────────────────────

@app.websocket("/ws/cameras/{camera_id}")
async def websocket_tracking(websocket: WebSocket, camera_id: str):
    from ai.auth.deps import verify_ws_token
    try:
        await verify_ws_token(websocket)
    except HTTPException:
        return

    await websocket.accept()
    ws_clients.add(websocket)
    try:
        while True:
            md = None
            if camera_manager:
                pipeline = camera_manager.get_pipeline(camera_id)
                if pipeline:
                    md = pipeline.get_metadata()
            if md:
                await websocket.send_json(md)
            else:
                await websocket.send_json({
                    "camera_id": camera_id,
                    "source": "real",
                    "detections": [],
                    "active_tracks": 0,
                })
            await asyncio.sleep(1.0 / settings.INFERENCE_FPS)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("[WS] Error: %s" % e)
    finally:
        ws_clients.discard(websocket)


# ──────────────────────────────────────────────────────────────────
# Zones
# ──────────────────────────────────────────────────────────────────

async def _refresh_camera_zones(camera_id: str):
    """Push the persisted zone list for a camera into its live pipeline.

    Called after any zone create/update/delete so running pipelines pick up
    changes immediately — without requiring a backend restart.
    """
    if not (_zone_repo and is_available() and camera_manager and camera_id):
        return
    pipeline = camera_manager._pipelines.get(camera_id)
    if pipeline:
        all_zones = await _zone_repo.list_for_camera(camera_id)
        pipeline.set_zones(all_zones)


def _validate_zone_payload(req: dict):
    """Validate zone payload shape before persistence (never crash the AI)."""
    zone_type = req.get("zone_type", "POLYGON_ZONE")
    points = req.get("points", [])
    if not isinstance(points, list):
        raise HTTPException(status_code=422, detail="points must be a list")
    for p in points:
        if (not isinstance(p, dict) or "x" not in p or "y" not in p
                or not isinstance(p["x"], (int, float))
                or not isinstance(p["y"], (int, float))):
            raise HTTPException(status_code=422, detail="each point must be {x, y} numbers (normalized 0-1)")
    if zone_type == "TRIPWIRE_LINE":
        if len(points) < 2:
            raise HTTPException(status_code=422, detail="tripwire requires at least 2 points")
    elif len(points) < 3:
        raise HTTPException(status_code=422, detail="polygon zone requires at least 3 points")
    if not str(req.get("camera_id", "")).strip():
        raise HTTPException(status_code=422, detail="camera_id is required")


@app.get("/zones")
async def get_zones(
    camera_id: Optional[str] = Query(None),
    _user: UserContext = Depends(require_permission(Permission.ZONE_READ)),
):
    """Return zones. If camera_id given, return zones for that camera."""
    if _zone_repo and is_available():
        if camera_id:
            zones = await _zone_repo.list_for_camera(camera_id)
        else:
            zones = await _zone_repo.list_all()
        return {"zones": [z.__dict__ if hasattr(z, '__dict__') else z for z in zones]}

    # Fallback (no database): cameras have no zones until an operator creates one
    return {"zones": []}


@app.post("/zones")
async def create_zone(
    req: dict,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    """Create or update (upsert) a zone, then refresh the live camera pipeline."""
    from ai.events.engine import Zone as ZoneCls
    _validate_zone_payload(req)
    zone = ZoneCls(
        id=req.get("id") or f"ZONE-{str(uuid.uuid4())[:8]}",
        camera_id=req.get("camera_id", ""),
        name=req.get("name", "Unnamed Zone"),
        points=req.get("points", []),
        enabled=req.get("enabled", True),
        severity=req.get("severity", "CRITICAL"),
        zone_type=req.get("zone_type", "POLYGON_ZONE"),
        rule=req.get("rule", "RESTRICTED_ENTRY"),
    )
    if _zone_repo and is_available():
        existing = await _zone_repo.get(zone.id)
        if existing:
            saved = await _zone_repo.update(
                zone.id,
                camera_id=zone.camera_id,
                name=zone.name,
                points=zone.points,
                enabled=zone.enabled,
                severity=zone.severity,
            )
            # Zone may have moved cameras — refresh both pipelines
            if existing.camera_id and existing.camera_id != zone.camera_id:
                await _refresh_camera_zones(existing.camera_id)
        else:
            saved = await _zone_repo.create(zone)
        if saved:
            await _refresh_camera_zones(saved.camera_id)
            return {"success": True, "zone": saved.__dict__}
        raise HTTPException(status_code=500, detail="Failed to persist zone")
    return {"success": True, "zone": zone.__dict__}


@app.delete("/zones/{zone_id}")
async def delete_zone(
    zone_id: str,
    _user: UserContext = Depends(require_permission(Permission.ZONE_WRITE)),
):
    """Delete a zone and stop intrusion evaluation for it immediately."""
    if _zone_repo and is_available():
        existing = await _zone_repo.get(zone_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Zone not found")
        deleted = await _zone_repo.delete(zone_id)
        if deleted:
            # Stop future intrusion alerts from this zone right away
            await _refresh_camera_zones(existing.camera_id)
            return {"success": True, "zone_id": zone_id}
        raise HTTPException(status_code=500, detail="Failed to delete zone")
    return {"error": "Zone not found"}


@app.get("/alerts")
async def get_alerts(
    severity: Optional[str] = Query(None),
    camera: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _user: UserContext = Depends(require_permission(Permission.ALERT_READ)),
):
    """Recent alerts from the events/alerts DB tables.

    This is the read path for the Express /api/alerts proxy so the UI's
    Alerts/Notifications list reflects real pipeline output (persisted
    by the AI service) instead of the never-populated Express memory store.
    """
    if not (_alert_repo and is_available()):
        return {"alerts": []}
    try:
        alerts = await _alert_repo.list_recent(limit=limit)
    except Exception:
        return {"alerts": []}

    # Enrich with camera names (BorderAlert.cameraName is always rendered)
    camera_names: dict = {}
    if _camera_repo and is_available():
        for a in alerts:
            cid = a.get("cameraId") or ""
            if cid and cid not in camera_names:
                try:
                    cam = await _camera_repo.get(cid)
                    camera_names[cid] = (cam.name if cam else cid)
                except Exception:
                    camera_names[cid] = cid
    for a in alerts:
        a["cameraName"] = camera_names.get(a.get("cameraId") or "", a.get("cameraId") or "")
        if not isinstance(a.get("evidenceChecklist"), list):
            a["evidenceChecklist"] = []
        a["trackId"] = str(a.get("trackId") if a.get("trackId") is not None else "")

    # Optional filters (used by the Express /api/alerts proxy)
    if severity and severity.upper() != "ALL":
        alerts = [a for a in alerts if (a.get("severity") or "").upper() == severity.upper()]
    if camera and camera.upper() != "ALL":
        alerts = [a for a in alerts if (a.get("cameraId") or "").lower() == camera.lower()]
    return {"alerts": alerts}


# ──────────────────────────────────────────────────────────────────
# Standalone Detection Endpoint
# ──────────────────────────────────────────────────────────────────

@app.post("/detect")
async def detect_frame(
    _user: UserContext = Depends(require_permission(Permission.CAMERA_READ)),
):
    from ai.video.capture import VideoCapture
    det = YoloDetector()
    if not det.load():
        return {"status": "error", "message": "Model load failed"}
    cap = VideoCapture()
    if not cap.open():
        return {"status": "error", "message": "Video open failed"}
    frame = cap.read_frame()
    cap.release()
    if frame is None:
        return {"status": "error", "message": "No frame"}
    result = det.detect(frame)
    dets = [
        {
            "class_id": d.class_id,
            "class_name": d.class_name,
            "confidence": d.confidence,
            "bbox": {"x1": d.bbox[0], "y1": d.bbox[1], "x2": d.bbox[2], "y2": d.bbox[3]},
        }
        for d in result.detections
    ]
    return {
        "status": "ok",
        "detections": dets,
        "inference_time_ms": result.inference_time_ms,
        "device": result.device,
    }
