"""The named camera moves, and the one resolver that expands one into a path.

A :class:`~burns.path.BurnsPath` is *resolved geometry*: rectangles measured
against one picture's pixels. That makes it the wrong thing to store when the
picture can change. What an editor wants to keep is the **authored intent** —
"push in on this, gently" — and have the rectangles computed against whatever
image is in the slot at render time. Replace the still and the move re-frames;
keep the still and the move is exactly what it was.

So this module is the vocabulary (:data:`MOVES`) plus the one function that
turns an intent into geometry (:func:`resolve_move`).

**One code path, two front doors.** ``resolve_move`` takes a *name* or an
explicit ``BurnsPath`` (or its ``to_dict()`` payload), so a caller that stores
both a named move and an optional hand-corrected path override makes one call
and the choice between them is made here — once — rather than once per consumer.
This is ``an.ir.camera.camera_keys``' arrangement: one table, not two tables
reconciled by a test.

**``seed`` replaces the ordinal, and does one job.** The motion in a sequence
used to be derived from each panel's *position* — style by ``i % 2``, zoom by
``i % 4``, push-or-pull by the parity of ``i``. Reordering one panel therefore
changed the camera on every panel after it, and "keep this move, change this
picture" was unexpressible. ``resolve_move`` is a pure function of its
arguments and never of a position; a caller mints a ``seed`` once, stores it
beside the move, and the move survives every reorder.

The seed's *only* job is choosing which concrete move ``"auto"`` becomes
(:func:`choose_move`). It deliberately does **not** perturb a named move's zoom
or framing: a named move is a decision, and a decision a seed can still nudge
is not one. Variety across a sequence comes from ``"auto"`` and from the
pictures themselves — the content-aware framing differs per image already.

    >>> import numpy as np
    >>> img = np.zeros((600, 800, 3), dtype='uint8'); img[380:520, 120:300] = 210
    >>> path = resolve_move("push_in", image=img, aspect=16 / 9, seed=41)
    >>> path.evaluate(1.0).zoom >= path.evaluate(0.0).zoom
    True
    >>> resolve_move("hold", image=img, aspect=16 / 9).evaluate(0.0) == \\
    ...     resolve_move("hold", image=img, aspect=16 / 9).evaluate(1.0)
    True
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Union

from burns.content import (
    Box,
    DFLT_KEEP_PAD,
    as_pil,
    axis_maxima,
    content_aware_path,
    fit_zoom,
    keep_window,
    pad_box,
    salient_box,
)
from burns.easing import DFLT_EASING, EasingLike
from burns.path import BurnsPath
from burns.rect import Rect

__all__ = [
    "MOVES",
    "AUTO_WEIGHTS",
    "DFLT_ZOOM",
    "DRIFT_TRAVEL",
    "DRIFT_SPAN",
    "DRIFT_MIN_ROOM",
    "MoveError",
    "choose_move",
    "move_kind",
    "resolve_move",
]

#: Default end magnification. Enough that a slow push reads as movement on a
#: 1080p frame, little enough that a found still is not visibly softened by the
#: upscale. It is also above the zoom a drift needs to have room to travel, so
#: the default never trips :data:`DRIFT_MIN_ROOM`'s floor.
DFLT_ZOOM: float = 1.18

#: How much of the available travel a drift uses, as a fraction of the room the
#: window leaves inside the image. Less than ``1.0`` on purpose: a drift that
#: runs wall to wall starts and ends against an edge, which reads as the frame
#: hitting a stop rather than as a camera continuing past the cut.
DRIFT_TRAVEL: float = 0.5

#: A ceiling on that travel, as a fraction of the **window** rather than of the
#: image — how far the camera crosses its own frame.
#:
#: Without it a drift's speed is whatever room the picture happened to leave,
#: which is not the same on both axes: on a 4:3 still delivered at 16:9 there is
#: twice as much vertical room as horizontal, so ``drift_up`` travelled ~29 % of
#: the frame where ``drift_left`` travelled ~9 % — the same named gesture at
#: three times the speed, decided by the aspect of the picture. ``an``'s camera
#: hit the same asymmetry from the other direction and answered it the same way,
#: with one fraction of the frame per axis (``an.ir.camera.PAN_FRACTION``).
#:
#: A tenth is calibrated against what the room-limited horizontal case already
#: produces at :data:`DFLT_ZOOM`, and against ``ken_burns_path(style="drift")``'s
#: ~7 %: legible at 1080p over a normal panel, and not a whip.
DRIFT_SPAN: float = 0.10

#: The least travel room a drift will accept, in image units. When the
#: requested ``zoom`` leaves less, the zoom is *raised* until it does — the same
#: way ``content_aware_path``'s ``min_zoom`` floor wins over its framing cap.
#: A drift with no room is a hold, and silently returning one is the failure
#: this floor exists to prevent.
DRIFT_MIN_ROOM: float = 0.08

#: Slack when comparing a stored path's ``output_aspect`` against the render's.
_ASPECT_EPS: float = 1e-3


class MoveError(ValueError):
    """A move that cannot be resolved into a path.

    A plain :class:`ValueError` subclass, so a consumer that already catches
    ``ValueError`` around its authoring layer keeps working, and so nothing
    downstream needs to import :mod:`burns.moves` to handle it.
    """


# --------------------------------------------------------------------------
# The table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Frame:
    """Everything a move builder needs: the picture, the intent, the delivery."""

    img_w: int
    img_h: int
    keep: Box  # the UNPADDED keep-region; each builder pads as it needs
    zoom: float
    aspect: Union[float, None]
    easing: EasingLike

    @property
    def padded(self) -> Box:
        return pad_box(self.keep, DFLT_KEEP_PAD)

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.padded
        return (x + w / 2, y + h / 2)

    def capped_zoom(self) -> float:
        """``zoom``, capped so the padded keep-region still fits the window."""
        cap = fit_zoom(
            self.img_w, self.img_h, keep=self.padded, output_aspect=self.aspect
        )
        return max(1.0, min(self.zoom, cap * 0.98))


@dataclass(frozen=True)
class _MoveSpec:
    """One row of the vocabulary: how a name is grouped, and how it is built."""

    kind: str  # "zoom" | "drift" | "static" | "select"
    build: Union[Callable[[_Frame], BurnsPath], None]


def _zoom_move(mode: str) -> Callable[[_Frame], BurnsPath]:
    """A zoom-led move: two windows on the same centre, differing in zoom."""

    def build(f: _Frame) -> BurnsPath:
        return content_aware_path(
            f.img_w,
            f.img_h,
            subject=f.keep,
            output_aspect=f.aspect,
            zoom=f.zoom,
            keep_pad=DFLT_KEEP_PAD,
            mode=mode,
            easing=f.easing,
        )

    return build


def _static(f: _Frame) -> BurnsPath:
    """A hold: two keyframes with equal rects.

    Two rather than one because that is what the spec calls a hold, and because
    the TypeScript schema requires at least two keyframes — a one-keyframe path
    is valid Python and invalid on the wire, so nothing here emits one.

    ``zoom`` is honoured: a hold is a *static framing*, not necessarily the
    whole picture. Pass ``zoom=1.0`` for the untouched frame.
    """
    window = keep_window(
        f.img_w,
        f.img_h,
        center=f.center,
        zoom=f.capped_zoom(),
        output_aspect=f.aspect,
    )
    return BurnsPath(
        keyframes=((0.0, window), (1.0, window)),
        easing=f.easing,
        output_aspect=f.aspect,
    )


def _drift(axis: str, sign: float) -> Callable[[_Frame], BurnsPath]:
    """A pan-led move: one window translated along ``axis``.

    **The name is the direction the CAMERA travels**, which is the direction the
    *content* appears to travel the other way — ``drift_right`` ends with the
    window further right, so the picture slides left across the frame. This is
    the convention ``ken_burns_path(style="drift")`` and ``an``'s ``pan_left``
    already use; the opposite reading is the one people reach for first, which
    is why it is written down rather than inferred.

    The travel is centred on the keep-region, so the subject is mid-frame at the
    midpoint of the move rather than arriving or departing; the cross axis stays
    locked to the keep-region, so a horizontal drift cannot slide off a face.
    """

    def build(f: _Frame) -> BurnsPath:
        zoom = max(f.capped_zoom(), _zoom_for_room(f, axis))
        window = keep_window(
            f.img_w, f.img_h, center=f.center, zoom=zoom, output_aspect=f.aspect
        )
        size = window.w if axis == "x" else window.h
        base = (f.center[0] if axis == "x" else f.center[1]) - size / 2
        lo, hi = 0.0, max(0.0, 1.0 - size)
        # Up to half the room, but never more than DRIFT_SPAN of the frame, so
        # a vertical and a horizontal drift read at the same speed on a picture
        # whose two axes leave very different amounts of room.
        half = min((hi - lo) * DRIFT_TRAVEL, size * DRIFT_SPAN) / 2.0
        # Slide the whole travel interval inside the image rather than clamping
        # each end: clamping ends independently collapses the travel to zero
        # whenever the keep-region sits near an edge, which is a silent hold.
        a, b = base - half, base + half
        if a < lo:
            a, b = lo, lo + 2 * half
        elif b > hi:
            a, b = hi - 2 * half, hi
        first, last = (a, b) if sign > 0 else (b, a)
        if axis == "x":
            start = Rect(first, window.y, window.w, window.h)
            end = Rect(last, window.y, window.w, window.h)
        else:
            start = Rect(window.x, first, window.w, window.h)
            end = Rect(window.x, last, window.w, window.h)
        return BurnsPath.from_start_end(
            start.clamped(), end.clamped(), easing=f.easing, output_aspect=f.aspect
        )

    return build


def _zoom_for_room(f: _Frame, axis: str) -> float:
    """The zoom at which the window leaves :data:`DRIFT_MIN_ROOM` to travel.

    The window is ``min(m / z, 1)`` of the image on ``axis``, so the room is
    ``1 - m / z`` and the zoom that buys ``r`` of room is ``m / (1 - r)``.
    """
    wmax, hmax = axis_maxima(f.img_w, f.img_h, f.aspect)
    m = wmax if axis == "x" else hmax
    return m / (1.0 - DRIFT_MIN_ROOM)


#: The vocabulary, as ONE table. ``MOVES`` and :func:`move_kind` are read off
#: it, so a UI that groups the directional moves separately from the static and
#: automatic ones does not maintain a second list that can disagree with this
#: one about what a valid move is.
#:
#: ``"auto"`` carries no builder: it is a *selector* over the others, resolved
#: to a concrete name by :func:`choose_move` before any geometry is built.
_MOVES: dict[str, _MoveSpec] = {
    "push_in": _MoveSpec("zoom", _zoom_move("in")),
    "pull_out": _MoveSpec("zoom", _zoom_move("out")),
    "drift_left": _MoveSpec("drift", _drift("x", -1.0)),
    "drift_right": _MoveSpec("drift", _drift("x", +1.0)),
    "drift_up": _MoveSpec("drift", _drift("y", -1.0)),
    "drift_down": _MoveSpec("drift", _drift("y", +1.0)),
    "hold": _MoveSpec("static", _static),
    "auto": _MoveSpec("select", None),
}

#: Every name a stored ``move`` field may hold — one vocabulary, because it is
#: one field. ``"hold"`` and ``"auto"`` sit beside the directional moves for
#: that reason: splitting them into separate constants would make a consumer
#: union two tuples to validate one field, which is the two-tables arrangement
#: this module exists to avoid. They differ in *kind*, not in membership, and
#: :func:`move_kind` is where that difference is read.
MOVES: tuple[str, ...] = tuple(_MOVES)

#: How often ``"auto"`` picks each move, as integer weights. Pushes and pulls
#: dominate because a commentary film is mostly faces and documents, where a
#: drift wanders off the thing being talked about; the drifts are there so a
#: long sequence does not read as one move repeated.
AUTO_WEIGHTS: dict[str, int] = {
    "push_in": 3,
    "pull_out": 3,
    "drift_left": 1,
    "drift_right": 1,
    "drift_up": 1,
    "drift_down": 1,
}

_AUTO_POOL: tuple[str, ...] = tuple(
    name for name, weight in AUTO_WEIGHTS.items() for _ in range(weight)
)


def move_kind(move: str) -> str:
    """How ``move`` is grouped: ``"zoom"``, ``"drift"``, ``"static"``, ``"select"``.

    For a UI that wants a compass of directions separately from the rest, read
    off the same table :func:`resolve_move` dispatches on.

    Examples:
        >>> move_kind("drift_left"), move_kind("hold"), move_kind("auto")
        ('drift', 'static', 'select')
        >>> sorted(m for m in MOVES if move_kind(m) == 'drift')
        ['drift_down', 'drift_left', 'drift_right', 'drift_up']
    """
    spec = _MOVES.get(move)
    if spec is None:
        raise MoveError(_unknown_move_message(move))
    return spec.kind


# --------------------------------------------------------------------------
# The seed
# --------------------------------------------------------------------------


def _mix(seed: int) -> int:
    """A stable 64-bit scramble of ``seed`` (splitmix64's finalizer).

    Python's ``hash()`` cannot be the basis of a *persisted* choice: it is
    salted for strings and unspecified for large integers, so the move a stored
    seed resolves to could differ between processes. This is arithmetic, so it
    does not.

    Examples:
        >>> _mix(0) == _mix(0)
        True
        >>> _mix(0) != _mix(1)
        True
    """
    mask = 0xFFFFFFFFFFFFFFFF
    x = (int(seed) + 0x9E3779B97F4A7C15) & mask
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & mask
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & mask
    return x ^ (x >> 31)


def choose_move(seed: int) -> str:
    """Which concrete move ``"auto"`` resolves to for ``seed``.

    Public because "auto" is a decision a person may want to *see* (a UI
    showing ``auto → drift_left``) and to *pin* (liking what auto chose and
    storing that name instead, so it survives a change to the weights).

    A pure function of ``seed`` alone — not of the image, and not of any
    position in a sequence. That is what makes a panel's move survive both a
    reorder and a swapped still.

    Examples:
        >>> choose_move(7) == choose_move(7)
        True
        >>> choose_move(7) in MOVES and choose_move(7) != 'auto'
        True
        >>> len({choose_move(s) for s in range(60)}) > 1   # not one move forever
        True
    """
    return _AUTO_POOL[_mix(seed) % len(_AUTO_POOL)]


# --------------------------------------------------------------------------
# The resolver
# --------------------------------------------------------------------------

#: What ``move`` accepts: a name, a built path, or a ``to_dict()`` payload.
MoveLike = Union[str, BurnsPath, Mapping[str, Any]]

#: What ``focus`` accepts: a :class:`~burns.rect.Rect`, a 4-tuple, or anything
#: with ``.x/.y/.w/.h``. burns does not define a competing rectangle type and
#: does not require consumers to import its own — a pydantic model with those
#: four fields is a focus box.
FocusLike = Any


def resolve_move(
    move: MoveLike,
    *,
    image: Any,
    aspect: Union[float, None],
    zoom: float = DFLT_ZOOM,
    focus: FocusLike = None,
    seed: int = 0,
    easing: EasingLike = DFLT_EASING,
) -> BurnsPath:
    """Resolve an authored camera intent against ``image`` into a path.

    Args:
        move: a name from :data:`MOVES`, or an explicit
            :class:`~burns.path.BurnsPath` / its ``to_dict()`` payload. The two
            are the two front doors on this one path: a stored panel that
            carries both a named move and a hand-corrected override passes the
            override here and the choice is made in one place.
        image: the still the move is framed against — a path, ``PIL.Image`` or
            ndarray. **Required, and read every time**: the framing depends on
            what is in the picture, so swapping the still must re-frame. Do not
            cache the returned path against the intent.
        aspect: the delivered ``width / height``. ``None`` means "match the
            image". Required rather than defaulted, because a cut has a
            delivery size and quietly framing for the image's aspect instead is
            a cover-crop nobody asked for.
        zoom: the end magnification, honoured — never jittered. It is capped so
            the keep-region stays framed (a subject filling the frame yields an
            almost static move; the fix is a tighter ``focus``, not a bigger
            ``zoom``), and raised for a drift that would otherwise have no room
            to travel.
        focus: an explicit keep-region overriding the saliency estimate. A
            :class:`~burns.rect.Rect`, a normalized ``(x, y, w, h)`` tuple, or
            any object with ``.x/.y/.w/.h``. When given,
            :func:`~burns.content.salient_box` is not called at all.
        seed: chooses which move ``"auto"`` becomes, and nothing else. Mint it
            once per panel and store it; never derive it from a position, which
            is the defect this parameter exists to remove.
        easing: CSS timing function or callable. A callable is fine here but
            cannot be serialized — see :meth:`BurnsPath.to_dict`.

    Returns:
        A :class:`~burns.path.BurnsPath`. Duration is not part of it; pass that
        to the renderer.

    Raises:
        MoveError: an unknown move name, a malformed ``focus``, or an explicit
            path whose ``output_aspect`` contradicts ``aspect``.

    Examples:
        >>> import numpy as np
        >>> img = np.zeros((600, 800, 3), dtype='uint8'); img[300:460, 500:700] = 230

        A named move is a decision, so the seed does not touch it:

        >>> resolve_move("push_in", image=img, aspect=16 / 9, seed=1) == \\
        ...     resolve_move("push_in", image=img, aspect=16 / 9, seed=999)
        True

        ``"auto"`` is where the seed does its one job:

        >>> a = resolve_move("auto", image=img, aspect=16 / 9, seed=3)
        >>> a == resolve_move("auto", image=img, aspect=16 / 9, seed=3)
        True

        A drift travels — and ``drift_right`` ends further right:

        >>> d = resolve_move("drift_right", image=img, aspect=16 / 9)
        >>> d.evaluate(1.0).x > d.evaluate(0.0).x
        True

        An explicit path is the other front door, returned as authored:

        >>> from burns import BurnsPath, Rect
        >>> hand = BurnsPath.from_start_end(
        ...     Rect(0, 0, 1, 1), Rect(0.1, 0.1, 0.6, 0.6), output_aspect=16 / 9
        ... )
        >>> resolve_move(hand.to_dict(), image=img, aspect=16 / 9) == hand
        True
    """
    if isinstance(move, BurnsPath):
        return _adopt(move, aspect)
    if isinstance(move, Mapping):
        return _adopt(BurnsPath.from_dict(dict(move)), aspect)
    if not isinstance(move, str):
        raise MoveError(_unknown_move_message(move))

    name = move.strip()
    spec = _MOVES.get(name)
    if spec is None:
        raise MoveError(_unknown_move_message(move))
    if spec.kind == "select":
        name = choose_move(seed)
        spec = _MOVES[name]

    img = as_pil(image)
    img_w, img_h = img.size
    keep = _focus_box(focus) if focus is not None else salient_box(img)
    return spec.build(
        _Frame(
            img_w=img_w,
            img_h=img_h,
            keep=keep,
            zoom=float(zoom),
            aspect=aspect,
            easing=easing,
        )
    )


def _adopt(path: BurnsPath, aspect: Union[float, None]) -> BurnsPath:
    """An explicit path, checked against the delivery aspect and returned as-is.

    A hand-corrected path is *resolved geometry*: its rectangles were drawn for
    one output shape, so re-stamping a different ``output_aspect`` onto them
    would cover-crop somebody's authored framing without saying so. That is the
    shape of defect this whole module exists to remove, so the mismatch raises
    instead.

    ``output_aspect=None`` is not a mismatch — it is a path that says "match the
    image", which is a deliberate authoring choice and is preserved.
    """
    stored = path.output_aspect
    if stored is None:
        return path
    if aspect is not None and abs(float(stored) - float(aspect)) <= _ASPECT_EPS:
        return path
    raise MoveError(
        f"this panel carries an explicit BurnsPath authored for "
        f"output_aspect={stored!r}, but the cut is being rendered at "
        f"aspect={aspect!r}. Its rectangles were drawn against the first shape, "
        "so honouring them at the second would silently crop the framing "
        "somebody chose by hand. Either render this cut at the aspect the path "
        "was authored for, drop the override so the named move re-frames, or "
        "author a second path for this delivery."
    )


def _focus_box(focus: FocusLike) -> Box:
    """Normalize ``focus`` to a ``(x, y, w, h)`` box, or say why it is not one."""
    if isinstance(focus, Rect):
        box = (focus.x, focus.y, focus.w, focus.h)
    elif all(hasattr(focus, a) for a in ("x", "y", "w", "h")):
        box = (focus.x, focus.y, focus.w, focus.h)
    else:
        try:
            box = tuple(float(v) for v in focus)
        except (TypeError, ValueError) as e:
            # ValueError as well as TypeError: a str is iterable, so `focus="nope"`
            # reached float() and escaped as a bare ValueError from a generator
            # expression, three frames from anything that named the argument.
            raise MoveError(
                f"focus must be a Rect, a normalized (x, y, w, h) sequence of 4 "
                f"components, or an object with .x/.y/.w/.h — got "
                f"{type(focus).__name__} {focus!r}"
            ) from e
        if len(box) != 4:
            raise MoveError(
                f"focus must have exactly 4 components (x, y, w, h), got {len(box)}"
            )
    x, y, w, h = (float(v) for v in box)
    if w <= 0 or h <= 0:
        raise MoveError(
            f"focus must have positive width and height, got {(x, y, w, h)}"
        )
    if not (-1e-6 <= x and -1e-6 <= y and x + w <= 1 + 1e-6 and y + h <= 1 + 1e-6):
        raise MoveError(
            f"focus must lie inside the image in normalized [0, 1] units with a "
            f"top-left origin, got {(x, y, w, h)}. A box in pixels is the usual "
            "cause — divide by the image's width and height."
        )
    return (x, y, w, h)


def _unknown_move_message(move: Any) -> str:
    return (
        f"unknown camera move {move!r}. The vocabulary is {list(MOVES)}. "
        "Pass an explicit BurnsPath (or its to_dict() payload) for a move the "
        "names do not cover."
    )
