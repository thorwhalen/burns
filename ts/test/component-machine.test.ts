/**
 * Unit tests for the headless state machine (the pure reducer + selectors).
 *
 * Covers init from config, every event, swap/reverse, edit-target mapping,
 * value emission (validated against the zod wire schema), and round-tripping an
 * emitted value back into editable state.
 */

import { describe, it, expect } from 'vitest';
import {
  initState,
  reduce,
  resolveCatalog,
  resolveStartEnd,
  editTargets,
  toValue,
  valueSchema,
  type ConfigInput,
  type State,
  type Event,
  type Catalog,
} from '../src/component/index.js';

const baseConfig: ConfigInput = {
  image: { src: 'x.png', width: 1920, height: 1080 },
  targetAspect: { num: 16, den: 9, locked: true },
};

function setup(config: ConfigInput = baseConfig): { state: State; catalog: Catalog } {
  const catalog = resolveCatalog(config);
  return { state: initState(config, { catalog }), catalog };
}

const step = (s: State, c: Catalog, ...events: Event[]): State =>
  events.reduce((acc, e) => reduce(acc, e, c), s);

describe('initState', () => {
  it('resolves a locked aspect and disables the AR control', () => {
    const { state } = setup();
    expect(state.outputAspect).toEqual({ num: 16, den: 9 });
    expect(state.aspectEditable).toBe(false);
    expect(state.durationMs).toBe(5000);
    expect(state.easing).toBe('ease-in-out');
  });

  it('match-image derives the AR from the image and locks it', () => {
    const { state } = setup({
      image: { src: 'x', width: 800, height: 600 },
      targetAspect: 'match-image',
    });
    expect(state.outputAspect).toEqual({ num: 4, den: 3 });
    expect(state.aspectEditable).toBe(false);
  });

  it('an absent targetAspect seeds from the image but stays editable', () => {
    const { state } = setup({ image: { src: 'x', width: 1000, height: 500 } });
    expect(state.outputAspect).toEqual({ num: 2, den: 1 });
    expect(state.aspectEditable).toBe(true);
  });

  it('honors duration + easing editability config', () => {
    const { state } = setup({
      ...baseConfig,
      duration: { defaultMs: 3000, editable: false },
      easing: { default: 'linear', editable: false },
    });
    expect(state.durationMs).toBe(3000);
    expect(state.durationEditable).toBe(false);
    expect(state.easingEditable).toBe(false);
  });
});

describe('resolveCatalog', () => {
  it('a string subset selects those presets in order', () => {
    const c = resolveCatalog({ ...baseConfig, presets: ['pull-out-from', 'push-in-to'] });
    expect(c.map((p) => p.id)).toEqual(['pull-out-from', 'push-in-to']);
  });

  it('allowCustom false drops the custom preset', () => {
    const c = resolveCatalog({ ...baseConfig, allowCustom: false });
    expect(c.some((p) => p.id === 'custom')).toBe(false);
  });
});

describe('reduce — events', () => {
  it('selectPreset switches preset, resets params + rects', () => {
    const { state, catalog } = setup();
    const s2 = step(state, catalog, { type: 'selectPreset', presetId: 'zoom-in' });
    expect(s2.presetId).toBe('zoom-in');
    expect(s2.presetParams['zoomFactor']).toBe(1.3);
    expect(s2.rects).toEqual([]); // arity 0
  });

  it('setParam updates a single preset parameter', () => {
    const { state, catalog } = setup();
    const s2 = step(state, catalog,
      { type: 'selectPreset', presetId: 'zoom-in' },
      { type: 'setParam', name: 'zoomFactor', value: 2 });
    expect(s2.presetParams['zoomFactor']).toBe(2);
  });

  it('setRect clamps the rect into the image', () => {
    const { state, catalog } = setup();
    const s2 = step(state, catalog,
      { type: 'selectPreset', presetId: 'push-in-to' },
      { type: 'setRect', index: 0, rect: { x: 0.9, y: 0.9, w: 0.5, h: 0.2 } });
    const r = s2.rects[0]!;
    expect(r.x + r.w).toBeLessThanOrEqual(1 + 1e-6);
    expect(r.y + r.h).toBeLessThanOrEqual(1 + 1e-6);
  });

  it('nudgeRect translates by a normalized delta', () => {
    const { state, catalog } = setup();
    const s1 = step(state, catalog, { type: 'selectPreset', presetId: 'push-in-to' });
    const before = s1.rects[0]!.x;
    const s2 = step(s1, catalog, { type: 'nudgeRect', index: 0, dx: 0.05, dy: 0 });
    expect(s2.rects[0]!.x).toBeCloseTo(before + 0.05, 6);
  });

  it('locked duration / easing / aspect are no-ops', () => {
    const { state, catalog } = setup(); // duration editable by default, aspect locked
    const s2 = step(state, catalog, { type: 'setAspect', aspect: { num: 1, den: 1 } });
    expect(s2.outputAspect).toEqual({ num: 16, den: 9 }); // unchanged (locked)
  });

  it('editable aspect updates and re-derives default rects', () => {
    const cfg: ConfigInput = { image: { src: 'x', width: 1000, height: 1000 } };
    const catalog = resolveCatalog(cfg);
    const s0 = initState(cfg, { catalog });
    const s1 = step(s0, catalog, { type: 'setAspect', aspect: { num: 4, den: 3 } });
    expect(s1.outputAspect).toEqual({ num: 4, den: 3 });
  });
});

