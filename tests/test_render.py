"""Tests for the Ken Burns renderers (``ken_burns_video`` / ``ken_burns_film``).

Covers the rectangle-spec parsing helpers and end-to-end renders of tiny
synthetic images. The renders use moviepy's bundled ffmpeg, so they run offline.
"""

import numpy as np
import pytest
from pathlib import Path

from burns import ken_burns_film, ken_burns_video
from burns.render import _parse_rectangle, _rect_to_box


def _gradient_image(width: int = 64, height: int = 48) -> np.ndarray:
    """A small RGB test image with a 2D color gradient (even dims for libx264)."""
    xs = np.linspace(0, 255, width, dtype=np.uint8)
    ys = np.linspace(0, 255, height, dtype=np.uint8)
    img = np.empty((height, width, 3), dtype=np.uint8)
    img[..., 0] = xs[None, :]
    img[..., 1] = ys[:, None]
    img[..., 2] = 128
    return img


class TestRectangleParsing:
    """The flexible (cx, cy, s) rectangle spec parsing."""

    def test_none_returns_default(self):
        assert _parse_rectangle(None, default=(0.5, 0.5, 1.0)) == (0.5, 0.5, 1.0)

    def test_scalar_is_scale_only(self):
        # A bare number is a zoom scale centered on the image.
        assert _parse_rectangle(2) == (0.5, 0.5, 2.0)

    def test_pair_is_pan_center(self):
        # A pair is a pan center at the original scale.
        assert _parse_rectangle((0.3, 0.7)) == (0.3, 0.7, 1.0)

    def test_triple_is_full_spec(self):
        assert _parse_rectangle((0.3, 0.7, 2)) == (0.3, 0.7, 2.0)

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError):
            _parse_rectangle((0.1, 0.2, 0.3, 0.4))


class TestRectToBox:
    """Conversion of an (cx, cy, s) spec to a pixel crop box."""

    def test_full_image_at_scale_one(self):
        assert _rect_to_box(0.5, 0.5, 1.0, 100, 100) == (0, 0, 100, 100)

    def test_zoom_in_shrinks_box(self):
        # s=2 → a centered crop box a quarter of the image area.
        assert _rect_to_box(0.5, 0.5, 2.0, 100, 100) == (25, 25, 75, 75)

    def test_pan_shifts_box(self):
        # Off-center pan; box stays the right size (pan-center is clamped,
        # not the box — preserves aspect ratio).
        assert _rect_to_box(0.25, 0.5, 2.0, 100, 100) == (0, 25, 50, 75)

    def test_pan_past_edge_preserves_box_size_not_distortion(self):
        """When the pan center would push the crop past an edge, the
        box must keep its full (img_w/s, img_h/s) size — only the
        center clamps, not the box. This is the fix for the
        breathing / stretching artefact on long pans."""
        # cx=0.9 with s=2.0 wants box [0.65, 1.15] × ... — past the right
        # edge. The fix clamps cx to 0.75 (the largest legal center for
        # s=2), giving box [0.5, 1.0] which is full-size.
        xmin, ymin, xmax, ymax = _rect_to_box(0.9, 0.5, 2.0, 100, 100)
        assert xmax - xmin == 50  # img_w / s, NOT shrunk by clamping
        assert ymax - ymin == 50  # img_h / s
        # And the box rides the right edge.
        assert xmax == 100

    def test_extreme_pan_keeps_aspect(self):
        """A non-square image with extreme pan: box width/height must
        match img_w/img_h (the source aspect), so the resize-back step
        never stretches the frame."""
        img_w, img_h = 1024, 576
        xmin, ymin, xmax, ymax = _rect_to_box(0.95, 0.95, 1.5, img_w, img_h)
        w = xmax - xmin
        h = ymax - ymin
        # Ratio of crop = ratio of source (within 1 px from rounding).
        assert abs(w / h - img_w / img_h) < 0.01


