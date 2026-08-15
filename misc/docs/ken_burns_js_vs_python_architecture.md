# Ken Burns: JS/TS-Only vs. Python+JS/TS Hybrid — An Architecture & Trade-off Report

*Author: Thor Whalen*
*Date: 28 May 2026*

> **Who this is for.** This report is written to be handed to a coding agent that will refactor an existing Python Ken Burns implementation into a system that offers **both** Python (server-side) and JS/TS (client-side) tooling. It lays out where each pipeline stage *can* run, the pros and cons of each deployment model, the cross-cutting technical traps, and a recommended architecture that lets one motion specification drive every backend. Sections 7–9 are the actionable contracts; sections 2–6 are the reasoning behind them.

---

## 1. Executive summary

- **The expensive stage (video encoding) is avoidable for most usage.** Ken Burns *playback* is a GPU-composited CSS transform — no rasterization, no encoding, no server. You only need to render a video file when the user wants a *downloadable artifact*. Designing around this single fact is the largest server-offload win available [1][9].
- **"JS/TS only" is two different topologies.** Client-side JS/TS (runs in the user's browser, offloads the server) and Node/serverless JS/TS (e.g. Remotion's headless-Chrome renderer — same language, but it *is* the server load you are trying to shed) [12][13]. Conflating them is the most common architectural mistake here.
- **The hybrid's real cost is keeping two language implementations in sync.** The motion math is trivial to dual-implement; the risk is that the JS preview and the Python (or JS) export disagree on how a normalized rectangle maps to output pixels. The fix is a single serializable spec plus golden-vector tests (Section 6).
- **Recommended shape:** one render-agnostic spec (`BurnsPath` → `evaluate(t) → Rect`), implemented identically in Python and TS, consumed by *pluggable, injected* render backends. Default client path: CSS transform for preview, **WebCodecs** for export. Default server path: reuse the existing Python (Pillow/FFmpeg). Route between them by capability and scale, not by default (Section 8).

---

## 2. Decompose the pipeline first (the cost asymmetry is everything)

Every Ken Burns implementation, in any language, is the same five stages. They differ by *orders of magnitude* in cost, which is why "where do I run Ken Burns" has no single answer — you place each stage independently.

| # | Stage | What it does | Relative cost | Naturally lives… |
|---|---|---|---|---|
| 1 | **Spec authoring** | Build the `BurnsPath` (start/end rects, easing, duration, fps) | ~0 (pure data) | Anywhere; ideally client (interactive) |
| 2 | **Preview / scrub** | Show the motion live | ~0 (GPU composite) | **Client, always** |
| 3 | **Rasterization** | Sample the image at the viewport `Rect` for each frame `t` | Moderate (one resize/draw per frame) | Client or server |
| 4 | **Encoding** | Frames → MP4 / WebM / GIF | **High** (the real bill) | Client or server |
| 5 | **Delivery / storage** | Hand the file to the user / CDN | I/O-bound | Server or client-direct |

The decisive observation: **stages 1–2 never require stages 3–4.** A browser plays the effect natively by animating `transform: scale() translate()` on an over-sized image inside an `overflow:hidden` container [1][9]. If a large fraction of your usage is "display this photo with motion," that path touches no server at all. Encoding is only triggered by an explicit "export/download/share-as-file" intent.

---

## 3. The three deployment models

### Model A — JS/TS only, client-side (browser does everything)

The browser authors the spec, previews via CSS, rasterizes to a canvas, and encodes to a file locally. The "server" is just static hosting / a CDN.

**Encoding options in the browser, best to worst for this use case:**

| Mechanism | How it works | Output | Quality | Notes |
|---|---|---|---|---|
| **WebCodecs `VideoEncoder`** | HW-accelerated encode of canvas frames; you drive the clock, not real time | H.264 / VP9 / AV1 *chunks* | Good–excellent | **Encode-only — you must mux chunks into a container yourself** (`mp4-muxer`, `webm-muxer`) [2][3]. The modern, correct choice. |
| **`MediaRecorder` + `canvas.captureStream()`** | Records the canvas as it plays | WebM (VP8/VP9) | Middling | **Real-time-locked** (a 10 s clip takes 10 s); simplest to write. |
| **`ffmpeg.wasm`** | Native FFmpeg compiled to WASM; runs `zoompan` or frame-piping | Anything FFmpeg supports | Inherits `zoompan` jitter [10] | ~25 MB download, slow, single-threaded-ish. Last resort. |
| **GIF**: `gifenc` / `gif.js` | Quantize + encode frames | GIF | Low (256 colors) | Neither WebCodecs nor MediaRecorder does GIF; needs a dedicated lib. |

