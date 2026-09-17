# burns.content

Content-aware Ken Burns: choose crop windows that keep the subject (and any
detected faces) framed, and avoid drifting over empty regions like sky.

Two layers, usable together or apart:

* [`salient_box()`](#burns.content.salient_box) — a **zero-dependency** (numpy + Pillow, already required)
  estimate of the busy / high-detail region of an image, so motion follows the
  subject instead of blank sky or plain ground. Good default when you have no
  detector.
* [`content_aware_path()`](#burns.content.content_aware_path) — the **pure geometry**: given the image size and a
  *keep-region* (the union of face boxes if any, else a subject box), build a
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath) whose start/end windows keep that region fully
  > framed while zooming toward or away from it. This is the reusable, testable
  > core; it touches no pixels.

Detection is **injected**, not built in: faces come from a caller-supplied
`faces_detector` (an LLM, an ONNX/cv2 model, or manual boxes), so this module
stays dependency-light and deterministic. Boxes everywhere are normalized
`(x, y, w, h)` in `[0, 1]` with a top-left origin — the same convention as
[`Rect`](burns.rect.html.md#burns.rect.Rect).

### Module Attributes

| [`FacesDetector`](#burns.content.FacesDetector)   | given an image, return normalized face boxes (empty if none).   |
|------------------------------------------------------------------|-----------------------------------------------------------------|

### Functions

| [`content_aware_path`](#burns.content.content_aware_path)(img_w, img_h, \*[, ...])     | A `BurnsPath` that keeps the subject/faces framed while zooming toward or away from them — the content-aware counterpart of [`ken_burns_path()`](burns.path.html.md#burns.path.ken_burns_path).                                         |
|--------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`content_aware_path_for`](#burns.content.content_aware_path_for)(image, \*[, faces, ...]) | Convenience: derive the subject (via [`salient_box()`](#burns.content.salient_box)) and faces (from `faces` or `faces_detector(image)`) straight from `image`, then call [`content_aware_path()`](#burns.content.content_aware_path). |
| [`salient_box`](#burns.content.salient_box)(image, \*[, downscale, ...])        | Estimate the salient (high-detail) region of `image` as a normalized box.                                                                                                                                                                                        |

### burns.content.FacesDetector

given an image, return normalized face boxes (empty if none).

* **Type:**
  A detector

alias of `Callable`[[[`Any`](https://docs.python.org/3/library/typing.html#typing.Any)], [`Sequence`](https://docs.python.org/3/library/typing.html#typing.Sequence)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float), [`float`](https://docs.python.org/3/builtins/functions.html#float)]]]

### burns.content.content_aware_path(img_w, img_h, , subject=None, faces=(), index=0, output_aspect=None, zoom=1.3, min_zoom=1.05, keep_pad=0.18, mode='auto', easing='ease-in-out')

A `BurnsPath` that keeps the subject/faces framed while zooming
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
    [`salient_box()`](#burns.content.salient_box)). Optional.
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

### burns.content.content_aware_path_for(image, , faces=(), faces_detector=None, index=0, output_aspect=None, \*\*kwargs)

Convenience: derive the subject (via [`salient_box()`](#burns.content.salient_box)) and faces (from
`faces` or `faces_detector(image)`) straight from `image`, then call
[`content_aware_path()`](#burns.content.content_aware_path). `image` may be a path, PIL image, or ndarray.

Keeps burns dependency-light: pass an LLM/cv2/manual `faces_detector` when
you want face-aware framing; omit it for saliency-only (sky-avoiding) motion.

* **Return type:**
  [`BurnsPath`](burns.path.html.md#burns.path.BurnsPath)

### burns.content.salient_box(image, , downscale=320, threshold_pct=72.0, trim_pct=4.0, pad=0.05, min_size=0.35)

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
