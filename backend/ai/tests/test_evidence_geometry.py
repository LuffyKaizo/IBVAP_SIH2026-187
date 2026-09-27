"""Coordinate validation tests for evidence geometry (spec PART 2/5/12)."""
import sys

import pytest

sys.path.insert(0, ".")

from ai.evidence.geometry import (
    MIN_CROP_PX,
    clamp_bbox,
    crop_rect,
    log_diagnostics,
    parse_bbox,
    validate_bbox,
)

FRAME_W, FRAME_H = 1920, 1080


# ── parse ──────────────────────────────────────────────────────────────

def test_parse_bbox_dict():
    assert parse_bbox({"x1": 10, "y1": 20, "x2": 30, "y2": 40}) == (10.0, 20.0, 30.0, 40.0)


def test_parse_bbox_sequence():
    assert parse_bbox([1, 2, 3, 4]) == (1.0, 2.0, 3.0, 4.0)


def test_parse_bbox_invalid():
    assert parse_bbox(None) is None
    assert parse_bbox({}) is None
    assert parse_bbox({"x1": "a", "y1": 0, "x2": 1, "y2": 1}) is None
    assert parse_bbox((1, 2, 3)) is None
    assert parse_bbox("10,20,30,40") is None


# ── validate (PART 12) ─────────────────────────────────────────────────

def test_valid_bbox_has_no_issues():
    assert validate_bbox(100, 100, 300, 400, FRAME_W, FRAME_H) == []


def test_validate_flags_degenerate_ordering():
    issues = validate_bbox(300, 100, 100, 400, FRAME_W, FRAME_H)
    assert "x1>=x2" in issues
    issues = validate_bbox(100, 400, 300, 100, FRAME_W, FRAME_H)
    assert "y1>=y2" in issues


def test_validate_flags_out_of_frame_and_negative():
    assert "negative_origin" in validate_bbox(-5, 10, 100, 100, FRAME_W, FRAME_H)
    assert "outside_frame" in validate_bbox(100, 100, FRAME_W + 50, 100, FRAME_W, FRAME_H)


def test_validate_flags_too_small():
    assert "too_small" in validate_bbox(100, 100, 100 + MIN_CROP_PX - 1, 400, FRAME_W, FRAME_H)


def test_validate_flags_normalized_coordinates():
    # 0..1-looking box on a real-size frame = coordinate-space bug (PART 2)
    issues = validate_bbox(0.1, 0.2, 0.4, 0.6, FRAME_W, FRAME_H)
    assert "looks_normalized" in issues


def test_validate_unknown_frame_size():
    assert validate_bbox(1, 2, 3, 4, 0, 0) == ["unknown_frame_size"]


def test_validate_non_finite():
    assert "non_finite" in validate_bbox(float("nan"), 0, 10, 10, FRAME_W, FRAME_H)


# ── clamp ──────────────────────────────────────────────────────────────

def test_clamp_bbox_stays_inside_frame():
    assert clamp_bbox(-50, -50, FRAME_W + 50, FRAME_H + 50, FRAME_W, FRAME_H) == (
        0, 0, FRAME_W, FRAME_H)


# ── crop_rect (PART 5) ─────────────────────────────────────────────────

def test_crop_rect_expands_by_configured_margin():
    rect, diag = crop_rect({"x1": 100, "y1": 100, "x2": 300, "y2": 400},
                           FRAME_W, FRAME_H, margin=0.2)
    # dx = 200*0.2 = 40, dy = 300*0.2 = 60
    assert rect == (60, 40, 340, 460)
    assert diag["crop_px"] == [60, 40, 340, 460]
    assert diag["bbox_px"] == [100.0, 100.0, 300.0, 400.0]
    assert diag["issues"] == []


def test_crop_rect_clamps_to_frame_edges():
    rect, diag = crop_rect({"x1": -50, "y1": -50, "x2": 80, "y2": 80},
                           FRAME_W, FRAME_H, margin=0.2)
    assert rect[0] >= 0 and rect[1] >= 0
    assert rect[2] <= FRAME_W and rect[3] <= FRAME_H
    assert diag["clamped"] is True


def test_crop_rect_rejects_missing_bbox():
    rect, diag = crop_rect({}, FRAME_W, FRAME_H, 0.2)
    assert rect is None
    assert "missing_bbox" in diag["issues"]


def test_crop_rect_rejects_degenerate_box():
    rect, diag = crop_rect({"x1": 300, "y1": 100, "x2": 100, "y2": 400},
                           FRAME_W, FRAME_H, 0.2)
    assert rect is None
    assert "x1>=x2" in diag["issues"]


def test_crop_rect_rejects_normalized_box():
    rect, diag = crop_rect({"x1": 0.1, "y1": 0.2, "x2": 0.4, "y2": 0.6},
                           FRAME_W, FRAME_H, 0.2)
    assert rect is None
    assert "looks_normalized" in diag["issues"]


def test_crop_rect_margin_is_clamped_to_safe_range():
    rect_hi, _ = crop_rect({"x1": 100, "y1": 100, "x2": 300, "y2": 400},
                           FRAME_W, FRAME_H, margin=0.9)
    # margin clamped to 0.5 -> dx=100, dy=150
    assert rect_hi == (0, 0, 400, 550)
    rect_lo, diag = crop_rect({"x1": 100, "y1": 100, "x2": 300, "y2": 400},
                              FRAME_W, FRAME_H, margin=-3)
    assert diag["margin"] == 0.0
    assert rect_lo == (100, 100, 300, 400)


def test_crop_rect_never_returns_negative_or_oversized():
    rect, _ = crop_rect({"x1": -500, "y1": -500, "x2": 100, "y2": 100},
                        640, 480, margin=0.5)
    assert rect is not None
    x1, y1, x2, y2 = rect
    assert 0 <= x1 < x2 <= 640
    assert 0 <= y1 < y2 <= 480


def test_crop_rect_tiny_box_after_clamp_rejected():
    rect, diag = crop_rect({"x1": -6, "y1": -6, "x2": 4, "y2": 4},
                           640, 480, margin=0.0)
    assert rect is None
    assert "crop_too_small_after_clamp" in diag["issues"] or "too_small" in diag["issues"]


def test_log_diagnostics_is_safe():
    log_diagnostics({"event_id": "evt-x"},
                    {"frame_width": 10, "frame_height": 10,
                     "bbox_px": [1, 2, 3, 4], "crop_px": None,
                     "clamped": False, "issues": ["x1>=x2"]})
    log_diagnostics({}, {"issues": []})
