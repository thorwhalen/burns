# burns

burns — Ken Burns pan/zoom video effects.

Turn a still image (or a sequence of stills) into a cinematic pan/zoom film,
driven by one **render-agnostic motion spec** so the same path feeds the Python
renderer here and the in-browser TypeScript port (`kenburnz`, in `ts/`).

The core abstraction is a pure, time-parameterized spec:

- [`Rect`](#burns.Rect) — a normalized `(x, y, w, h)` viewport over the image
  (top-left origin, window-fraction zoom).
- [`BurnsPath`](#burns.BurnsPath) — keyframes + easing, with `evaluate(t) -> Rect` (pure,
  deterministic, frame-count-free) and JSON `to_dict` / `from_dict`.
- [`ken_burns_path()`](#burns.ken_burns_path) — build a cohesive, deterministic path per sequence
  index from a little intent (style / zoom / pan / easing).
- [`content_aware_path_for()`](#burns.content_aware_path_for) — the content-aware counterpart: keep the
  subject (via [`salient_box()`](#burns.salient_box)) and any injected face boxes framed.

Two renderers consume a path plus a render-time `duration`:

- [`ken_burns_video()`](#burns.ken_burns_video) — one image -> one mp4 (pluggable backend).
- [`ken_burns_film()`](#burns.ken_burns_film) — a sequence of `(image, path, duration)` panels ->
  one continuous mp4 (single encode pass, no seams), with optional audio.

Quickstart:

```pycon
>>> from burns import ken_burns_video, ken_burns_path
>>> ken_burns_video("photo.jpg")  # 2s push-in
>>> ken_burns_video(  # path per sequence index
...     "photo.jpg", ken_burns_path(1, style="push"), duration=5.0
... )
```

### Functions

| [`ken_burns_path`](#burns.ken_burns_path)(index, \*[, style, zoom, pan, ...])   | A deterministic [`BurnsPath`](#burns.BurnsPath) for the `index`-th image of a sequence.                                                                                                                                                      |
|-------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`content_aware_path`](#burns.content_aware_path)(img_w, img_h, \*[, ...])          | A [`BurnsPath`](#burns.BurnsPath) that keeps the subject/faces framed while zooming toward or away from them — the content-aware counterpart of [`ken_burns_path()`](burns.path.html.md#burns.path.ken_burns_path). |
| [`content_aware_path_for`](#burns.content_aware_path_for)(image, \*[, faces, ...])      | Convenience: derive the subject (via [`salient_box()`](#burns.salient_box)) and faces (from `faces` or `faces_detector(image)`) straight from `image`, then call [`content_aware_path()`](#burns.content_aware_path).        |
| [`salient_box`](#burns.salient_box)(image, \*[, downscale, ...])             | Estimate the salient (high-detail) region of `image` as a normalized box.                                                                                                                                                                                               |
| [`ken_burns_video`](#burns.ken_burns_video)(image[, path, duration, ...])        | Render one image into a pan/zoom video from a [`BurnsPath`](#burns.BurnsPath).                                                                                                                                                               |
| [`ken_burns_film`](#burns.ken_burns_film)(panels, \*, saveas[, fps, ...])       | Render an N-panel Ken Burns film in a single pass.                                                                                                                                                                                                                      |
| [`parse_easing`](#burns.parse_easing)([spec])                                 | Resolve an easing spec to a callable `f: [0, 1] -> [0, 1]`.                                                                                                                                                                                                             |
| [`cubic_bezier`](#burns.cubic_bezier)(x1, y1, x2, y2)                         | A CSS-style cubic-bezier easing `f: [0, 1] -> [0, 1]`.                                                                                                                                                                                                                  |
| [`register_backend`](#burns.register_backend)(name, backend)                      | Register a render backend under `name` (open-closed extension point).                                                                                                                                                                                                   |
| [`get_backend`](#burns.get_backend)([name])                                  | Look up a registered backend by name.                                                                                                                                                                                                                                   |

### Classes

| [`Rect`](#burns.Rect)(x, y, w, h)                            | A normalized `(x, y, w, h)` viewport over a source image.                                                    |
|----------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| [`BurnsPath`](#burns.BurnsPath)(keyframes[, easing, interp, ...]) | A time-parameterized pan/zoom motion over a still image.                                                     |
| [`RenderBackend`](#burns.RenderBackend)(\*args, \*\*kwargs)           | Encode one image + [`BurnsPath`](#burns.BurnsPath) into a video file at `output`. |

### *class* burns.BurnsPath(keyframes, easing='ease-in-out', interp='linear', output_aspect=None, version=1)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A time-parameterized pan/zoom motion over a still image.

Construct it directly from keyframes, or via [`from_start_end()`](#burns.BurnsPath.from_start_end) /
[`push_in()`](#burns.BurnsPath.push_in) for the common cases, or via [`ken_burns_path()`](#burns.ken_burns_path) for
deterministic per-index motion across a sequence.

* **Parameters:**
  * **keyframes** ([`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`Rect`](burns.rect.html.md#burns.rect.Rect)], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]) – a sequence of `(t, Rect)` waypoints, `t in [0, 1]`,
    strictly increasing in `t`. Must have at least one entry; the
    first `t` should be `0.0` and the last `1.0` for the whole
    clock to be covered (out-of-range `t` clamps to the ends).
  * **easing** (`Union`[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – a CSS timing-function spec (name / `cubic-bezier(...)` /
    4-tuple) or a callable `[0,1] -> [0,1]`. Default `"ease-in-out"`.
  * **interp** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – geometry interpolation between keyframes. Only `"linear"` is
    implemented; the field exists so the spec can carry richer schemes
    (`"catmull-rom"`, `"bezier"`) without a format change.
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the aspect ratio (`width / height`) the render should
    fill. `None` means “match the source image”.
  * **version** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – spec schema version (for forward-compatible serialization).

### Examples

```pycon
>>> p = BurnsPath.from_start_end(
...     Rect(0, 0, 1, 1), Rect.from_center_zoom(0.5, 0.5, 1.3)
... )
>>> p.evaluate(0.0)
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> round(p.evaluate(1.0).zoom, 4)
1.3
>>> p.duration_keyframes  # number of waypoints
2
```

#### *property* duration_keyframes *: [int](https://docs.python.org/3/builtins/functions.html#int)*

Number of keyframe waypoints (`2` for the canonical Start/End).

#### evaluate(t)

The viewport [`Rect`](#burns.Rect) at normalized clock time `t in [0, 1]`.

Applies easing to the clock, then linearly interpolates the geometry at
the eased progress. Pure and deterministic: no image, no I/O, no frame
count. `t` outside `[0, 1]` clamps to the nearest end.

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

### Examples

```pycon
>>> p = BurnsPath.from_start_end(
...     Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing="linear"
... )
>>> p.evaluate(0.5)
Rect(x=0.0, y=0.0, w=0.75, h=0.75)
```

#### *classmethod* from_dict(d)

Rebuild a [`BurnsPath`](#burns.BurnsPath) from [`to_dict()`](#burns.BurnsPath.to_dict) output.

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> BurnsPath.from_dict(p.to_dict()) == p
True
```

#### *classmethod* from_start_end(start, end, , easing='ease-in-out', output_aspect=None)

The canonical two-rectangle Ken Burns case (Start frame -> End frame).

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
...
BurnsPath(keyframes=((0.0, Rect(...)), (1.0, Rect(...))), ...)
```

#### *classmethod* push_in(zoom=1.3, , to=(0.5, 0.5), easing='ease-in-out', output_aspect=None)

The 90%-case constructor: a slow push from the full image toward
`to` at `zoom`.

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> round(BurnsPath.push_in().evaluate(1.0).zoom, 4)
1.3
```

#### reversed()

Swap start and end (the NLE “Swap Start and End Areas” button).

Mirrors every keyframe’s time about `0.5` and re-sorts, so the motion
plays back-to-front. Easing/interp/output_aspect are preserved.

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> p.reversed().evaluate(0.0)
Rect(x=0.0, y=0.0, w=0.5, h=0.5)
```

#### to_dict()

Serialize to the versioned JSON wire format (the cross-language SSOT).

Easing is stored as the original CSS string / 4-tuple. A callable easing
cannot be serialized and raises — use a CSS spec for paths that travel.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### Examples

```pycon
>>> p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, .5, .5))
>>> d = p.to_dict()
>>> d["version"], d["easing"], len(d["keyframes"])
(1, 'ease-in-out', 2)
```

### *class* burns.Rect(x, y, w, h)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A normalized `(x, y, w, h)` viewport over a source image.

All four components are fractions of the image in `[0, 1]` with a
top-left origin. `(x, y)` is the top-left corner of the window; `w` and
`h` are its width and height. `Rect(0, 0, 1, 1)` is the whole image.

### Examples

```pycon
>>> full = Rect(0.0, 0.0, 1.0, 1.0)
>>> full.center
(0.5, 0.5)
>>> full.zoom
1.0
>>> Rect.from_center_zoom(0.5, 0.5, 2.0)
Rect(x=0.25, y=0.25, w=0.5, h=0.5)
```

#### *property* aspect *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Aspect ratio of the window *in normalized image units* (`w / h`).

Note this is not the rendered-pixel aspect ratio unless the image is
square — the pixel AR is `(w * img_w) / (h * img_h)`. The render path
reconciles the window with the desired output AR via a cover-crop.

#### *property* center *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[float](https://docs.python.org/3/builtins/functions.html#float), [float](https://docs.python.org/3/builtins/functions.html#float)]*

The window’s center `(cx, cy)` in `[0, 1]` image units.

#### clamped()

Slide the window inside the image **without resizing it**.

Clamps the top-left corner so the window “rides the wall” at an edge
rather than shrinking — shrinking the box would change its aspect ratio
and make the rendered frame breathe/stretch. Windows larger than the
image in a dimension are centered in that dimension.

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

### Examples

```pycon
>>> Rect(0.8, 0.0, 0.5, 0.5).clamped()
Rect(x=0.5, y=0.0, w=0.5, h=0.5)
>>> Rect(-0.2, 0.3, 0.4, 0.4).clamped()
Rect(x=0.0, y=0.3, w=0.4, h=0.4)
```

#### *classmethod* from_center_zoom(cx, cy, zoom=1.0, , aspect=1.0)

Build a rect from a pan center, a zoom, and a window aspect ratio.

This is the bridge from the older center+magnification mental model to
the `(x, y, w, h)` representation. `zoom` is window-fraction
magnification (`1.0` = full image, `> 1.0` = zoomed in). `aspect`
is the window’s normalized `w / h`; the default `1.0` yields an
isotropic window (`w == h`) whose rendered AR equals the source
image’s — reproducing the legacy behavior exactly. The result is
clamped to stay inside the image.

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

### Examples

```pycon
>>> Rect.from_center_zoom(0.5, 0.5, 1.0)
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> Rect.from_center_zoom(0.75, 0.5, 2.0)  # off-center zoom-in
Rect(x=0.5, y=0.25, w=0.5, h=0.5)
```

#### is_contained()

True when the window lies wholly inside the image.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### Examples

```pycon
>>> Rect(0.1, 0.1, 0.5, 0.5).is_contained()
True
>>> Rect(0.8, 0.0, 0.5, 0.5).is_contained()
False
```

#### lerp(other, t)

Linearly interpolate toward `other` by `t` in `[0, 1]`.

* **Return type:**
  [`Rect`](burns.rect.html.md#burns.rect.Rect)

### Examples

```pycon
>>> Rect(0, 0, 1, 1).lerp(Rect(0.25, 0.25, 0.5, 0.5), 0.5)
Rect(x=0.125, y=0.125, w=0.75, h=0.75)
```

#### to_pixels(img_w, img_h)

Map the (clamped) window to an integer pixel box `(x0, y0, x1, y1)`.

Clamps first so the box is always inside the raster, then rounds (not
truncates) for symmetric integer conversion. The returned box is a
half-open crop region suitable for `ndarray[y0:y1, x0:x1]`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int), [`int`](https://docs.python.org/3/builtins/functions.html#int)]

### Examples

```pycon
>>> Rect(0.0, 0.0, 1.0, 1.0).to_pixels(100, 80)
(0, 0, 100, 80)
>>> Rect.from_center_zoom(0.5, 0.5, 2.0).to_pixels(100, 80)
(25, 20, 75, 60)
```

#### *property* zoom *: [float](https://docs.python.org/3/builtins/functions.html#float)*

Magnification implied by the window, `1 / max(w, h)`.

`1.0` = the full image; `> 1.0` = zoomed in. This is the derived
value an FFmpeg `zoompan` backend consumes; the window-fraction
`(w, h)` is the authoritative, user-facing representation.

### *class* burns.RenderBackend(\*args, \*\*kwargs)

Bases: [`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)

Encode one image + [`BurnsPath`](#burns.BurnsPath) into a video file at `output`.

Args mirror [`burns.ken_burns_video()`](#burns.ken_burns_video) after argument resolution: the
image is already a decoded `(H, W, C)` uint8 array with its pixel size,
and the output frame size `(out_w, out_h)` is already even-snapped.
Returns the written path.

### burns.content_aware_path(img_w, img_h, , subject=None, faces=(), index=0, output_aspect=None, zoom=1.3, min_zoom=1.05, keep_pad=0.18, mode='auto', easing='ease-in-out')

A [`BurnsPath`](#burns.BurnsPath) that keeps the subject/faces framed while zooming
toward or away from them — the content-aware counterpart of
[`ken_burns_path()`](burns.path.html.md#burns.path.ken_burns_path).

The *keep-region* is the union of `faces` if any, else `subject` (else a
centered default). Both start and end crop windows are built to contain that
region fully, centered on it; the end zoom is capped so the region never
leaves the frame. Windows carry the output pixel-aspect so the render’s
cover-crop is a no-op and what you frame is what shows.

* **Parameters:**
  * **img_w** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – source image pixel size (the subject box lives in this space).
  * **img_h** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – source image pixel size (the subject box lives in this space).
  * **subject** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – normalized `(x,y,w,h)` of the main subject (e.g. from
    [`salient_box()`](#burns.salient_box)). Optional.
  * **faces** ([`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – normalized face boxes; when present they are the keep-region and
    take priority over `subject`.
  * **index** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – sequence position; in `mode="auto"` odd indices push in, even
    pull out, giving a sequence rhythm (mirrors `ken_burns_path`).
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – the render’s `width/height`; defaults to the image’s.
  * **zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – target end magnification (capped to keep the region framed).
  * **min_zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – floor magnification for the non-zoomed end.
  * **keep_pad** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – fractional padding around the keep-region.
  * **mode** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `"auto"` (alternate by index) · `"in"` (always toward) ·
    `"out"` (always away).
* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### Examples

```pycon
>>> p = content_aware_path(1600, 900, subject=(0.6, 0.55, 0.2, 0.25), index=1)
>>> r0, r1 = p.evaluate(0.0), p.evaluate(1.0)
>>> r1.zoom >= r0.zoom            # index 1 -> push in
True
>>> content_aware_path(100, 100, subject=(0,0,1,1)) == content_aware_path(100, 100, subject=(0,0,1,1))
True
```

### burns.content_aware_path_for(image, , faces=(), faces_detector=None, index=0, output_aspect=None, \*\*kwargs)

Convenience: derive the subject (via [`salient_box()`](#burns.salient_box)) and faces (from
`faces` or `faces_detector(image)`) straight from `image`, then call
[`content_aware_path()`](#burns.content_aware_path). `image` may be a path, PIL image, or ndarray.

Keeps burns dependency-light: pass an LLM/cv2/manual `faces_detector` when
you want face-aware framing; omit it for saliency-only (sky-avoiding) motion.

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### burns.cubic_bezier(x1, y1, x2, y2)

A CSS-style cubic-bezier easing `f: [0, 1] -> [0, 1]`.

The curve runs from `(0, 0)` to `(1, 1)` with control points
`(x1, y1)` and `(x2, y2)`. Evaluation inverts `x(t)` for the curve
parameter (bisection — robust for any monotone-x curve) then returns
`y(t)`.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### Examples

```pycon
>>> linear = cubic_bezier(0.0, 0.0, 1.0, 1.0)
>>> round(linear(0.5), 6)
0.5
>>> round(cubic_bezier(0.42, 0.0, 0.58, 1.0)(0.5), 6)  # ease-in-out
0.5
```

### burns.get_backend(name='pillow')

Look up a registered backend by name.

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis), [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path)]

### Examples

```pycon
>>> get_backend() is get_backend("pillow")
True
```

### burns.ken_burns_film(panels, , saveas, fps=30, audio_path=None, codec='libx264', audio_codec='aac', \*\*write_kwargs)

Render an N-panel Ken Burns film in a single pass.

Each panel is an `(image, path, duration_s)` triple
(`burns.PanelInput`): `image` is a path / `PIL.Image` /
`np.ndarray`, `path` a [`BurnsPath`](#burns.BurnsPath), `duration_s` how long the
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

### burns.ken_burns_path(index, , style='push', zoom=1.1, pan=0.03, easing='ease-in-out', output_aspect=None)

A deterministic [`BurnsPath`](#burns.BurnsPath) for the `index`-th image of a sequence.

Maps intent to geometry so a sequence of images gets cohesive, non-repetitive
motion without hand-authoring rectangles. Per-index deterministic: identical
args always return an identical path. Duration is *not* part of the path — it
is a render-time parameter (pass it to [`burns.ken_burns_video()`](#burns.ken_burns_video) /
[`burns.ken_burns_film()`](#burns.ken_burns_film)).

Two styles:

- `style="push"` (default) — the “cinematic push”: one slow zoom toward an
  off-center focal point. **Odd indices push in, even indices pull out**, so a
  sequence has visual rhythm without changing direction *within* a shot. The
  focal direction rotates through compass octants per index.
- `style="drift"` — pure horizontal pan at a constant zoom, alternating
  direction per index (odd drifts right, even left). `zoom` is ignored;
  drift derives its own zoom from `pan` so the slide is visible.

* **Parameters:**
  * **index** ([`int`](https://docs.python.org/3/builtins/functions.html#int)) – the image’s 1-based position in the sequence.
  * **style** ([`str`](https://docs.python.org/3/builtins/stdtypes.html#str)) – `"push"` (default) or `"drift"`.
  * **zoom** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – the zoomed-end magnification (> 1.0) for `"push"`.
  * **pan** ([`float`](https://docs.python.org/3/builtins/functions.html#float)) – focal-point offset (`"push"`) or total horizontal travel
    (`"drift"`), in `[0, 1]` image units.
  * **easing** (`Union`[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]]) – CSS timing function or callable. Default `"ease-in-out"` — the
    cinematic slow-in/slow-out. Pass `"linear"` for constant velocity.
  * **output_aspect** ([`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[[`float`](https://docs.python.org/3/builtins/functions.html#float)]) – aspect ratio the render should fill (`None` = match image).
* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)
* **Returns:**
  A [`BurnsPath`](#burns.BurnsPath) (two keyframes — Start and End).

### Examples

```pycon
>>> ken_burns_path(1).evaluate(0.0)  # odd: push in, starts full
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> ken_burns_path(2).evaluate(1.0)  # even: pull out, ends full
Rect(x=0.0, y=0.0, w=1.0, h=1.0)
>>> ken_burns_path(3) == ken_burns_path(3)  # deterministic
True
```

### burns.ken_burns_video(image, path=BurnsPath(keyframes=((0.0, Rect(x=0.0, y=0.0, w=1.0, h=1.0)), (1.0, Rect(x=0.11538461538461542, y=0.11538461538461542, w=0.7692307692307692, h=0.7692307692307692))), easing='ease-in-out', interp='linear', output_aspect=None, version=1), , duration=2.0, fps=30, saveas=None, output_size=None, backend='pillow', codec='libx264', audio_codec='aac', \*\*write_kwargs)

Render one image into a pan/zoom video from a [`BurnsPath`](#burns.BurnsPath).

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

### burns.parse_easing(spec='ease-in-out')

Resolve an easing spec to a callable `f: [0, 1] -> [0, 1]`.

Accepts:

> - a CSS name (`"linear"`, `"ease"`, `"ease-in"`, `"ease-out"`,
>   `"ease-in-out"`);
> - a CSS `"cubic-bezier(x1, y1, x2, y2)"` string;
> - a 4-element sequence `(x1, y1, x2, y2)`;
> - any callable, returned unchanged.

### Examples

```pycon
>>> parse_easing("linear")(0.3)
0.3
>>> round(parse_easing("cubic-bezier(0,0,1,1)")(0.7), 6)
0.7
>>> parse_easing(lambda t: t * t)(0.5)
0.25
```

* **Return type:**
  [`Callable`](https://docs.python.org/3/library/typing.html#typing.Callable)[[[`float`](https://docs.python.org/3/builtins/functions.html#float)], [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### burns.register_backend(name, backend)

Register a render backend under `name` (open-closed extension point).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### burns.salient_box(image, , downscale=320, threshold_pct=72.0, trim_pct=4.0, pad=0.05, min_size=0.35)

Estimate the salient (high-detail) region of `image` as a normalized box.

Uses gradient magnitude: flat regions (sky, walls, water) have low gradient
and fall away, so the bounding box of the high-gradient pixels tracks the
subject. Robust to outliers via percentile trimming. Falls back to a
centered box when the image is too uniform to decide.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]

### Examples

```pycon
>>> import numpy as np
>>> a = np.zeros((100, 100), dtype='uint8'); a[60:90, 40:70] = 255
>>> x, y, w, h = salient_box(a, min_size=0.0, pad=0.0)
>>> 0.3 < x < 0.45 and 0.55 < y < 0.65   # box around the bright square
True
```

### Modules

| [`backends`](burns.backends.html.md#module-burns.backends)   | Pluggable single-clip render backends — the open-closed seam.                                                                                       |
|-----------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| [`content`](burns.content.html.md#module-burns.content)     | Content-aware Ken Burns: choose crop windows that keep the subject (and any detected faces) framed, and avoid drifting over empty regions like sky. |
| [`easing`](burns.easing.html.md#module-burns.easing)       | Timing functions (easing) for Ken Burns motion.                                                                                                     |
| [`path`](burns.path.html.md#module-burns.path)           | The render-agnostic Ken Burns motion spec: [`BurnsPath`](#burns.BurnsPath).                                              |
| [`rect`](burns.rect.html.md#module-burns.rect)           | The Ken Burns viewport rectangle — the render-agnostic geometric atom.                                                                              |
| [`render`](burns.render.html.md#module-burns.render)       | Ken Burns **renderers** — turn still images into pan/zoom video.                                                                                    |
