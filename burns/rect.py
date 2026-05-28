"""The Ken Burns viewport rectangle — the render-agnostic geometric atom.

A :class:`Rect` is a normalized region of interest (ROI) over a source image:
``(x, y, w, h)`` with **top-left origin, y-down**, every component a fraction
of the image in ``[0, 1]``. This is the convention shared by ``videopython``'s
``BoundingBox``, CSS ``transform-origin`` semantics, and FFmpeg's coordinate
origin — adopting it (rather than the older center+magnification spec) is what
lets one spec drive a Python renderer, a future JS/TS renderer, and a CSS
preview without each reinventing the pixel mapping.

Zoom is expressed as **window-fraction** (the visible window is a fraction of
the image) rather than magnification; the magnification a backend like FFmpeg
``zoompan`` wants is the derived read-only :attr:`Rect.zoom`.

The rect is pure data: no I/O, no image needed to construct or interpolate one.
Only :meth:`to_pixels` takes image dimensions, because that is the single point
where normalized geometry meets a concrete raster.
"""

from __future__ import annotations

from dataclasses import dataclass

# Floating-point slack for the aspect-ratio / containment invariants. Rects are
# authored by humans and interpolators, both of which accumulate rounding.
_EPS = 1e-6


@dataclass(frozen=True)
class Rect:
    """A normalized ``(x, y, w, h)`` viewport over a source image.

    All four components are fractions of the image in ``[0, 1]`` with a
    top-left origin. ``(x, y)`` is the top-left corner of the window; ``w`` and
    ``h`` are its width and height. ``Rect(0, 0, 1, 1)`` is the whole image.

    Examples:
        >>> full = Rect(0.0, 0.0, 1.0, 1.0)
        >>> full.center
        (0.5, 0.5)
        >>> full.zoom
        1.0
        >>> Rect.from_center_zoom(0.5, 0.5, 2.0)
        Rect(x=0.25, y=0.25, w=0.5, h=0.5)
    """

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        # Coerce to float so int literals (Rect(0, 0, 1, 1)) interpolate and
        # repr consistently, and so window math never silently does int ops.
        for name in ("x", "y", "w", "h"):
            object.__setattr__(self, name, float(getattr(self, name)))

    @property
    def aspect(self) -> float:
        """Aspect ratio of the window *in normalized image units* (``w / h``).

        Note this is not the rendered-pixel aspect ratio unless the image is
        square — the pixel AR is ``(w * img_w) / (h * img_h)``. The render path
        reconciles the window with the desired output AR via a cover-crop.
        """
        return self.w / self.h

    @property
    def center(self) -> tuple[float, float]:
        """The window's center ``(cx, cy)`` in ``[0, 1]`` image units."""
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    @property
    def zoom(self) -> float:
        """Magnification implied by the window, ``1 / max(w, h)``.

        ``1.0`` = the full image; ``> 1.0`` = zoomed in. This is the derived
        value an FFmpeg ``zoompan`` backend consumes; the window-fraction
        ``(w, h)`` is the authoritative, user-facing representation.
        """
        return 1.0 / max(self.w, self.h)

    def is_contained(self) -> bool:
        """True when the window lies wholly inside the image.

        Examples:
            >>> Rect(0.1, 0.1, 0.5, 0.5).is_contained()
            True
            >>> Rect(0.8, 0.0, 0.5, 0.5).is_contained()
            False
        """
        return (
            self.x >= -_EPS
            and self.y >= -_EPS
            and self.x + self.w <= 1.0 + _EPS
            and self.y + self.h <= 1.0 + _EPS
        )

    def clamped(self) -> "Rect":
        """Slide the window inside the image **without resizing it**.

        Clamps the top-left corner so the window "rides the wall" at an edge
        rather than shrinking — shrinking the box would change its aspect ratio
        and make the rendered frame breathe/stretch. Windows larger than the
        image in a dimension are centered in that dimension.

        Examples:
            >>> Rect(0.8, 0.0, 0.5, 0.5).clamped()
            Rect(x=0.5, y=0.0, w=0.5, h=0.5)
            >>> Rect(-0.2, 0.3, 0.4, 0.4).clamped()
            Rect(x=0.0, y=0.3, w=0.4, h=0.4)
        """
        x = _clamp_corner(self.x, self.w)
        y = _clamp_corner(self.y, self.h)
        return Rect(x, y, self.w, self.h)

    def lerp(self, other: "Rect", t: float) -> "Rect":
        """Linearly interpolate toward ``other`` by ``t`` in ``[0, 1]``.

        Examples:
            >>> Rect(0, 0, 1, 1).lerp(Rect(0.25, 0.25, 0.5, 0.5), 0.5)
            Rect(x=0.125, y=0.125, w=0.75, h=0.75)
        """
        return Rect(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
            self.w + (other.w - self.w) * t,
            self.h + (other.h - self.h) * t,
        )

    def to_pixels(self, img_w: int, img_h: int) -> tuple[int, int, int, int]:
        """Map the (clamped) window to an integer pixel box ``(x0, y0, x1, y1)``.

        Clamps first so the box is always inside the raster, then rounds (not
        truncates) for symmetric integer conversion. The returned box is a
        half-open crop region suitable for ``ndarray[y0:y1, x0:x1]``.

        Examples:
            >>> Rect(0.0, 0.0, 1.0, 1.0).to_pixels(100, 80)
            (0, 0, 100, 80)
            >>> Rect.from_center_zoom(0.5, 0.5, 2.0).to_pixels(100, 80)
            (25, 20, 75, 60)
        """
        r = self.clamped()
        x0 = int(round(r.x * img_w))
        y0 = int(round(r.y * img_h))
        x1 = int(round((r.x + r.w) * img_w))
        y1 = int(round((r.y + r.h) * img_h))
        return (x0, y0, x1, y1)

    @classmethod
    def from_center_zoom(
        cls, cx: float, cy: float, zoom: float = 1.0, *, aspect: float = 1.0
    ) -> "Rect":
        """Build a rect from a pan center, a zoom, and a window aspect ratio.

        This is the bridge from the older center+magnification mental model to
        the ``(x, y, w, h)`` representation. ``zoom`` is window-fraction
        magnification (``1.0`` = full image, ``> 1.0`` = zoomed in). ``aspect``
        is the window's normalized ``w / h``; the default ``1.0`` yields an
        isotropic window (``w == h``) whose rendered AR equals the source
        image's — reproducing the legacy behavior exactly. The result is
        clamped to stay inside the image.

        Examples:
            >>> Rect.from_center_zoom(0.5, 0.5, 1.0)
            Rect(x=0.0, y=0.0, w=1.0, h=1.0)
            >>> Rect.from_center_zoom(0.75, 0.5, 2.0)  # off-center zoom-in
            Rect(x=0.5, y=0.25, w=0.5, h=0.5)
        """
        if zoom <= 0:
            raise ValueError(f"Rect.from_center_zoom: zoom must be > 0, got {zoom}")
        # Largest window of the requested aspect that fits the unit square,
        # then scaled down by 1/zoom.
        if aspect >= 1.0:
            w = 1.0 / zoom
            h = w / aspect
        else:
            h = 1.0 / zoom
            w = h * aspect
        return cls(cx - w / 2.0, cy - h / 2.0, w, h).clamped()


def _clamp_corner(origin: float, size: float) -> float:
    """Clamp a top-left coordinate so ``[origin, origin+size]`` fits ``[0, 1]``.

    When ``size > 1`` (window larger than the image in this dimension) the valid
    range is empty; we center the window instead (``(1 - size) / 2``).
    """
    high = 1.0 - size
    if high < 0.0:
        return high / 2.0
    return max(0.0, min(high, origin))
