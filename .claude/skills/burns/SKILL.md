---
name: burns
description: Use when turning a still image (or a sequence of stills) into a pan/zoom video — the "Ken Burns effect". Triggers on "ken burns", "pan and zoom a photo", "animate a still image", "make a slideshow with motion", "zoom into an image as video", "photo to video", or any use of ken_burns_video / ken_burns_film / ken_burns_path / BurnsPath. Use BEFORE hand-rolling moviepy crop/resize-per-frame logic.
---

# burns — Ken Burns pan/zoom video effects

`burns` turns still images into cinematic pan/zoom films, driven by one
**render-agnostic motion spec** (so the same path can feed the Python renderer
today and a JS/TS renderer later). Top-level imports:
`from burns import BurnsPath, Rect, ken_burns_path, ken_burns_video, ken_burns_film`.

Requires `ffmpeg` on PATH (moviepy encodes with it). Deps: numpy, moviepy, pillow.

## The viewport: `Rect(x, y, w, h)`

A *rect* is a normalized window over the image: `(x, y, w, h)` all in `[0, 1]`,
**top-left origin, y-down** (the videopython / CSS / FFmpeg convention).
`Rect(0, 0, 1, 1)` is the whole image. Zoom is **window-fraction** — a smaller
`w`/`h` is more zoomed in; `Rect.zoom` is the derived `1/max(w,h)` magnification.

- `Rect.from_center_zoom(cx, cy, zoom, *, aspect=1.0)` — build from a pan center
  + zoom (the bridge from the old center+scale model). Auto-clamped inside the image.
- `Rect.clamped()` — slide a window inside the image **without resizing** it
  ("ride the wall" — avoids the breathing/stretch artefact).
- `Rect.to_pixels(img_w, img_h)` — integer crop box `(x0, y0, x1, y1)`.

## The motion spec: `BurnsPath`

Pure, time-parameterized, frame-count-free. **`path.evaluate(t) -> Rect`** for
`t ∈ [0, 1]` is the single primitive everything else builds on.

- `BurnsPath.from_start_end(start, end, *, easing="ease-in-out", output_aspect=None)`
  — the canonical two-rectangle (Start → End) case.
- `BurnsPath.push_in(zoom=1.3, *, to=(0.5,0.5), easing=..., output_aspect=None)`
  — the 90%-case one-liner.
- `BurnsPath(keyframes=((t, rect), ...), easing=..., output_aspect=...)` — N
  keyframes (a hold = two keyframes with equal rects).
- `path.reversed()` — swap Start/End (the NLE "Swap" button).
- `path.to_dict()` / `BurnsPath.from_dict(d)` — versioned JSON wire format (the
  cross-language SSOT). Callable easings aren't serializable — use CSS strings.

**Easing is composed over geometry**: `evaluate(t) == geometry(easing(t))`.
Easing is a CSS timing function — `"linear"`, `"ease"`, `"ease-in"`,
`"ease-out"`, `"ease-in-out"` (default — the cinematic norm), a
`"cubic-bezier(x1,y1,x2,y2)"` string, a 4-tuple, or any callable `[0,1]→[0,1]`.

**`output_aspect`** is the AR the render should fill, *independent of the source
image* — set it to `16/9` to make a widescreen clip from a portrait photo. When
it differs from the image AR the renderer center-cover-crops (no stretch). `None`
= match the image (the legacy behavior).

## `ken_burns_path(index, *, style="push", zoom=1.10, pan=0.03, easing="ease-in-out", output_aspect=None)`

Build a cohesive, **deterministic** `BurnsPath` for the `index`-th image of a
sequence — no hand-authored rectangles. Same args → same path. **Duration is
NOT part of the path** (it's a render-time arg).

- `index` (1-based): **odd indices push in, even pull out**; focal direction
  rotates per index → sequence rhythm without changing direction within a shot.
- `style="push"` (default): zoom-led toward an off-center focal point.
- `style="drift"`: pure horizontal pan, alternating direction per index (`zoom`
  ignored — drift derives its own from `pan`).

## `ken_burns_video(image, path=DEFAULT_BURNS_PATH, *, duration=2.0, fps=30, saveas=None, output_size=None, backend="pillow", ...)`

Render ONE image → mp4. `image` is a path / `PIL.Image` / numpy array. `path` is
a `BurnsPath`; `duration` is seconds. Returns the output `Path` (auto-named
`{stem}_kenburns.mp4` next to the source when `saveas` is None).

```python
ken_burns_video("photo.jpg")                                   # 2s default push-in
ken_burns_video("photo.jpg", ken_burns_path(1), duration=5.0, saveas="out.mp4")
ken_burns_video("portrait.jpg", BurnsPath.push_in(1.4, output_aspect=16/9), duration=6)
```

Backends are pluggable via the `RenderBackend` registry (`register_backend`);
`"pillow"` (lazy moviepy + per-frame Pillow, jitter-free) is the only one today.

## `ken_burns_film(panels, *, saveas, fps=30, audio_path=None, ...)`

Render a sequence of `(image, path, duration_s)` **triples** as ONE continuous
film — a single encode pass, so no concatenation seams and no per-image freeze
frames at cuts. `saveas` required. Optional `audio_path` muxes in a pre-built
track (assemble/pad it to the film duration yourself — renderer stays pure visual).

```python
panels = [("a.jpg", ken_burns_path(1), 4.0),
          ("b.jpg", ken_burns_path(2), 4.0),
          ("c.jpg", ken_burns_path(3), 4.0)]
ken_burns_film(panels, saveas="film.mp4", fps=30, audio_path="narration.mp3")
```

## Gotchas

- **Build films with one `ken_burns_film` call**, not by rendering per-image
  clips and concatenating — concat reintroduces the seam/freeze artefacts.
- `duration` lives on the renderer, not the path — `ken_burns_path` and
  `BurnsPath` are duration-free (the clock is normalized `[0,1]`).
- Default easing is `"ease-in-out"`, NOT linear — pass `"linear"` for constant velocity.
- Even pixel dimensions are required by libx264; the renderer snaps output dims
  to even automatically, but synthetic test images should use even width/height.
- fps below ~24 looks choppy; default 30 is smooth.
- A serializable path needs a CSS easing (string/tuple), not a Python callable.
