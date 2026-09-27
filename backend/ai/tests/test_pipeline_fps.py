"""Unit tests for ProcessingPipeline._resolve_target_fps (source-FPS policy).

The resolution order has no global hardcoded ceiling:
  1. nominal container/RTSP FPS when inside [SOURCE_FPS_MIN, SOURCE_FPS_MAX]
  2. measured incoming frame rate when nominal is unusable
  3. settings.INFERENCE_FPS as the last-resort documented fallback
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai.config import settings
from ai.pipeline import ProcessingPipeline


def _cap(measured=None):
    cap = MagicMock()
    cap.get_status.return_value = SimpleNamespace(measured_source_fps=measured)
    return cap


class TestResolveTargetFps:
    def test_nominal_in_range_wins(self):
        mid = (settings.SOURCE_FPS_MIN + settings.SOURCE_FPS_MAX) / 2
        assert ProcessingPipeline._resolve_target_fps(mid, _cap(1.0)) == mid

    def test_no_global_ceiling_near_source_max(self):
        """A high-rate source must not be clamped down to INFERENCE_FPS."""
        near_max = settings.SOURCE_FPS_MAX - 1
        assert (
            ProcessingPipeline._resolve_target_fps(near_max, _cap(None))
            == near_max
        )

    @pytest.mark.parametrize("nominal", [0, -5, 10_000, None, "abc", float("nan")])
    def test_unusable_nominal_falls_back_to_measured(self, nominal):
        assert ProcessingPipeline._resolve_target_fps(nominal, _cap(29.97)) == 29.97

    def test_both_unusable_falls_back_to_settings(self):
        result = ProcessingPipeline._resolve_target_fps(0, _cap(10_000.0))
        assert result == float(settings.INFERENCE_FPS)

    def test_measured_below_range_falls_back_to_settings(self):
        result = ProcessingPipeline._resolve_target_fps(
            0, _cap(settings.SOURCE_FPS_MIN - 0.5)
        )
        assert result == float(settings.INFERENCE_FPS)

    def test_cap_status_error_falls_back_to_settings(self):
        cap = MagicMock()
        cap.get_status.side_effect = RuntimeError("boom")
        assert (
            ProcessingPipeline._resolve_target_fps(0, cap)
            == float(settings.INFERENCE_FPS)
        )