**Pros**
- Zero server compute for the expensive stage; scales to infinity because the cost is the *user's* device.
- No source-image upload: lower latency, better privacy, no egress.
- Preview and export share one codebase and one language.

**Cons**
- Quality and speed vary by device; not bitwise-deterministic across clients.
- WebCodecs codec/container support has edges; you own the muxing [2][3].
- Heavy for `ffmpeg.wasm`; battery/thermal cost on mobile for long clips.
- No batch/headless automation; no programmatic pipeline; no depth-aware 3D Ken Burns [42].

### Model B — JS/TS only, server-rendered (Node / serverless)

Same language top-to-bottom, but rendering happens on a server. The canonical example is **Remotion**, which renders React compositions via headless Chromium, locally or on Lambda / Cloud Run [12][13].

**Pros**: deterministic, high quality, one language across the stack, strong ecosystem, the `interpolate(frame, inputRange, outputRange, {easing})` primitive is an excellent design reference [13][14].

**Cons**: it is the *opposite* of offloading — a headless browser per render is heavy; cost scales with render count; cold starts; licensing is per-company for Remotion. Use it when you want JS everywhere *and* are willing to pay for server rendering — not when the goal is to relieve the server.

### Model C — Python server + JS/TS client (the hybrid you're targeting)

Client does spec + preview (free); server does canonical rendering in Python, reusing your existing code. Python also owns anything heavy or programmatic: batch jobs, automation, and depth-aware 3D Ken Burns via PyTorch [42][27].

**Pros**
- **Reuses your existing Python investment**; Python is strong for batch/programmatic/CLI/pipeline use.
- Deterministic, high-quality canonical renders (Pillow `LANCZOS` per-frame, or FFmpeg) [22][33].
- The only viable home for depth-aware 3D parallax [42].
- Client still gets free preview, so the server is only hit on explicit export.

**Cons**
- **Two languages ⇒ two implementations of the spec to keep in sync** (Section 6 — this is the defining tax of the hybrid).
- Server compute cost for actual encodes; source-image upload latency.
- More deployment surface (web client + Python service).

---

## 4. Backend inventory by stage and language

This is the menu the refactoring agent is choosing from. "Jitter-free" means the approach computes geometry in floating point and never integer-rounds per frame.

