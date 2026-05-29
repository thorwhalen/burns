/**
 * The single point where a {@link BurnsPath} meets pixels — a port of
 * `burns._frame`.
 *
 * {@link sampleBox} is the pure integer geometry a renderer must reproduce:
 * evaluate the path to a {@link Rect}, map it to a clamped pixel box, then
 * cover-crop that box to the output aspect ratio (center-cropped — the FCP /
 * iMovie default). It touches no image data, so it is the exact cross-language
 * crop contract the golden vectors pin. A WebCodecs / canvas renderer slices
 * the source image with this box and resizes to the output size.
 */

import type { BurnsPath } from './path.js';
import { roundHalfToEven } from './_round.js';
import type { PixelBox } from './rect.js';

/** Round `n` down to the nearest positive even integer (H.264 needs even dims). */
export function even(n: number): number {
  n = Math.trunc(n);
  return Math.max(2, n - (n % 2));
}

/**
 * Resolve the (even) output frame size.
 *
 * Priority: an explicit `outputSize` wins; else derive from `outputAspect`
 * keeping the image's height; else the image's own size.
 */
export function outputSizeFor(
  imgW: number,
  imgH: number,
  {
    outputAspect = null,
    outputSize = null,
  }: {
    outputAspect?: number | null;
    outputSize?: readonly [number, number] | null;
  } = {},
): [number, number] {
  if (outputSize !== null) {
    return [even(outputSize[0]), even(outputSize[1])];
  }
  if (outputAspect !== null) {
    return [even(roundHalfToEven(imgH * outputAspect)), even(imgH)];
  }
  return [even(imgW), even(imgH)];
}

/**
 * Center-crop the integer box `[x0, y0, x1, y1]` to `targetAspect`
 * (width / height). Trims the longer dimension symmetrically, keeping it
 * centered. A no-op when the box already matches within a 1px tolerance.
 */
export function coverCropBox(
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  targetAspect: number,
): PixelBox {
  const w = x1 - x0;
  const h = y1 - y0;
  const cur = w / h;
  if (Math.abs(cur - targetAspect) < 1 / Math.max(w, h)) {
    return [x0, y0, x1, y1];
  }
  if (cur > targetAspect) {
    // too wide — trim left/right
    const newW = Math.max(1, roundHalfToEven(h * targetAspect));
    const nx0 = x0 + Math.floor((w - newW) / 2);
    return [nx0, y0, nx0 + newW, y1];
  }
  // too tall — trim top/bottom
  const newH = Math.max(1, roundHalfToEven(w / targetAspect));
  const ny0 = y0 + Math.floor((h - newH) / 2);
  return [x0, ny0, x1, ny0 + newH];
}

/**
 * The integer crop box `[x0, y0, x1, y1]` read from the source image.
 *
 * Pure integer geometry — evaluate the path to a {@link Rect}, map it to a
 * clamped pixel box, then cover-crop to the output aspect ratio. The box is
 * half-open. This is the side-effect-free crop contract the golden vectors pin.
 */
export function sampleBox(
  path: BurnsPath,
  t: number,
  imgW: number,
  imgH: number,
  outW: number,
  outH: number,
): PixelBox {
  const rect = path.evaluate(t);
  const [x0, y0, x1, y1] = rect.toPixels(imgW, imgH);
  return coverCropBox(x0, y0, x1, y1, outW / outH);
}
