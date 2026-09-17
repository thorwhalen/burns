# burns.render

Ken Burns **renderers** — turn still images into pan/zoom video.

Two entry points, both consuming a [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath) (the
render-agnostic motion spec) plus a render-time `duration`:

- [`ken_burns_video()`](#burns.render.ken_burns_video) — one image, one `BurnsPath`, one mp4. Dispatches
  to a pluggable backend (see [`burns.backends`](burns.backends.html.md#module-burns.backends)); the default `"pillow"`
  backend is a lazy moviepy clip, so the whole video is never held in memory.
- [`ken_burns_film()`](#burns.render.ken_burns_film) — a sequence of `(image, path, duration)` panels
  rendered as a **single** continuous film (no per-panel intermediate files, no
  concat seams, no per-panel tail freezes), with an optional pre-built audio
  track muxed in.

Use [`burns.ken_burns_path()`](burns.html.md#burns.ken_burns_path) (or `BurnsPath.push_in()`) to build paths
instead of hand-authoring keyframes.

### Functions

| [`ken_burns_film`](#burns.render.ken_burns_film)(panels, \*, saveas[, fps, ...])   | Render an N-panel Ken Burns film in a single pass.         |
|---------------------------------------------------------------------------------------------------|------------------------------------------------------------|
| [`ken_burns_video`](#burns.render.ken_burns_video)(image[, path, duration, ...])    | Render one image into a pan/zoom video from a `BurnsPath`. |

### burns.render.ken_burns_film(panels, , saveas, fps=30, audio_path=None, codec='libx264', audio_codec='aac', \*\*write_kwargs)

Render an N-panel Ken Burns film in a single pass.

Each panel is an `(image, path, duration_s)` triple
(`burns.PanelInput`): `image` is a path / `PIL.Image` /
`np.ndarray`, `path` a `BurnsPath`, `duration_s` how long the
panel occupies the film. Panels play back-to-back; the camera cuts at panel
boundaries but motion never pauses on a static frame within a panel.

A single `VideoClip` (rather than per-panel render + concatenate) avoids
the concat re-encode seam and per-panel tail freeze, and keeps frame
generation lazy via one global `make_frame(t)` closure.

* **Parameters:**
  * **panels** – iterable of `(image, path, duration_s)` triples.
  * **saveas** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – output mp4 path (required — a film has no single source image).
  * **fps** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – frame rate.
  * **audio_path** – optional pre-built track (already matching the film
    duration); muxed in when supplied. Per-panel audio assembly is the
    caller’s job — the renderer stays pure visual.
  * **codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **audio_codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **\*\*write_kwargs** – forwarded to `write_videofile`.
* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
* **Returns:**
  The written mp4 [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path).

### burns.render.ken_burns_video(image, path=BurnsPath(keyframes=((0.0, Rect(x=0.0, y=0.0, w=1.0, h=1.0)), (1.0, Rect(x=0.11538461538461542, y=0.11538461538461542, w=0.7692307692307692, h=0.7692307692307692))), easing='ease-in-out', interp='linear', output_aspect=None, version=1), , duration=2.0, fps=30, saveas=None, output_size=None, backend='pillow', codec='libx264', audio_codec='aac', \*\*write_kwargs)

Render one image into a pan/zoom video from a `BurnsPath`.

* **Parameters:**
  * **image** – path / `PIL.Image` / `np.ndarray`.
  * **path** ([`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)) – the motion spec. Default is a 2-second standard push-in.
  * **duration** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – clip length in seconds (the path’s clock is normalized, so
    duration is supplied here, not baked into the path).
  * **fps** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – frames per second.
  * **saveas** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – output path. Default: the source image’s name with
    `_kenburns` appended (auto-uniquified so an existing file is not
    overwritten). Required-ish when `image` has no source path —
    falls back to a temp file.
  * **output_size** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)] | [`None`](https://docs.python.org/3/builtins/constants.html#None)) – explicit `(width, height)` (even-snapped). If omitted and
    `path.output_aspect` is set, the size is derived from it; otherwise
    the source image’s size is used.
  * **backend** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – registered render backend name (default `"pillow"`).
  * **codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **audio_codec** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – forwarded to `write_videofile`.
  * **\*\*write_kwargs** – forwarded to `write_videofile`.
* **Return type:**
  [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)
* **Returns:**
  The output [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path).

### Examples

```pycon
>>> ken_burns_video("photo.jpg")  # 2s push-in
>>> from burns import ken_burns_path
>>> ken_burns_video(
...     "photo.jpg", ken_burns_path(1), duration=5.0, saveas="out.mp4"
... )
```
