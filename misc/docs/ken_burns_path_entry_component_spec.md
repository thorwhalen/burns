# Ken Burns Path-Entry Component — Specification

*Author: Thor Whalen*
*Date: 28 May 2026*

> A specification for a **headless, schema-first UI component** that lets a user upload an image, define a Ken Burns motion path (in its simplest "Start rect → End rect" form, with presets for the common cases), and emit a serializable spec the host application can submit to any rendering backend. The component owns *interaction logic and state*, not look-and-feel; it ships with a default renderer that hosts may replace.
>
> This document describes *what* to build, not *how*. The output spec emitted by this component is the same `BurnsPath` JSON described in the architecture report (one source of truth across Python and JS/TS).

---

## 1. Goals and non-goals

**Goals**

- A **standalone**, **drop-in** path-entry control: any host app (React, Vue, vanilla, plain HTML page) can mount it, wire its input/output, and obtain a valid `BurnsPath` spec on submit.
- **Schema-first** (zodal): all inputs, outputs, and configuration are described by zod schemas, with an exported JSON Schema for non-TS consumers.
- **Renderer-agnostic** ("headless"): zero hard-coded styling, zero framework lock-in in the core; a default renderer is provided for out-of-the-box use and is *meant to be replaceable*.
- Cover the high-value common cases (presets) with one click; allow full custom path entry as the fallback.
- The output spec is **backend-agnostic** — the same JSON drives the Python (Pillow / FFmpeg) renderer, a JS WebCodecs renderer, or any other.

**Non-goals**

