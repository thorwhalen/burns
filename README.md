# burns

Ken Burns pan/zoom video effects: turn a still image — or a sequence of stills —
into a cinematic pan/zoom film.

The [Ken Burns effect](https://en.wikipedia.org/wiki/Ken_Burns_effect) animates a
static photograph by slowly panning across it and zooming in or out, giving still
images a sense of motion. `burns` does exactly that, with a tiny API and no
configuration required — and a clean, render-agnostic motion spec underneath so
the same path drives the Python renderer here and the TypeScript one in `ts/`.

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

## Content-aware motion

`ken_burns_path` frames by index, not by what is in the picture — so it will
happily drift across empty sky. `content_aware_path_for` looks at the image
first and builds a path that keeps the subject framed:

```python
from burns import ken_burns_video, content_aware_path_for

ken_burns_video("photo.jpg", content_aware_path_for("photo.jpg", index=1), duration=5.0)
```

No extra install: the subject estimate is a gradient-magnitude ("busyness")
heuristic over numpy + Pillow, which `burns` already requires. Flat regions —
sky, walls, water — have low gradient and fall away, so the box tracks the
detailed part of the frame.

**Faces, when you have a detector.** `burns` ships no face model. Detection is
*injected*, so you choose the dependency: pass boxes you already have, or a
`faces_detector` callable that returns normalized `(x, y, w, h)` boxes. The
detector always receives a `PIL.Image` — whatever you passed as `image` is
opened or converted first.

```python
# boxes you already have (faces win over the saliency estimate)
path = content_aware_path_for("group.jpg", faces=[(0.31, 0.22, 0.09, 0.12)])

# or a detector — anything callable: OpenCV, ONNX, a vision model, a lookup
path = content_aware_path_for("group.jpg", faces_detector=my_detector, index=2)
```

With neither `faces` nor `faces_detector` you simply get saliency-only,
sky-avoiding motion — no error, no warning, just a less specific keep-region.

**The geometry on its own.** `content_aware_path` is the pixel-free core: give
it the image size and a keep-region and it returns the `BurnsPath`. Reach for it
when the boxes come from somewhere else — a UI, a database, an upstream vision
pipeline.

```python
from burns import content_aware_path

path = content_aware_path(
    1920, 1080, subject=(0.60, 0.55, 0.20, 0.25), index=1, output_aspect=16 / 9
)
```

Start and end windows are both centered on the keep-region (sliding inside the
image edges when they'd overhang) and sized to the output aspect, so the
renderer's cover-crop is a no-op — what you frame is what shows.

The requested `zoom` is **capped** so the padded keep-region normally stays
inside the frame — but a `min_zoom + 0.02` floor wins over that cap, so a
keep-region that fills the picture is cropped slightly rather than yielding no
motion at all. If a subject that fills the frame must stay whole, tighten the
keep-region (a smaller `keep_pad`, or explicit boxes); raising `zoom` cannot do
it. `index` keeps the same rhythm as `ken_burns_path` (odd pushes in, even pulls
out); `mode="in"` / `mode="out"` overrides it.

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
(and back via `BurnsPath.from_dict(...)`). That is the wire format, and it is
already shared across two languages: [`kenburnz`](https://www.npmjs.com/package/kenburnz)
is a TypeScript port of the same `evaluate(t)` math, living in this repo's
[`ts/`](ts) directory and published to npm. It is pinned to the Python side by a
shared golden-vector fixture, and adds browser-only pieces: a zero-cost CSS
transform preview, a WebCodecs `.webm` exporter, and `mountPathEntry` — a
headless component for *authoring* a path in a UI. It is young (0.0.1), and its
browser-only paths are verified locally rather than in CI. No renderer owns the
motion.

## API

| Object | What it does |
|--------|--------------|
| `Rect(x, y, w, h)` | A normalized viewport over the image. `.from_center_zoom`, `.clamped`, `.to_pixels`, `.zoom`, `.center`. |
| `BurnsPath` | The motion spec. `.evaluate(t) -> Rect`, `.from_start_end`, `.push_in`, `.reversed`, `.to_dict` / `.from_dict`. |
| `ken_burns_path(index, *, style="push", zoom=1.10, pan=0.03, easing="ease-in-out", output_aspect=None)` | Deterministic per-index `BurnsPath` for a sequence. |
| `salient_box(image, *, downscale=320, threshold_pct=72.0, trim_pct=4.0, pad=0.05, min_size=0.35)` | Estimate the busy/detailed region of an image as a normalized `(x, y, w, h)` box. |
| `content_aware_path(img_w, img_h, *, subject=None, faces=(), index=0, output_aspect=None, zoom=1.3, min_zoom=1.05, keep_pad=0.18, mode="auto", easing="ease-in-out")` | Pure geometry: a `BurnsPath` that keeps a keep-region framed. |
| `content_aware_path_for(image, *, faces=(), faces_detector=None, index=0, output_aspect=None, **kwargs)` | The same, deriving subject (`salient_box`) and faces from the image itself. |
| `ken_burns_video(image, path=DEFAULT_BURNS_PATH, *, duration=2.0, fps=30, saveas=None, output_size=None, backend="pillow", ...)` | Render one image into a pan/zoom mp4. |
| `ken_burns_film(panels, *, saveas, fps=30, audio_path=None, ...)` | Render `(image, path, duration_s)` panels as one continuous film. |