describe('swap / reverse', () => {
  it('swap toggles the reversed flag and flips start/end', () => {
    const { state, catalog } = setup();
    const s1 = step(state, catalog, { type: 'selectPreset', presetId: 'zoom-in' });
    const before = resolveStartEnd(s1, catalog);
    const s2 = step(s1, catalog, { type: 'swap' });
    expect(s2.reversed).toBe(true);
    const after = resolveStartEnd(s2, catalog);
    expect(after.start.w).toBeCloseTo(before.end.w, 9);
    expect(after.end.w).toBeCloseTo(before.start.w, 9);
  });

  it('selectPreset resets the reversed flag', () => {
    const { state, catalog } = setup();
    const s2 = step(state, catalog, { type: 'swap' }, { type: 'selectPreset', presetId: 'drift' });
    expect(s2.reversed).toBe(false);
  });
});

describe('editTargets', () => {
  it('arity-0 presets expose no editable rect', () => {
    const { state, catalog } = setup();
    const s = step(state, catalog, { type: 'selectPreset', presetId: 'zoom-in' });
    expect(editTargets(s, catalog)).toEqual({});
  });

  it('push-in-to puts the editable rect on End', () => {
    const { state, catalog } = setup();
    const s = step(state, catalog, { type: 'selectPreset', presetId: 'push-in-to' });
    expect(editTargets(s, catalog)).toEqual({ end: 0 });
  });

  it('swap moves the editable rect to the other slot', () => {
    const { state, catalog } = setup();
    const s = step(state, catalog,
      { type: 'selectPreset', presetId: 'push-in-to' },
      { type: 'swap' });
    expect(editTargets(s, catalog)).toEqual({ start: 0 });
  });

  it('custom exposes both rects', () => {
    const { state, catalog } = setup();
    const s = step(state, catalog, { type: 'selectPreset', presetId: 'custom' });
    expect(editTargets(s, catalog)).toEqual({ start: 0, end: 1 });
  });
});

describe('toValue', () => {
  it('emits a wire value that validates against valueSchema', () => {
    const { state, catalog } = setup();
    const s = step(state, catalog, { type: 'selectPreset', presetId: 'zoom-in' });
    const value = toValue(s, catalog);
    expect(() => valueSchema.parse(value)).not.toThrow();
    expect(value.version).toBe(1);
    expect(value.keyframes).toHaveLength(2);
    expect(value.output_aspect).toBeCloseTo(16 / 9, 6);
    expect(value.duration_ms).toBe(5000);
    expect(value.meta?.preset_id).toBe('zoom-in');
    expect(value.meta?.output_aspect_ratio).toEqual({ num: 16, den: 9 });
  });

  it('round-trips: an emitted value re-opens as editable state', () => {
    const { state, catalog } = setup();
    const s = step(state, catalog,
      { type: 'selectPreset', presetId: 'custom' },
      { type: 'setRect', index: 1, rect: { x: 0.2, y: 0.1, w: 0.4, h: (0.4 * 9) / 16 } });
    const value = toValue(s, catalog);
    const reopened = initState(baseConfig, { catalog, initialValue: value });
    expect(reopened.presetId).toBe('custom');
    expect(reopened.durationMs).toBe(value.duration_ms);
    const reEmitted = toValue(reopened, catalog);
    expect(reEmitted.keyframes).toEqual(value.keyframes);
  });

  it('all default presets emit schema-valid values', () => {
    const { state, catalog } = setup();
    for (const preset of catalog) {
      const s = step(state, catalog, { type: 'selectPreset', presetId: preset.id });
      expect(() => valueSchema.parse(toValue(s, catalog)), preset.id).not.toThrow();
    }
  });
});