- Video preview / encoding / playback. Those belong to the host app or to a separate companion component. This component emits a spec; it does not call the renderer.
- Multi-keyframe (3+) paths, rotation, per-axis easing, depth-aware (3D) Ken Burns. Reserve schema room (Section 6), do not implement now.
- Upload pipeline, drag-and-drop file management, image storage. The host supplies an already-resolved image reference (URL, Blob, ImageBitmap, or pixel dimensions + URL — host's choice, schema-validated).

---

## 2. Architectural pattern: headless logic + adapter renderers

**"Headless"** here means the [TanStack / Downshift / Radix Primitives sense](https://www.radix-ui.com/primitives) of the word: the component is a pure state-and-behaviour core with no markup or styling of its own. Concretely:

- The **core** is a framework-free TypeScript module exposing:
  - zod schemas for `Config`, `Value` (the `BurnsPath` emitted), and the internal `State`.
  - A small reducer / state machine over `State` (events in, new state out — pure functions).
  - Pure geometry helpers (`Rect`, `evaluate(t) → Rect`, AR-lock math, containment clamp).
  - No DOM, no React, no event listeners.
- A **renderer adapter** wraps the core for a specific environment (vanilla DOM, React, Vue, …). The adapter owns DOM/markup, pointer/keyboard event wiring, and visual styling; it talks to the core only through the core's typed events and state.

The shipping default is a **vanilla DOM/TS renderer**. This is feasible — the only non-trivial interaction (drag-resize an aspect-ratio-locked rectangle over an image, with an inside-bright / outside-dim mask) is well-precedented in vanilla by [`cropperjs`](https://github.com/fengyuanchen/cropperjs) and similar libraries, in well under a few hundred lines. Hosts who want React/Vue/Svelte either consume the vanilla renderer in a thin wrapper or implement their own adapter against the core. Documentation must point both at the "bring your own renderer" path and at one example wrapper for reference.

The zodal layering, top to bottom:

```
zod schemas (Config, Value, State)         ← contract, JSON-Schema-exportable
   ↓
core state machine + geometry (pure TS)    ← headless logic
   ↓
renderer adapter (vanilla DOM = default)   ← swappable
   ↓
host application                           ← consumes Value, calls the renderer
```

The boundary between core and adapter is the only stable API; everything below the boundary is replaceable.

---

## 3. Configuration (host-provided, zod-validated)

The host instantiates the component with a `Config` object. Every field that the host *can* fix in advance must be lockable so the in-UI control disappears or becomes read-only; this is essential for embedding the component in larger flows where the target video format is already known.

| Field | Type | Purpose |
|---|---|---|
| `image` | `{ src: string, width: number, height: number }` (or equivalent — settle in zod) | The image to author over. Pixel dimensions are required (they're the SSOT for AR-from-image and for converting normalized coords to host-display pixels). |
| `targetAspect` | `{ num: number, den: number, locked: boolean }` \| `"match-image"` \| `undefined` | The output video's aspect ratio. **`locked: true`** hides the editor; **`"match-image"`** sets it from the image's pixel dimensions on mount; **`undefined`** means the user picks. |
| `duration` | `{ defaultMs: number, minMs?, maxMs?, editable: boolean }` | Default 4000–6000 ms is typical for Ken Burns. Hostable as fixed. |
| `easing` | `{ default: EasingId, editable: boolean, options?: EasingId[] }` | `EasingId` ∈ `"linear" \| "ease-in" \| "ease-out" \| "ease-in-out" \| `cubic-bezier(...)` string`. Default: **`ease-in-out`** (the cinematic and Final Cut Pro default). |
| `presets` | `Preset[]` \| `"default"` | The set of named presets shown (Section 5). `"default"` ships the built-in catalog. |
| `allowCustom` | `boolean` | Whether the "Custom (two rects)" mode is offered. Default `true`. |
| `dualView` | `"side-by-side" \| "overlay" \| "tabbed"` | How the Start and End rects are presented (Section 4.2). Default `"side-by-side"`. |
| `i18n` | `Record<string, string>` | Label/tooltip overrides. |
| `theme` | `unknown` (renderer-specific) | Passed through to the renderer; ignored by core. |

The `Config` schema is the host-facing contract and must be stable across renderer changes.

---

## 4. The path-entry interaction

### 4.1 Resolving the target aspect ratio

The crop rectangles' aspect ratio is determined by the **output video's** AR, **not** the input image's — this is the hard invariant from professional NLEs (Final Cut Pro's documentation states the Ken Burns effect "creates video that must fully fill the frame at all times"). The component must:

1. If `targetAspect` is provided and `locked`, use it. The AR control is hidden / read-only.
2. If `targetAspect === "match-image"`, compute `num / den` from `image.width / image.height` (in raw pixels — pixel ratio is the most precise expression of the image's AR).
3. Otherwise present an AR control: two integer inputs (numerator, denominator), with a "Use image dimensions" button that fills them with the image's pixel `width` and `height`. Validate `num > 0`, `den > 0`. Display the simplified form alongside (e.g. `1920 × 1080 → 16:9`) but keep the entered values as the truth.

The component **must not assume `output AR == image AR`**; the backend must (and per the architecture report, does) support the general case where they differ. When they differ, the largest "zoomed-out" rectangle of the target AR that fits inside the image is the cap on the user's zoom-out — this is the *containment constraint* (see 4.3).

### 4.2 Choosing a preset or going custom

A **preset** is a parameterised template that takes 0 or 1 user-supplied rectangles and yields the full `(startRect, endRect)` pair. The set is configurable via `Config.presets`, with a sensible default catalog (Section 5).

The selection UI is a row of labelled icons. Picking a preset:

- Shows the appropriate authoring surface (0, 1, or 2 rectangles to draw).
- Pre-fills any preset-specific parameters (e.g. zoom percentage) with sane defaults the user can adjust.
- Recomputes the derived rectangle(s) live as the user edits.

A "Custom" entry, if `allowCustom`, lets the user draw both Start and End rects directly (Section 4.3).

### 4.3 Drawing rectangles on the image

This is the cropper-style interaction; the established convention (`cropperjs`, `react-image-crop`, `react-easy-crop`, iMovie, Final Cut Pro) is well-known and should not be reinvented.

**Visual contract:**

- Display the source image at a host-chosen size (scale is irrelevant to the spec because coordinates are normalised).
- The rectangle is drawn as a bright window over a **darkened overlay** (alpha ≈ 0.55–0.70 — the image stays barely visible outside, focus is the rect). This "matte" framing is the iMovie/FCP convention.
- Handles on the four corners and (optionally) the four edge midpoints. **Aspect ratio is locked** to the resolved `targetAspect`, so all handle drags scale uniformly — there is no axis-independent resize.
- A subtle rule-of-thirds grid inside the rect, common in cropper UIs, is recommended.

**Interaction contract:**

- Click-drag on the image canvas (no existing rect) → create a new rect anchored at the down-point.
- Drag inside the rect → translate (pan) the rect.
- Drag a handle → scale uniformly (AR-locked).
- Keyboard arrows (with rect focused) → 1-pixel nudge; with Shift → 10-pixel nudge.
- All operations are **clamped to the containment constraint**: the rect must satisfy `0 ≤ x, y` and `x + w ≤ 1` and `y + h ≤ 1` in normalised coordinates. The clamp happens in the core, not the renderer.
- A small readout shows the current rect in some human-legible form (e.g. `x: 12%  y: 18%  zoom: 1.8×`). "Zoom" here is **window-fraction-based** (`1 / max(w, h)`) — i.e. matches what every NLE shows — not magnification.

**Layout of the two rectangles** depends on `Config.dualView`:

- `"side-by-side"` (default): two copies of the image laid out left/right, the Start rect on the left copy, the End rect on the right copy. Simplest for non-expert users; matches the user's preferred layout from the conversation.
- `"overlay"`: a single image with both rects drawn over it, using the iMovie/FCP convention (green for Start, red for End). More compact, professional-feeling, mildly harder to read.
- `"tabbed"`: one image, a Start/End toggle. Most compact, fine for mobile.

In presets that derive one of the two rectangles (Section 5), only the user-drawn rectangle is interactive; the derived one is shown as a non-interactive ghost in whichever layout is active, so the user can see the motion implied by their choice.

### 4.4 Other parameters

Below the canvas, exposed only when `Config.<field>.editable` is true:

- **Duration** (slider + numeric input, in ms or seconds; default 4000–6000 ms).
- **Easing** (segmented control or dropdown): `linear`, `ease-in`, `ease-out`, `ease-in-out`, plus optionally a custom `cubic-bezier(x1, y1, x2, y2)` entry. Default `ease-in-out`.
  - Note: with only two keyframes, the "linear vs curved *path*" distinction collapses — the spatial path is always a straight line through rect-space. What varies is the *speed profile along the path*, which is exactly the easing. The UI should label this as "Motion speed" or "Easing", not "Linear vs curved", to avoid the confusion of conflating spatial and temporal interpolation (After Effects' canonical split).
- **Reverse / Swap** button: swap Start and End. Matches the dedicated "Swap Start and End Areas" button in iMovie and Final Cut Pro; users expect it.

### 4.5 Submission

A single **Submit** (or "Done" / "Use this path") button finalises the current state and invokes the host's `onSubmit(value)` callback with the `BurnsPath` JSON. The component does not navigate, does not render video, does not encode. Optionally a continuous `onChange(value)` fires on every state change for hosts that want live preview.

---

## 5. Preset catalog (the default set)

Each preset has a stable `id`, a display `label`, a short `description`, an `icon` (recommend `lucide-react`-equivalent names so adapters can pick matching icon families), the number of user-supplied rectangles it takes (`arity ∈ {0, 1, 2}`), and a pure function `derive(userRects, params) → (startRect, endRect)`. The catalog is data — adding a preset is adding an entry, not editing the core.

**Arity-0 presets** (no rectangle drawn; one parameter at most):

- **`zoom-in`** — *Push in to centre.* Start = full image (at target AR, centered); End = centred rectangle of size `1 / zoomFactor`. Param: `zoomFactor` (default 1.3). Icon: `zoom-in`.
- **`zoom-out`** — *Pull out from centre.* Mirror of `zoom-in`. Icon: `zoom-out`.
- **`pan-left-to-right`** — *Slow pan across the image.* No zoom change. Start = left-anchored window of size `1 / zoomFactor`, End = right-anchored window of same size. Param: `zoomFactor` (default 1.2). Icon: `arrow-right`.
- **`pan-right-to-left`** — mirror. Icon: `arrow-left`.
- **`pan-top-to-bottom`** / **`pan-bottom-to-top`** — vertical pans. Icons: `arrow-down` / `arrow-up`.
- **`drift`** — *Subtle drift.* Small random pan + tiny zoom. Param: `intensity` (default 0.05). Icon: `move`.

**Arity-1 presets** (user draws one rect; the other is derived):

- **`push-in-to`** — *Push in to selection.* Start = full image at target AR; End = user's rect. Icon: `crosshair-zoom-in`.
- **`pull-out-from`** — *Pull out from selection.* Start = user's rect; End = full image at target AR. Icon: `crosshair-zoom-out`.
- **`enter-from-left`** — *Enter from off-frame left.* Start = user's rect, translated leftward until it touches the left image edge (within the containment clamp); End = user's rect at its drawn position. Icon: `arrow-right-circle`.
- **`enter-from-right`**, **`enter-from-top`**, **`enter-from-bottom`** — directional analogues.
- **`exit-to-left`**, **`exit-to-right`**, etc. — mirror of the enter family.
- **`reveal-around`** — *Reveal context around subject.* Start = user's rect; End = image (or largest target-AR rect that contains user's rect plus a margin). Icon: `expand`.

**Arity-2 preset** (only one):

- **`custom`** — user draws both. Icon: `pencil`.

The default set is opinionated but explicitly overridable: a host that wants only `push-in-to` and `pull-out-from` passes a two-item `presets` array.

---

## 6. The output spec (`Value` schema)

The emitted value is the same shape used everywhere else in the system — the `BurnsPath` JSON from the architecture report. It is the **single point of contact** between this component and any rendering backend. Versioned, additive, forwards-compatible:

```jsonc
{
  "version": 1,
  "outputAspect": { "num": 16, "den": 9 },
  "keyframes": [
    { "t": 0.0, "rect": { "x": 0.10, "y": 0.10, "w": 0.50, "h": 0.281 } },
    { "t": 1.0, "rect": { "x": 0.30, "y": 0.20, "w": 0.25, "h": 0.141 } }
  ],
  "interp": "linear",
  "easing": "ease-in-out",
  "durationMs": 5000,
  "meta": {
    "presetId": "push-in-to",          // for round-trip editing
    "presetParams": { "zoomFactor": 1.3 }
  }
}
```

Key points:

- `rect` is **normalised `[0, 1]`, top-left origin, y-down** — matches `videopython.BoundingBox`, CSS `transform-origin` semantics, and FFmpeg coordinates. Spec is resolution-independent.
- `w / h` **must equal** `outputAspect.num / outputAspect.den` for every keyframe — invariant validated by the schema.
- All rects satisfy the containment constraint — invariant validated by the schema.
- `interp` is `"linear"` for the present (only two-keyframe paths); the field exists so future multi-keyframe versions can introduce `"catmull-rom"` etc. without a v2.
- `easing` is a CSS-compatible identifier or `cubic-bezier(...)` string — the cross-ecosystem lingua franca (CSS, Remotion, GSAP all accept the same four-number form).
- `meta.presetId` / `meta.presetParams` are **advisory**: they let the same UI re-open a spec in preset mode for further editing without losing the user's intent. Renderers ignore them.

A **JSON Schema** is generated from the zod schema and shipped alongside, so non-TS consumers (Python validation, OpenAPI, etc.) can validate the wire format without depending on the zod source.

---

## 7. Default renderer

Ship a **vanilla TypeScript renderer** as the default. The interaction (drag-resize AR-locked rectangle over an image with a dim-outside mask) is well-precedented in plain DOM (`cropperjs` is the canonical reference) and does not need a framework. Distribute it as a separate package or subpath import (`@your-org/kenburns-path-entry/vanilla`) so a host using its own renderer pays nothing for the default.

**If a vanilla implementation turns out to add disproportionate maintenance cost during build-out**, the documented fallback is **Preact** (≈ 3 KB gzipped, drop-in JSX, no ecosystem lock-in). Avoid React as the default because of bundle weight and because hosts who *aren't* on React would prefer not to ship it. Document this decision in the repo.

The default renderer:

- Is a registered example, not a privileged one — it must be implementable by any reasonably skilled adapter author using only the public core API. Its source doubles as the canonical "how to write a renderer" reference.
- Includes minimal but tasteful styling (CSS custom properties for theming), and exposes the same core events any other renderer would.

The README and any agent-facing skill files must state, prominently:

1. The default renderer is functional but unopinionated; hosts are expected to replace it for production look-and-feel.
2. Where the "bring your own renderer" guide lives, with a worked React (or Vue / Solid) adapter as the example.

---

## 8. Open questions for the implementer

These are the points where the spec deliberately leaves a choice, and where the agent should either decide and document, or surface back for review:

1. **Image input shape.** Settle one of: `{ src, width, height }` (URL + dims), `ImageBitmap`, `File / Blob`, or a discriminated union. Recommend the URL+dims form (smallest contract, host owns upload).
2. **Coordinate readout units in the UI.** Percent, normalised float, or pixels-of-original? Recommend percent in the UI, normalised float in the spec.
3. **Preset icon library.** `lucide` is the recommendation for ubiquity, but the renderer is free to substitute; the preset definition should reference a *name*, not an SVG.
4. **AR display style.** Always show simplified ratio (`gcd`-reduced) next to raw num/den, or just one?
5. **Containment vs. cropping policy when image AR ≠ output AR.** Two reasonable choices: (a) restrict the user to drawing rects strictly inside the image at output AR (current spec — simplest, safest), or (b) allow rects to extend outside, with the host's renderer applying letterbox/pillarbox. Recommend (a) for v1; (b) is a non-breaking future extension.
6. **Whether the component owns *any* preview at all.** The spec says no. A weaker option is a tiny "ghost" animation of an empty rectangle moving over the still image, which the core can drive purely from `BurnsPath.evaluate(t)` without involving a renderer. Cheap and visually informative. Decide.

---

## 9. What the agent should *not* do

- Do not add multi-keyframe (3+) authoring now. Schema is forward-compatible; UI is not.
- Do not couple this component to any specific rendering backend (Pillow, FFmpeg, WebCodecs, Remotion, …). The output is JSON; what consumes it is the host's concern.
- Do not bake styling into the core. Even the default vanilla renderer must theme via CSS custom properties.
- Do not invent new vocabulary. Use `start` / `end` rectangles (iMovie / FCP), `easing` (CSS / Remotion / GSAP), `keyframe` (universal NLE), `preset` (common UI term). The architecture report's glossary is authoritative.
- Do not assume `outputAspect == imageAspect`. The backend supports the general case; the UI must too.
