/**
 * Unit tests for the CSS-preview geometry (the numeric output only — the visual
 * result is not browser-verified here).
 */

import { describe, expect, it } from 'vitest';

import { Rect } from '../src/rect.js';
import { BurnsPath } from '../src/path.js';
import {
  coverCropWindow,
  cssPreviewAt,
  cssTransformForRect,
} from '../src/css-preview.js';

describe('coverCropWindow', () => {
  it('is a no-op when window pixel AR already matches output AR', () => {
    const win = { x: 0, y: 0, w: 1, h: 1 };
    expect(coverCropWindow(win, 1, 1)).toEqual(win);
  });

  it('trims width when the window is too wide (square output, 4:3 image)', () => {
    // Full window of a 4:3 image into a 1:1 output trims the sides to 0.75 wide.
    const out = coverCropWindow({ x: 0, y: 0, w: 1, h: 1 }, 4 / 3, 1);
    expect(out.w).toBeCloseTo(0.75, 10);
    expect(out.h).toBe(1);
    expect(out.x).toBeCloseTo(0.125, 10);
    expect(out.y).toBe(0);
  });

  it('trims height when the window is too tall (2:1 output, 4:3 image)', () => {
    const out = coverCropWindow({ x: 0, y: 0, w: 1, h: 1 }, 4 / 3, 2);
    expect(out.w).toBe(1);
    expect(out.h).toBeCloseTo((4 / 3) / 2, 10); // w*imageAspect/outputAspect
    expect(out.y).toBeCloseTo((1 - (4 / 3) / 2) / 2, 10);
  });
});

describe('cssTransformForRect', () => {
  it('full image, matching AR -> identity-ish (100% size, no translate)', () => {
    const css = cssTransformForRect(new Rect(0, 0, 1, 1), {
      imageAspect: 1,
      outputAspect: 1,
    });
    expect(css.width).toBe('100.0000%');
    expect(css.height).toBe('100.0000%');
    expect(css.transform).toBe('translate(0.0000%, 0.0000%)');
    expect(css.transformOrigin).toBe('0 0');
  });

  it('zoomed window scales the image up and shifts it', () => {
    // A centered half-size window must display the image at 200% and shift it
    // by -25% of its own box on each axis to center the crop.
    const css = cssTransformForRect(new Rect(0.25, 0.25, 0.5, 0.5), {
      imageAspect: 1,
      outputAspect: 1,
    });
    expect(css.width).toBe('200.0000%');
    expect(css.height).toBe('200.0000%');
    expect(css.transform).toBe('translate(-25.0000%, -25.0000%)');
  });
});

describe('cssPreviewAt', () => {
  it('defaults outputAspect to the path, then to imageAspect', () => {
    const path = BurnsPath.fromStartEnd(new Rect(0, 0, 1, 1), new Rect(0, 0, 1, 1), {
      easing: 'linear',
    });
    // No path.outputAspect -> falls back to imageAspect (no reframing).
    const css = cssPreviewAt(path, 0, { imageAspect: 1.5 });
    expect(css.width).toBe('100.0000%');
    expect(css.transform).toBe('translate(0.0000%, 0.0000%)');
  });
});
