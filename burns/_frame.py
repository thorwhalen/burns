"""The single point where a :class:`~burns.path.BurnsPath` meets pixels.

Every render backend — and the multi-panel film renderer — samples frames
through :func:`sample_frame`, so the spec-to-pixel mapping is defined *once*.
Pinning it here is what lets a future JS/TS implementation reproduce the exact
crop, because the rule is short and explicit:

1. ``path.evaluate(t)`` -> a normalized :class:`~burns.rect.Rect` window.
2. The window maps to a pixel box, clamped inside the image.
3. If the requested output aspect ratio differs from the window's pixel AR,
   **cover-crop** the window to the output AR (center-cropped — the FCP /
   iMovie default), so frames fill the output without stretching.
4. Resize the result to the (even-snapped) output size with a quality filter.

Step 2 exists in two resolutions, and which one you want depends on what you are
asking:

- :func:`sample_box` — **integer** pixels. The region a caller reads, and the
  cross-language contract the golden-vector fixtures pin.
- :func:`sample_box_exact` — **sub-pixel** floats. What :func:`sample_frame`
  actually samples.

The renderer needs the float one, and this is not a refinement — it is the
difference between smooth motion and visible stepping. Ken Burns motion is
*slower than one pixel per frame*: a 1.18x push over eight seconds moves the
window by a few hundredths of a source pixel per frame. Round that to whole
pixels and the window is perfectly still for a run of frames and then jumps a
full pixel; measured on a real panel, 71% of consecutive frames had an identical
integer box. Pillow's ``resize(box=...)`` resamples from a float region, so
consecutive frames differ continuously instead of snapping.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image as PIL_Image

from burns.path import BurnsPath
from burns.rect import Rect


def even(n: int) -> int:
    """Round ``n`` down to the nearest positive even integer (H.264 needs even
    width/height for yuv420p).

    Examples:
        >>> even(101), even(100), even(1)
        (100, 100, 2)
    """
    n = int(n)
    return max(2, n - (n % 2))


def output_size_for(
    img_w: int, img_h: int, *, output_aspect: float | None, output_size=None
) -> tuple[int, int]:
    """Resolve the (even) output frame size.

    Priority: an explicit ``output_size`` wins; else derive from
    ``output_aspect`` keeping the image's height; else the image's own size.

    Examples:
        >>> output_size_for(800, 600, output_aspect=None)
        (800, 600)
        >>> output_size_for(800, 600, output_aspect=1.0)
        (600, 600)
        >>> output_size_for(801, 599, output_aspect=None)
        (800, 598)
    """
    if output_size is not None:
        w, h = output_size
        return (even(w), even(h))
    if output_aspect is not None:
        return (even(round(img_h * output_aspect)), even(img_h))
    return (even(img_w), even(img_h))


def _cover_crop_box(
    x0: int, y0: int, x1: int, y1: int, target_aspect: float
) -> tuple[int, int, int, int]:
    """Center-crop the integer box ``(x0, y0, x1, y1)`` to ``target_aspect``.

    Trims the longer dimension symmetrically so the box's pixel AR becomes
    ``target_aspect`` (width / height), keeping it centered — the FCP / iMovie
    default. A no-op when the box already matches within a 1px tolerance.
    Returns the trimmed box in the same coordinate frame as the input.
    """
    w = x1 - x0
    h = y1 - y0
    cur = w / h
    if abs(cur - target_aspect) < (1.0 / max(w, h)):
        return (x0, y0, x1, y1)
    if cur > target_aspect:  # too wide — trim left/right
        new_w = max(1, int(round(h * target_aspect)))
        nx0 = x0 + (w - new_w) // 2
        return (nx0, y0, nx0 + new_w, y1)
    new_h = max(1, int(round(w / target_aspect)))  # too tall — trim top/bottom
    ny0 = y0 + (h - new_h) // 2
    return (x0, ny0, x1, ny0 + new_h)


def sample_box(
    path: BurnsPath,
    t: float,
    img_w: int,
    img_h: int,
    out_w: int,
    out_h: int,
) -> tuple[int, int, int, int]:
    """The integer crop box ``(x0, y0, x1, y1)`` read from the source image.

    Pure integer geometry — steps 1-3 of the module mapping: evaluate the path
    to a :class:`~burns.rect.Rect`, map it to a clamped pixel box via
    :meth:`Rect.to_pixels`, then cover-crop that box to the output aspect ratio.
    No image array is touched, so this is the exact, side-effect-free crop
    contract a cross-language renderer must reproduce; the golden vectors pin it.

    The box is half-open (``img_np[y0:y1, x0:x1]``).

    Examples:
        >>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 1, 1))
        >>> sample_box(p, 0.0, 64, 48, 64, 48)  # output AR == image AR
        (0, 0, 64, 48)
        >>> sample_box(p, 0.0, 64, 48, 48, 48)  # square output cover-crops wide
        (8, 0, 56, 48)
    """
    rect = path.evaluate(t)
    x0, y0, x1, y1 = rect.to_pixels(img_w, img_h)
    return _cover_crop_box(x0, y0, x1, y1, out_w / out_h)


def _cover_crop_box_exact(
    x0: float, y0: float, x1: float, y1: float, target_aspect: float
) -> tuple[float, float, float, float]:
    """Sub-pixel :func:`_cover_crop_box`: same centered trim, no rounding."""
    w = x1 - x0
    h = y1 - y0
    if h <= 0 or w <= 0:
        return (x0, y0, x1, y1)
    if w / h > target_aspect:  # too wide — trim left/right
        new_w = h * target_aspect
        nx0 = x0 + (w - new_w) / 2.0
        return (nx0, y0, nx0 + new_w, y1)
    new_h = w / target_aspect  # too tall — trim top/bottom
    ny0 = y0 + (h - new_h) / 2.0
    return (x0, ny0, x1, ny0 + new_h)


def sample_box_exact(
    path: BurnsPath,
    t: float,
    img_w: int,
    img_h: int,
    out_w: int,
    out_h: int,
) -> tuple[float, float, float, float]:
    """The **sub-pixel** crop box — the same geometry as :func:`sample_box`,
    without the integer rounding.

    This is what the renderer samples, and the distinction is the whole reason
    Ken Burns motion looks smooth rather than stepped.

    A slow move is *slower than one pixel per frame*. A 1.18x push across eight
    seconds advances the window by a few hundredths of a source pixel per frame,
    so rounding each frame's window to whole pixels holds it perfectly still for
    a run of frames and then jumps it a full pixel. Measured on a real panel,
    71% of consecutive frames had an identical integer box; the motion was not
    slow-and-smooth but still-then-snap. No easing curve or frame rate fixes
    that, because the information is destroyed after the curve is evaluated.

    :func:`sample_box` is kept as-is: it is the integer region a caller reads,
    and the cross-language golden vectors pin it. This is the float region the
    *resampler* needs, and a port that wants matching output must reproduce this
    one.

    Examples:
        >>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 1, 1))
        >>> sample_box_exact(p, 0.0, 64, 48, 64, 48)
        (0.0, 0.0, 64.0, 48.0)
        >>> sample_box_exact(p, 0.0, 64, 48, 48, 48)  # square output, wide image
        (8.0, 0.0, 56.0, 48.0)

    Where the move is slowest — the ease-in at the head of a push — the integer
    box stalls on two adjacent frames while this one still advances:

        >>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.5, 1.2))
        >>> sample_box(p, 0.02, 1920, 1080, 1920, 1080) == sample_box(p, 0.03, 1920, 1080, 1920, 1080)
        True
        >>> sample_box_exact(p, 0.02, 1920, 1080, 1920, 1080) != sample_box_exact(p, 0.03, 1920, 1080, 1920, 1080)
        True
    """
    rect = path.evaluate(t).clamped()
    x0 = rect.x * img_w
    y0 = rect.y * img_h
    x1 = (rect.x + rect.w) * img_w
    y1 = (rect.y + rect.h) * img_h
    return _cover_crop_box_exact(x0, y0, x1, y1, out_w / out_h)


def sample_frame(
    path: BurnsPath,
    t: float,
    img_np: np.ndarray,
    img_w: int,
    img_h: int,
    out_w: int,
    out_h: int,
    *,
    resample: int = PIL_Image.BICUBIC,
) -> np.ndarray:
    """Render the single frame at normalized time ``t in [0, 1]``.

    Uses the **sub-pixel** box (:func:`sample_box_exact`), not the integer one,
    because rounding the window to whole source pixels is what makes slow motion
    visibly step — see that function's docstring. The fractional part is handed
    to Pillow's ``resize(box=...)``, which resamples from a float region, so
    consecutive frames differ continuously instead of snapping.

    Only the enclosing integer pixels are sliced out of ``img_np`` (at most one
    extra row/column per side), so this stays a cheap view rather than
    converting the whole image every frame.

    Returns an ``(out_h, out_w, C)`` uint8 array.
    """
    fx0, fy0, fx1, fy1 = sample_box_exact(path, t, img_w, img_h, out_w, out_h)

    # Slice the enclosing integer box, then let resize() do the sub-pixel part
    # relative to that slice.
    ix0, iy0 = int(math.floor(fx0)), int(math.floor(fy0))
    ix1, iy1 = min(img_w, int(math.ceil(fx1))), min(img_h, int(math.ceil(fy1)))
    crop = img_np[iy0:iy1, ix0:ix1]

    relative_box = (fx0 - ix0, fy0 - iy0, fx1 - ix0, fy1 - iy0)
    crop_img = PIL_Image.fromarray(crop).resize(
        (out_w, out_h), resample=resample, box=relative_box
    )
    return np.asarray(crop_img)
