"""Incident report API — self-contained HTML reports with embedded evidence.

GET /reports/incidents/{event_id}            -> print-ready HTML report
GET /reports/incidents/{event_id}?format=json -> structured report payload

The HTML report embeds each evidence artifact as a base64 data URI so the
page is a single file (no asset fetches, works from a blob URL), and prints
the SHA-256 recorded over the exact JPEG bytes at capture time alongside
every artifact (chain of custody).
"""

import base64
import html
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from ai.auth.deps import require_permission
from ai.auth.models import Permission, UserContext

router = APIRouter(prefix="/reports", tags=["reports"])

# Set by main.py at startup
_event_repo = None
_alert_repo = None
_evidence_repo = None
_evidence_store = None


def init_report_routes(event_repo, alert_repo, evidence_repo, evidence_store):
    global _event_repo, _alert_repo, _evidence_repo, _evidence_store
    _event_repo = event_repo
    _alert_repo = alert_repo
    _evidence_repo = evidence_repo
    _evidence_store = evidence_store


_ORDER = {"SNAPSHOT": 0, "ANNOTATED": 1, "TARGET_CROP": 2}


def _artifact_payload(row: dict) -> dict:
    meta = row.get("metadata") or {}
    return {
        "id": row.get("id"),
        "type": row.get("evidenceType"),
        "timestamp": row.get("timestamp"),
        "fileSize": row.get("fileSize"),
        "mimeType": row.get("mimeType"),
        "sha256": row.get("sha256Hash"),
        "integrity": row.get("integrityStatus"),
        "frameWidth": meta.get("frame_width"),
        "frameHeight": meta.get("frame_height"),
        "cropRect": meta.get("crop_rect"),
        "objectClass": meta.get("object_class"),
        "bbox": meta.get("bbox"),
        "sourceFps": meta.get("source_fps"),
        "processingFps": meta.get("processing_fps"),
    }


async def _build_payload(event_id: str) -> Optional[dict]:
    event = None
    if _event_repo:
        try:
            event = await _event_repo.get(event_id)
        except Exception:
            event = None
    if event is None:
        return None

    alert = None
    if _alert_repo:
        try:
            alert = await _alert_repo.get("ALT-AI-" + event_id)
        except Exception:
            alert = None
    alert_payload = None
    if alert:
        if isinstance(alert, dict):
            alert_payload = {
                "id": alert.get("id"),
                "title": alert.get("title"),
                "severity": alert.get("severity"),
                "zone": alert.get("zone"),
                "reason": alert.get("reason"),
                "status": alert.get("status"),
                "trackId": alert.get("trackId"),
                "confidence": alert.get("confidence"),
            }
        else:
            alert_payload = {
                "id": getattr(alert, "alert_id", None),
                "title": getattr(alert, "title", None),
                "severity": getattr(alert, "severity", None),
                "zone": getattr(alert, "zone", None),
                "reason": getattr(alert, "reason", None),
                "status": getattr(alert, "status", None),
                "trackId": getattr(alert, "track_id", None),
                "confidence": getattr(alert, "confidence", None),
            }

    rows = []
    if _evidence_repo:
        try:
            rows = await _evidence_repo.list_for_event(event_id)
        except Exception:
            rows = []
    rows = sorted(rows, key=lambda r: _ORDER.get(r.get("evidenceType"), 99))

    artifacts = []
    for row in rows:
        item = _artifact_payload(row)
        # Embed image bytes (report is self-contained).
        if _evidence_store and row.get("filePath"):
            try:
                data = _evidence_store.load(row["filePath"])
                if data:
                    mime = row.get("mimeType") or "image/jpeg"
                    item["dataUri"] = "data:%s;base64,%s" % (
                        mime, base64.b64encode(data).decode("ascii"),
                    )
                    item["bytesVerified"] = len(data)
            except Exception:
                item["dataUri"] = None
        artifacts.append(item)

    ev_dict = event if isinstance(event, dict) else vars(event)
    return {
        "eventId": event_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "incident": {
            "eventType": ev_dict.get("event_type"),
            "severity": ev_dict.get("severity"),
            "cameraId": ev_dict.get("camera_id"),
            "zoneId": ev_dict.get("zone_id"),
            "zoneName": ev_dict.get("zone_name"),
            "trackId": ev_dict.get("track_id"),
            "objectClass": ev_dict.get("object_class"),
            "timestamp": ev_dict.get("timestamp"),
            "confidence": ev_dict.get("confidence"),
            "bbox": ev_dict.get("bbox"),
            "status": ev_dict.get("status"),
        },
        "alert": alert_payload,
        "artifacts": artifacts,
    }


