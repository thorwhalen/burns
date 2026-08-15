# Ken Burns Effect Libraries, Tooling, and API Design: A Research Brief

*Author: Thor Whalen*
*Date: 28 May 2026*

## TL;DR

- **The professional consensus model is exactly two crop rectangles (Start, End) + duration + a timing function** — confirmed verbatim by Apple's official iMovie and Final Cut Pro documentation [1][2][3], iMovie's predecessor [4], the FFmpeg `zoompan` filter family [5], and Pydantic-modeled Python prior art (`videopython.KenBurns(start_region, end_region, easing=…)`) [6]. The two-rectangle model should be the library's *core* representation; multi-keyframe paths are a strict generalization.
- **A render-agnostic, time-parameterized `BurnsPath.evaluate(t∈[0,1]) → Rect` object is a genuine ecosystem gap.** The Python landscape (MoviePy, Pillow, OpenCV, ffmpeg-python, `kburns-slideshow`, `videopython`, 3d-ken-burns) couples the motion spec to a render backend; the closest design precedent is the dormant JavaScript `gre/kenburns` family which separates `rect-crop` from `bezier-easing` from DOM/Canvas/WebGL render strategies [7][8][9]. Building `BurnsPath` is novel — but should reuse existing *vocabulary* and *coordinate conventions*, not invent new ones.
- **Recommended stack:** Python primary backend = **Pillow + imageio-ffmpeg** for frames; FFmpeg `zoompan` only as an optional fast-path (it has a documented integer-pixel rounding/jitter problem [10][11]). JS/TS primary = **Remotion's `interpolate()` + `Easing`** (their `inputRange/outputRange` API is the clearest existing precedent for a time-parameterized animation primitive) [12][13][14]. Coordinate convention: **normalized [0,1] top-left-origin rectangles as `(x, y, w, h)` matching `videopython.BoundingBox`** [6] and CSS [15], with zoom expressed as **fraction-of-image (window size)** rather than magnification — because that is what every keyframe-based tool (iMovie, FCP, After Effects, Premiere) actually exposes [1][2][16][3].

---

## Key Findings

1. **Two crop rectangles is the standard.** Every major NLE — Apple iMovie [1][4], Apple Final Cut Pro [2][3], and Adobe Premiere/After Effects via position+scale keyframes [16][17] — exposes Ken Burns as a Start (green) frame and End (red) frame, with duration coming from the parent clip and an ease-in/ease-out timing function applied by default.
2. **The aspect ratio of the crop must equal the OUTPUT frame, not the input image.** Apple's FCP documentation states this as a non-negotiable invariant ("The Ken Burns effect creates video that must fully fill the frame at all times") [18], and the same is observed in iMovie when switching projects from 16:9 to vertical [19].
3. **Default timing is ease-in-and-out, not linear.** Final Cut Pro applies ease-in-and-out by default and exposes the four standard options (Ease In and Out, Ease In, Ease Out, Linear) via right-click [3]. This contradicts the assumption a programmer might bring from CSS (where `linear` is mathematically default).
4. **Sub-pixel jitter is a real, documented problem with three known mitigations:** (a) up-scale the source image before zoompan to a much larger working resolution (e.g. `scale=8000:-1`) [20][21]; (b) keep all dimensions even and use `Image.LANCZOS` resampling [22][23]; (c) compute the rectangle in floating-point and rasterize once. The FFmpeg official docs are silent on this — it is folklore from the GitHub bug tracker and blog posts.
5. **Zoom is *fraction-of-image* in keyframe-based tools and *magnification* in FFmpeg.** FCP, iMovie, After Effects, and Premiere all let the user *draw the visible rectangle* (i.e. specify its size as a fraction of the image) [1][2][16][17]. FFmpeg's `zoompan` instead takes `z` as a magnification factor in the range 1–10, with `iw/zoom` giving the window width [5]. The user-facing concept that aligns with prior art is **window-fraction (or normalized window rect)**; magnification should be a derived value.
6. **CSS `cubic-bezier()` is the universal lingua franca for timing functions** [24][25]. Both Remotion's `Easing.bezier(x1, y1, x2, y2)` [13] and GSAP's `CustomEase` [26] accept CSS-compatible four-number bezier curves. Adopting CSS easing strings as the primary public API for the `timing` parameter aligns with the broadest ecosystem.

---

## Details

### 1. Conceptual Model & Terminology — Glossary

