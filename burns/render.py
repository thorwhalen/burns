"""Ken Burns **renderers** — turn still images into pan/zoom video.

Two entry points, both backed by a lazy ``moviepy.VideoClip`` so the whole
clip is never materialised in memory:

- :func:`ken_burns_video` — one image, a multi-phase pan/zoom, one mp4.
- :func:`ken_burns_film` — a sequence of ``(image, phases)`` panels rendered
  as a **single** continuous film (no per-panel intermediate files, no concat
  seams, no per-panel tail freezes), with an optional pre-built audio track
  muxed in.

Both consume the ``(cx, cy, s)`` rectangle spec described under
:func:`ken_burns_video`. Use :func:`burns.ken_burns_path` to generate cohesive
multi-phase paths instead of hand-authoring rectangles.
"""

import os
import tempfile
from pathlib import Path

import numpy as np
import moviepy as mp
from PIL import Image as PIL_Image

from ._util import _auto_video_path, _ensure_output_path, _non_colliding_key

_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")


def _parse_rectangle(rect, default=(0.5, 0.5, 1.0)):
    """Normalize a rectangle input to a ``(cx, cy, s)`` tuple.

    Accepts:
        - ``None``: returns ``default``
        - single number: ``(0.5, 0.5, value)`` (a centered zoom)
        - pair: ``(cx, cy, 1.0)`` (a pan center at full scale)
        - triple: ``(cx, cy, s)`` (the full spec)
    """
    if rect is None:
        return default
    if isinstance(rect, (int, float)):
        return (0.5, 0.5, float(rect))
    if isinstance(rect, (list, tuple)):
        if len(rect) == 1:
            return (0.5, 0.5, float(rect[0]))
        elif len(rect) == 2:
            return (float(rect[0]), float(rect[1]), 1.0)
        elif len(rect) == 3:
            return (float(rect[0]), float(rect[1]), float(rect[2]))
    raise ValueError(f"Invalid rectangle: {rect}")


def _rect_to_box(cx, cy, s, img_w, img_h):
    """Convert ``(cx, cy, s)`` to a pixel crop box ``(xmin, ymin, xmax, ymax)``.

    The crop's width and height in pixels are ``img_w / s`` and ``img_h / s``
    respectively — same aspect ratio as the source image, so the resize-back-to-
    ``(img_w, img_h)`` step that follows never stretches the frame.

    Pan-center clamping: when ``(cx, cy)`` would push the crop past an edge, we
    clamp the **center**, not the crop box. Clamping the box itself shrinks one
    side and breaks the aspect ratio — that was the source of the breathing /
    stretching artefact in long pans. By clamping the center, the box "rides
    the wall" at the edge but stays the right size.
    """
    half_w = 0.5 / s
    half_h = 0.5 / s
    # Clamp the pan center so the crop box fits inside the image. When zoom
    # s <= 1.0, half_w >= 0.5 → the valid range collapses to {0.5} (i.e. the
    # only legal center is the image middle); ``max(low, min(high, x))`` is
    # robust to that case because ``min(...)`` still returns 0.5.
    cx = max(half_w, min(1.0 - half_w, cx))
    cy = max(half_h, min(1.0 - half_h, cy))
    xmin = (cx - half_w) * img_w
    ymin = (cy - half_h) * img_h
    xmax = (cx + half_w) * img_w
    ymax = (cy + half_h) * img_h
    # Round (not truncate) for symmetric int conversion — the ±1 px drift
    # from truncation can also nudge aspect ratio on extreme zooms.
    return (
        int(round(xmin)),
        int(round(ymin)),
        int(round(xmax)),
        int(round(ymax)),
    )


DEFAULT_KENBURNS_PHASES = (((0.5, 0.5, 1.0), (0.5, 0.5, 1.3), 2.0),)


