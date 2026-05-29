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

## Development

This package lives co-located in the `burns` Python repo under `ts/` so the
single golden-vector fixture (`../tests/golden/vectors.json`) can't drift
between the two languages.

```bash
pnpm install
pnpm test         # vitest — pure spec + conformance, offline
pnpm build        # tsup → dist/ (ESM + CJS + d.ts)
pnpm typecheck    # tsc --noEmit
```

### Browser verification (local-only)

The CSS preview and WebCodecs encode path only run in a real browser, so they're
verified against Python reference renders rather than in Node:

```bash
cd demo && pnpm dev     # side-by-side CSS preview vs Python frames + live export
pnpm test:e2e           # headed Playwright: pixel-diff the browser vs Python
```

Both regenerate the reference frames via the repo's
`misc/gen_preview_reference.py` (needs the `burns` Python package importable),
which is why the e2e suite is local-only and not in CI.

## Publishing

`npm` releases are wired through `.github/workflows/publish-ts.yml` (manual
dispatch, dry-run by default; or a `kenburnz-v*` tag). See that file's header
for the OIDC Trusted-Publishing setup and the first-publish bootstrap.

## License

MIT
