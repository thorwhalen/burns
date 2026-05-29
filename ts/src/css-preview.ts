/**
 * Zero-cost in-browser preview of a {@link BurnsPath} via CSS transforms.
 *
 * The renderer (Python or WebCodecs) crops the source image to
 * {@link sampleBox} and resizes. For a *live* scrubbable preview you don't want
 * to re-rasterize every frame — you want the GPU to do it. This module turns
 * `evaluate(t)` into a CSS transform that frames the same window, so an `<img>`
 * animates with `transform` alone (compositor-friendly, no repaint).
 *
 * ## Expected DOM
 *
 * ```html
 * <div class="kb-viewport"><img class="kb-img" src="…" /></div>
 * ```
 * ```css
 * .kb-viewport { position: relative; overflow: hidden; aspect-ratio: <outputAspect>; }
 * .kb-img      { position: absolute; top: 0; left: 0; transform-origin: 0 0; }
 * ```
 *
 * Apply a {@link CssPreview}'s `width` / `height` / `transform` /
 * `transformOrigin` to `.kb-img`. The image keeps its own aspect ratio (no
 * stretch) because the window is cover-cropped to the output AR first — exactly
 * what the renderer does.
 *
 * NOTE: the geometry here is unit-tested, but the *visual* result has not been
 * verified in a real browser in this environment. Eyeball it against the
 * rendered video before relying on pixel-exact preview/export parity.
 */

import type { BurnsPath } from './path.js';
import type { Rect } from './rect.js';

/** A normalized window `(x, y, w, h)` in `[0, 1]` image units. */
export interface NormWindow {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** CSS to apply to the previewed `<img>` (see module docs for the DOM). */
export interface CssPreview {
  /** Image display width as a percentage of the viewport width. */
  width: string;
  /** Image display height as a percentage of the viewport height. */
  height: string;
  /** Compositor-friendly translate (percent of the image's own box). */
  transform: string;
  /** Always `"0 0"` — the math assumes a top-left origin. */
  transformOrigin: string;
}

/**
 * Cover-crop a normalized window to `outputAspect`, in normalized image units.
 *
 * The continuous-float analogue of {@link coverCropBox}: trims the longer side
 * of the window so its *pixel* AR (which depends on `imageAspect`) becomes
 * `outputAspect`, keeping it centered. Returns the trimmed window.
 */
export function coverCropWindow(
  win: NormWindow,
  imageAspect: number,
  outputAspect: number,
): NormWindow {
  const pixelAspect = (win.w * imageAspect) / win.h;
  if (pixelAspect > outputAspect) {
    // Window is too wide in pixels — trim left/right.
    const w2 = (win.h * outputAspect) / imageAspect;
    return { x: win.x + (win.w - w2) / 2, y: win.y, w: w2, h: win.h };
  }
  if (pixelAspect < outputAspect) {
    // Too tall — trim top/bottom.
    const h2 = (win.w * imageAspect) / outputAspect;
    return { x: win.x, y: win.y + (win.h - h2) / 2, w: win.w, h: h2 };
  }
  return { ...win };
}

/**
 * The CSS that frames `rect` (cover-cropped to `outputAspect`) inside the
 * viewport. `imageAspect` is the source image's `width / height`.
 *
 * Derivation: to make a window `(x, y, w, h)` of the image fill the viewport,
 * the image must be displayed at `1/w` × the viewport width and `1/h` × its
 * height, shifted so the window's top-left sits at the origin — a translate of
 * `-x` / `-y` *of the image's own box*. Cover-cropping first guarantees the
 * window's pixel AR equals the viewport's, so the scale is uniform (no stretch).
 */
export function cssTransformForRect(
  rect: Rect,
  { imageAspect, outputAspect }: { imageAspect: number; outputAspect: number },
): CssPreview {
  const win = coverCropWindow(
    { x: rect.x, y: rect.y, w: rect.w, h: rect.h },
    imageAspect,
    outputAspect,
  );
  return {
    width: `${(100 / win.w).toFixed(4)}%`,
    height: `${(100 / win.h).toFixed(4)}%`,
    transform: `translate(${(-win.x * 100).toFixed(4)}%, ${(-win.y * 100).toFixed(4)}%)`,
    transformOrigin: '0 0',
  };
}

/**
 * Convenience: the {@link CssPreview} for a path at normalized clock time `t`.
 *
 * `outputAspect` defaults to the path's own `outputAspect`, falling back to the
 * source `imageAspect` (i.e. no reframing) when the path doesn't specify one.
 */
export function cssPreviewAt(
  path: BurnsPath,
  t: number,
  {
    imageAspect,
    outputAspect = path.outputAspect ?? imageAspect,
  }: { imageAspect: number; outputAspect?: number },
): CssPreview {
  return cssTransformForRect(path.evaluate(t), { imageAspect, outputAspect });
}
