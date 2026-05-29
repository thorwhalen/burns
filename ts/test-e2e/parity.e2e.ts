/**
 * Headed-browser parity: the two browser-only kenburnz surfaces vs Python.
 *
 * For every reference scenario/frame this asserts, in a real Chromium:
 *
 * 1. **WebCodecs frame geometry** — the encoder's per-frame image (the
 *    {@link sampleBox} crop drawn to a canvas) matches the Python reference
 *    frame within a mean-absolute-difference tolerance. The crop box is already
 *    pinned bit-exact by the golden vectors; this confirms the *browser* draws
 *    that box (a wrong box lands on a different quadrant → diff explodes).
 * 2. **CSS preview framing** — the source-pixel window implied by
 *    `cssPreviewAt`'s CSS matches the integer `sampleBox` window within a few
 *    pixels (float cover-crop vs integer cover-crop).
 * 3. **The encoder actually produces a file** — `exportWebmBlob` yields a
 *    non-empty `video/webm` Blob with the expected frame count and size.
 *
 * Local-only; see `playwright.config.ts`. The diff tolerance is generous on
 * purpose: resampling filters differ (PIL BICUBIC vs canvas drawImage), so a
 * few units of mean diff is expected, but a *geometry* error is tens of units.
 */

import { expect, test, type Page } from '@playwright/test';

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
  frames: FrameRef[];
}
interface Manifest {
  imgW: number;
  imgH: number;
  scenarios: Scenario[];
}

// Mean abs RGB diff allowed between the browser crop and the Python frame.
// Observed ~0.2–few units (resampling-filter delta only: PIL BICUBIC vs canvas
// drawImage); a real geometry bug lands on the wrong region → tens of units.
const MEAN_DIFF_TOL = 12;
// Per-edge pixel tolerance between the CSS-implied window and sampleBox.
const CSS_EDGE_TOL = 6;
const DURATION_S = 2;
const FPS = 30;

async function manifestOf(page: Page): Promise<Manifest> {
  await page.goto('/harness.html');
  await page.evaluate(() => window.kbReady);
  return page.evaluate(() => window.kb!.manifest as unknown as Manifest);
}

test.describe('kenburnz ↔ Python parity', () => {
  test('WebCodecs frame geometry matches Python reference frames', async ({
    page,
  }) => {
    const manifest = await manifestOf(page);
    for (const scene of manifest.scenarios) {
      for (const frame of scene.frames) {
        const diff = await page.evaluate(
          ({ id, t, file }) => window.kb!.frameDiff(id, t, file),
          { id: scene.id, t: frame.t, file: frame.file },
        );
        test.info().annotations.push({
          type: 'frame-diff',
          description: `${scene.id} t=${frame.t} meanRgbDiff=${diff.toFixed(2)}`,
        });
        expect(
          diff,
          `${scene.id} t=${frame.t}: browser crop vs Python frame`,
        ).toBeLessThan(MEAN_DIFF_TOL);
      }
    }
  });

  test('CSS preview frames the same window as sampleBox', async ({ page }) => {
    const manifest = await manifestOf(page);
    for (const scene of manifest.scenarios) {
      for (const frame of scene.frames) {
        const win = await page.evaluate(
          ({ id, t }) => window.kb!.cssWindowPx(id, t),
          { id: scene.id, t: frame.t },
        );
        const [x0, y0, x1, y1] = frame.box;
        const edges: Array<[string, number, number]> = [
          ['x0', win.x0, x0],
          ['y0', win.y0, y0],
          ['x1', win.x1, x1],
          ['y1', win.y1, y1],
        ];
        for (const [name, got, want] of edges) {
          expect(
            Math.abs(got - want),
            `${scene.id} t=${frame.t} ${name}: css ${got.toFixed(1)} vs box ${want}`,
          ).toBeLessThanOrEqual(CSS_EDGE_TOL);
        }
      }
    }
  });

  test('exportWebmBlob produces a playable .webm per scenario', async ({
    page,
  }) => {
    const manifest = await manifestOf(page);
    const supported = await page.evaluate(() => window.kb!.webCodecs);
    test.skip(!supported, 'WebCodecs unavailable in this browser');
    for (const scene of manifest.scenarios) {
      const info = await page.evaluate(
        (id) => window.kb!.exportWebm(id),
        scene.id,
      );
      expect(info.type, `${scene.id} mime`).toBe('video/webm');
      expect(info.size, `${scene.id} byte size`).toBeGreaterThan(0);
      expect(info.frameCount, `${scene.id} frame count`).toBe(
        DURATION_S * FPS,
      );
      expect(info.width, `${scene.id} width`).toBe(scene.outW);
      expect(info.height, `${scene.id} height`).toBe(scene.outH);
    }
  });
});