def ken_burns_video(
    image,
    *,
    phases=DEFAULT_KENBURNS_PHASES,
    fps: int = 30,
    saveas: str | None = None,
    codec: str = "libx264",
    audio_codec: str = "aac",
    **write_kwargs,
) -> Path:
    """Create a Ken Burns effect video from an image with multi-phase pan/zoom.

    Args:
        image: Path to image file or image object (PIL.Image, np.ndarray)
        phases: Iterable of ``(start_rect, end_rect, duration_s)`` phases. The
            camera moves linearly from ``start_rect`` to ``end_rect`` over each
            phase's ``duration_s``; phases play back-to-back so total clip
            length is the sum of their durations. Default is a single 2-second
            standard Ken Burns push-in.
        fps: Frames per second (default 30)
        saveas: Where to save video (default: image path with "_kenburns" appended before extension)
        codec: Video codec (default libx264)
        audio_codec: Audio codec (default aac)
        **write_kwargs: Passed to write_videofile

    Returns:
        Path to saved video

    Rectangle parameterization:
        Rect = (cx, cy, s) — pan center (cx, cy) in [0, 1] and zoom scale s > 0.
        s = 1: the full image; s > 1: zoomed in (a smaller crop box).
        The crop box is clamped to the image, so you cannot zoom out past the
        original — express a zoom-out as start s > 1 panning to end s = 1.
        Standard Ken Burns: the full image (s=1) zooming in to s=1.3.
        Rects accept the same flexible forms as elsewhere: a scalar zoom, a
        (cx, cy) pan pair, or the full (cx, cy, s) triple.

    Phase continuity:
        A phase's ``end_rect`` does not need to match the next phase's
        ``start_rect`` — discontinuities are allowed and produce an
        instantaneous cut. For continuous motion, set each phase's
        ``start_rect`` equal to the previous phase's ``end_rect``.

    Examples:
        >>> ken_burns_video("photo.jpg")  # Standard 2s push-in  # doctest: +SKIP
        >>> ken_burns_video(  # doctest: +SKIP
        ...     "photo.jpg",
        ...     phases=[((0.5, 0.5, 1.0), (0.65, 0.4, 1.2), 5.0)],
        ... )
        >>> ken_burns_video(  # doctest: +SKIP
        ...     "photo.jpg",
        ...     phases=[
        ...         ((0.5, 0.5, 1.0), (0.65, 0.4, 1.2), 4.0),
        ...         ((0.65, 0.4, 1.2), (0.35, 0.6, 1.2), 4.0),
        ...         ((0.35, 0.6, 1.2), (0.5, 0.5, 1.3), 4.0),
        ...     ],
        ... )
    """
    # Accept image as path, PIL.Image, or np.ndarray.
    # Track the original image path for output path generation.
    image_path = None
    if isinstance(image, (str, Path)):
        image_path = Path(image)
        img = PIL_Image.open(str(image)).convert("RGB")
    elif isinstance(image, np.ndarray):
        img = PIL_Image.fromarray(image)
    elif hasattr(image, "convert"):
        img = image.convert("RGB")
    else:
        raise ValueError(f"Unsupported image type: {type(image)}")

    img_w, img_h = img.size
    img_np = np.array(img)  # preload once for fast per-frame cropping

    # Normalize phases: each entry → (start_rect, end_rect, duration_s).
    parsed_phases: list[tuple[tuple, tuple, float]] = []
    for i, phase in enumerate(phases):
        if not isinstance(phase, (list, tuple)) or len(phase) != 3:
            raise ValueError(
                f"phase {i}: expected (start_rect, end_rect, duration_s), got {phase!r}"
            )
        start_rect = _parse_rectangle(phase[0], default=(0.5, 0.5, 1.0))
        end_rect = _parse_rectangle(phase[1], default=(0.5, 0.5, 1.3))
        dur = float(phase[2])
        if dur <= 0:
            raise ValueError(f"phase {i}: duration_s must be > 0, got {dur}")
        parsed_phases.append((start_rect, end_rect, dur))
    if not parsed_phases:
        raise ValueError("ken_burns_video: phases must be non-empty")

    duration_s = sum(p[2] for p in parsed_phases)
    # Cumulative phase-start times for fast lookup at frame time.
    cum_starts = [0.0]
    for _, _, dur in parsed_phases:
        cum_starts.append(cum_starts[-1] + dur)

    def _lerp(a, b, t):
        return a + (b - a) * t

    def _ken_burns_frame(t):
        """Render the pan/zoom frame at time ``t`` (seconds), one frame at a time.

        Computed lazily so the whole clip is never materialised in memory.
        Picks the active phase by ``t`` and lerps linearly within it; clamps
        to the last phase's end-rect once ``t`` reaches the total duration.
        """
        if t >= duration_s:
            start_rect, end_rect, _ = parsed_phases[-1]
            cx, cy, s = end_rect
        else:
            # Linear scan is fine — a film typically has < 20 phases per image.
            for idx, (start_rect, end_rect, dur) in enumerate(parsed_phases):
                if t < cum_starts[idx + 1]:
                    local_t = (t - cum_starts[idx]) / dur
                    cx = _lerp(start_rect[0], end_rect[0], local_t)
                    cy = _lerp(start_rect[1], end_rect[1], local_t)
                    s = _lerp(start_rect[2], end_rect[2], local_t)
                    break
            else:  # pragma: no cover — covered by the t >= duration_s branch
                start_rect, end_rect, _ = parsed_phases[-1]
                cx, cy, s = end_rect
        xmin, ymin, xmax, ymax = _rect_to_box(cx, cy, s, img_w, img_h)
        crop = img_np[ymin:ymax, xmin:xmax]
        crop_img = PIL_Image.fromarray(crop).resize(
            (img_w, img_h), resample=PIL_Image.BICUBIC
        )
        return np.asarray(crop_img)

    # Determine output path.
    if saveas is None:
        if image_path is not None:
            # Append "_kenburns" to the source image's filename.
            output_path = _auto_video_path(str(image_path), "_kenburns", ext=".mp4")
        else:
            # Fallback to temp directory when there is no source path.
            output_path = Path(tempfile.gettempdir()) / f"kenburns_{os.getpid()}.mp4"
    else:
        output_path = _ensure_output_path(saveas)
        # Ensure it has a video extension.
        if not output_path.suffix or output_path.suffix.lower() not in _VIDEO_EXTS:
            output_path = output_path.with_suffix(".mp4")

    # Avoid overwriting an existing auto-generated path.
    if saveas is None:
        directory = output_path.parent
        filename = output_path.name
        try:
            existing_files = (
                set(os.listdir(directory)) if directory else set(os.listdir("."))
            )
        except OSError:
            existing_files = set()
        if filename in existing_files:
            output_path = directory / _non_colliding_key(filename, existing_files)

    # Create the clip lazily: frames are computed on demand during encoding.
    clip = mp.VideoClip(_ken_burns_frame, duration=duration_s).with_fps(fps)

    # Set default kwargs for better compatibility.
    write_kwargs.setdefault("bitrate", "5000k")
    write_kwargs.setdefault("preset", "medium")
    write_kwargs.setdefault("logger", None)  # Suppress verbose output

    clip.write_videofile(
        str(output_path), codec=codec, audio_codec=audio_codec, **write_kwargs
    )
    clip.close()

    print(f"Saved Ken Burns video to: {output_path}")
    return output_path


