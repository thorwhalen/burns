# burns

Ken Burns pan/zoom video effects: turn a still image — or a sequence of stills —
into a cinematic pan/zoom film.

The [Ken Burns effect](https://en.wikipedia.org/wiki/Ken_Burns_effect) animates a
static photograph by slowly panning across it and zooming in or out, giving still
images a sense of motion. `burns` does exactly that, with a tiny API and no
configuration required — and a clean, render-agnostic motion spec underneath so
the same path can drive Python today and other renderers later.

```bash
pip install burns
```

`burns` needs `ffmpeg` available on your system (moviepy uses it to encode video).
On macOS: `brew install ffmpeg`. On Debian/Ubuntu: `sudo apt-get install ffmpeg`.

## Demo

Starting from a single still image:

<img src="https://raw.githubusercontent.com/thorwhalen/burns/main/assets/demo_landscape.jpg" width="640" alt="input still image">

…two lines of code turn it into two different Ken Burns films — a slow zoom-in
("push") and a lateral pan ("drift"):

```python
from burns import ken_burns_video, ken_burns_path

ken_burns_video("demo_landscape.jpg", ken_burns_path(1, zoom=1.4, pan=0.06), duration=4.0)
ken_burns_video("demo_landscape.jpg", ken_burns_path(2, style="drift", pan=0.14), duration=4.0)
```

| `style="push"` — eased zoom-in | `style="drift"` — lateral pan |
| :---: | :---: |
| ![push](https://raw.githubusercontent.com/thorwhalen/burns/main/assets/demo_push.gif) | ![drift](https://raw.githubusercontent.com/thorwhalen/burns/main/assets/demo_drift.gif) |

The full script that generated this still and these GIFs is
[`misc/generate_demo.py`](misc/generate_demo.py).

## Quickstart

A standard 2-second push-in, written next to the source image:

```python
from burns import ken_burns_video

ken_burns_video("photo.jpg")          # → photo_kenburns.mp4
```

That's it. The result is an mp4 that slowly zooms into the center of `photo.jpg`.

## The motion spec: `BurnsPath`

The camera motion is a `BurnsPath` — a pure, time-parameterized spec. Its core is
`evaluate(t) -> Rect` for `t ∈ [0, 1]`: where the viewport is at each instant,
independent of any renderer, frame rate, or duration.

A *rect* is `Rect(x, y, w, h)` — a normalized window over the image, top-left
origin, every component in `[0, 1]`. `Rect(0, 0, 1, 1)` is the whole image; a
smaller `w`/`h` is zoomed in. The common cases have one-liners:

```python
from burns import ken_burns_video, BurnsPath, Rect

# The 90% case: push from the full image toward a point at a given zoom.
ken_burns_video("photo.jpg", BurnsPath.push_in(1.3, to=(0.65, 0.40)), duration=5.0)

# The canonical two-rectangle (Start → End) case, full control:
path = BurnsPath.from_start_end(
    Rect(0, 0, 1, 1),                       # start: whole image
    Rect.from_center_zoom(0.65, 0.40, 1.2), # end: zoomed toward upper-right
    easing="ease-in-out",                   # the cinematic default
)
ken_burns_video("photo.jpg", path, duration=5.0, saveas="out.mp4")

# N keyframes for a multi-beat move (a hold = two equal keyframes):
path = BurnsPath(keyframes=[
    (0.0, Rect(0, 0, 1, 1)),
    (0.5, Rect.from_center_zoom(0.65, 0.40, 1.2)),
    (1.0, Rect.from_center_zoom(0.35, 0.60, 1.3)),
])
```

**Easing** is a CSS timing function (`"linear"`, `"ease-in-out"` (default),
`"cubic-bezier(...)"`, or any callable) and is composed *over* the geometry —
motion shape and motion speed stay orthogonal.

**Output aspect ratio is independent of the source image.** Set `output_aspect`
to make a widescreen clip from a portrait photo (the renderer cover-crops, never
stretches):

```python
ken_burns_video("portrait.jpg", BurnsPath.push_in(1.4, output_aspect=16/9), duration=6.0)
```

## Let `burns` design the motion for you

Hand-authoring rectangles for every image gets tedious. `ken_burns_path` generates
a cohesive, **deterministic, non-repetitive** path from a little intent — pass the
image's position (`index`) and it picks the framing. Duration is supplied at render
time, so a path is reusable across clip lengths:

```python
from burns import ken_burns_video, ken_burns_path

# index seeds the focal direction; odd indices push in, even pull out.
ken_burns_video("photo.jpg", ken_burns_path(1), duration=5.0)

# styles: "push" (zoom-led, the default) or "drift" (pure horizontal pan)
ken_burns_video("photo.jpg", ken_burns_path(2, style="drift"), duration=5.0)

# easing controls the velocity curve (default "ease-in-out"); "linear" is constant
ken_burns_video("photo.jpg", ken_burns_path(1, easing="linear"), duration=6.0)
```

## Multi-image films

`ken_burns_film` renders a sequence of `(image, path, duration_s)` panels as **one
continuous film** — a single encode pass, so there are no concatenation seams and
no per-image freeze frames at the cuts. Pass an optional pre-built audio track to
mux it in.

```python
from burns import ken_burns_film, ken_burns_path

panels = [
    ("a.jpg", ken_burns_path(1), 4.0),
    ("b.jpg", ken_burns_path(2), 4.0),
    ("c.jpg", ken_burns_path(3), 4.0),
]
ken_burns_film(panels, saveas="film.mp4", fps=30, audio_path="narration.mp3")
```

## Interop: one spec, many renderers

A `BurnsPath` serializes to a small versioned JSON document via `path.to_dict()`
(and back via `BurnsPath.from_dict(...)`). That is the wire format: the same spec
can be evaluated by this Python renderer, or by a JS/TS renderer / CSS preview
that mirrors the trivial `evaluate(t)` math — no renderer owns the motion.

## API

| Object | What it does |
|--------|--------------|
| `Rect(x, y, w, h)` | A normalized viewport over the image. `.from_center_zoom`, `.clamped`, `.to_pixels`, `.zoom`, `.center`. |
| `BurnsPath` | The motion spec. `.evaluate(t) -> Rect`, `.from_start_end`, `.push_in`, `.reversed`, `.to_dict` / `.from_dict`. |
| `ken_burns_path(index, *, style="push", zoom=1.10, pan=0.03, easing="ease-in-out", output_aspect=None)` | Deterministic per-index `BurnsPath` for a sequence. |
| `ken_burns_video(image, path=DEFAULT_BURNS_PATH, *, duration=2.0, fps=30, saveas=None, output_size=None, backend="pillow", ...)` | Render one image into a pan/zoom mp4. |
| `ken_burns_film(panels, *, saveas, fps=30, audio_path=None, ...)` | Render `(image, path, duration_s)` panels as one continuous film. |