| Stage | Python options | JS/TS options | Jitter behaviour |
|---|---|---|---|
| **Preview (2)** | — (not Python's job) | CSS `transform` on `<img>` [1][9]; WebGL texture | Jitter-free (GPU) |
| **Rasterize (3)** | Pillow `resize`+`crop` (LANCZOS) [22]; OpenCV `cv2.resize`/`warpAffine`; NumPy | Canvas2D `drawImage(img, sx,sy,sw,sh, …)`; WebGL/WebGPU texture sampling; `OffscreenCanvas` in a Worker | Float source coords ⇒ jitter-free |
| **Encode (4)** | imageio-ffmpeg; FFmpeg via `ffmpeg-python`; MoviePy v2 `with_effects([...])` [34][35]; FFmpeg `zoompan` fast-path [5] | WebCodecs `VideoEncoder` + `mp4-muxer`/`webm-muxer` [2][3]; `MediaRecorder`; `ffmpeg.wasm` | `zoompan` integer-rounds (mitigate by 4–10× source upscale) [10][20]; frame-pipe paths are jitter-free |
| **3D / depth (3–4)** | `sniklaus/3d-ken-burns`, `pierlj/ken-burns-effect` (PyTorch+CUDA, **non-commercial license**) [42][27] | — | n/a |

**Two practical traps the agent must internalize:**

1. **WebCodecs is encode-only.** `VideoEncoder` emits `EncodedVideoChunk`s, not a playable file. You *must* mux into MP4 or WebM with a separate library (`mp4-muxer`, `webm-muxer`) [2][3]. A frontend-novice consumer will not expect this; it is the #1 source of "the export produces a corrupt file" bugs.
2. **Do encoding off the UI thread.** Use `OffscreenCanvas` + a Web Worker so rasterize+encode doesn't jank the page during export.

---

## 5. Cross-cutting technical issues (apply to every model)

These are invariants from the core research that survive regardless of language or topology:

- **Aspect-ratio invariant:** the crop rect's AR must equal the **output frame's** AR (not the input image's), or frames stretch [18]. Validate at spec construction.
- **Containment:** the rect must stay inside the image (`0 ≤ x,y` and `x+w ≤ 1`, `y+h ≤ 1`) [6].
- **Even dimensions:** H.264/yuv420p encoders require even width/height; snap output dims [48]. Applies to FFmpeg, WebCodecs H.264, everything.
- **Default easing is `ease-in-out`, not linear** — the cinematic/professional default [3]. CSS `cubic-bezier` strings are the cross-ecosystem lingua franca and are understood by CSS, Remotion `Easing.bezier`, and GSAP `CustomEase` alike [24][14][26].
- **Jitter mitigation differs by backend:** GPU/CSS and float-based canvas/Pillow paths are inherently jitter-free; only FFmpeg `zoompan` needs the source-upscale workaround [10][20]. Prefer float-based rasterization and you sidestep the whole problem.
- **Determinism asymmetry:** server FFmpeg/Pillow output is reproducible and cacheable; client WebCodecs output is *not* bitwise-identical across devices. This matters if you plan to dedupe/cache rendered assets by spec hash — you can only safely do that for server renders.
- **Color/gamma:** canvas and Pillow can differ subtly in color management. If preview-vs-export color fidelity matters, pin a color space.

---

## 6. The defining hybrid problem: keeping Python and JS/TS in sync

If you offer Ken Burns in both languages, you have two implementations of the same effect, and they **must** agree. The good news: the part that's easy to get wrong is small and testable.

**What must agree, in order of risk:**

1. **The `Rect → output-pixels` mapping (highest risk).** Given a normalized `Rect(x,y,w,h)` and an output size, *exactly* which source pixels fill which output pixels? The CSS-transform preview, the canvas `drawImage` export, and the Pillow `crop+resize` export must all compute this identically (same "cover" fit, same origin handling, same rounding). Disagreement here means **your preview lies about your export** — the worst possible bug because it's invisible until users compare.
2. **`evaluate(t)` — the interpolation math (low risk).** Lerp of rect components + easing application. Trivial, but must use the same easing definitions (use CSS `cubic-bezier` constants verbatim [24]).
3. **The spec serialization (low risk).** One JSON shape, ideally versioned and schema-validated.

**Strategy — single source of truth across languages:**

- Define the spec as **one schema** (JSON Schema, or Pydantic-on-Python with a generated TS type). The spec is plain data and travels client↔server as JSON.
- Implement `evaluate(t)` and the `Rect→pixels` mapping **independently in each language** (they're short) rather than bridging — but treat one as canonical.
- **Golden-vector tests are the contract.** Generate a fixture: a set of `(spec, t)` inputs and the expected `Rect` outputs, plus a few `(spec, output_size, t)` → expected integer pixel-box outputs. Both the Python and TS test suites assert against the *same* fixture file. This is the SSOT mechanism that actually holds two languages together — the fixture is the source of truth, the code merely conforms.

This directly serves the design values in the existing codebase: the spec is the SSOT, the backends are injected strategies (open-closed), and the fixture pins behavioural equivalence without coupling the implementations.

---

## 7. Recommended architecture

A layered design with the spec as a pure data core and rendering as injected, pluggable strategies:

```
            ┌─────────────────────────────────────────────┐
            │  SPEC  (pure data, language-mirrored, JSON)  │
            │  Rect(x,y,w,h)  ·  BurnsPath.evaluate(t)→Rect│  ← SSOT (+ golden vectors)
            └─────────────────────────────────────────────┘
                 │                                   │
        ┌────────▼─────────┐               ┌─────────▼──────────┐
        │  CLIENT (JS/TS)  │               │  SERVER (Python)   │
        │                  │               │                    │
        │ preview: CSS xform (free)        │ render backends:   │
        │ export:                          │  · Pillow + imageio│
        │  · WebCodecs+muxer (default)     │  · FFmpeg (fast)   │
        │  · MediaRecorder (fallback)      │  · zoompan (opt.)  │
        │  · ffmpeg.wasm (last resort)     │  · 3D/PyTorch (opt)│
        └──────────────────┘               └────────────────────┘
                 ▲                                   ▲
                 └──── same spec JSON crosses the wire ────┘
```

**Backend interface (the open-closed seam).** Every renderer is a strategy with the same shape, so adding one never edits existing code:

*Python:*
```python
class RenderBackend(Protocol):
    def render(
        self, image, path: BurnsPath, *, duration: float, fps: int, output: str, **opts
    ) -> bytes | str: ...


# registry: {"pillow": ..., "ffmpeg": ..., "zoompan": ..., "kb3d": ...}
# facade picks/injects: render(image, path, backend="auto", ...)
```

*TS:*
```ts
interface RenderBackend {
  render(image: ImageBitmap, path: BurnsPath,
         opts: { durationMs: number; fps: number; format: 'mp4'|'webm'|'gif' })
    : Promise<Blob>;
}
// registry: { webcodecs, mediarecorder, ffmpegwasm }
```

**Progressive disclosure** (matches the rest of the ecosystem [12][26]): a one-liner for the common case, full control underneath.
```python
ken_burns(img, zoom=1.3, to="center")  # 90% case
render(
    img,
    BurnsPath(start, end, easing="ease-in-out"),  # full control
    duration=5,
    fps=30,
    output="out.mp4",
    backend="ffmpeg",
)
```

---

## 8. Decision matrix — which model, when

| Use case | Recommended model | Why |
|---|---|---|
| Display photo-with-motion in a web UI | **A — client CSS, no encode** | Free, instant, no server [1][9] |
| User downloads a short clip, modern browser | **A — client WebCodecs + muxer** | Offloads encode entirely; good quality [2] |
| User downloads, old browser / no WebCodecs | **C — Python server FFmpeg** (fallback) | Deterministic, device-independent |
| Guaranteed-identical output / cacheable by spec hash | **C — Python server** | Only server renders are reproducible (Section 5) |
| Batch / programmatic / CLI / pipelines | **C — Python** | Reuses existing code; Python's strength |
| 3D depth parallax | **C — Python GPU** | Only viable home [42]; non-commercial license caveat |
| Want one language everywhere, will pay for renders | **B — Remotion** | JS top-to-bottom, but server-heavy [12] |
| GIF export | A (`gifenc`) for short; C (FFmpeg) for quality | Neither WebCodecs nor MediaRecorder does GIF |

**The pragmatic default for an offload-oriented app:** client-side spec + CSS preview always; client WebCodecs export as the default; Python server FFmpeg as the capability/scale fallback. The spec JSON is what crosses the wire; the server reuses your existing code largely unchanged behind the backend interface.

---

## 9. Concrete contracts for the refactoring agent

**Spec JSON (the wire format and SSOT):**
```json
{
  "version": 1,
  "keyframes": [
    { "t": 0.0, "rect": { "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.281 } },
    { "t": 1.0, "rect": { "x": 0.3, "y": 0.2, "w": 0.25, "h": 0.141 } }
  ],
  "interp": "linear",
  "easing": "ease-in-out",
  "output_aspect": 1.7777
}
```
- `rect` is normalized `[0,1]`, top-left origin, y-down — matches `videopython.BoundingBox` [6], CSS `transform-origin` semantics [15], and FFmpeg's coordinate origin [5].
- Two keyframes = the canonical Start/End case [1][3]; N keyframes generalizes it (Remotion-style input/output ranges [12]).
- `easing` is a CSS string (`"ease-in-out"`, `"cubic-bezier(...)"`, `"linear"`) or, in code, an injected callable.

**Pure evaluator contract (mirror in both languages):**
```
evaluate(t: float) -> Rect      # t ∈ [0,1]; deterministic; no I/O; no frame count
viewport(t_clock) = path(easing(t_clock))   # timing composed over geometry (AE-style split [17])
```

**Invariants to validate at construction (both languages):**
- `rect.w / rect.h == output_aspect` (AR matches OUTPUT, not image) [18]
- `0 ≤ x,y` and `x+w ≤ 1`, `y+h ≤ 1` (containment) [6]
- output width/height snapped to even integers before encode [48]

**Golden-vector fixture (the equivalence contract):** a checked-in JSON of `(spec, t) → expected rect` and `(spec, output_size, t) → expected pixel box`, asserted by *both* test suites (Section 6).

**Backend registry:** Python `{"pillow","ffmpeg","zoompan","kb3d"}`; TS `{"webcodecs","mediarecorder","ffmpegwasm"}`; facade chooses via `backend="auto"` based on capability + clip size.

---

## 10. Migration notes given the existing Python code

1. **Extract the spec from the renderer.** Whatever currently computes the per-frame rectangle becomes `BurnsPath.evaluate(t)`, pure and frame-count-free. Everything that touches Pillow/FFmpeg becomes a `RenderBackend` behind the Protocol.
2. **Pin the `Rect→pixels` mapping** as a single tested function; this is what the TS side must replicate. Emit golden vectors *from the existing Python* so the new JS conforms to current behaviour (no visual regression).
3. **Keep FFmpeg `zoompan` as an optional fast-path only**, with the source-upscale jitter mitigation baked in [10][20]; make a float-based Pillow/imageio path the quality default.
4. **Generate the TS spec type from the Python schema** (Pydantic → JSON Schema → TS) so the wire format has one author.
5. **Don't port the encoder.** The client encoder (WebCodecs) and server encoder (FFmpeg) are *different by design*; only the spec and the `Rect→pixels` mapping are shared.

---

## REFERENCES

[1] [Add the Ken Burns effect in iMovie on Mac — Apple Support](https://support.apple.com/guide/imovie/add-the-ken-burns-effect-movc6e02f503/mac)
[2] [WebCodecs API — MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/API/WebCodecs_API)
[3] [VideoEncoder — MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/API/VideoEncoder)
[5] [zoompan filter — FFmpeg Filters Documentation](https://ffmpeg.org/ffmpeg-filters.html#zoompan-1)
[6] [Effects (KenBurns, BoundingBox) — videopython documentation](https://videopython.com/api/effects/)
[9] [The Ken Burns Effect Using CSS Animations — kirupa.com](https://www.kirupa.com/html5/ken_burns_effect_css.htm)
[10] [Ken Burns Effect Slideshows with FFMpeg — mko.re](https://mko.re/blog/ken-burns-ffmpeg/)
[12] [interpolate() — Remotion docs](https://www.remotion.dev/docs/interpolate)
[13] [interpolate.ts source — remotion-dev/remotion (GitHub)](https://github.com/remotion-dev/remotion/blob/main/packages/core/src/interpolate.ts)
[14] [Easing — Remotion docs](https://www.remotion.dev/docs/easing)
[15] [animation-timing-function — MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/animation-timing-function)
[17] [Keyframe interpolation in After Effects — Adobe Help](https://helpx.adobe.com/after-effects/using/keyframe-interpolation.html)
[18] [Final Cut Pro X: Create a Ken Burns Effect — Larry Jordan](https://larryjordan.com/articles/final-cut-pro-x-create-a-ken-burns-effect/)
[20] [ffmpeg: smooth zoompan with no jiggle — DataRecoveryUnion](https://www.datarecoveryunion.com/video-ffmpeg-smooth-zoompan-with-no-jiggle/)
[22] [Pillow 2.7.0 release notes (convolution-based resampling) — Pillow docs](https://pillow.readthedocs.io/en/stable/releasenotes/2.7.0.html)
[24] [CSS Timing Functions Level 1 — W3C](https://www.w3.org/TR/2017/WD-css-timing-1-20170221/)
[26] [CustomEase — GSAP Documentation](https://gsap.com/docs/v3/Eases/CustomEase/)
[27] [pierlj/ken-burns-effect — 3D Ken Burns + dolly zoom (GitHub)](https://github.com/pierlj/ken-burns-effect)
[33] [Pillow Performance — python-pillow.github.io](https://python-pillow.github.io/pillow-perf/)
[34] [Updating from v1.X to v2.X — MoviePy documentation](https://zulko.github.io/moviepy/getting_started/updating_to_v2.html)
[35] [Modifying clips and apply effects — MoviePy documentation](https://zulko.github.io/moviepy/user_guide/modifying.html)
[42] [sniklaus/3d-ken-burns — GitHub](https://github.com/sniklaus/3d-ken-burns)
[48] [Zoom-In Effect for moviepy — GitHub Issue #1402](https://github.com/Zulko/moviepy/issues/1402)
