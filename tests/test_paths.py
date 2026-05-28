"""Tests for the deterministic Ken Burns path builder (``ken_burns_path``)."""

import pytest

from burns import ken_burns_path


class TestKenBurnsPath:
    """The deterministic per-index "cinematic push" pan/zoom path."""

    def test_is_deterministic(self):
        assert ken_burns_path(3, 6.0) == ken_burns_path(3, 6.0)

    def test_single_phase_spanning_full_duration(self):
        # Cinematic-push policy: one continuous linear motion per image.
        # Direction changes within a shot break the contemplative feel,
        # so the generator never produces multi-phase paths without ease.
        path = ken_burns_path(1, 6.0)
        assert len(path) == 1
        assert abs(path[0][2] - 6.0) < 1e-9

    def test_odd_index_is_push_in_even_is_pull_out(self):
        # Visual rhythm comes from alternating push-in / pull-out per
        # index, NOT from changing direction within a shot.
        odd = ken_burns_path(1, 5.0)
        even = ken_burns_path(2, 5.0)
        (odd_start, odd_end, _) = odd[0]
        (even_start, even_end, _) = even[0]
        # Odd: starts at full image, ends zoomed in.
        assert odd_start[2] == 1.0 and odd_end[2] > 1.0
        # Even: starts zoomed, ends at full image.
        assert even_start[2] > 1.0 and even_end[2] == 1.0

    def test_focal_offset_uses_pan_arg(self):
        path = ken_burns_path(1, 5.0, pan=0.05, zoom=1.10)
        (_, end, _) = path[0]
        # Pan offset magnitude (sqrt(dx^2 + dy^2)) ≈ pan arg.
        dx, dy = end[0] - 0.5, end[1] - 0.5
        magnitude = (dx * dx + dy * dy) ** 0.5
        assert abs(magnitude - 0.05) < 1e-3

    def test_rectangles_are_cx_cy_scale_triples(self):
        path = ken_burns_path(1, 8.0, zoom=1.15, pan=0.04)
        for start_rect, end_rect, dur in path:
            assert dur > 0.0
            for rect in (start_rect, end_rect):
                assert len(rect) == 3
                cx, cy, s = rect
                assert 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0 and s > 0.0

    def test_invalid_duration_raises(self):
        with pytest.raises(ValueError, match="duration_s must be"):
            ken_burns_path(1, 0.0)

    # --- ease=True: 3-phase velocity curve ------------------------------

    def test_ease_splits_into_three_phases_preserving_total_duration(self):
        """An `ease=True` path is 3 phases (slow-fast-slow) summing to duration_s."""
        path = ken_burns_path(1, 8.0, ease=True)
        assert len(path) == 3
        assert abs(sum(phase[2] for phase in path) - 8.0) < 1e-9
        # 25% / 50% / 25% time distribution.
        assert abs(path[0][2] - 2.0) < 1e-6
        assert abs(path[1][2] - 4.0) < 1e-6
        assert abs(path[2][2] - 2.0) < 1e-6

    def test_ease_endpoints_match_the_no_ease_motion(self):
        """Ease changes velocity, not direction or magnitude."""
        plain = ken_burns_path(1, 8.0)[0]
        eased = ken_burns_path(1, 8.0, ease=True)
        # Eased starts where plain starts and ends where plain ends.
        assert eased[0][0] == plain[0]   # start rect
        assert eased[-1][1] == plain[1]  # end rect
        # The two intermediate split points are between start and end.
        assert eased[0][1] == eased[1][0]  # chain continuity
        assert eased[1][1] == eased[2][0]

    def test_ease_intermediate_points_are_slow_fast_slow(self):
        """10% / 70% / 20% of motion across the 3 phases."""
        eased = ken_burns_path(1, 8.0, ease=True)
        # In phase 0 we cover 10% of total motion in 25% of total time:
        # zoom interpolates from 1.0 → 1.0 + 0.1 * (zoom_end - 1.0)
        # where zoom_end = 1.10 by default.
        # So phase-0 end scale is 1.0 + 0.10 * 0.10 = 1.010.
        # Phase 1 covers next 70% (cumulative 80%): scale 1.0 + 0.80 * 0.10 = 1.08.
        # Phase 2 covers final 20% (cumulative 100%): scale 1.10.
        scale_after_phase_0 = eased[0][1][2]
        scale_after_phase_1 = eased[1][1][2]
        scale_after_phase_2 = eased[2][1][2]
        assert abs(scale_after_phase_0 - 1.010) < 1e-6
        assert abs(scale_after_phase_1 - 1.080) < 1e-6
        assert abs(scale_after_phase_2 - 1.100) < 1e-6

    def test_ease_works_for_pull_out_too(self):
        """Even-index images (pull-out) get the same 3-phase split."""
        path = ken_burns_path(2, 8.0, ease=True)
        assert len(path) == 3
        # Pull-out: scale at start is the zoomed value, end is 1.0.
        assert path[0][0][2] == 1.10
        assert abs(path[-1][1][2] - 1.0) < 1e-9

    # --- style="drift": lateral pan -------------------------------------

    def test_drift_style_is_horizontal_pan(self):
        """Drift moves only along x — no vertical pan, no zoom change."""
        path = ken_burns_path(1, 6.0, style="drift")
        assert len(path) == 1
        start, end, dur = path[0]
        # No vertical motion (cy stays at the center).
        assert start[1] == 0.5
        assert end[1] == 0.5
        # There IS horizontal motion.
        assert start[0] != end[0]
        # And the zoom stays the same end-to-end (no zoom-in / pull-out).
        assert start[2] == end[2]
        assert abs(dur - 6.0) < 1e-9

    def test_drift_style_alternates_direction_per_index(self):
        """Visual rhythm: image n drifts opposite of image n+1."""
        odd = ken_burns_path(1, 5.0, style="drift")[0]
        even = ken_burns_path(2, 5.0, style="drift")[0]
        odd_dir = odd[1][0] - odd[0][0]
        even_dir = even[1][0] - even[0][0]
        # Opposite signs.
        assert odd_dir * even_dir < 0

    def test_drift_style_supports_ease(self):
        """style=drift + ease=True: a 3-phase horizontal pan with the same curve."""
        path = ken_burns_path(1, 8.0, style="drift", ease=True)
        assert len(path) == 3
        # Vertical never changes.
        for start, end, _ in path:
            assert start[1] == end[1] == 0.5
        # Total duration preserved.
        assert abs(sum(phase[2] for phase in path) - 8.0) < 1e-9

    def test_unknown_style_raises(self):
        with pytest.raises(ValueError, match="style"):
            ken_burns_path(1, 6.0, style="not-a-real-style")