| Term | Definition | Canonical source |
|---|---|---|
| **Ken Burns effect** | Slow pan-and-zoom over a still image. Per Burns's 2014 Reddit AMA, Steve Jobs phoned in December 2002 and Burns agreed: *"asked my permission. I said yes. And six billion saved wedding, bar mitzvahs, vacation slideshows later, it's still going"* — Apple shipped the feature on every Mac from January 2003 in exchange for hardware Burns donated to nonprofits [4]. | Apple iMovie docs; Wikipedia [4][1] |
| **Pan** | Horizontal/vertical translation of the viewport over the image. | iMovie [1] |
| **Zoom (push-in / pull-out)** | Change of viewport size; push-in = zoom-in, pull-out = zoom-out. | FCP "pan and zoom" docs [3] |
| **Tilt** | Vertical pan (cinematography term); a Ken Burns "tilt" is just a Y-axis pan. | General cinematography |
| **Dolly zoom** | Combined zoom + focal-length change that keeps a target subject the same size while perspective shifts. Implemented by `pierlj/ken-burns-effect` via `--dolly` flag [27]. | 3D Ken Burns research |
| **Crop frame / viewport / region of interest (ROI)** | The rectangle of the source image that fills the output frame at a given instant. iMovie calls them "Start" and "End" frames [1]; FCP also calls them "green" and "red" rectangles [3]. | iMovie, FCP |
| **Keyframe** | A named time point with associated property values; the renderer interpolates between them. After Effects uses keyframes for both spatial (motion path) and temporal (value graph) curves [17]. | After Effects [17] |
| **Tween / interpolation** | The computed values between keyframes. | After Effects [17] |
| **Easing / timing function** | A function mapping normalized time → normalized progress. CSS Timing Functions Level 1 defines `linear`, `ease`, `ease-in`, `ease-out`, `ease-in-out`, `cubic-bezier(x1,y1,x2,y2)`, `steps()`, and `linear()` [24][15]. | CSS Timing Functions L1 [24] |
| **Anchor / transform-origin** | The fixed point that a `scale()`/`rotate()` transform leaves invariant; in CSS this is `transform-origin` (default `50% 50%`) [15]. | CSS Transforms [15] |
| **Dwell / hold** | A segment where the viewport does not change. In After Effects this is "Hold interpolation" [17]; in Remotion you express it by repeating a value in `outputRange` [12]. | AE, Remotion |
| **Spatial vs temporal interpolation** | AE distinguishes the **motion path** (spatial, Bezier curve in 2D) from the **value graph** (temporal, speed along the path) [17]. This decomposition is a strong precedent for keeping path orthogonal to timing in any new API. | After Effects [17] |
| **Containment / "dynamic scaling"** | The constraint that the viewport must not extend beyond the image bounds. In `videopython` enforced as `region.x + region.width ≤ 1`, `region.y + region.height ≤ 1` [6]. | videopython [6] |

### 2. Confirming "two crop rectangles + duration + timing function"

The verbatim Apple guidance for iMovie on Mac: *"Two frames, labeled Start and End, appear over the clip in the viewer. Set the crop at the beginning of the clip: Select the Start frame, and then drag and resize it... Set the crop at the end of the clip: Select the End frame, and then drag and resize it..."* [1]. The reversal is a single "Swap Start and End Areas" button [1].

For Final Cut Pro: *"The Ken Burns effect is actually a Crop effect with two crop settings, one at the clip start and another at its end... By default, a Ken Burns animation performs both [Ease Out and Ease In], but you can customize the effect to limit the result to just easing out, just easing in, or making a linear movement"* [3].

Capabilities beyond the two-rectangle minimum exposed by professional tools:

| Tool | Multi-keyframe path? | Per-channel easing? | Rotation? | Hold? | Reverse/Swap? |
|---|---|---|---|---|---|
| **iMovie** | No (Start/End only) | No (single ease) | No | No (use second clip with Crop-to-Fill) | Yes (Swap button) [1] |
| **Final Cut Pro X** | Yes via Crop keyframes; native Ken Burns is two-rectangle | Linear / Ease-In / Ease-Out / Ease-In-and-Out for the whole effect [3] | No (use Transform separately) | Via keyframes | Yes (Swap) [3] |
| **After Effects** | Yes (unlimited spatial + temporal keyframes, Auto/Continuous/Bezier/Hold per keyframe) [17] | Yes (separate dimensions, value graph) | Yes | Yes (Hold interpolation) [17] | Manual |
| **Adobe Premiere** | Yes (Scale + Position keyframes in Effect Controls) [28] | Yes (per-property eases) | Yes (Rotation property) | Yes | Manual |
| **Remotion** | Yes (interpolate accepts arbitrary `inputRange[]` / `outputRange[]` arrays of equal length) [12] | Yes (each `interpolate` call has its own `easing`) | Yes (via CSS `transform`) | Yes (repeat values) | Manual |

### 3. Rectangle / Viewport Representation Survey

| Tool / Library | Coordinates | Origin | Units | Notes |
|---|---|---|---|---|
| **iMovie / FCP** | Center+size (drag handles) | UI-relative | Display pixels | UI hides the underlying numbers; aspect-ratio-locked to project [18][19] |
| **After Effects** | Position (anchor) + Scale (%) | Top-left default; movable anchor | Pixels | `transform-origin` is the anchor [17] |
| **FFmpeg `zoompan`** | `x, y` of top-left corner + `z` magnification | Top-left | Pixels (integers) [5] | Window is `iw/zoom × ih/zoom`; `s=hd720` default [5] |
| **CSS / Remotion** | `transform: scale() translate()` + `transform-origin` | `transform-origin` (default 50% 50%) | Pixels or `%` of element | Container has `overflow:hidden`; image is over-sized [29] |
| **ImageMagick `-distort SRT`** | `ix,iy scale rotation ox,oy` (5 args, plus viewport) | Top-left, with `-define distort:viewport` | Pixels (float) | Native sub-pixel support [30] |
| **`videopython.BoundingBox`** | `x, y, width, height` | Top-left | **Normalized [0,1]** | `x+w ≤ 1` enforced [6] |
| **`gre/kenburns` (JS)** | `from = [zoom, [centerX, centerY]]` | Center+zoom | Normalized [0,1] | Decoupled from renderer [8] |
| **3D Ken Burns CLI** | `--startU --startV --startW --startH` and end- equivalents | Top-left | Pixels [27] | |

