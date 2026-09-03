"""The FFmpeg render backend: burns samples the path, `looks` compiles it.

The second backend `burns.backends` has named as its intended extension since it
was written. The split is the one RULE G draws across the two packages:

- **burns owns the authored geometry.** The `BurnsPath`, its easing, the
  decision that this is the shot, and — crucially — the cover-crop to the output
  aspect that :func:`burns._frame.sample_box` already performs.
- **`looks` owns the compilation.** Normalised keyframes in, an ffmpeg filter
  fragment out. It never learns what ``ease_in_out`` means.
- **burns runs the argv.** `looks` starts no process that produces media; that
  is its own invariant, and executing is this module's job.

The dependency points ``burns -> looks``, which is legal because `looks` declares
no dependencies at all and is stdlib-only on import. The reverse stays
forbidden: `burns` pulls `moviepy`, which pulls a GPL-configured ffmpeg binary.

## Why the geometry comes from `sample_box` and not from `path.evaluate`

The obvious adapter samples `path.evaluate(t)` and hands those rects to `looks`.
That would be **wrong**, and wrong in the invisible direction: the pillow backend
does not show `evaluate(t)` either — it shows that rect *cover-cropped to the
output aspect* (:func:`burns._frame.sample_box`, steps 1-3). Sampling the raw
path would frame every clip differently from the default backend whenever the
output aspect differs from the image's, which is the common case.

Reading the window out of `sample_box` instead makes the two backends agree **by
construction** rather than by coincidence, and it means this module contains no
second copy of the crop contract that the golden vectors pin.

It also lands the path in exactly the shape `looks` wants: every window carries
the output's aspect, so they are all the same shape, and
:func:`looks.reframe_motion` can lift the whole path into a frame of that shape.

## What the sampling costs, measured

`looks` interpolates **linearly** between the keyframes it is given — that is the
seam, not a limitation. So an eased path has to be sampled densely enough that
the linear rebuild is indistinguishable from the easing. Measured on the default
ease-in-out push-in, max deviation from the true path:

=====  ==================  =====================
n      normalised          at 1920 px
=====  ==================  =====================
2      0.0280              53.7 px
5      0.00773             14.8 px
9      0.00199             3.8 px
17     0.000496            0.95 px
33     0.000125            0.24 px
=====  ==================  =====================

so the default is adaptive: sample until the worst deviation is under half a
source pixel, rather than pin a magic number that is wasteful at SD and
insufficient at 4K.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image as PIL_Image

from burns._frame import sample_box
from burns.path import BurnsPath

#: How far the linear rebuild of an eased path may stray from the path itself,
#: in source pixels, before another sample is added. Half a pixel is below what
#: any resampler can express, so a tighter tolerance buys nothing visible.
DFLT_TOLERANCE_PX = 0.5

#: Sample counts tried, in order. Each reuses the previous set's points, and the
#: ceiling is where the measured deviation is already sub-pixel at 4K.
SAMPLE_LADDER = (3, 5, 9, 17, 33, 65)

#: How many points the deviation is measured at. Dense enough that the worst
#: excursion of a smooth easing is not stepped over.
DEVIATION_PROBES = 401

#: Encoder default matching the pillow backend's, so the two produce comparable
#: files rather than differing on a flag nobody chose.
DFLT_PIX_FMT = "yuv420p"

#: `write_videofile` keywords this backend understands, mapped to ffmpeg flags.
#: Anything else raises rather than being silently dropped — a caller who gets a
#: kwarg ignored has no signal that the backends are not interchangeable.
WRITE_KWARG_FLAGS = {"bitrate": "-b:v", "preset": "-preset"}

#: Matched to `pillow_backend`'s own `setdefault` calls, so swapping backends
#: does not silently change the encode.
DFLT_WRITE_KWARGS = {"bitrate": "5000k", "preset": "medium"}

#: Accepted and ignored, with a reason. `logger` is moviepy's progress bar and
#: has no ffmpeg meaning; the pillow backend defaults it, so a caller forwarding
#: its own defaults must not trip the unknown-kwarg refusal.
WRITE_KWARGS_IGNORED = ("logger",)


class FfmpegBackendError(RuntimeError):
    """This path or these options cannot be rendered by the ffmpeg backend."""


def default_ffmpeg_exe() -> str:
    """The ffmpeg binary this backend runs.

    Defaults to the one `imageio-ffmpeg` bundles, which every burns install
    already has via moviepy — so the backend needs no new system requirement.
    Falls back to a system `ffmpeg` on PATH.

    **That bundled binary is a ``--enable-gpl`` build.** For most callers that is
    irrelevant; for one shipping a commercial product it is exactly the question
    `looks` exists to answer, which is why :func:`ffmpeg_backend` takes an
    ``ffmpeg_exe`` argument rather than hard-coding this.
    """
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - depends on the install
        import shutil

        found = shutil.which("ffmpeg")
        if found is None:
            raise FfmpegBackendError(
                "no ffmpeg found. It normally arrives with moviepy via "
                "imageio-ffmpeg; install that, put an ffmpeg on PATH, or pass "
                "ffmpeg_exe= explicitly."
            ) from None
        return found


def _window_at(
    path: BurnsPath, t: float, img_w: int, img_h: int, out_w: int, out_h: int
):
    """The window burns actually shows at ``t``, normalised for `looks`.

    Read out of :func:`sample_box`, so it includes the cover-crop to the output
    aspect and agrees with the pillow backend by construction.
    """
    from looks.motion import Window

    x0, y0, x1, y1 = sample_box(path, t, img_w, img_h, out_w, out_h)
    box_w, box_h = x1 - x0, y1 - y0

    # `sample_box` has already cover-cropped to the output aspect, but it
    # returns an INTEGER box for array slicing — so the aspect it hands back
    # carries up to a pixel of quantisation, and no two frames agree on it
    # exactly. Measured on a 1.35x push-in over 640x480 into 16:9: ratios
    # spread across 1.3310-1.3358 where every one of them means 1.3333.
    #
    # `zoompan` can only show ONE shape, so it needs the aspect that was meant,
    # not the aspect that survived rounding. Restore it about the box's centre,
    # holding the area, so the correction is split between the two axes and is
    # sub-pixel on both. Doing this here rather than loosening looks' tolerance
    # is deliberate: a loose tolerance there would silently accept a genuinely
    # anisotropic path and render a shape nobody asked for.
    target = out_w / out_h
    exact_h = (box_w * box_h / target) ** 0.5
    exact_w = target * exact_h
    x = min(max((x0 + x1) / 2 - exact_w / 2, 0.0), max(img_w - exact_w, 0.0))
    y = min(max((y0 + y1) / 2 - exact_h / 2, 0.0), max(img_h - exact_h, 0.0))
    return Window(x / img_w, y / img_h, exact_w / img_w, exact_h / img_h)


def _max_deviation(
    path: BurnsPath, n: int, img_w: int, img_h: int, out_w: int, out_h: int
) -> float:
    """How far an ``n``-sample linear rebuild strays from the eased path.

    In normalised units, over both axes and both extents. This is what makes the
    sampling density a measurement rather than a guess — under-sampling silently
    replaces the author's easing with a linear approximation, which still renders
    and is simply the wrong motion.
    """
    # Measured on `path.evaluate` — the SMOOTH authored path — and deliberately
    # not on `_window_at`. The latter goes through `sample_box`, whose integer
    # quantisation is up to a pixel of noise that no amount of sampling can
    # track: measuring there conflates "the easing needs more keyframes" with
    # "the box rounded", and the adaptive search then never converges and
    # always returns the ladder's top.
    knots = [i / (n - 1) for i in range(n)]
    samples = [path.evaluate(t) for t in knots]
    worst = 0.0
    for probe in range(DEVIATION_PROBES):
        t = probe / (DEVIATION_PROBES - 1)
        true = path.evaluate(t)
        # locate the bracketing knots and interpolate linearly between them
        index = min(int(t * (n - 1)), n - 2)
        span = knots[index + 1] - knots[index]
        frac = 0.0 if span <= 0 else (t - knots[index]) / span
        a, b = samples[index], samples[index + 1]
        for name in ("x", "y", "w", "h"):
            rebuilt = getattr(a, name) + frac * (getattr(b, name) - getattr(a, name))
            worst = max(worst, abs(rebuilt - getattr(true, name)))
    return worst


def sample_count(
    path: BurnsPath,
    img_w: int,
    img_h: int,
    out_w: int,
    out_h: int,
    *,
    tolerance_px: float = DFLT_TOLERANCE_PX,
) -> int:
    """How many keyframes this path needs to survive linear interpolation.

    Climbs :data:`SAMPLE_LADDER` until the worst deviation is under
    ``tolerance_px`` source pixels, and returns the ladder's top if none is.
    """
    scale = max(img_w, img_h)
    for n in SAMPLE_LADDER:
        if _max_deviation(path, n, img_w, img_h, out_w, out_h) * scale <= tolerance_px:
            return n
    return SAMPLE_LADDER[-1]


def keyframes_for(
    path: BurnsPath,
    *,
    duration: float,
    img_w: int,
    img_h: int,
    out_w: int,
    out_h: int,
    samples: Optional[int] = None,
):
    """Sample a `BurnsPath` into the keyframes `looks` compiles.

    Two clocks meet here and they are not the same one: burns' path is
    parameterised on a **normalised** ``t in [0, 1]`` and `looks` keyframes carry
    a time in **seconds**. Getting that wrong produces a path that runs in the
    first second of a ten-second clip and then holds, which renders fine.
    """
    from looks.motion import Keyframe

    n = (
        sample_count(path, img_w, img_h, out_w, out_h)
        if samples is None
        else int(samples)
    )
    if n < 2:
        raise FfmpegBackendError(f"a path needs at least 2 samples, got {n}")
    return [
        Keyframe(
            duration * (i / (n - 1)),
            _window_at(path, i / (n - 1), img_w, img_h, out_w, out_h),
        )
        for i in range(n)
    ]


def _encode_args(codec: str, write_kwargs: dict) -> list[str]:
    unknown = sorted(
        set(write_kwargs) - set(WRITE_KWARG_FLAGS) - set(WRITE_KWARGS_IGNORED)
    )
    if unknown:
        raise FfmpegBackendError(
            f"the ffmpeg backend does not understand {unknown}. It is not a "
            "drop-in swap for the pillow backend: those keywords are moviepy's "
            f"`write_videofile` arguments. Understood here: "
            f"{sorted(WRITE_KWARG_FLAGS)}; accepted and ignored: "
            f"{list(WRITE_KWARGS_IGNORED)}."
        )
    # The same defaults the pillow backend sets, for the same reason: without
    # them `backend="ffmpeg"` silently re-encodes at a different rate, and the
    # measured effect is not subtle — 270 KB against 1084 KB for one 2 s clip,
    # which reads as a quality regression rather than as an unset flag.
    write_kwargs = {**DFLT_WRITE_KWARGS, **write_kwargs}
    args = ["-c:v", codec, "-pix_fmt", DFLT_PIX_FMT]
    for key, flag in WRITE_KWARG_FLAGS.items():
        if write_kwargs.get(key) is not None:
            args += [flag, str(write_kwargs[key])]
    return args


def ffmpeg_backend(
    img_np: np.ndarray,
    img_w: int,
    img_h: int,
    path: BurnsPath,
    *,
    duration: float,
    fps: int,
    output: Path,
    out_w: int,
    out_h: int,
    codec: str,
    audio_codec: str,
    samples: Optional[int] = None,
    ffmpeg_exe: Optional[str] = None,
    **write_kwargs,
) -> Path:
    """Render one image + path with a single ffmpeg process.

    One decode, one filter graph, one encode — against the pillow backend's
    per-frame Python resampling.

    Args:
        samples: How many keyframes to sample the path into. ``None`` (default)
            measures it: enough that the linear rebuild stays within half a
            source pixel of the eased path.
        ffmpeg_exe: Which binary. Defaults to :func:`default_ffmpeg_exe`, the one
            `imageio-ffmpeg` bundles — note that it is a GPL-configured build.
        audio_codec: **Accepted and ignored.** A still image has no audio track,
            so nothing is ever encoded; the pillow backend is in the same
            position, where the argument reaches `write_videofile` with nothing
            to encode. Said out loud rather than left for a reader to assume
            audio works.

    Raises:
        FfmpegBackendError: If the path cannot be compiled to a filter fragment,
            or an unrecognised `write_videofile` keyword is passed. Both name
            ``backend="pillow"`` as the way through, because it is.
    """
    from looks.geometry import Size
    from looks.motion import MotionError, compile_motion

    frames = keyframes_for(
        path,
        duration=duration,
        img_w=img_w,
        img_h=img_h,
        out_w=out_w,
        out_h=out_h,
        samples=samples,
    )
    try:
        fragment = compile_motion(frames, output=Size(out_w, out_h), fps=fps)
    except MotionError as e:
        raise FfmpegBackendError(
            f"this path cannot be compiled to an ffmpeg filter: {e} "
            'Render it with backend="pillow", which rasterises every frame in '
            "Python and has no such constraint."
        ) from None

    binary = default_ffmpeg_exe() if ffmpeg_exe is None else ffmpeg_exe
    output = Path(output)
    with tempfile.TemporaryDirectory(prefix="burns-ffmpeg-") as tmp:
        # The backend is handed a decoded array, never the source path, so the
        # image has to be re-materialised before ffmpeg can open it. PNG because
        # it is lossless: re-encoding the source through a lossy format would
        # put artefacts under the whole render.
        still = Path(tmp) / "source.png"
        PIL_Image.fromarray(img_np).save(still)
        argv = [
            binary, "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-framerate", str(fps), "-i", str(still),
            "-t", f"{duration:.6f}",
            "-vf", fragment,
            *_encode_args(codec, write_kwargs),
            str(output),
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True)
        except OSError as e:
            raise FfmpegBackendError(
                f"could not run {binary!r}: {e}. Pass ffmpeg_exe= a binary that "
                "exists, or leave it unset to use the one moviepy brings."
            ) from None
    if proc.returncode != 0:
        raise FfmpegBackendError(
            f"ffmpeg failed (exit {proc.returncode}) rendering {output.name}:\n"
            f"{proc.stderr.strip()[-1200:]}\n"
            f"filter: {fragment}"
        )
    return output