# --------------------------------------------------------------------- #
# Multi-panel Ken Burns film
# --------------------------------------------------------------------- #


def ken_burns_film(
    panels,
    *,
    saveas: str,
    fps: int = 30,
    audio_path=None,
    codec: str = "libx264",
    audio_codec: str = "aac",
    **write_kwargs,
) -> Path:
    """Render an N-panel Ken Burns film in a single pass — no per-panel
    intermediate files, no concat seams, no per-panel tail freezes.

    Each panel is one ``(image, phases)`` pair where ``image`` is a path /
    PIL.Image / np.ndarray and ``phases`` is the same shape as in
    :func:`ken_burns_video`. The film plays panels back-to-back; the camera
    cuts at panel boundaries (different image) but motion never pauses on
    a static frame within a panel.

    Args:
        panels: iterable of ``(image, phases)`` pairs. Each panel's total
            duration = sum of its phase durations. Film total = sum across
            panels.
        saveas: output mp4 path (required — multi-panel films don't have a
            single source image to derive an auto-name from).
        fps: frame rate of the film.
        audio_path: optional pre-built audio track (already concatenated,
            already matching the film duration). When supplied it is muxed
            in. Per-panel audio is the caller's job to assemble — keep
            the renderer pure visual.
        codec, audio_codec, **write_kwargs: forwarded to ``write_videofile``.

    Why a single VideoClip rather than per-panel render + concatenate:

    - Concat re-encodes at I-frame boundaries; the last few frames of each
      input clip can drop and the next clip's first frame may freeze
      briefly. With one VideoClip the encoder writes a single stream.
    - No per-panel tail-pad: the pan reaches the panel's last frame exactly
      when the panel ends; the next frame is already the next panel's
      first.
    - Lazy frame generation: a single ``make_frame(t)`` closure dispatches
      by global ``t`` to the right (panel, phase) — the whole film is
      never materialised in memory.

    Returns:
        Path to the written mp4.
    """
    # Load each panel's image once; pre-parse phases.
    panel_renders = []
    film_duration = 0.0
    for idx, panel in enumerate(panels):
        if not isinstance(panel, (list, tuple)) or len(panel) != 2:
            raise ValueError(
                f"panel {idx}: expected (image, phases) pair, got {panel!r}"
            )
        image, phases = panel
        if isinstance(image, (str, Path)):
            img = PIL_Image.open(str(image)).convert("RGB")
        elif isinstance(image, np.ndarray):
            img = PIL_Image.fromarray(image)
        elif hasattr(image, "convert"):
            img = image.convert("RGB")
        else:
            raise ValueError(f"panel {idx}: unsupported image type: {type(image)}")
        img_w, img_h = img.size
        img_np = np.array(img)

        parsed: list[tuple[tuple, tuple, float]] = []
        for j, phase in enumerate(phases):
            if not isinstance(phase, (list, tuple)) or len(phase) != 3:
                raise ValueError(
                    f"panel {idx}, phase {j}: expected (start, end, dur), got {phase!r}"
                )
            s = _parse_rectangle(phase[0], default=(0.5, 0.5, 1.0))
            e = _parse_rectangle(phase[1], default=(0.5, 0.5, 1.3))
            d = float(phase[2])
            if d <= 0:
                raise ValueError(
                    f"panel {idx}, phase {j}: duration_s must be > 0, got {d}"
                )
            parsed.append((s, e, d))
        if not parsed:
            raise ValueError(f"panel {idx}: phases must be non-empty")

        panel_dur = sum(p[2] for p in parsed)
        cum = [0.0]
        for _, _, d in parsed:
            cum.append(cum[-1] + d)
        panel_renders.append(
            {
                "img_np": img_np,
                "img_w": img_w,
                "img_h": img_h,
                "phases": parsed,
                "cum_starts": cum,
                "duration": panel_dur,
                "film_offset": film_duration,
                "size": (img_w, img_h),
            }
        )
        film_duration += panel_dur

    if film_duration <= 0:
        raise ValueError("ken_burns_film: panels must be non-empty")

    # Common output frame size = first panel's size. When all panels share the
    # same size (common for storyboard demos), every panel is rendered at its
    # native size and no letter/pillar-boxing happens.
    out_w, out_h = panel_renders[0]["size"]

    def _lerp(a, b, t):
        return a + (b - a) * t

    def make_frame(t):
        """Render the film's frame at global time ``t``.

        Walks the panel list once per frame (typical film: < 50 panels —
        cheap). Within a panel, linearly interpolates between the active
        phase's start and end rect; clamps to the last phase's end-rect
        when ``t`` lands exactly on a boundary (avoids a 1-frame flicker
        at panel transitions).
        """
        if t >= film_duration:
            pr = panel_renders[-1]
            cx, cy, s = pr["phases"][-1][1]
        else:
            pr = None
            for candidate in panel_renders:
                if t < candidate["film_offset"] + candidate["duration"]:
                    pr = candidate
                    break
            assert pr is not None  # guarded by t < film_duration
            local_t = t - pr["film_offset"]
            cx = cy = s = None
            for idx, (start, end, dur) in enumerate(pr["phases"]):
                if local_t < pr["cum_starts"][idx + 1]:
                    inner = (local_t - pr["cum_starts"][idx]) / dur
                    cx = _lerp(start[0], end[0], inner)
                    cy = _lerp(start[1], end[1], inner)
                    s = _lerp(start[2], end[2], inner)
                    break
            if cx is None:  # exactly on a boundary
                start, end, _ = pr["phases"][-1]
                cx, cy, s = end

        img_w, img_h = pr["img_w"], pr["img_h"]
        xmin, ymin, xmax, ymax = _rect_to_box(cx, cy, s, img_w, img_h)
        crop = pr["img_np"][ymin:ymax, xmin:xmax]
        # Resize the crop back to the film's output frame size. When panels
        # are all the same size (common case), this equals the crop's own
        # (img_w, img_h) and the aspect is preserved exactly.
        crop_img = PIL_Image.fromarray(crop).resize(
            (out_w, out_h), resample=PIL_Image.BICUBIC
        )
        return np.asarray(crop_img)

    output_path = _ensure_output_path(saveas)
    if not output_path.suffix or output_path.suffix.lower() not in _VIDEO_EXTS:
        output_path = output_path.with_suffix(".mp4")

    clip = mp.VideoClip(make_frame, duration=film_duration).with_fps(fps)
    if audio_path is not None:
        audio_clip = mp.AudioFileClip(str(audio_path))
        clip = clip.with_audio(audio_clip)

    write_kwargs.setdefault("bitrate", "5000k")
    write_kwargs.setdefault("preset", "medium")
    write_kwargs.setdefault("logger", None)

    clip.write_videofile(
        str(output_path), codec=codec, audio_codec=audio_codec, **write_kwargs
    )
    clip.close()

    print(
        f"Saved Ken Burns film ({len(panel_renders)} panels, "
        f"{film_duration:.1f}s) to: {output_path}"
    )
    return output_path
