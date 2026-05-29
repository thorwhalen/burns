# kenburnz

A TypeScript port of the [`burns`](https://github.com/thorwhalen/burns) Ken
Burns **motion spec**: a pure, time-parameterized `BurnsPath.evaluate(t) → Rect`
plus the cover-crop pixel geometry (`sampleBox`), a **WebCodecs** video exporter,
and a zero-cost **CSS preview** for the browser. The spec math is pinned
bit-for-bit to the Python renderer by a shared golden-vector fixture, so a path
rendered in Node/Python and previewed/exported in the browser frame the
identical window.

```bash
npm install kenburnz
```

## Quick start

```ts
import { BurnsPath, sampleBox, cssPreviewAt, exportWebmBlob } from 'kenburnz';

// A 2-second-ish push-in to 1.3×, centered, ease-in-out.
const path = BurnsPath.pushIn({ zoom: 1.3 });

// Pure spec: the normalized viewport at clock time t ∈ [0, 1].
path.evaluate(0.5); // → Rect { x, y, w, h }

// The exact integer crop box (x0, y0, x1, y1) a renderer reads from the image.
sampleBox(path, 0.5, imgW, imgH, outW, outH);
```

### Live CSS preview (no re-rasterizing)

`cssPreviewAt` turns `evaluate(t)` into a GPU-friendly CSS transform on an
`<img>`, so a preview scrubs with `transform` alone:

```ts
const css = cssPreviewAt(path, t, { imageAspect: 16 / 9, outputAspect: 1 });
img.style.width = css.width;            // e.g. "153.8462%"
img.style.height = css.height;
img.style.transform = css.transform;    // e.g. "translate(-26.92%, -0.00%)"
img.style.transformOrigin = css.transformOrigin;
```

See `cssPreviewAt`'s docs for the expected `.kb-viewport` / `.kb-img` DOM.

### Export to video (browser, WebCodecs)

The encoder draws each frame's `sampleBox` crop onto an `OffscreenCanvas` and
hands it to a `VideoEncoder`. The core stays muxer-free and streams raw chunks;
the optional `exportWebmBlob` helper produces a playable `.webm`:

```ts
import { exportWebmBlob, isWebCodecsSupported } from 'kenburnz';

if (isWebCodecsSupported()) {
  const { blob } = await exportWebmBlob(imageBitmap, path, {
    duration: 3,
    fps: 30,
  });
  videoEl.src = URL.createObjectURL(blob); // VP9 in WebM
}
```

`exportWebmBlob` / `createWebmMuxer` require the optional peer dependency
[`webm-muxer`](https://www.npmjs.com/package/webm-muxer):

```bash
npm install webm-muxer
```

If you'd rather mux elsewhere (a different library, or server-side), use the
lower-level `exportWebCodecsVideo` directly — it takes no muxer dependency and
streams every `EncodedVideoChunk` to your `onChunk` callback. (`webm-muxer` is
soft-deprecated upstream in favor of [Mediabunny](https://mediabunny.dev); the
helper's chunk-stream interface makes swapping muxers a local change.)

## Path-entry component (authoring a `BurnsPath`)

A **headless, schema-first** UI component for *authoring* a `BurnsPath`: the
user picks a preset (or draws a crop window over an image), tunes duration and
motion speed, and the component emits the same `BurnsPath` wire value the
renderers above consume. It owns *interaction logic and state*, not
look-and-feel — see [`misc/docs/ken_burns_path_entry_component_spec.md`](../misc/docs/ken_burns_path_entry_component_spec.md).

Two entry points keep the DOM-free core separate from the default renderer:

| Import | What it is |
|---|---|
| `kenburnz/component` | The **headless core** — zod schemas, pure geometry, the preset catalog, and the state machine. No DOM. Build any renderer (React/Vue/Solid/…) on top. |
| `kenburnz/vanilla` | The **default vanilla DOM renderer** — `mountPathEntry(el, config, opts)`. Functional and themeable, but *unopinionated*: replace it for production look-and-feel. |

### Drop-in (default renderer)

```ts
import { mountPathEntry } from 'kenburnz/vanilla';

const handle = mountPathEntry(el, {
  image: { src: url, width: 1920, height: 1080 },
  targetAspect: { num: 16, den: 9, locked: true }, // hides the AR editor
  // duration / easing / presets / dualView / allowCustom are all optional
}, {
  onChange: (value) => preview(value),   // fires on every edit (live preview)
  onSubmit: (value) => submit(value),    // the emitted BurnsPath JSON
});

handle.getValue();   // the current BurnsPath wire value
handle.destroy();    // tear down listeners + DOM
```

The crop rect is locked to the **output** aspect ratio (not the image's), drawn
as a bright window over a dim matte with corner handles, a rule-of-thirds grid,
drag-to-pan, drag-handle-to-resize, and arrow-key nudge (Shift = ×10). Theme it
by overriding the `--kb-*` CSS custom properties on the mount target.

### The emitted value

The output is the `BurnsPath` JSON — the single point of contact with any
rendering backend — extended with two **optional, additive** fields the UI
authors (`duration_ms`, `meta`). Core fields are byte-compatible with the Python
golden-vector contract:

```jsonc
{
  "version": 1,
  "keyframes": [
    { "t": 0, "rect": { "x": 0, "y": 0.125, "w": 1, "h": 0.75 } },
    { "t": 1, "rect": { "x": 0.22, "y": 0.29, "w": 0.56, "h": 0.42 } }
  ],
  "interp": "linear",
  "easing": "ease-in-out",
  "output_aspect": 1.7778,
  "duration_ms": 5000,
  "meta": { "preset_id": "push-in-to", "output_aspect_ratio": { "num": 16, "den": 9 } }
}
```

A **JSON Schema** for this wire format is generated from the zod source and
committed under [`schemas/burns-path.schema.json`](schemas/burns-path.schema.json)
(plus `path-entry-config.schema.json`) so non-TS consumers (Python validation,
OpenAPI, …) can validate it without depending on zod. Regenerate with
`pnpm schema`.

### Bring your own renderer

The boundary between core and renderer is the only stable API; the vanilla
renderer is a *registered example, not a privileged one*. A renderer is a thin
shell that (1) maps interaction to the core's `Event`s, (2) dispatches them
through `reduce`, and (3) draws the resulting state. Everything it shows comes
from the core:

```ts
import {
  initState, reduce, resolveCatalog, resolveStartEnd,
  editTargets, toValue, type State, type Event,
} from 'kenburnz/component';

const catalog = resolveCatalog(config);
let state: State = initState(config, { catalog });

function dispatch(event: Event) {
  state = reduce(state, event, catalog);   // pure: (state, event) → state
  render();                                 // draw resolveStartEnd(state, catalog)
  onChange?.(toValue(state, catalog));      // the emitted BurnsPath
}

// e.g. the user dragged the End window:
dispatch({ type: 'setRect', index: 0, rect: { x, y, w, h } });
```

Key selectors: `resolveStartEnd(state, catalog)` (the derived Start/End rects to
draw), `editTargets(state, catalog)` (which displayed slot maps to which
editable user-rect index — accounts for the swap toggle), and `toValue(state,
catalog)` (the emitted wire value). The geometry helpers (`maxContainedRect`,
`scaledContainedRect`, `rectFromDrag`, `translateRect`, `scaleRect`,
`rectReadout`) build AR-locked, containment-clamped rects from pointer input.
`kenburnz/vanilla`'s source is the canonical worked example.

### Presets

The catalog is **data** — adding a preset is adding a `{ id, label, icon,
arity, params?, derive }` entry, not editing the core. The default set covers
zoom in/out, four pans, drift (arity 0); push-in-to / pull-out-from /
enter-/exit-from-edge / reveal-around (arity 1, user draws one rect); and custom
(arity 2). Hosts pass `presets: ["push-in-to", "pull-out-from"]` to restrict the
set, `allowCustom: false` to drop free-draw, or their own `Preset[]` via
`initState`'s `catalog` option.

## Development

This package lives co-located in the `burns` Python repo under `ts/` so the
single golden-vector fixture (`../tests/golden/vectors.json`) can't drift
between the two languages.

```bash
pnpm install
pnpm test         # vitest — pure spec + conformance + component, offline
pnpm build        # tsup → dist/ (3 entries: ., ./component, ./vanilla)
pnpm typecheck    # tsc --noEmit
pnpm schema       # regenerate schemas/*.schema.json from the zod source
```

### Browser verification (local-only)

The CSS preview and WebCodecs encode path only run in a real browser, so they're
verified against Python reference renders rather than in Node:

```bash
cd demo && pnpm dev     # /index.html: CSS preview vs Python frames + live export
                        # /path-entry.html: the path-entry component, live
pnpm test:e2e           # headed Playwright: parity pixel-diff + path-entry smoke
```

Both regenerate the reference frames via the repo's
`misc/gen_preview_reference.py` (needs the `burns` Python package importable),
which is why the e2e suite is local-only and not in CI.

## Publishing

`npm` releases go through wads's reusable NPM CI (`.github/workflows/npm-ci.yml`
→ `i2mint/wads/.github/workflows/npm-ci.yml`), configured by the `wads.ci` block
in `package.json`. Publishing is opt-in: bump the `version`, then push to `main`
with **`[publish-npm]`** in the commit message. It uses OIDC trusted publishing +
provenance (configure the trusted publisher on the npm package page once;
`NPM_TOKEN` is only a first-publish fallback) and a version-already-published
guard. kenburnz is a pnpm package, so the workflow runs the pnpm path.

## License

MIT
