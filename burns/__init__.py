"""burns — Ken Burns pan/zoom video effects.

Turn a still image (or a sequence of stills) into a cinematic pan/zoom film,
driven by one **render-agnostic motion spec** so the same path can feed a Python
renderer today and an in-browser JS/TS renderer tomorrow.

The core abstraction is a pure, time-parameterized spec:

- :class:`Rect` — a normalized ``(x, y, w, h)`` viewport over the image
  (top-left origin, window-fraction zoom).
- :class:`BurnsPath` — keyframes + easing, with ``evaluate(t) -> Rect`` (pure,
  deterministic, frame-count-free) and JSON ``to_dict`` / ``from_dict``.
- :func:`ken_burns_path` — build a cohesive, deterministic path per sequence
  index from a little intent (style / zoom / pan / easing).

Two renderers consume a path plus a render-time ``duration``:

- :func:`ken_burns_video` — one image -> one mp4 (pluggable backend).
- :func:`ken_burns_film` — a sequence of ``(image, path, duration)`` panels ->
  one continuous mp4 (single encode pass, no seams), with optional audio.

Quickstart:

    >>> from burns import ken_burns_video, ken_burns_path
    >>> ken_burns_video("photo.jpg")  # 2s push-in  # doctest: +SKIP
    >>> ken_burns_video(  # path per sequence index  # doctest: +SKIP
    ...     "photo.jpg", ken_burns_path(1, style="push"), duration=5.0
    ... )
"""

from burns.rect import Rect
from burns.easing import parse_easing, cubic_bezier, CSS_BEZIERS
from burns.path import BurnsPath, ken_burns_path, PanelInput
from burns.content import (
    content_aware_path,
    content_aware_path_for,
    salient_box,
    FacesDetector,
)
from burns.render import (
    ken_burns_video,
    ken_burns_film,
    DEFAULT_BURNS_PATH,
    DEFAULT_DURATION_S,
)
from burns.backends import RenderBackend, register_backend, get_backend

__all__ = [
    "Rect",
    "BurnsPath",
    "ken_burns_path",
    "content_aware_path",
    "content_aware_path_for",
    "salient_box",
    "FacesDetector",
    "ken_burns_video",
    "ken_burns_film",
    "PanelInput",
    "DEFAULT_BURNS_PATH",
    "DEFAULT_DURATION_S",
    "parse_easing",
    "cubic_bezier",
    "CSS_BEZIERS",
    "RenderBackend",
    "register_backend",
    "get_backend",
]