class TestKenBurnsVideo:
    """End-to-end rendering of the Ken Burns clip."""

    def test_renders_file_with_expected_dims_and_duration(self, tmp_path):
        from moviepy import VideoFileClip

        out = tmp_path / "kb.mp4"
        result = ken_burns_video(
            _gradient_image(64, 48),
            phases=[((0.5, 0.5, 1.0), (0.5, 0.5, 1.3), 0.5)],
            fps=10,
            saveas=str(out),
        )

        assert isinstance(result, Path)
        assert result.is_file()
        with VideoFileClip(str(result)) as clip:
            assert tuple(clip.size) == (64, 48)
            assert abs(clip.duration - 0.5) < 0.15

    def test_pan_zoom_actually_moves(self, tmp_path):
        from moviepy import VideoFileClip

        result = ken_burns_video(
            _gradient_image(64, 48),
            phases=[((0.5, 0.5, 1.0), (0.5, 0.5, 1.6), 0.5)],
            fps=10,
            saveas=str(tmp_path / "motion.mp4"),
        )
        with VideoFileClip(str(result)) as clip:
            first = clip.get_frame(0)
            last = clip.get_frame(clip.duration - 1 / clip.fps)
        assert not np.array_equal(first, last)

    def test_multiphase_total_duration_sums(self, tmp_path):
        """A multi-phase path's clip duration is the sum of phase durations."""
        from moviepy import VideoFileClip

        out = tmp_path / "multi.mp4"
        ken_burns_video(
            _gradient_image(64, 48),
            phases=[
                ((0.5, 0.5, 1.0), (0.6, 0.4, 1.2), 0.4),
                ((0.6, 0.4, 1.2), (0.4, 0.6, 1.2), 0.4),
                ((0.4, 0.6, 1.2), (0.5, 0.5, 1.3), 0.4),
            ],
            fps=10,
            saveas=str(out),
        )
        with VideoFileClip(str(out)) as clip:
            assert abs(clip.duration - 1.2) < 0.2

    def test_multiphase_moves_through_each_phase(self, tmp_path):
        """Each phase contributes distinct motion — the frame mid-way through
        phase 2 differs from both the start and the final frame."""
        from moviepy import VideoFileClip

        out = tmp_path / "phased.mp4"
        ken_burns_video(
            _gradient_image(96, 72),
            phases=[
                ((0.3, 0.5, 1.0), (0.3, 0.5, 1.5), 0.4),
                ((0.3, 0.5, 1.5), (0.7, 0.5, 1.5), 0.4),
            ],
            fps=10,
            saveas=str(out),
        )
        with VideoFileClip(str(out)) as clip:
            first = clip.get_frame(0)
            mid_phase2 = clip.get_frame(0.6)  # 0.2s into the pan
            last = clip.get_frame(clip.duration - 1 / clip.fps)
        assert not np.array_equal(first, mid_phase2)
        assert not np.array_equal(mid_phase2, last)

    def test_empty_phases_raises(self, tmp_path):
        with pytest.raises(ValueError, match="non-empty"):
            ken_burns_video(
                _gradient_image(64, 48),
                phases=[],
                fps=10,
                saveas=str(tmp_path / "x.mp4"),
            )

    def test_zero_duration_phase_raises(self, tmp_path):
        with pytest.raises(ValueError, match="duration_s must be"):
            ken_burns_video(
                _gradient_image(64, 48),
                phases=[((0.5, 0.5, 1.0), (0.5, 0.5, 1.3), 0.0)],
                fps=10,
                saveas=str(tmp_path / "x.mp4"),
            )

    def test_accepts_image_path_and_auto_names_output(self, tmp_path):
        from PIL import Image

        image_path = tmp_path / "photo.png"
        Image.fromarray(_gradient_image(64, 48)).save(image_path)

        result = ken_burns_video(
            str(image_path),
            phases=[((0.5, 0.5, 1.0), (0.5, 0.5, 1.3), 0.3)],
            fps=10,
        )

        # Auto-generated path sits next to the source image.
        assert result.is_file()
        assert result.parent == tmp_path
        assert "kenburns" in result.stem

    def test_default_phases_produces_standard_kenburns(self, tmp_path):
        """No phases arg → the standard 2-second push-in default."""
        from moviepy import VideoFileClip

        out = tmp_path / "default.mp4"
        ken_burns_video(_gradient_image(64, 48), fps=10, saveas=str(out))
        with VideoFileClip(str(out)) as clip:
            assert abs(clip.duration - 2.0) < 0.2


