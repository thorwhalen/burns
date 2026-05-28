"""burns — Ken Burns pan/zoom video effects.

Turn a still image (or a sequence of stills) into a cinematic pan/zoom film.

Three building blocks:

- :func:`ken_burns_video` — render one image into a multi-phase pan/zoom mp4.
- :func:`ken_burns_film` — render a sequence of ``(image, phases)`` panels as
  one continuous film (no concat seams, no per-panel freezes), with optional
  audio.
- :func:`ken_burns_path` — generate a cohesive, non-repetitive pan/zoom *path*
  (the ``phases`` the renderers consume) from a few intent parameters.

Quickstart:

    >>> from burns import ken_burns_video, ken_burns_path
    >>> ken_burns_video("photo.jpg")  # standard 2s push-in  # doctest: +SKIP
    >>> ken_burns_video(  # path generated per index/style  # doctest: +SKIP
    ...     "photo.jpg", phases=ken_burns_path(1, 5.0, style="push", ease=True)
    ... )

Rectangles everywhere are ``(cx, cy, s)`` — pan center in ``[0, 1]`` and zoom
scale (``1.0`` = full frame). See :func:`ken_burns_video` for the full spec.
"""

from burns.render import (
    ken_burns_video,
    ken_burns_film,
    DEFAULT_KENBURNS_PHASES,
)
from burns.paths import (
    ken_burns_path,
    KenBurnsRect,
    KenBurnsPhase,
    KenBurnsPath,
    PanelInput,
)

__all__ = [
    "ken_burns_video",
    "ken_burns_film",
    "ken_burns_path",
    "DEFAULT_KENBURNS_PHASES",
    "KenBurnsRect",
    "KenBurnsPhase",
    "KenBurnsPath",
    "PanelInput",
]
