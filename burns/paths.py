"""Deterministic Ken Burns pan/zoom **paths**.

A *path* is a list of ``(start_rect, end_rect, duration_s)`` phases describing
how the virtual camera moves over a single still image. :func:`ken_burns_path`
builds such a path from a small set of intent parameters (style, zoom, pan,
ease) so a sequence of images gets cohesive, non-repetitive motion without the
caller hand-authoring rectangles.

Rectangles are ``(cx, cy, s)`` — pan center ``(cx, cy)`` in ``[0, 1]`` image
units and zoom scale ``s`` (``1.0`` = full frame, ``> 1.0`` = zoomed in). This
is the same rectangle parameterization the renderers in :mod:`burns.render`
consume, so a path drops straight into :func:`burns.ken_burns_video` (as its
``phases``) or :func:`burns.ken_burns_film` (as a panel's phases).

The functions here are **pure** — they map intent to geometry with no I/O — so
they are cheap to unit-test and produce identical paths for identical inputs.
"""

from __future__ import annotations

import math

# A single (start_rect, end_rect, duration_s) segment of a path.
# Rect is (cx, cy, s) — pan center in [0, 1] and zoom scale (1.0 = full).
KenBurnsRect = tuple[float, float, float]
KenBurnsPhase = tuple[KenBurnsRect, KenBurnsRect, float]
KenBurnsPath = list[KenBurnsPhase]

# A single panel input to a film renderer: image to animate + its pan/zoom
# path. Audio, when present, is supplied separately as one combined track for
# the whole film, so the renderer stays pure visual.
from pathlib import Path  # noqa: E402  (kept next to the alias that uses it)

PanelInput = tuple[Path, KenBurnsPath]


_EASE_PHASES: tuple[tuple[float, float], ...] = (
    (0.25, 0.10),  # slow start: 25% of time covers 10% of motion
    (0.50, 0.70),  # mid:        50% of time covers 70% of motion
    (0.25, 0.20),  # slow end:   25% of time covers 20% of motion
)
"""Three (time_fraction, motion_fraction) phases approximating a quadratic
ease. Slow-fast-slow — preserves single-direction motion while losing the
"robotic" constant-velocity feel."""


_VALID_STYLES = ("push", "drift")


def ken_burns_path(
    index: int,
    duration_s: float,
    *,
    style: str = "push",
    zoom: float = 1.10,
    pan: float = 0.03,
    ease: bool = False,
) -> KenBurnsPath:
    """A deterministic pan/zoom path for one image.

    Two named styles, opt-in ease curve:

    - ``style="push"`` (default) — the "cinematic push". One slow zoom
      (dominant motion) plus a subtle pan toward an off-center focal
      point. Odd indices push *in*, even indices pull *out* — a sequence
      of images has visual rhythm without changing direction *within*
      a shot.

    - ``style="drift"`` — pure horizontal pan, no zoom variance,
      alternating direction per index. Useful for museum-style sequences
      where the dominant motion should be pan, not zoom.

    - ``ease=True`` — splits the single-phase motion into three phases
      (slow-start, mid, slow-end) approximating a quadratic ease.
      Velocity changes; direction and total magnitude do not.

    Per-index deterministic: same args always return the same path.

    Args:
        index: the image's 1-based position in the sequence (seeds the
            focal-point direction and the push-in/pull-out alternation).
        duration_s: total time the path should cover, in seconds.
        style: ``"push"`` (default) or ``"drift"``.
        zoom: the zoomed-end scale (> 1.0). Ignored for ``"drift"`` —
            drift uses a single constant zoom end-to-end, derived from
            ``pan`` so the lateral slide is actually visible.
        pan: how far the framing drifts off-center, in [0, 1] image
            units. For ``"push"`` it controls focal-point offset; for
            ``"drift"`` it is the total horizontal distance covered.
        ease: when True, split the single phase into the slow-fast-slow
            3-phase ease curve.

    Returns:
        A :data:`KenBurnsPath` — a list of ``(start_rect, end_rect,
        duration_s)`` phases whose durations sum to ``duration_s``.

    Examples:
        >>> ken_burns_path(1, 5.0)
        [((0.5, 0.5, 1.0), (0.4788, 0.5212, 1.1), 5.0)]
        >>> ken_burns_path(2, 5.0)[0][2]  # one phase, full duration
        5.0
        >>> len(ken_burns_path(1, 6.0, ease=True))  # slow-fast-slow
        3
    """
    if duration_s <= 0:
        raise ValueError(f"ken_burns_path: duration_s must be > 0, got {duration_s}")
    if style not in _VALID_STYLES:
        raise ValueError(
            f"ken_burns_path: style must be one of {_VALID_STYLES}, got {style!r}"
        )

    start, end = _endpoints_for_style(style, index, zoom=zoom, pan=pan)
    if not ease:
        return [(start, end, duration_s)]
    return _split_with_ease(start, end, duration_s)


