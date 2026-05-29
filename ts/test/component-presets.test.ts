/**
 * Unit tests for the preset catalog (spec §5).
 *
 * Each preset's `derive` is pure, returns contained rects at the lock ratio,
 * and produces the expected motion (zoom in pushes inward, pans translate,
 * arity-1 presets pass the user's rect through as one endpoint).
 */

import { describe, it, expect } from 'vitest';
import {
  DEFAULT_PRESETS,
  type Preset,
  type PresetContext,
  EPS,
} from '../src/component/index.js';

const ctx16x9: PresetContext = { lockRatio: 16 / 9, imageAspect: 1 };

const byId = (id: string): Preset => {
  const p = DEFAULT_PRESETS.find((x) => x.id === id);
  if (!p) throw new Error(`no preset ${id}`);
  return p;
};

const contained = (r: { x: number; y: number; w: number; h: number }): boolean =>
  r.x >= -EPS && r.y >= -EPS && r.x + r.w <= 1 + EPS && r.y + r.h <= 1 + EPS;

const defaultParams = (p: Preset): Record<string, number> =>
  Object.fromEntries((p.params ?? []).map((s) => [s.name, s.default]));

describe('catalog shape', () => {
  it('has the documented presets, all with valid arity and a derive fn', () => {
    for (const p of DEFAULT_PRESETS) {
      expect([0, 1, 2]).toContain(p.arity);
      expect(typeof p.derive).toBe('function');
      expect(p.icon).toBeTruthy();
      expect(p.label).toBeTruthy();
    }
    const ids = DEFAULT_PRESETS.map((p) => p.id);
    for (const want of ['zoom-in', 'zoom-out', 'pan-left-to-right', 'drift', 'push-in-to', 'pull-out-from', 'custom']) {
      expect(ids).toContain(want);
    }
  });
});

describe('arity-0 presets', () => {
  it('zoom-in starts full and ends tighter, centered', () => {
    const p = byId('zoom-in');
    const { start, end } = p.derive([], defaultParams(p), ctx16x9);
    expect(start.zoom).toBeCloseTo(1, 6); // full
    expect(end.zoom).toBeGreaterThan(start.zoom);
    expect(end.center[0]).toBeCloseTo(0.5, 6);
    expect(contained(start) && contained(end)).toBe(true);
  });

  it('zoom-out is the mirror of zoom-in', () => {
    const zin = byId('zoom-in');
    const zout = byId('zoom-out');
    const a = zin.derive([], defaultParams(zin), ctx16x9);
    const b = zout.derive([], defaultParams(zout), ctx16x9);
    expect(b.start.w).toBeCloseTo(a.end.w, 9);
    expect(b.end.w).toBeCloseTo(a.start.w, 9);
  });

  it('pan-left-to-right moves the window rightward at constant size', () => {
    const p = byId('pan-left-to-right');
    const { start, end } = p.derive([], defaultParams(p), ctx16x9);
    expect(end.center[0]).toBeGreaterThan(start.center[0]);
    expect(start.w).toBeCloseTo(end.w, 9);
    expect(start.h).toBeCloseTo(end.h, 9);
  });

  it('drift is deterministic (same args ⇒ same rects)', () => {
    const p = byId('drift');
    const a = p.derive([], defaultParams(p), ctx16x9);
    const b = p.derive([], defaultParams(p), ctx16x9);
    expect(a.start).toEqual(b.start);
    expect(a.end).toEqual(b.end);
  });
});

describe('arity-1 presets', () => {
  const userRect = { x: 0.3, y: 0.3, w: 0.3, h: 0.3 * (9 / 16) };

  it('push-in-to: start full, end is the user rect', () => {
    const p = byId('push-in-to');
    const { start, end } = p.derive([userRect], {}, ctx16x9);
    expect(start.zoom).toBeCloseTo(1, 6);
    expect(end.x).toBeCloseTo(userRect.x, 9);
    expect(end.w).toBeCloseTo(userRect.w, 9);
  });

  it('pull-out-from: start is the user rect, end full', () => {
    const p = byId('pull-out-from');
    const { start, end } = p.derive([userRect], {}, ctx16x9);
    expect(start.x).toBeCloseTo(userRect.x, 9);
    expect(end.zoom).toBeCloseTo(1, 6);
  });

  it('enter-from-left: start rides the left edge, end is the user rect', () => {
    const p = byId('enter-from-left');
    const { start, end } = p.derive([userRect], {}, ctx16x9);
    expect(start.x).toBeCloseTo(0, 6);
    expect(end.x).toBeCloseTo(userRect.x, 9);
    expect(start.w).toBeCloseTo(end.w, 9);
  });

  it('exit-to-right: start is the user rect, end rides the right edge', () => {
    const p = byId('exit-to-right');
    const { start, end } = p.derive([userRect], {}, ctx16x9);
    expect(start.x).toBeCloseTo(userRect.x, 9);
    expect(end.x + end.w).toBeCloseTo(1, 6);
  });
});

describe('custom preset (arity 2)', () => {
  it('passes both drawn rects through as start and end', () => {
    const p = byId('custom');
    const a = { x: 0, y: 0, w: 1, h: 9 / 16 };
    const b = { x: 0.3, y: 0.1, w: 0.4, h: (0.4 * 9) / 16 };
    const { start, end } = p.derive([a, b], {}, ctx16x9);
    expect(start.x).toBeCloseTo(a.x, 9);
    expect(end.x).toBeCloseTo(b.x, 9);
  });
});
