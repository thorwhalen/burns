"""The sub-pixel crop box must stay inside the image.

Regression tests for a bug with two faces and one cause. ``sample_box_exact``
can return an edge a rounding error outside the image — ``-1.1e-14`` where
``0.0`` was meant. ``math.floor`` turns that into ``-1``, numpy reads ``-1`` as
"from the last row", and the frame is then resampled from a different region of
the picture entirely.

Depending on whether the relative box happens to fit the (wrong) crop, that
surfaces either as ``ValueError: box can't exceed original image size`` — which
kills a render late, after the expensive work — or, worse, as a frame that
silently shows a different rectangle, which on screen is the motion "jumping".

Both are covered here, because only fixing the crash leaves the silent one.
"""

import math

import numpy as np
import pytest

from burns import BurnsPath, Rect
from burns._frame import clamp_box_to_image, sample_box_exact, sample_frame


def _gradient(w: int, h: int) -> np.ndarray:
    """An image whose rows are all different, so a wrong crop is detectable."""
    rows = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
    return np.repeat(np.repeat(rows, w, axis=1)[:, :, None], 3, axis=2)


# --- the clamp itself --------------------------------------------------------


def test_a_hair_outside_is_pulled_to_the_edge():
    assert clamp_box_to_image(
        -1.1e-14, -1.1e-14, 1080.0, 1920.0 + 1e-9, 1080, 1920
    ) == (
        0.0,
        0.0,
        1080.0,
        1920.0,
    )


def test_a_box_already_inside_is_untouched():
    box = (10.5, 20.25, 100.5, 200.75)
    assert clamp_box_to_image(*box, 1080, 1920) == box


def test_the_clamp_never_inverts_the_box():
    x0, y0, x1, y1 = clamp_box_to_image(50.0, 10.0, 20.0, 5.0, 100, 100)
    assert x0 <= x1 and y0 <= y1


def test_a_grossly_out_of_bounds_box_is_confined():
    x0, y0, x1, y1 = clamp_box_to_image(-500.0, -500.0, 5000.0, 5000.0, 640, 480)
    assert (x0, y0, x1, y1) == (0.0, 0.0, 640.0, 480.0)


# --- the failure it prevents -------------------------------------------------


def test_floor_of_a_tiny_negative_is_a_destructive_numpy_index():
    """The mechanism, pinned so nobody 'simplifies' the clamp away."""
    assert math.floor(-1.1e-14) == -1
    img = _gradient(8, 100)
    # -1 does not mean "one above the top"; it means "the last row".
    assert img[-1:50].shape[0] == 0
    assert img[0:50].shape[0] == 50


@pytest.mark.parametrize("out_size", [(1080, 1920), (1920, 1080), (1000, 1000)])
def test_sample_frame_never_raises_on_an_edge_hugging_path(out_size):
    out_w, out_h = out_size
    img_w, img_h = 1080, 1920
    img = _gradient(img_w, img_h)
    # A full-frame path is exactly the case that lands edges on 0 and img_h,
    # where the cover-crop's float arithmetic can tip one of them over.
    path = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.5, 1.18)
    )
    for k in range(101):
        sample_frame(path, k / 100, img, img_w, img_h, out_w, out_h)


@pytest.mark.parametrize("out_size", [(1080, 1920), (1920, 1080)])
def test_the_sampled_box_stays_inside_the_image(out_size):
    out_w, out_h = out_size
    img_w, img_h = 1080, 1920
    path = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.5, 1.18)
    )
    for k in range(101):
        box = sample_box_exact(path, k / 100, img_w, img_h, out_w, out_h)
        x0, y0, x1, y1 = clamp_box_to_image(*box, img_w, img_h)
        assert 0.0 <= x0 <= x1 <= img_w
        assert 0.0 <= y0 <= y1 <= img_h


def test_motion_is_continuous_with_no_jump():
    """The silent face of the bug: a frame from the wrong region of the image.

    A wrong crop on a vertical gradient shows up as a large isolated step in
    mean brightness between consecutive frames.
    """
    img_w, img_h = 1080, 1920
    img = _gradient(img_w, img_h)
    path = BurnsPath.from_start_end(
        Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.35, 1.18)
    )
    means = [
        float(sample_frame(path, k / 200, img, img_w, img_h, 1080, 1920).mean())
        for k in range(201)
    ]
    steps = np.abs(np.diff(means))
    # A wrapped crop moves the mean by tens of levels; honest motion creeps.
    assert steps.max() < 5.0, f"largest step {steps.max():.2f} looks like a jump"


def test_many_geometries_none_raise():
    """A sweep, because the bug turns on where a float lands.

    The original failure appeared on 66 of 601 sampled times for one particular
    still at one particular output aspect, and not at all for the eight others
    in the same film. A single hand-picked case is not enough coverage for a
    bug whose trigger is rounding.
    """
    rng = np.random.default_rng(20260917)
    sizes = [(1080, 1920), (1920, 1080), (1000, 1000), (1440, 1080), (720, 1280)]
    for img_w, img_h in sizes:
        img = _gradient(img_w, img_h)
        for out_w, out_h in sizes:
            for _ in range(6):
                cx, cy = rng.uniform(0.2, 0.8, 2)
                z0, z1 = rng.uniform(1.0, 1.4, 2)
                path = BurnsPath.from_start_end(
                    Rect.from_center_zoom(cx, cy, z0),
                    Rect.from_center_zoom(cx, cy, z1),
                )
                for k in (0, 25, 50, 75, 100):
                    sample_frame(path, k / 100, img, img_w, img_h, out_w, out_h)
