/**
 * Unit tests for the TS-authored spec constructors. The golden vectors rebuild
 * paths via `fromDict` (Python-authored), so these cover the TS-side builders
 * (`pushIn`, `kenBurnsPath`, `reversed`, validation) the fixture doesn't touch.
 */

import { describe, expect, it } from 'vitest';

import { Rect } from '../src/rect.js';
import { BurnsPath, kenBurnsPath } from '../src/path.js';
import { parseEasing } from '../src/easing.js';

describe('Rect', () => {
  it('center / zoom / fromCenterZoom', () => {
    expect(new Rect(0, 0, 1, 1).center).toEqual([0.5, 0.5]);
    expect(new Rect(0, 0, 1, 1).zoom).toBe(1);
    expect(Rect.fromCenterZoom(0.5, 0.5, 2)).toMatchObject({ x: 0.25, y: 0.25, w: 0.5, h: 0.5 });
  });

  it('clamped rides the wall keeping size', () => {
    const r = new Rect(0.8, 0, 0.5, 0.5).clamped();
    expect([r.w, r.h]).toEqual([0.5, 0.5]);
    expect(r.x).toBe(0.5);
  });

  it('toPixels rounds half-to-even (Python parity)', () => {
    expect([...new Rect(0, 0, 1, 1).toPixels(100, 80)]).toEqual([0, 0, 100, 80]);
    expect([...Rect.fromCenterZoom(0.5, 0.5, 2).toPixels(100, 80)]).toEqual([25, 20, 75, 60]);
  });
});

describe('easing', () => {
  it('linear is identity; ease-in-out is symmetric at 0.5', () => {
    expect(parseEasing('linear')(0.3)).toBeCloseTo(0.3, 10);
    expect(parseEasing('ease-in-out')(0.5)).toBeCloseTo(0.5, 6);
  });
  it('parses cubic-bezier strings and tuples', () => {
    expect(parseEasing('cubic-bezier(0,0,1,1)')(0.7)).toBeCloseTo(0.7, 6);
    expect(parseEasing([0, 0, 1, 1])(0.42)).toBeCloseTo(0.42, 6);
  });
  it('rejects unknown names', () => {
    expect(() => parseEasing('boing')).toThrow(/unknown easing/);
  });
});

describe('BurnsPath constructors', () => {
  it('pushIn ends zoomed to the requested magnification', () => {
    expect(BurnsPath.pushIn({ zoom: 1.3 }).evaluate(1).zoom).toBeCloseTo(1.3, 4);
  });

  it('kenBurnsPath: odd pushes in (starts full), even pulls out (ends full)', () => {
    expect(kenBurnsPath(1).evaluate(0)).toMatchObject({ x: 0, y: 0, w: 1, h: 1 });
    expect(kenBurnsPath(2).evaluate(1)).toMatchObject({ x: 0, y: 0, w: 1, h: 1 });
  });

  it('kenBurnsPath is deterministic per index', () => {
    expect(kenBurnsPath(3).toDict()).toEqual(kenBurnsPath(3).toDict());
  });

  it('reversed swaps start and end', () => {
    const p = BurnsPath.fromStartEnd(new Rect(0, 0, 1, 1), new Rect(0, 0, 0.5, 0.5), {
      easing: 'linear',
    });
    expect(p.reversed().evaluate(0)).toMatchObject({ w: 0.5, h: 0.5 });
  });

  it('rejects non-increasing keyframe times', () => {
    expect(
      () =>
        new BurnsPath([
          [0, new Rect(0, 0, 1, 1)],
          [0, new Rect(0, 0, 0.5, 0.5)],
        ]),
    ).toThrow(/strictly increase/);
  });

  it('toDict round-trips through fromDict', () => {
    const p = BurnsPath.pushIn({ zoom: 1.4, easing: 'ease-in' });
    expect(BurnsPath.fromDict(p.toDict()).toDict()).toEqual(p.toDict());
  });
});
