/**
 * Golden-vector conformance — the cross-language equivalence contract.
 *
 * Loads the *same* `tests/golden/vectors.json` the Python suite asserts against
 * (this package is co-located in the `burns` repo precisely so there is one
 * physical fixture, not a copy that can drift) and proves the TypeScript port
 * reproduces it:
 *
 *   - `evaluate`  — `(spec, t) -> Rect` within the fixture's `eps`.
 *   - `pixel_box` — `(spec, image, output, t) -> box` as EXACT integers.
 *
 * If this fails, the two languages have diverged — fix the TS port (or, if the
 * Python spec math changed intentionally, regenerate the fixture there).
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { BurnsPath, type BurnsPathDict } from '../src/path.js';
import { sampleBox } from '../src/frame.js';

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = resolve(here, '..', '..', 'tests', 'golden', 'vectors.json');

interface EvalVector {
  name: string;
  path: BurnsPathDict;
  samples: { t: number; rect: { x: number; y: number; w: number; h: number } }[];
}
interface PixelBoxVector {
  name: string;
  path: BurnsPathDict;
  image_size: [number, number];
  output_size: [number, number];
  samples: { t: number; box: [number, number, number, number] }[];
}
interface Fixture {
  spec_version: number;
  eps: number;
  t_samples: number[];
  evaluate: EvalVector[];
  pixel_box: PixelBoxVector[];
}

const fixture: Fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));

describe('golden vectors fixture', () => {
  it('is present and populated', () => {
    expect(fixture.evaluate.length).toBeGreaterThan(0);
    expect(fixture.pixel_box.length).toBeGreaterThan(0);
  });

  it('covers the required surface (constructors, easings, kbp, clamp, AR)', () => {
    const evalNames = new Set(fixture.evaluate.map((v) => v.name));
    for (const n of ['from_start_end_linear', 'push_in_default', 'three_keyframe', 'reversed']) {
      expect(evalNames).toContain(n);
    }
    for (const n of [
      'easing_linear',
      'easing_ease',
      'easing_ease-in',
      'easing_ease-out',
      'easing_ease-in-out',
      'easing_cubic_bezier',
    ]) {
      expect(evalNames).toContain(n);
    }
    for (const n of ['kbp_push_odd', 'kbp_push_even', 'kbp_drift', 'clamp_ride_the_wall']) {
      expect(evalNames).toContain(n);
    }
    const boxNames = [...new Set(fixture.pixel_box.map((v) => v.name))];
    expect(boxNames.some((n) => n.endsWith('__match'))).toBe(true);
    expect(boxNames.some((n) => n.endsWith('__square'))).toBe(true);
    expect(boxNames.some((n) => n.endsWith('__wide'))).toBe(true);
    expect(boxNames.some((n) => n.startsWith('clamp_ride_the_wall'))).toBe(true);
  });
});

describe('evaluate vectors reproduce (within eps)', () => {
  const eps = fixture.eps;
  for (const vec of fixture.evaluate) {
    it(vec.name, () => {
      const path = BurnsPath.fromDict(vec.path);
      for (const { t, rect } of vec.samples) {
        const r = path.evaluate(t);
        expect(r.x, `${vec.name}@${t}.x`).toBeCloseTo(rect.x, -Math.log10(eps));
        expect(r.y, `${vec.name}@${t}.y`).toBeCloseTo(rect.y, -Math.log10(eps));
        expect(r.w, `${vec.name}@${t}.w`).toBeCloseTo(rect.w, -Math.log10(eps));
        expect(r.h, `${vec.name}@${t}.h`).toBeCloseTo(rect.h, -Math.log10(eps));
      }
    });
  }
});

describe('pixel_box vectors reproduce (exact integers)', () => {
  for (const vec of fixture.pixel_box) {
    it(vec.name, () => {
      const path = BurnsPath.fromDict(vec.path);
      const [imgW, imgH] = vec.image_size;
      const [outW, outH] = vec.output_size;
      for (const { t, box } of vec.samples) {
        const got = sampleBox(path, t, imgW, imgH, outW, outH);
        expect([...got], `${vec.name}@${t}`).toEqual(box);
      }
    });
  }
});

describe('path round-trips through the wire format', () => {
  for (const vec of fixture.evaluate) {
    it(vec.name, () => {
      const path = BurnsPath.fromDict(vec.path);
      // Re-serializing must reproduce the stored dict exactly (the wire format
      // is itself part of the contract).
      expect(path.toDict()).toEqual(vec.path);
    });
  }
});
