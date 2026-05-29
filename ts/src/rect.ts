/**
 * The Ken Burns viewport rectangle — the render-agnostic geometric atom.
 *
 * A {@link Rect} is a normalized region of interest over a source image:
 * `(x, y, w, h)` with **top-left origin, y-down**, every component a fraction
 * of the image in `[0, 1]`. This mirrors the Python `burns.rect.Rect` exactly;
 * the golden vectors pin the equivalence.
 *
 * The rect is pure data: no I/O, no image needed to construct or interpolate.
 * Only {@link Rect.toPixels} takes image dimensions, the single point where
 * normalized geometry meets a concrete raster.
 */

import { roundHalfToEven } from './_round.js';

/** Floating-point slack for the containment invariant (matches Python `_EPS`). */
const EPS = 1e-6;

/** Half-open integer pixel box `[x0, y0, x1, y1]` (suitable for `array[y0:y1, x0:x1]`). */
export type PixelBox = readonly [number, number, number, number];

export class Rect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;

  constructor(x: number, y: number, w: number, h: number) {
    this.x = x;
    this.y = y;
    this.w = w;
    this.h = h;
  }

  /** Aspect ratio of the window in normalized image units (`w / h`). */
  get aspect(): number {
    return this.w / this.h;
  }

  /** The window's center `[cx, cy]` in `[0, 1]` image units. */
  get center(): readonly [number, number] {
    return [this.x + this.w / 2, this.y + this.h / 2];
  }

  /** Magnification implied by the window, `1 / max(w, h)` (`1.0` = full image). */
  get zoom(): number {
    return 1 / Math.max(this.w, this.h);
  }

  /** True when the window lies wholly inside the image. */
  isContained(): boolean {
    return (
      this.x >= -EPS &&
      this.y >= -EPS &&
      this.x + this.w <= 1 + EPS &&
      this.y + this.h <= 1 + EPS
    );
  }

  /**
   * Slide the window inside the image **without resizing it** ("ride the wall"
   * at an edge rather than shrinking). Windows larger than the image in a
   * dimension are centered in that dimension.
   */
  clamped(): Rect {
    return new Rect(
      clampCorner(this.x, this.w),
      clampCorner(this.y, this.h),
      this.w,
      this.h,
    );
  }

  /** Linearly interpolate toward `other` by `t` in `[0, 1]`. */
  lerp(other: Rect, t: number): Rect {
    return new Rect(
      this.x + (other.x - this.x) * t,
      this.y + (other.y - this.y) * t,
      this.w + (other.w - this.w) * t,
      this.h + (other.h - this.h) * t,
    );
  }

  /**
   * Map the (clamped) window to an integer pixel box `[x0, y0, x1, y1]`.
   *
   * Clamps first, then rounds half-to-even (Python's `round`) — **not**
   * `Math.round` — so the box is bit-identical to the Python renderer's.
   */
  toPixels(imgW: number, imgH: number): PixelBox {
    const r = this.clamped();
    return [
      roundHalfToEven(r.x * imgW),
      roundHalfToEven(r.y * imgH),
      roundHalfToEven((r.x + r.w) * imgW),
      roundHalfToEven((r.y + r.h) * imgH),
    ];
  }

  /**
   * Build a rect from a pan center, a zoom, and a window aspect ratio.
   *
   * The bridge from the older center+magnification mental model. `zoom` is
   * window-fraction magnification (`1.0` = full image, `> 1.0` = zoomed in).
   * `aspect` is the window's normalized `w / h`. The result is clamped.
   */
  static fromCenterZoom(
    cx: number,
    cy: number,
    zoom = 1,
    { aspect = 1 }: { aspect?: number } = {},
  ): Rect {
    if (zoom <= 0) {
      throw new Error(`Rect.fromCenterZoom: zoom must be > 0, got ${zoom}`);
    }
    let w: number;
    let h: number;
    if (aspect >= 1) {
      w = 1 / zoom;
      h = w / aspect;
    } else {
      h = 1 / zoom;
      w = h * aspect;
    }
    return new Rect(cx - w / 2, cy - h / 2, w, h).clamped();
  }
}

/** Clamp a top-left coordinate so `[origin, origin+size]` fits `[0, 1]`. */
function clampCorner(origin: number, size: number): number {
  const high = 1 - size;
  if (high < 0) return high / 2;
  return Math.max(0, Math.min(high, origin));
}