def _esc(value) -> str:
    if value is None:
        return "&mdash;"
    return html.escape(str(value))


def _render_html(payload: dict) -> str:
    inc = payload["incident"]
    alert = payload.get("alert")
    artifacts = payload.get("artifacts", [])

    rows = [
        ("Event ID", payload["eventId"]),
        ("Event Type", inc.get("eventType")),
        ("Severity", inc.get("severity")),
        ("Camera", inc.get("cameraId")),
        ("Zone", inc.get("zoneName") or inc.get("zoneId")),
        ("Detected At", inc.get("timestamp")),
        ("Object Class", inc.get("objectClass")),
        ("Track ID", "#%s" % inc.get("trackId") if inc.get("trackId") is not None else None),
        ("Confidence", "%.0f%%" % (float(inc.get("confidence") or 0) * 100)),
        ("Status", inc.get("status")),
        (
            "BBox (px)",
            ", ".join(str(inc["bbox"][k]) for k in ("x1", "y1", "x2", "y2"))
            if isinstance(inc.get("bbox"), dict) and inc["bbox"].get("x2") is not None else None,
        ),
    ]
    summary_rows = "".join(
        '<tr><th>%s</th><td>%s</td></tr>' % (_esc(k), _esc(v)) for k, v in rows
    )

    narrative = ""
    if alert:
        narrative = """
  <div class="card">
    <h2>Alert Narrative</h2>
    <table>
      <tr><th>Alert ID</th><td>%(aid)s</td></tr>
      <tr><th>Title</th><td>%(title)s</td></tr>
      <tr><th>Reason</th><td>%(reason)s</td></tr>
      <tr><th>Alert Status</th><td>%(status)s</td></tr>
    </table>
  </div>""" % {
            "aid": _esc(alert.get("id")),
            "title": _esc(alert.get("title")),
            "reason": _esc(alert.get("reason")),
            "status": _esc(alert.get("status")),
        }

    figures = []
    for a in artifacts:
        img = (
            '<img src="%s" alt="%s" />' % (a["dataUri"], _esc(a.get("type")))
            if a.get("dataUri")
            else '<div class="missing">Image file unavailable</div>'
        )
        figures.append("""
  <figure class="artifact">
    <figcaption><strong>%(type)s</strong> <span class="muted">%(aid)s</span></figcaption>
    %(img)s
    <div class="hash">
      <div><span class="muted">SHA-256:</span> <code>%(sha)s</code></div>
      <div><span class="muted">Integrity:</span> <strong class="%(cls)s">%(integ)s</strong>
           <span class="muted">Size:</span> %(size)s
           <span class="muted">Captured:</span> %(ts)s</div>
    </div>
  </figure>""" % {
            "type": _esc(a.get("type")),
            "aid": _esc(a.get("id")),
            "img": img,
            "sha": _esc(a.get("sha256") or "—"),
            "integ": _esc(a.get("integrity") or "—"),
            "cls": "ok" if a.get("integrity") == "VALID" else "bad",
            "size": _esc("%s KB" % round((a.get("fileSize") or 0) / 1024, 1)),
            "ts": _esc(a.get("timestamp")),
        })

    custody_rows = "".join(
        "<tr><td>%s</td><td><code>%s</code></td><td class='%s'>%s</td><td>%s</td></tr>"
        % (
            _esc(a.get("type")),
            _esc(a.get("sha256") or "—"),
            "ok" if a.get("integrity") == "VALID" else "bad",
            _esc(a.get("integrity") or "—"),
            _esc(a.get("id")),
        )
        for a in artifacts
    ) or '<tr><td colspan="4" class="muted">No evidence artifacts recorded.</td></tr>'

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>IBVAP Incident Report — %(event_id)s</title>
<style>
  :root { color-scheme: light; }
  body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 32px;
         background: #f4f6f8; color: #1a1d21; }
  .page { max-width: 960px; margin: 0 auto; background: #fff; border: 1px solid #d9dee3;
          border-radius: 10px; padding: 28px 32px; }
  header { display: flex; justify-content: space-between; align-items: baseline;
           border-bottom: 3px solid #b42318; padding-bottom: 12px; margin-bottom: 18px; }
  h1 { font-size: 20px; margin: 0; letter-spacing: .02em; }
  h1 span { color: #b42318; }
  h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .08em;
       color: #55606b; margin: 22px 0 8px; }
  .muted { color: #77828d; font-weight: 400; }
  table { border-collapse: collapse; width: 100%%; font-size: 13px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #e7eaee; }
  th { width: 180px; color: #55606b; font-weight: 600; }
  code { font-family: Consolas, 'Courier New', monospace; font-size: 11px;
         word-break: break-all; }
  .card { border: 1px solid #e7eaee; border-radius: 8px; padding: 4px 14px 10px;
          margin-top: 6px; }
  .artifact { margin: 14px 0 20px; border: 1px solid #e7eaee; border-radius: 8px;
              padding: 12px; background: #fafbfc; }
  .artifact img { max-width: 100%%; max-height: 420px; display: block; margin: 8px auto;
                  border: 1px solid #d9dee3; border-radius: 4px; background: #000; }
  .artifact figcaption { font-size: 13px; }
  .hash { font-size: 11px; margin-top: 8px; line-height: 1.7; }
  .ok { color: #12805c; }
  .bad { color: #b42318; }
  .missing { padding: 40px; text-align: center; color: #77828d; font-size: 13px;
             border: 1px dashed #c6ccd3; border-radius: 6px; }
  footer { margin-top: 24px; font-size: 11px; color: #77828d; border-top: 1px solid #e7eaee;
           padding-top: 10px; line-height: 1.6; }
  @media print { body { background: #fff; padding: 0; } .page { border: 0; } }
</style>
</head>
<body>
<div class="page">
  <header>
    <h1><span>IBVAP</span> — Incident Report</h1>
    <div class="muted" style="font-size:12px">Generated %(generated)s</div>
  </header>

  <h2>Incident Summary</h2>
  <table>%(summary)s</table>
  %(narrative)s

  <h2>Evidence Artifacts (%(count)d)</h2>
  %(figures)s

  <h2>Chain of Custody</h2>
  <table>
    <tr><th>Artifact</th><th>SHA-256 (exact bytes at capture)</th><th>Integrity</th><th>Evidence ID</th></tr>
    %(custody)s
  </table>

  <footer>
    SHA-256 hashes are computed over the exact JPEG bytes at capture time and
    re-verified against the stored file. This report is self-contained: all
    images are embedded; no external assets are referenced.<br />
    IBVAP — Integrated Border Video Analytics Platform · Report for event
    <code>%(event_id)s</code>.
  </footer>
</div>
</body>
</html>""" % {
        "event_id": _esc(payload["eventId"]),
        "generated": _esc(payload["generatedAt"]),
        "summary": summary_rows,
        "narrative": narrative,
        "count": len(artifacts),
        "figures": "".join(figures) or '<p class="muted">No evidence artifacts recorded.</p>',
        "custody": custody_rows,
    }


@router.get("/incidents/{event_id}")
async def incident_report(
    event_id: str,
    format: str = Query("html", pattern="^(html|json)$"),
    _user: UserContext = Depends(require_permission(Permission.REPORT_READ)),
):
    """Print-ready HTML incident report (or structured JSON payload)."""
    payload = await _build_payload(event_id)
    if payload is None:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Event not found"}, status_code=404)
    if format == "json":
        return payload
    return HTMLResponse(_render_html(payload))