**De-facto standards:**
- **Top-left origin, y-down** is universal in image/video processing (only AE allows a moveable anchor).
- **Normalized `[0,1]` `(x, y, w, h)`** is the cleanest representation for a render-agnostic spec — it is exactly what `videopython` adopted [6] and what `gre/kenburns` adopted (in `[zoom, [cx, cy]]` form) [8]. Pixel coordinates couple the spec to a particular input resolution; magnification (`z` in zoompan) couples it to a particular zoom semantic. Normalized rects survive both.

**Aspect-ratio relationship.** The crop's aspect ratio **must** equal the **output frame's** aspect ratio (not the input image's). Apple is explicit: *"The Ken Burns effect creates video that must fully fill the frame at all times. For this reason, we can't rotate images or scale outside the image itself"* [18]. FCP forces the start/end rectangles to project aspect ratio, and switching project AR breaks existing Ken Burns effects in ways users find surprising [19].

When output AR ≠ image AR, tools handle it three ways: (a) **cover** the image with the largest rectangle of project AR that fits (default in FCP/iMovie); (b) **fit** the image with letterboxing (FFmpeg `pad` + `zoompan`) [10]; (c) **pad-then-zoompan** the image to project AR first, as documented in the canonical FFmpeg Ken Burns blog [10].

**Containment.** Every tool enforces "crop ⊂ image"; `videopython` validates it explicitly:
```python
if region.x + region.width > 1 or region.y + region.height > 1:
    raise ...
```
[6]. FCP's UI clamps the drag handles; iMovie clamps invisibly.

**Zoom semantics.** Two competing definitions:
- **Magnification** (`z`): output pixel size ÷ source pixel size. FFmpeg uses this with `z ∈ [1, 10]`, default 1 [5]. CSS `scale()` is the same.
- **Window fraction** (`s`): visible window edge ÷ image edge, so `s ∈ (0, 1]`, with 1 = full image. This is what every NLE's user-drawn rectangle implements. The two are reciprocals: `s = 1/z`.

The **window-fraction model is more natural for keyframing** because it composes directly with `(x, y, w, h)` rectangles; magnification requires an extra anchor parameter.

### 4. Motion: Spatial Path + Timing

**Interpolation across keyframes.**

- **CSS `@keyframes`**: per-property linear interpolation between adjacent stops, optionally with an `animation-timing-function` set *per keyframe* applied until the next [15][29].
- **Remotion `interpolate(input, [0, 30, 60, 90], [0, 1, 1, 0], { easing })`**: equal-length input/output arrays, piece-wise interpolation, single `easing` applied to each segment [12].
- **After Effects**: per-keyframe interpolation type (Linear / Bezier / Auto-Bezier / Continuous-Bezier / Hold), **with spatial and temporal types set independently** [17].
- **GSAP**: `gsap.to()` with `ease` and (in TweenMax era) BezierPlugin for path arrays; modern GSAP uses MotionPathPlugin and `CustomEase` for arbitrary Bezier easings [26].
- **ImageMagick `-distort SRT`**: per-frame evaluation; no built-in tweener — caller produces frames in a loop with their own clock parameter [30][31].

**Easing presets — canonical CSS names** (verbatim from CSS Timing Functions L1 [24]):
- `linear` = `cubic-bezier(0, 0, 1, 1)`
- `ease` = `cubic-bezier(0.25, 0.1, 0.25, 1)`
- `ease-in` = `cubic-bezier(0.42, 0, 1, 1)`
- `ease-out` = `cubic-bezier(0, 0, 0.58, 1)`
- `ease-in-out` = `cubic-bezier(0.42, 0, 0.58, 1)`
- `cubic-bezier(x1, y1, x2, y2)` with `x1, x2 ∈ [0, 1]`
- `steps(n, position)` and the new `linear(...)` multi-stop function [15]

**Professional default.** Final Cut Pro defaults to **Ease-In-and-Out** for Ken Burns [3]; iMovie applies a smoothed easing by default [1]. CSS technically defaults to `ease` (asymmetric) for transitions but `linear` for animations. **For a Ken Burns library, the appropriate default is `ease-in-out`**, matching cinematic norms.

**Should spatial path and timing be orthogonal?** Yes. After Effects' explicit split into spatial and temporal interpolation [17] is the single most influential design lesson here: the *shape* of the motion (the curve through (x, y, w, h) space) is a separate concern from the *speed* along it. This maps directly onto the proposed `BurnsPath` design: the path geometry is a function `t → Rect` for `t ∈ [0, 1]` with **linear** progress along whatever shape (line, Catmull-Rom, multi-keyframe), and the timing function `f: [0,1] → [0,1]` is composed on top: `viewport(t_clock) = path(f(t_clock))`.

### 5. Tools & Libraries Landscape

#### 5.1 System / CLI

| Tool | Best at | Parametrization | Quality | Performance | License | Maintenance |
|---|---|---|---|---|---|---|
| **FFmpeg `zoompan`** [5] | One-shot rendering directly to MP4/WebM/GIF | Per-frame expressions `z`, `x`, `y`, `d` (frames), `s` (output), `fps`; defaults `z=1, x=0, y=0, d=90, s=hd720, fps=25` | Integer-pixel rounding causes sub-pixel jitter [10][11][20] | Excellent (C) | LGPL/GPL | Active |
| **FFmpeg expression vars** [5] | Inputs to `z/x/y` | `iw/ih/ow/oh/in/on/it/ot/zoom/pzoom/duration/a/sar/dar` | n/a | n/a | LGPL/GPL | Active |
| **ImageMagick `-distort SRT`** [30][31][32] | Per-frame transforms with true sub-pixel support | `ix,iy scale rotation ox,oy`; viewport via `-define distort:viewport`; super-sampling via `-define distort:scale=N` [32] | High (Lanczos/EWA), no integer rounding | Slow (≈20× slower than Skia) [33] | Apache-2.0 | Active |

**FFmpeg sub-pixel jitter.** Documented exhaustively in user discussions but absent from the official filter docs. The pattern that consistently helps: pre-scale the source image to a much higher resolution before `zoompan` (e.g. `scale=8000:-1`) so that the integer rounding inside zoompan happens at a finer pixel grid [20][21]. Fred Weinhaus / Anthony Thyssen's analysis on the ImageMagick forum is the clearest primary source on *why* this occurs (per-frame integer rounding accumulates a stair-step) [11].

#### 5.2 Python

| Library | Best at | Motion spec | Output | Quality | Performance | License | Maintenance |
|---|---|---|---|---|---|---|---|
| **MoviePy v2.x** [34][35] | High-level clip-graph editing; effects chain via `with_effects([Resize(lambda t: 1+0.04*t)])` [34][35] | Functional: `t → frame`; v2 renamed `clip.resize` → `clip.resized`, `clip.crop` → `clip.cropped` [34][36] | MP4/GIF via ffmpeg | Pillow LANCZOS [37] | Moderate (Python loop + ffmpeg pipe) | MIT | Active (v2.0.0 shipped Nov 20, 2024; any code older than that targets v1 and breaks under v2) |
| **Pillow (PIL fork)** [37][38][39] | Per-frame resize+crop with high-quality `LANCZOS` (`ANTIALIAS` alias) [37] | None — you write the frame loop | PNG sequence; pass to ffmpeg/imageio for video | Convolution-based since 2.7 [37] | High (SIMD fork available) | HPND | Very active |
| **OpenCV (cv2)** [6] | Fast resize/warpAffine | None | Frames | INTER_LANCZOS4 etc. | Fastest CPU | Apache-2.0 | Very active |
| **imageio / imageio-ffmpeg** | Frame I/O & video writing | None | MP4/WebM/GIF | Depends on backend | Good | BSD-2-Clause | Very active |
| **ffmpeg-python** [40] | Programmatic filter-graph builder; wraps `zoompan` | Strings passed to FFmpeg | Whatever ffmpeg supports | Inherits zoompan | Excellent | Apache-2.0 | Maintained (limited) |
| **`kburns-slideshow`** (Trekky12) [41] | Slideshow generator combining onset-detected music with ken-burns slides | High-level JSON: `zoom_direction_x ∈ {left,center,right,random}`, `zoom_direction_y ∈ {top,center,bottom,random}`, `zoom_direction_z ∈ {in,out,none,random}`, `zoom_rate`, `scale_mode`, `transition` [41] | MP4 (via ffmpeg) | Inherits zoompan | Good | MIT | **Active (v1.10, Nov 2025)** [41] |
| **`videopython`** [6] | Pydantic-modeled video FX including `KenBurns(start_region, end_region, easing)` [6] | `BoundingBox(x, y, width, height)` normalized [0,1], top-left; easing ∈ `{linear, ease_in, ease_out, ease_in_out}` [6] | MP4 via OpenCV+ffmpeg | OpenCV `cv2.resize` | Good | (Apache-2.0/MIT family) | **Active (v0.26.3, Apr 2026)** [6] |
| **`sniklaus/3d-ken-burns`** [42] | Depth-aware 3D Ken Burns from single image via PyTorch + CuPy | High-level autozoom or manual UI | MP4 | Excellent (parallax) | Requires CUDA | CC-BY-NC-SA (non-commercial) | Dormant |
| **`pierlj/ken-burns-effect`** [27] | 3D KBE + dolly zoom variant of above | `--startU/V/W/H` and end equivalents in pixels [27] | Frames/MP4 | Excellent | CUDA | Research | Dormant |
| **`kenburns` (PyPI)** | (Abandoned placeholder per subagent survey) | n/a | n/a | n/a | n/a | n/a |

**MoviePy v1 vs v2 — methods to know.** In v2 the methods are `resized()`, `cropped()`, `rotated()`, and effects must be applied via `clip.with_effects([…])` [34][35]. The pre-v2 `clip.fl(effect_func)` API is now `clip.transform(func, apply_to=…)` [35]. v2.0.0 was released **November 20, 2024**; any StackOverflow/blog snippet predating that targets v1 and will fail silently if mixed with v2.

**Quality.** Pillow ≥ 2.7 uses true convolution-based Lanczos for all resampling filters [37] — `Image.LANCZOS` (alias `Image.ANTIALIAS`) is the right default for offline rendering. OpenCV's `cv2.INTER_LANCZOS4` is faster and visually equivalent for the modest scale factors typical of Ken Burns (1×–3×).

#### 5.3 JavaScript / TypeScript

| Library | Realtime in-browser? | Renders to file? | Motion spec | Quality | License | Maintenance |
|---|---|---|---|---|---|---|
| **Remotion** [12][13][14][43] | Yes (Studio preview) | Yes (CLI / Lambda / Cloud Run [43][44]) | React components with `useCurrentFrame()` + `interpolate(frame, inputRange, outputRange, { easing })` | Chromium rendering with `swangle` GPU backend [44] | Custom (free for individuals / paid for companies, see remotion.pro/license) | Very active |
| **CSS `@keyframes` + `transform: scale() translate()`** [29][15] | Yes | No (requires headless browser) | Per-keyframe `transform`, with `transform-origin` as anchor; `animation-timing-function: cubic-bezier(...)` [24] | GPU-composited; no jitter | Web standard | Standards body |
| **GSAP** [26][45] | Yes | No (DOM-only) | `gsap.to(el, { duration, ease, x, y, scale })` with `CustomEase` accepting CSS `cubic-bezier` strings [26] | Excellent | Standard "No Charge" license following Webflow's October 15, 2024 acquisition of GreenSock — free for all web use; the sole restriction is on building tools that compete with Webflow's visual animation builder | Very active |
| **ffmpeg.wasm** | Yes | Yes (in-browser via WASM) | Same zoompan strings as native FFmpeg | Inherits jitter | LGPL | Active |
| **`gre/kenburns`** (npm) [7][8] | Yes | No | `from = [zoom, [cx, cy]]` + bezier-easing; pluggable DOM/Canvas2D/WebGL backends [8] | Backend-dependent | ISC | **Dormant (kenburns-core last published ~7 years ago)** [7] |
| **`gre/kenburns-editor`** [8] | Yes (interactive editor) | No | `{ from: [zoom, [cx, cy]], to: [zoom, [cx, cy]] }` [8] | UI-only | ISC | Dormant (~6 years) |
| **`react-kenburns`** [7] | Yes | No | Component props | OK | MIT | Dormant (last published April 17, 2015 — 11 years) [7] |
| **`react-native-kenburns-view`** [7] | Yes (RN) | No | `tension`, `friction` (spring physics) [7] | OK | ISC | Dormant |
| **`react-ken-burns-video`** [7] | Yes (records via MediaRecorder) | Yes (browser-side) | UI editor | OK | MIT | Dormant |

**Remotion's `interpolate()` as design precedent.** Remotion's source (`packages/core/src/interpolate.ts`) [13] is worth reading verbatim because it implements exactly the abstraction this library wants:

```ts
function interpolate(
  input: number,
  inputRange: number[],
  outputRange: number[],
  options?: { easing?: (t: number) => number;
              extrapolateLeft?: 'extend'|'clamp'|'identity'|'wrap';
              extrapolateRight?: 'extend'|'clamp'|'identity'|'wrap'; }
): number
```

It is pure, deterministic, frame-number-agnostic (you can pass any number), composable across multiple properties (call once per dimension), and decoupled from the React renderer. A Python `BurnsPath.evaluate(t)` should expose the same shape, returning a `Rect` instead of a `number`.

### 6. Quality & Rendering

**Sub-pixel jitter — causes and fixes.**

| Cause | Fix | Source |
|---|---|---|
| FFmpeg `zoompan` rounds `x`, `y`, and the window size to integer pixels each frame; small per-frame deltas land on the same integer for several frames then jump | Pre-scale source 4–10× before `zoompan`, then `scale` back to output at the end | StackOverflow / DataRecoveryUnion [20]; Bannerbear [21] |
| FCPX integer-clamping crops produces AR drift on time-lapse stacks (1/8 of AR drift fixed by using RAW vs JPG-rounded) | Use larger source resolution; let LRTimelapse keep 64-bit precision crops | LRTimelapse forum [46] |
| Sharp horizontal lines + small motion → interlace-like patterning | Apply 0.5–1 px vertical Gaussian blur | Apple Communities (FCPX) [47] |
| Insufficient frame rate for the motion magnitude | Increase fps (60 fps for large pans) | mko.re Ken Burns FFmpeg blog [10] |
| Even-dimension requirement for H.264 (yuv420p) | Round output W and H to nearest even integer | MoviePy GitHub issue 1402 [48] |

**Resampling filter trade-offs.** Pillow's documented order from fastest/lowest-quality to slowest/highest-quality is `NEAREST < BOX < BILINEAR < HAMMING < BICUBIC < LANCZOS` [37][38]. For Ken Burns where each frame requires a single resize, `LANCZOS` is the right default; for live preview, `BILINEAR` is acceptable.

**GPU vs CPU.** For offline rendering, CPU + Pillow/OpenCV is sufficient (single-image-per-frame operations). For real-time JS, transform-based animation (`scale3d`/`translate3d`) is GPU-composited by browsers without re-rasterization [9]. Pure-WebGL shader approaches give the best in-browser quality but are over-engineered for static images.

### 7. API / Architecture Design Precedent

**The gap.** No actively-maintained library cleanly separates a Ken Burns motion-spec from a render backend. `videopython.KenBurns` is the closest [6]: it has the right normalized `BoundingBox(x, y, w, h)` shape and the right easing vocabulary, but the path evaluator (`_precompute_regions(n_frames, width, height) → ndarray`) is private, returns integer pixel coordinates, requires a frame count up front, and is hard-wired to the OpenCV render path inside the same Pydantic class. There is no public `evaluate(t: float) → Rect`.

**Design patterns from prior art that should be adopted:**

1. **`gre/kenburns` decoupled inputs** [8]: takes any `rect-crop` value and any `bezier-easing` value; the renderer is pluggable (DOM / Canvas / WebGL). This is the closest existing strategy-pattern implementation.
2. **Remotion's input/output range abstraction** [12]: `interpolate(t, [0, 0.3, 0.7, 1], [r0, r1, r2, r3])` generalises naturally to multi-keyframe paths while subsuming the two-rectangle case as the length-2 special case.
3. **After Effects' spatial vs temporal split** [17]: keep `path(u)` (shape) and `timing(t)` (speed) independent; the final viewport is `path(timing(t))`.
4. **Pydantic validation** as in `videopython` [6]: model containment as a class-level `model_validator`.

**Progressive-disclosure naming.** Existing libraries use these names for their motion objects:
- Remotion: `interpolate(...)` returns a number, not a named object — the abstraction is anonymous.
- `gre/kenburns`: `Kenburns` instance configured with `value = { from, to }`.
- `videopython`: `KenBurns` effect class.
- After Effects: "Motion Path" (spatial) + "Value Graph" (temporal).
- iMovie / FCP: "Ken Burns effect" (the whole thing) + "Start / End frames".
- GSAP: `Timeline`, `Tween`.

A `BurnsPath` / `KBPath` name is consistent with this prior art — *"path"* matches AE's "motion path" and is the term audience already understands; *"Ken"* or *"KB"* is a recognisable disambiguator. The progressive-disclosure pattern (one-liner default, full control available) is well-represented by Remotion (`interpolate(frame, [0, 60], [0, 1])`) and GSAP (`gsap.to(el, { x: 100 })`). Adopt the same shape: a one-arg `BurnsPath.from_crop(end_rect)` for the common case, full-signature `BurnsPath(rects=[…], times=[…], easing=…)` for everything else.

---

## Recommendations

### Primary backend choices

**Python — primary backend: Pillow + imageio-ffmpeg (frame-by-frame).** Rationale:
- Pillow's `LANCZOS` resampling is documented as a true convolution filter since 2.7 [37] and is the highest-quality option for the resize-each-frame loop characteristic of Ken Burns.
- imageio-ffmpeg shells out to FFmpeg for encoding without inheriting `zoompan`'s integer-rounding jitter.
- Both libraries have permissive licenses and very active maintenance.

**Python — optional fast-path: FFmpeg `zoompan` (via ffmpeg-python).** Rationale:
- Acceptable for short clips at modest zoom factors where the pre-scale-by-8× jitter mitigation is acceptable [20][21].
- Should be exposed as `render(spec, backend="ffmpeg-zoompan", source_upscale=8)`.

**Python — optional 2nd-tier backends:** OpenCV (when already a project dependency, faster), MoviePy v2 (for users wanting clip-graph composition, using `with_effects([Resize(lambda t: …)])` [35]).

**JS/TS — primary: Remotion `interpolate` + `Easing`** [12][13]. Rationale:
- Native frame-by-frame model maps 1:1 to a `t → Rect` evaluator.
- `interpolate(frame, inputRange, outputRange, { easing })` *is* the abstraction we want.
- Renders to MP4/WebM/GIF via Lambda or local Chrome [43][44].
- Big ecosystem, very active development.

**JS/TS — optional realtime: CSS `@keyframes` with `transform: scale() translate()` + `transform-origin`** [15][29]. Generate a stylesheet from a `BurnsPath`; GPU-composited; no render server needed.

### Coordinate / representation convention to adopt

1. **Rect representation:** `Rect(x, y, w, h)` with **normalized [0,1]** floats, **top-left origin**, y-down. Matches `videopython.BoundingBox` [6], CSS `transform-origin` semantics [15], and FFmpeg's coordinate origin [5].
2. **Containment invariant:** `0 ≤ x, y` and `x + w ≤ 1` and `y + h ≤ 1`, validated at construction. Following `videopython`'s validator [6].
3. **Aspect-ratio invariant:** `w / h == output_aspect_ratio`. This must be checked against the *output frame*, not the input image — Apple's FCP doc says this explicitly [18].
4. **Zoom semantics:** *window-fraction*, i.e. expose `w` and `h` as the user-facing parameters; provide `zoom = 1 / max(w, h)` as a derived read-only property. Aligns with iMovie/FCP UI [1][3]; FFmpeg's magnification can be computed on demand for the backend.
5. **Timing function:** accept either (a) a CSS easing string (`"linear"`, `"ease-in-out"`, `"cubic-bezier(0.42,0,0.58,1)"`) [24]; (b) a callable `f: [0,1] → [0,1]`. Default `"ease-in-out"`, matching FCP's professional default [3].
6. **Path representation:** `BurnsPath(rects: Sequence[Rect], times: Sequence[float] | None = None, interp: Literal["linear","catmull-rom","bezier"] = "linear")` — analogous to Remotion's `interpolate` shape [12]. With `len(rects) == 2`, this collapses to the canonical two-rectangle case.
7. **`BurnsPath.evaluate(t: float) → Rect`** as the single render-agnostic primitive. Pure, deterministic, t-only.
8. **Render facade:** `render(image, path, *, duration, fps, output, backend="auto", **opts)` — dispatches to pluggable backends (`pillow`, `opencv`, `moviepy`, `ffmpeg-zoompan`, `imageio`).

### Vocabulary to adopt (and avoid)

- Use **"path"** (After Effects vocabulary [17]) over "track" or "trajectory."
- Use **"viewport"** and **"crop rect"** interchangeably — both are widely understood; "viewport" is the cleaner CS term, "crop rect" is what NLE users know [1][3].
- Use **"easing"** (CSS / Remotion / GSAP all converge here [24][13][26]) over "tween curve."
- Use **"keyframe"** (universal NLE term [17]) for waypoints.
- Use **"start" / "end"** rectangles (iMovie / FCP [1][3]) for the two-rect special case — not "from"/"to" (less aligned with NLE convention; "from/to" is mostly a GSAP/CSS convention).
- **Avoid** "Burns" as a method name (commercially unwise / awkward); use it only as a class qualifier (e.g., `BurnsPath`). Wikipedia confirms the term is licensed only informally by Apple [4].
- **Avoid** redefining "zoom" as magnification in the user-facing API; reserve the magnification value for the FFmpeg-backend translation layer.

### Essential capabilities a naive design would omit

| Capability | Why essential | Prior-art reference |
|---|---|---|
| **Swap / reverse** | Single operation that flips start/end; appears as a dedicated button in every NLE [1][3]. | iMovie "Swap Start and End Areas" [1] |
| **Hold / dwell segments** | Multi-keyframe paths where a segment has zero motion; supported by AE Hold interpolation [17] and Remotion via repeated outputRange values [12]. | After Effects [17] |
| **Per-axis easing** | A Ken Burns motion frequently wants X to ease differently from W ("zoom slows but pan continues"); AE's separated-dimensions design [17]. | After Effects [17] |
| **Containment validator** | Without it, the "rectangle outside image" bug is silent and the resulting video has black bars or distortion. | videopython [6] |
| **Output-AR enforcement** | Without it, frames are stretched. | FCP doc [18] |
| **Sub-pixel-aware rendering path** | Default must mitigate jitter (upscale source before zoompan, or use float-precision Pillow path). | mko.re [10], StackOverflow [20] |
| **Even-dimension snap** | H.264 yuv420p requires even W and H or encoding fails | MoviePy issue [48] |
| **Frame-sequence output** | Many users want PNG sequences for further editing; FFmpeg-only backends omit this. | Remotion `--sequence` [44] |
| **GIF / WebM output** | Both are needed; H.264 is not enough for blog/UI use. | n/a |
| **`evaluate(t)` exposed publicly** | Without it, the library cannot be unit-tested deterministically and cannot be composed with other animation systems. | Remotion `interpolate` [12] |

---

## Caveats

- **The author's proposed `BurnsPath` is novel in Python.** The subagent survey could not find any actively-maintained PyPI package that exposes a render-agnostic, time-parameterized motion evaluator. This is genuinely a gap, but it means there is no upstream library to defer to for the *core abstraction* — only for *vocabulary* and *coordinate conventions*.
- **The FFmpeg `zoompan` jitter problem is folk-documented, not officially documented.** The official FFmpeg filter docs list parameters and example expressions [5] but say nothing about integer-pixel rounding or jitter mitigation. The widely-cited workaround (`scale=8000:-1` before `zoompan`) comes from blog posts and forum threads [10][20][21], not from FFmpeg developers — though the consensus across independent sources is strong enough to treat it as a de-facto requirement.
- **The 3D Ken Burns research code (sniklaus, pierlj)** [42][27] is **CC-BY-NC-SA (non-commercial)**, so it cannot be a dependency or template for a permissively-licensed library. It is referenced only as evidence of the depth-aware future direction.
- **`react-kenburns`, `react-native-kenburns-view`, `react-ken-burns-video`, `gre/kenburns`, `kenburns-editor`** are all dormant (6–11 years since last release per npm registry; `react-kenburns` specifically last published April 17, 2015) [7]. They are useful as design references but not as live integrations.
- **MoviePy is mid-API-transition.** v2 (current) renames `.resize`/`.crop` to `.resized`/`.cropped`, replaces `clip.fl()` with `clip.transform()`, and requires `with_effects([…])` [34][35]. **MoviePy v2.0.0 was released November 20, 2024**; any code snippet found on the web older than that targets the v1 API and will fail under v2 without changes.
- **CSS `linear()` multi-stop easing** [15] is supported across the latest devices and browser versions since December 2023 (Chrome 113+, Firefox 112+, Safari 17.2+ per MDN); fallback to `cubic-bezier()` is only needed for clients predating December 2023.
- **Apple's iMovie iOS** recently removed the explicit Ken Burns toggle, replacing it with a pinch-gesture-based interaction [49]; the *concept* is unchanged but the UI vocabulary is in flux on mobile.
- **GSAP licensing changed in late 2024.** Webflow acquired GreenSock on October 15, 2024; GSAP is now free for all web use under the Standard "No Charge" GSAP License, whose sole restriction is on tools that "encourage, induce, or materially assist in creating a solution that competes with Webflow's visual animation building capabilities." There is no longer a separate paid business tier. This makes GSAP a safe dependency for almost any commercial library — verify only that your product is not a Webflow competitor.

## REFERENCES

[1] [Add the Ken Burns effect in iMovie on Mac — Apple Support](https://support.apple.com/guide/imovie/add-the-ken-burns-effect-movc6e02f503/mac)
[2] [Modify crop, rotation, or Ken Burns effects in iMovie on Mac — Apple Support](https://support.apple.com/guide/imovie/modify-crop-rotation-or-ken-burns-effects-mov26d3f6a6c/mac)
[3] [Pan and zoom clips in Final Cut Pro for Mac — Apple Support](https://support.apple.com/guide/final-cut-pro/pan-and-zoom-clips-verb8e5de9c/mac)
[4] [Ken Burns effect — Wikipedia](https://en.wikipedia.org/wiki/Ken_Burns_effect)
[5] [zoompan filter — FFmpeg Filters Documentation](https://ffmpeg.org/ffmpeg-filters.html#zoompan-1)
[6] [Effects (KenBurns, BoundingBox) — videopython documentation](https://videopython.com/api/effects/)
[7] [keywords:kenburns — npm](https://www.npmjs.com/search?q=keywords:kenburns)
[8] [kenburns-editor — GitHub (gre)](https://github.com/gre/kenburns-editor)
[9] [The Ken Burns Effect Using CSS Animations — kirupa.com](https://www.kirupa.com/html5/ken_burns_effect_css.htm)
[10] [Ken Burns Effect Slideshows with FFMpeg — mko.re](https://mko.re/blog/ken-burns-ffmpeg/)
[11] [Crop to 16:9 and zoom with maximal quality — ImageMagick Forum (Fred Weinhaus / Anthony Thyssen)](https://jqmagick.imagemagick.org/discourse-server/viewtopic.php?f=1&t=24898)
[12] [interpolate() — Remotion docs](https://www.remotion.dev/docs/interpolate)
[13] [interpolate.ts source — remotion-dev/remotion on GitHub](https://github.com/remotion-dev/remotion/blob/main/packages/core/src/interpolate.ts)
[14] [Easing — Remotion docs](https://www.remotion.dev/docs/easing)
[15] [animation-timing-function — MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/animation-timing-function)
[16] [Ken Burns Effect — Complete Guide and How to Apply It — Cloudinary](https://cloudinary.com/guides/image-effects/ken-burns-effect-complete-guide-and-how-to-apply-it)
[17] [Keyframe interpolation in After Effects — Adobe Help](https://helpx.adobe.com/after-effects/using/keyframe-interpolation.html)
[18] [Final Cut Pro X: Create a Ken Burns Effect — Larry Jordan](https://larryjordan.com/articles/final-cut-pro-x-create-a-ken-burns-effect/)
[19] [Ken Burns: change aspect ratio — Creative COW](https://creativecow.net/forums/thread/ken-burns-change-aspect-ratio/)
[20] [ffmpeg: smooth zoompan with no jiggle — DataRecoveryUnion](https://www.datarecoveryunion.com/video-ffmpeg-smooth-zoompan-with-no-jiggle/)
[21] [How to Create Videos with a Ken Burns Effect using FFmpeg — Bannerbear](https://www.bannerbear.com/blog/how-to-do-a-ken-burns-style-effect-with-ffmpeg/)
[22] [Pillow 2.7.0 release notes — Pillow Documentation](https://pillow.readthedocs.io/en/stable/releasenotes/2.7.0.html)
[23] [Resize images with Python, Pillow — note.nkmk.me](https://note.nkmk.me/en/python-pillow-image-resize/)
[24] [CSS Timing Functions Level 1 — W3C Working Draft](https://www.w3.org/TR/2017/WD-css-timing-1-20170221/)
[25] [cubic-bezier() — CSS-Tricks Almanac](https://css-tricks.com/almanac/functions/c/cubic-bezier/)
[26] [CustomEase — GSAP Documentation](https://gsap.com/docs/v3/Eases/CustomEase/)
[27] [pierlj/ken-burns-effect — 3D Ken Burns + dolly zoom](https://github.com/pierlj/ken-burns-effect)
[28] [Understanding Keyframe Interpolation in Adobe After Effects — PremiumBeat](https://www.premiumbeat.com/blog/understanding-keyframe-interpolation-after-effects/)
[29] [Pure CSS Slideshow With Ken Burns Effect — CSS Script](https://www.cssscript.com/pure-css-slideshow-ken-burns-effect/)
[30] [Animation with SRT — ImageMagick (Alan Gibson "snibgo")](https://im.snibgo.com/animsrt.htm)
[31] [Zoom & rotate animation — ImageMagick Discussions #4443](https://github.com/ImageMagick/ImageMagick/discussions/4443)
[32] [ImageMagick Command-line Options (-define distort:scale, -distort SRT)](https://imagemagick.org/script/command-line-options.php)
[33] [Pillow Performance — python-pillow.github.io](https://python-pillow.github.io/pillow-perf/)
[34] [Updating from v1.X to v2.X — MoviePy documentation](https://zulko.github.io/moviepy/getting_started/updating_to_v2.html)
[35] [Modifying clips and apply effects — MoviePy documentation](https://zulko.github.io/moviepy/user_guide/modifying.html)
[36] [moviepy.video.fx.Resize — MoviePy documentation](https://zulko.github.io/moviepy/reference/reference/moviepy.video.fx.Resize.html)
[37] [Pillow 2.7.0 (2014-12-31) release notes](https://pillow.readthedocs.io/en/stable/releasenotes/2.7.0.html)
[38] [Python PIL Image.resize() — GeeksforGeeks](https://www.geeksforgeeks.org/python/python-pil-image-resize-method/)
[39] [Resampling Filters (Pillow) — 1Cademy](https://1cademy.com/node/resampling-filters-pillow/mnLtyVhBvLrzHaiHttwQ)
[40] [ffmpeg-python: Python bindings for FFmpeg](https://kkroening.github.io/ffmpeg-python/)
[41] [Trekky12/kburns-slideshow — GitHub](https://github.com/Trekky12/kburns-slideshow)
[42] [sniklaus/3d-ken-burns — GitHub](https://github.com/sniklaus/3d-ken-burns)
[43] [@remotion/lambda — Remotion docs](https://www.remotion.dev/docs/lambda)
[44] [Render your video — Remotion docs](https://www.remotion.dev/docs/render)
[45] [An introduction to animations with GSAP — Zell Liew](https://zellwk.com/blog/gsap/)
[46] [Zoom makes movie jitter? — LRTimelapse forum](https://forum.lrtimelapse.com/Thread-zoom-makes-movie-jitter?page=2)
[47] [FCPX jittery stills using Ken Burns — Apple Community](https://discussions.apple.com/thread/7999496)
[48] [Zoom-In Effect for moviepy — GitHub Issue #1402](https://github.com/Zulko/moviepy/issues/1402)
[49] [How can I start the Ken Burns from current clip's crop — Apple Community](https://discussions.apple.com/thread/254964721)