class TestKenBurnsFilm:
    """Multi-panel single-pass renderer — the structural fix that avoids
    per-panel concat seams and per-panel tail-pad freezes."""

    def test_renders_total_duration_equals_sum_of_panel_durations(self, tmp_path):
        from moviepy import VideoFileClip

        out = tmp_path / "film.mp4"
        ken_burns_film(
            [
                (_gradient_image(64, 48), [((0.5, 0.5, 1.0), (0.5, 0.5, 1.3), 0.5)]),
                (_gradient_image(64, 48), [((0.5, 0.5, 1.3), (0.5, 0.5, 1.0), 0.3)]),
            ],
            saveas=str(out),
            fps=10,
        )
        with VideoFileClip(str(out)) as clip:
            assert abs(clip.duration - 0.8) < 0.2

    def test_motion_continues_through_each_panel(self, tmp_path):
        """The last frame of panel 1 must differ from its first — no
        per-panel tail freeze."""
        from moviepy import VideoFileClip

        out = tmp_path / "film.mp4"
        ken_burns_film(
            [
                (_gradient_image(96, 72), [((0.3, 0.5, 1.0), (0.7, 0.5, 1.4), 0.5)]),
                (_gradient_image(96, 72), [((0.5, 0.3, 1.0), (0.5, 0.7, 1.4), 0.5)]),
            ],
            saveas=str(out),
            fps=10,
        )
        with VideoFileClip(str(out)) as clip:
            panel1_first = clip.get_frame(0.05)
            panel1_last = clip.get_frame(0.45)  # just before panel boundary
            panel2_first = clip.get_frame(0.55)
            panel2_last = clip.get_frame(clip.duration - 1 / clip.fps)
        # Motion within panel 1 → frames differ.
        assert not np.array_equal(panel1_first, panel1_last)
        # Panel boundary → different image / framing.
        assert not np.array_equal(panel1_last, panel2_first)
        # Motion within panel 2 → frames differ.
        assert not np.array_equal(panel2_first, panel2_last)

    def test_multi_phase_panel_does_not_freeze_at_phase_boundary(self, tmp_path):
        """A panel with multiple phases must have moving frames in EVERY
        phase — no stop mid-segment."""
        from moviepy import VideoFileClip

        out = tmp_path / "phased.mp4"
        ken_burns_film(
            [
                (
                    _gradient_image(96, 72),
                    [
                        ((0.3, 0.5, 1.0), (0.3, 0.5, 1.4), 0.4),  # zoom in
                        ((0.3, 0.5, 1.4), (0.7, 0.5, 1.4), 0.4),  # pan right
                        ((0.7, 0.5, 1.4), (0.5, 0.5, 1.0), 0.4),  # zoom out
                    ],
                ),
            ],
            saveas=str(out),
            fps=10,
        )
        with VideoFileClip(str(out)) as clip:
            # Sample mid-phase in each of the three phases.
            f_phase1 = clip.get_frame(0.2)
            f_phase2 = clip.get_frame(0.6)
            f_phase3 = clip.get_frame(1.0)
        # All three differ — motion continues across phase boundaries.
        assert not np.array_equal(f_phase1, f_phase2)
        assert not np.array_equal(f_phase2, f_phase3)

    def test_empty_panels_raises(self, tmp_path):
        with pytest.raises(ValueError):
            ken_burns_film([], saveas=str(tmp_path / "x.mp4"), fps=10)


class TestDriftRendersMotion:
    """`style="drift"` must produce a genuinely moving pan when rendered.

    Drift sets a constant zoom; that zoom must exceed 1.0 or the renderer
    clamps the pan center to 0.5 and the clip is static. This locks the fix.
    """

    def test_drift_path_actually_pans(self, tmp_path):
        from moviepy import VideoFileClip

        from burns import ken_burns_path

        out = tmp_path / "drift.mp4"
        ken_burns_video(
            _gradient_image(120, 80),
            phases=ken_burns_path(1, 1.0, style="drift", pan=0.12),
            fps=10,
            saveas=str(out),
        )
        with VideoFileClip(str(out)) as clip:
            first = clip.get_frame(0.0)
            last = clip.get_frame(clip.duration - 1 / clip.fps)
        assert not np.array_equal(first, last)

    def test_invalid_panel_shape_raises(self, tmp_path):
        with pytest.raises(ValueError, match="image, phases"):
            ken_burns_film(
                [(_gradient_image(64, 48),)],  # missing phases
                saveas=str(tmp_path / "x.mp4"),
                fps=10,
            )
