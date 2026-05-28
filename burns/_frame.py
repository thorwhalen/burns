"""The single point where a :class:`~burns.path.BurnsPath` meets pixels.

Every render backend — and the multi-panel film renderer — samples frames
through :func:`sample_frame`, so the spec-to-pixel mapping is defined *once*.
Pinning it here is what lets a future JS/TS implementation reproduce the exact
crop, because the rule is short and explicit:

1. ``path.evaluate(t)`` -> a normalized :class:`~burns.rect.Rect` window.
2. The window maps to an integer pixel box via :meth:`Rect.to_pixels` (which
   clamps it inside the image).
3. If the requested output aspect ratio differs from the cropped window's pixel
   AR, **cover-crop** the window to the output AR (center-cropped — the FCP /
   iMovie default), so frames fill the output without stretching.
4. Resize the result to the (even-snapped) output size with a quality filter.
"""

from __future__ import annotations

import numpy as np
from PIL import Image as PIL_Image

from burns.path import BurnsPath


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


def _cover_crop(frame: np.ndarray, target_aspect: float) -> np.ndarray:
    """Center-crop ``frame`` (H, W[, C]) to ``target_aspect`` (width / height).

    Returns the largest centered sub-image of the requested AR. A no-op when the
    frame already matches (within a 1px tolerance).
    """
    h, w = frame.shape[:2]
    cur = w / h
    if abs(cur - target_aspect) < (1.0 / max(w, h)):
        return frame
    if cur > target_aspect:  # too wide — trim left/right
        new_w = max(1, int(round(h * target_aspect)))
        x0 = (w - new_w) // 2
        return frame[:, x0 : x0 + new_w]
    new_h = max(1, int(round(w / target_aspect)))  # too tall — trim top/bottom
    y0 = (h - new_h) // 2
    return frame[y0 : y0 + new_h]


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

    See the module docstring for the four-step mapping. Returns an
    ``(out_h, out_w, C)`` uint8 array.
    """
    rect = path.evaluate(t)
    x0, y0, x1, y1 = rect.to_pixels(img_w, img_h)
    crop = img_np[y0:y1, x0:x1]
    crop = _cover_crop(crop, out_w / out_h)
    crop_img = PIL_Image.fromarray(crop).resize((out_w, out_h), resample=resample)
    return np.asarray(crop_img)
