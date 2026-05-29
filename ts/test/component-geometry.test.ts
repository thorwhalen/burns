/**
 * Unit tests for the path-entry component's pure geometry helpers.
 *
 * The geometry is the headless heart's foundation: AR-lock ratio, the
 * max-contained / scaled-contained constructors, drag-to-rect, pan, scale, and
 * the readout. All resolution-independent, all clamped to containment.
 */

import { describe, it, expect } from 'vitest';
import {
  aspectValue,
  imageAspectOf,
  lockRatio,
  simplifyRatio,
  maxContainedRect,
  scaledContainedRect,
  rectFromDrag,
  translateRect,
  scaleRect,
  rectReadout,
  EPS,
} from '../src/component/index.js';

const contained = (r: { x: number; y: number; w: number; h: number }): boolean =>
  r.x >= -EPS && r.y >= -EPS && r.x + r.w <= 1 + EPS && r.y + r.h <= 1 + EPS;

describe('aspect helpers', () => {
  it('aspectValue and imageAspectOf compute num/den and w/h', () => {
    expect(aspectValue({ num: 16, den: 9 })).toBeCloseTo(16 / 9, 9);
    expect(imageAspectOf(1920, 1080)).toBeCloseTo(16 / 9, 9);
  });

  it('lockRatio is outputAspect / imageAspect (so the rect pixel-AR == output)', () => {
    // 16:9 output over a square (1:1) image ⇒ normalized w/h = 16/9.
    expect(lockRatio({ num: 16, den: 9 }, 1)).toBeCloseTo(16 / 9, 9);
    // 16:9 output over a 16:9 image ⇒ normalized w/h = 1 (full image is the window).
    expect(lockRatio({ num: 16, den: 9 }, 16 / 9)).toBeCloseTo(1, 9);
  });

  it('simplifyRatio reduces to lowest terms', () => {
    expect(simplifyRatio(1920, 1080)).toEqual({ num: 16, den: 9 });
    expect(simplifyRatio(800, 600)).toEqual({ num: 4, den: 3 });
    expect(simplifyRatio(7, 5)).toEqual({ num: 7, den: 5 });
  });
});

describe('maxContainedRect', () => {
  it('a wide ratio fills the width and is letterboxed, centered', () => {
    const r = maxContainedRect(16 / 9);
    expect(r.w).toBeCloseTo(1, 9);
    expect(r.h).toBeCloseTo(9 / 16, 9);
    expect(r.x).toBeCloseTo(0, 9);
    expect(r.y).toBeCloseTo((1 - 9 / 16) / 2, 9);
    expect(r.w / r.h).toBeCloseTo(16 / 9, 9);
    expect(contained(r)).toBe(true);
  });

  it('a tall ratio fills the height, pillarboxed', () => {
    const r = maxContainedRect(2 / 3);
    expect(r.h).toBeCloseTo(1, 9);
    expect(r.w).toBeCloseTo(2 / 3, 9);
    expect(contained(r)).toBe(true);
  });

  it('ratio 1 is the full image', () => {
    const r = maxContainedRect(1);
    expect(r).toMatchObject({ x: 0, y: 0, w: 1, h: 1 });
  });
});

describe('scaledContainedRect', () => {
  it('zoom 1 equals maxContainedRect', () => {
    const full = maxContainedRect(16 / 9);
    const z1 = scaledContainedRect(16 / 9, 1);
    expect(z1.w).toBeCloseTo(full.w, 9);
    expect(z1.h).toBeCloseTo(full.h, 9);
  });

  it('zoom > 1 shrinks the window keeping the AR', () => {
    const r = scaledContainedRect(16 / 9, 2);
    const full = maxContainedRect(16 / 9);
    expect(r.w).toBeCloseTo(full.w / 2, 9);
    expect(r.w / r.h).toBeCloseTo(16 / 9, 9);
    expect(contained(r)).toBe(true);
  });

  it('off-center requests still clamp inside the image', () => {
    const r = scaledContainedRect(1, 1.2, 0.95, 0.95);
    expect(contained(r)).toBe(true);
  });

  it('throws on non-positive zoom', () => {
    expect(() => scaledContainedRect(1, 0)).toThrow();
  });
});

describe('rectFromDrag', () => {
  it('AR-locks a freehand drag and clamps', () => {
    const r = rectFromDrag({ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.5 }, 16 / 9);
    expect(r.w / r.h).toBeCloseTo(16 / 9, 6);
    expect(contained(r)).toBe(true);
  });

  it('grows toward the pointer from the anchor corner', () => {
    const r = rectFromDrag({ x: 0.3, y: 0.3 }, { x: 0.6, y: 0.6 }, 1);
    // Square lock; the dominant axis is the diagonal — both extents 0.3.
    expect(r.x).toBeCloseTo(0.3, 6);
    expect(r.y).toBeCloseTo(0.3, 6);
    expect(r.w).toBeCloseTo(0.3, 6);
    expect(r.h).toBeCloseTo(0.3, 6);
  });
});

describe('translateRect / scaleRect', () => {
  it('translate pans and clamps (rides the wall)', () => {
    const r = translateRect({ x: 0.4, y: 0.4, w: 0.5, h: 0.5 }, 0.5, 0);
    expect(r.x).toBeCloseTo(0.5, 9); // clamped: 0.9 would overflow, rides to 1-w
    expect(contained(r)).toBe(true);
  });

  it('scale about center preserves AR and clamps', () => {
    const r = scaleRect({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 }, 1.5);
    expect(r.w / r.h).toBeCloseTo(1, 9);
    expect(contained(r)).toBe(true);
  });

  it('scaleRect throws on non-positive factor', () => {
    expect(() => scaleRect({ x: 0, y: 0, w: 0.5, h: 0.5 }, -1)).toThrow();
  });
});

describe('rectReadout', () => {
  it('reports percent position and window-fraction zoom', () => {
    const ro = rectReadout({ x: 0.1, y: 0.2, w: 0.5, h: 0.5 });
    expect(ro.xPercent).toBeCloseTo(10, 9);
    expect(ro.yPercent).toBeCloseTo(20, 9);
    expect(ro.zoom).toBeCloseTo(2, 9); // 1 / max(0.5, 0.5)
  });
});