def _endpoints_for_style(
    style: str, index: int, *, zoom: float, pan: float
) -> tuple[KenBurnsRect, KenBurnsRect]:
    """Return the ``(start_rect, end_rect)`` for one image under one style."""
    if style == "push":
        # The focal-point direction cycles through compass octants per index —
        # each image zooms toward (or pulls back from) a different corner.
        angle = (index * 2 + 1) * (math.pi / 4)
        off_cx = round(0.5 + pan * math.cos(angle), 4)
        off_cy = round(0.5 + pan * math.sin(angle), 4)
        center: KenBurnsRect = (0.5, 0.5, 1.0)
        offset: KenBurnsRect = (off_cx, off_cy, zoom)
        if index % 2 == 1:
            return center, offset  # push in
        return offset, center  # pull out

    # style == "drift": purely horizontal pan at a constant zoom.
    # Alternate direction per index — odd drifts right, even drifts left.
    direction = 1 if index % 2 == 1 else -1
    # The drift distance scales with `pan`; we use a wider default offset
    # than the push style because there is no zoom rhythm to share the
    # frame budget with. A `pan` of 0.03 gives a noticeable but not
    # frenetic horizontal slide.
    half = min(pan, 0.45)  # guard: pan must stay < 0.5
    start_cx = round(0.5 - direction * half, 4)
    end_cx = round(0.5 + direction * half, 4)
    # The zoom MUST exceed 1.0: at scale 1.0 the crop window is the whole
    # frame, so the renderer clamps the pan center to 0.5 and nothing moves.
    # Pick the smallest zoom whose (smaller-than-frame) window can reach
    # 0.5 ± half — that is 1 / (1 - 2*half) — plus a little headroom so the
    # slide reads as motion rather than riding the edges.
    drift_zoom = round(1.0 / (1.0 - 2.0 * half) + 0.05, 4)
    return (
        (start_cx, 0.5, drift_zoom),
        (end_cx, 0.5, drift_zoom),
    )


def _split_with_ease(
    start: KenBurnsRect, end: KenBurnsRect, duration_s: float
) -> KenBurnsPath:
    """Break ``[start → end]`` into the slow-fast-slow 3-phase ease curve.

    The straight-line motion is identical; only the *velocity* changes
    along the way. Each phase's time fraction and motion fraction come
    from :data:`_EASE_PHASES`. The chain is continuous — phase N+1
    starts exactly where phase N ended.
    """
    phases: KenBurnsPath = []
    cumulative_motion = 0.0
    last_point = start
    for time_frac, motion_frac in _EASE_PHASES:
        cumulative_motion += motion_frac
        next_point = _interp_rect(start, end, cumulative_motion)
        phases.append((last_point, next_point, duration_s * time_frac))
        last_point = next_point
    return phases


def _interp_rect(a: KenBurnsRect, b: KenBurnsRect, t: float) -> KenBurnsRect:
    """Linear interpolation between two ``(cx, cy, s)`` rectangles."""
    return (
        round(a[0] + (b[0] - a[0]) * t, 6),
        round(a[1] + (b[1] - a[1]) * t, 6),
        round(a[2] + (b[2] - a[2]) * t, 6),
    )
