---
name: burns
description: Use when turning a still image (or a sequence of stills) into a pan/zoom video — the "Ken Burns effect". Triggers on "ken burns", "pan and zoom a photo", "animate a still image", "make a slideshow with motion", "zoom into an image as video", "photo to video", or any use of ken_burns_video / ken_burns_film / ken_burns_path. Use BEFORE hand-rolling moviepy crop/resize-per-frame logic.
---

# burns — Ken Burns pan/zoom video effects

`burns` turns still images into cinematic pan/zoom films. Three functions, all
importable from the top level: `from burns import ken_burns_video, ken_burns_film, ken_burns_path`.

Requires `ffmpeg` on PATH (moviepy encodes with it). Deps: numpy, moviepy, pillow.

## The rectangle spec (everything is `(cx, cy, s)`)

A *rect* is `(cx, cy, s)`: pan center `(cx, cy)` in `[0, 1]` image units, zoom
scale `s` (`1.0` = full frame, `> 1.0` = zoomed in). Flexible shorthand:
a bare number is a centered zoom (`1.3` → `(0.5, 0.5, 1.3)`); a pair is a pan
center at full scale (`(0.3, 0.7)` → `(0.3, 0.7, 1.0)`); a triple is the full spec.

**The crop box is clamped to the image**, so you cannot zoom out past the
original. Express a zoom-out as a start `s > 1` panning to an end `s = 1`.

## `ken_burns_video(image, *, phases=..., fps=30, saveas=None, ...)`

Render ONE image into a multi-phase pan/zoom mp4. `image` is a path, a
`PIL.Image`, or a numpy array. `phases` is a list of `(start_rect, end_rect,
duration_s)`; the camera lerps from start to end over each phase, phases play
back-to-back, total length = sum of durations. Default = a 2s push-in. Returns
the output `Path` (auto-named `{stem}_kenburns.mp4` next to the source when
`saveas` is None).

```python
ken_burns_video("photo.jpg")  # 2s push-in → photo_kenburns.mp4
ken_burns_video("photo.jpg", phases=[((0.5,0.5,1.0), (0.65,0.4,1.2), 5.0)], saveas="out.mp4")
```

## `ken_burns_path(index, duration_s, *, style="push", zoom=1.10, pan=0.03, ease=False)`

Generate a cohesive, **deterministic** path (the `phases` the renderers consume)
from intent, so you don't hand-author rectangles. Pure function — same args →
same path. Feed it straight into `ken_burns_video(..., phases=ken_burns_path(...))`.

- `index` (1-based): seeds the focal direction and the push-in/pull-out
  alternation — **odd indices push in, even indices pull out**. Pass the image's
  position in the sequence.
- `style="push"` (default): zoom-led move toward an off-center focal point.
- `style="drift"`: pure horizontal pan, alternating direction per index.
  (Drift derives its own zoom from `pan` so the slide is visible — don't set
  `zoom` for drift.)
- `ease=True`: split into a slow-fast-slow 3-phase velocity curve (same
  direction + magnitude, smoother feel).

## `ken_burns_film(panels, *, saveas, fps=30, audio_path=None, ...)`

Render a sequence of `(image, phases)` panels as ONE continuous film — a single
encode pass, so no concatenation seams and no per-image freeze frames at cuts.
`saveas` is required. Optional `audio_path` muxes in a pre-built track (you
assemble/pad it to the film duration yourself — the renderer stays pure visual).

```python
panels = [("a.jpg", ken_burns_path(1, 4.0)),
          ("b.jpg", ken_burns_path(2, 4.0)),
          ("c.jpg", ken_burns_path(3, 4.0))]
ken_burns_film(panels, saveas="film.mp4", fps=30, audio_path="narration.mp3")
```

## Gotchas

- **Don't build a film by rendering per-image clips and concatenating** — that
  reintroduces the seam/freeze artefacts `ken_burns_film` exists to avoid. Use
  one `ken_burns_film` call.
- A phase's `end_rect` need not equal the next phase's `start_rect`; a mismatch
  is an instantaneous cut. For continuous motion, chain them.
- fps below ~24 makes the motion look choppy; default 30 is smooth.
- Even pixel dimensions are required by libx264 — synthetic test images should
  use even width/height.
