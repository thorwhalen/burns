/**
 * Parity harness for the headed Playwright test (`ts/test-e2e/parity.e2e.ts`).
 *
 * Exposes `window.kb` so the test can, *in a real browser*, exercise the two
 * browser-only kenburnz surfaces and compare them to the Python reference:
 *
 * - `canvasCropPixels` — draws the WebCodecs encoder's exact per-frame image
 *   (the {@link sampleBox} crop resized onto a canvas) and returns its pixels,
 *   so the test can diff it against the matching Python reference frame. This
 *   is the WebCodecs *geometry* check minus the lossy encode.
 * - `refPixels` — the Python reference PNG's pixels (same size), for the diff.
 * - `cssWindowPx` — the source-pixel window implied by `cssPreviewAt`'s CSS, so
 *   the test can assert the CSS preview frames the same region as `sampleBox`.
 * - `exportWebm` — runs the full encode→mux path and reports the resulting
 *   `.webm` size + frame count, proving the encoder actually produces a file.
 *
 * Loaded only by `harness.html`; never shipped.
 */

import {
  BurnsPath,
  cssPreviewAt,
  exportWebmBlob,
  isWebCodecsSupported,
  sampleBox,
} from 'kenburnz';

const REF_BASE = '/reference';

interface FrameRef {
  t: number;
  file: string;
  box: [number, number, number, number];
}
interface Scenario {
  id: string;
  outW: number;
  outH: number;
  outputAspect: number | null;
  imageAspect: number;
  path: Record<string, unknown>;
  frames: FrameRef[];
}
interface Manifest {
  image: string;
  imgW: number;
  imgH: number;
  tSamples: number[];
  scenarios: Scenario[];
}

interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
interface ExportInfo {
  size: number;
  type: string;
  frameCount: number;
  width: number;
  height: number;
  codec: string;
}

interface KbHarness {
  manifest: Manifest;
  webCodecs: boolean;
  frameDiff(scenarioId: string, t: number, file: string): Promise<number>;
  cssWindowPx(scenarioId: string, t: number): Box;
  exportWebm(scenarioId: string): Promise<ExportInfo>;
}

/** Mean absolute per-channel RGB difference between two equal-size RGBA buffers. */
function meanRgbDiff(a: Uint8ClampedArray, b: Uint8ClampedArray): number {
  let sum = 0;
  let n = 0;
  for (let i = 0; i < a.length; i += 4) {
    sum += Math.abs(a[i] - b[i]);
    sum += Math.abs(a[i + 1] - b[i + 1]);
    sum += Math.abs(a[i + 2] - b[i + 2]);
    n += 3;
  }
  return sum / n;
}

declare global {
  interface Window {
    kb?: KbHarness;
    kbReady: Promise<void>;
  }
}

async function loadBitmap(src: string): Promise<ImageBitmap> {
  return createImageBitmap(await (await fetch(src)).blob());
}

function canvas2d(w: number, h: number): {
  cv: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
} {
  const cv = document.createElement('canvas');
  cv.width = w;
  cv.height = h;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  if (ctx === null) throw new Error('harness: no 2D context');
  return { cv, ctx };
}

async function init(): Promise<void> {
  const manifest = (await (
    await fetch(`${REF_BASE}/manifest.json`)
  ).json()) as Manifest;
  const source = await loadBitmap(`${REF_BASE}/source.png`);
  const scene = (id: string): Scenario => {
    const s = manifest.scenarios.find((x) => x.id === id);
    if (s === undefined) throw new Error(`harness: no scenario ${id}`);
    return s;
  };

  window.kb = {
    manifest,
    webCodecs: isWebCodecsSupported(),

    // Mean RGB diff between the WebCodecs encoder's per-frame image (the
    // sampleBox crop drawn to a canvas) and the Python reference frame —
    // computed in-browser so only the scalar crosses the page.evaluate bridge.
    async frameDiff(scenarioId, t, file) {
      const s = scene(scenarioId);
      const path = BurnsPath.fromDict(s.path as never);
      const [x0, y0, x1, y1] = sampleBox(
        path,
        t,
        manifest.imgW,
        manifest.imgH,
        s.outW,
        s.outH,
      );
      const a = canvas2d(s.outW, s.outH);
      a.ctx.imageSmoothingEnabled = true;
      a.ctx.imageSmoothingQuality = 'high';
      a.ctx.drawImage(source, x0, y0, x1 - x0, y1 - y0, 0, 0, s.outW, s.outH);

      const bmp = await loadBitmap(`${REF_BASE}/${file}`);
      const b = canvas2d(s.outW, s.outH);
      b.ctx.drawImage(bmp, 0, 0, s.outW, s.outH);

      return meanRgbDiff(
        a.ctx.getImageData(0, 0, s.outW, s.outH).data,
        b.ctx.getImageData(0, 0, s.outW, s.outH).data,
      );
    },

    cssWindowPx(scenarioId, t) {
      const s = scene(scenarioId);
      const path = BurnsPath.fromDict(s.path as never);
      const css = cssPreviewAt(path, t, {
        imageAspect: s.imageAspect,
        outputAspect: s.outputAspect ?? s.imageAspect,
      });
      const winW = 100 / parseFloat(css.width);
      const winH = 100 / parseFloat(css.height);
      const m = css.transform.match(
        /translate\(\s*(-?[\d.]+)%\s*,\s*(-?[\d.]+)%\s*\)/,
      );
      if (m === null) throw new Error(`harness: bad transform ${css.transform}`);
      const winX = -parseFloat(m[1]) / 100;
      const winY = -parseFloat(m[2]) / 100;
      return {
        x0: winX * manifest.imgW,
        y0: winY * manifest.imgH,
        x1: (winX + winW) * manifest.imgW,
        y1: (winY + winH) * manifest.imgH,
      };
    },

    async exportWebm(scenarioId) {
      const s = scene(scenarioId);
      const path = BurnsPath.fromDict(s.path as never);
      const r = await exportWebmBlob(source, path, {
        duration: 2,
        fps: 30,
        outputAspect: s.outputAspect,
      });
      return {
        size: r.blob.size,
        type: r.blob.type,
        frameCount: r.frameCount,
        width: r.width,
        height: r.height,
        codec: r.codec,
      };
    },
  };

  const el = document.getElementById('ready');
  if (el !== null) el.textContent = 'kb ready';
}

window.kbReady = init();
