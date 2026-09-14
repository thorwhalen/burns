"""Motion must be *continuous* — the regression guard for visible stepping.

The bug these tests pin had shipped in real films and was reported as the render
looking "jittery", "more like jumps rather than some smooth movement". The cause
was not the easing, the frame rate, or the encoder: :func:`sample_frame` rounded
each frame's window to whole source pixels.

Ken Burns motion is *slower than one pixel per frame*. A 1.18x push over eight
seconds moves the window by a few hundredths of a source pixel per frame, so
rounding holds it perfectly still for a run of frames and then jumps it a whole
pixel. Measured on the panel that prompted the report, 56% of consecutive frames
were pixel-identical.

What makes this worth a test file of its own: **every individual frame was
correct**, so nothing that checked frames, geometry, or output dimensions could
see it. The defect lives only in the relationship between consecutive frames,
which is exactly what these assertions look at.

Run: ``python -m pytest tests/test_smoothness.py -q``
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from burns import BurnsPath, ken_burns_path
from burns._frame import sample_box, sample_box_exact, sample_frame
from burns.rect import Rect


def gradient_image(w: int, h: int) -> np.ndarray:
    """A smooth non-repeating gradient, so any frame-to-frame move shows up as a
    pixel change (a flat or periodic image could hide one)."""
    ys, xs = np.mgrid[0:h, 0:w]
    r = (xs * 255 // max(1, w - 1)).astype(np.uint8)
    g = (ys * 255 // max(1, h - 1)).astype(np.uint8)
    b = ((xs + ys) * 255 // max(1, w + h - 2)).astype(np.uint8)
    return np.dstack([r, g, b])


SLOW_PANEL = dict(img_w=1920, img_h=1080, out_w=1920, out_h=1080)


def _times(fps: int = 30, duration: float = 8.0) -> list[float]:
    n = int(fps * duration)
    return [i / (n - 1) for i in range(n)]


class TestTheWindowMovesEveryFrame:
    def test_exact_box_never_repeats_on_a_slow_push(self):
        """The defining property. A slow push must advance every single frame —
        a repeated window IS a dropped frame of motion."""
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=1.18)
        boxes = [
            sample_box_exact(path, t, **SLOW_PANEL) for t in _times()
        ]
        repeats = [i for i in range(1, len(boxes)) if boxes[i] == boxes[i - 1]]
        assert not repeats, f"{len(repeats)} static frames at {repeats[:8]}"

    def test_the_integer_box_is_why_this_test_exists(self):
        """Documents the defect rather than asserting it away: the integer box
        DOES stall, which is why the renderer must not sample it."""
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=1.18)
        boxes = [sample_box(path, t, **SLOW_PANEL) for t in _times()]
        repeats = sum(1 for i in range(1, len(boxes)) if boxes[i] == boxes[i - 1])
        assert repeats > len(boxes) // 4, (
            "the integer box no longer stalls — if to_pixels became sub-pixel, "
            "fold these two tests together"
        )

    @pytest.mark.parametrize("zoom", [1.05, 1.18, 1.35, 2.0])
    def test_holds_across_zoom_depths(self, zoom):
        """A gentler push is *more* prone to stalling, not less."""
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=zoom)
        boxes = [sample_box_exact(path, t, **SLOW_PANEL) for t in _times()]
        assert all(boxes[i] != boxes[i - 1] for i in range(1, len(boxes)))


class TestRenderedFramesChangeEvenly:
    def test_no_two_consecutive_frames_are_identical(self):
        img = gradient_image(1920, 1080)
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=1.18)
        frames = [
            sample_frame(path, t, img, 1920, 1080, 1920, 1080)
            for t in _times()[:90]
        ]
        identical = [
            i for i in range(1, len(frames))
            if np.array_equal(frames[i], frames[i - 1])
        ]
        assert not identical, f"frozen frames at {identical[:8]}"

    def test_change_per_frame_is_near_constant(self):
        """Stepping shows up as near-zero changes punctuated by large ones, so
        the *evenness* of the change is the thing to assert. A linear path at
        constant speed should vary little frame to frame."""
        img = gradient_image(1920, 1080)
        path = BurnsPath.from_start_end(
            Rect(0.0, 0.0, 1.0, 1.0),
            Rect.from_center_zoom(0.5, 0.5, 1.3),
            easing="linear",
        )
        frames = [
            sample_frame(path, t, img, 1920, 1080, 1920, 1080).astype(np.int16)
            for t in _times()[40:100]
        ]
        deltas = np.array([
            np.abs(frames[i] - frames[i - 1]).mean() for i in range(1, len(frames))
        ])
        assert deltas.min() > 0, "a frame did not change at all"
        # Coefficient of variation: stepping measured ~1.0+ before the fix.
        cv = deltas.std() / deltas.mean()
        assert cv < 0.35, f"uneven motion (cv={cv:.3f}); deltas={deltas[:10]}"


class TestGeometryStillAgrees:
    """The sub-pixel box must be the same rectangle, only unrounded."""

    @pytest.mark.parametrize(
        "img_w, img_h, out_w, out_h",
        [(640, 480, 640, 480), (640, 480, 1280, 720), (1080, 1920, 1920, 1080)],
    )
    def test_exact_box_rounds_back_to_the_integer_box(self, img_w, img_h, out_w, out_h):
        path = ken_burns_path(0, output_aspect=out_w / out_h, zoom=1.25)
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            exact = sample_box_exact(path, t, img_w, img_h, out_w, out_h)
            integer = sample_box(path, t, img_w, img_h, out_w, out_h)
            for e, i in zip(exact, integer):
                assert abs(e - i) <= 1.0, (t, exact, integer)

    def test_exact_box_carries_the_output_aspect(self):
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=1.2)
        for t in (0.0, 0.3, 0.7, 1.0):
            x0, y0, x1, y1 = sample_box_exact(path, t, 640, 480, 1280, 720)
            assert (x1 - x0) / (y1 - y0) == pytest.approx(16 / 9, rel=1e-9)

    def test_exact_box_stays_inside_the_image(self):
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=1.4)
        for t in (0.0, 0.5, 1.0):
            x0, y0, x1, y1 = sample_box_exact(path, t, 640, 480, 1280, 720)
            assert 0.0 <= x0 < x1 <= 640.0
            assert 0.0 <= y0 < y1 <= 480.0

    def test_frame_dimensions_are_unchanged(self):
        img = gradient_image(640, 480)
        path = ken_burns_path(0, output_aspect=16 / 9, zoom=1.2)
        frame = sample_frame(path, 0.5, img, 640, 480, 1280, 720)
        assert frame.shape == (720, 1280, 3)
