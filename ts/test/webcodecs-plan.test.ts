/**
 * Unit tests for the pure WebCodecs frame *plan* (the encode path itself needs
 * a browser and is not tested here).
 */

import { describe, expect, it } from 'vitest';

import { Rect } from '../src/rect.js';
import { BurnsPath } from '../src/path.js';
import { sampleBox } from '../src/frame.js';
import { isWebCodecsSupported, planFrames } from '../src/render-webcodecs.js';

const PATH = BurnsPath.fromStartEnd(
  new Rect(0, 0, 1, 1),
  new Rect(0, 0, 0.5, 0.5),
  { easing: 'linear' },
);

describe('planFrames', () => {
  it('produces round(duration*fps) frames', () => {
    const plans = planFrames(PATH, {
      imgW: 64,
      imgH: 48,
      outW: 64,
      outH: 48,
      duration: 2,
      fps: 30,
    });
    expect(plans.length).toBe(60);
    expect(plans[0]!.index).toBe(0);
  });

  it('matches the Python frame schedule: t = (i/fps)/duration, not endpoint-inclusive', () => {
    const fps = 10;
    const duration = 1;
    const plans = planFrames(PATH, {
      imgW: 64,
      imgH: 48,
      outW: 64,
      outH: 48,
      duration,
      fps,
    });
    expect(plans.length).toBe(10);
    expect(plans[0]!.t).toBe(0);
    // Last frame is i=9 -> t = (9/10)/1 = 0.9, NOT 1.0.
    expect(plans[9]!.t).toBeCloseTo(0.9, 10);
    expect(plans[9]!.timestampMicros).toBe(900_000);
  });

  it("each plan's sourceBox equals a direct sampleBox call", () => {
    const dims = { imgW: 64, imgH: 48, outW: 48, outH: 48 };
    const plans = planFrames(PATH, { ...dims, duration: 0.5, fps: 8 });
    for (const p of plans) {
      expect([...p.sourceBox]).toEqual([
        ...sampleBox(PATH, p.t, dims.imgW, dims.imgH, dims.outW, dims.outH),
      ]);
    }
  });

  it('rejects non-positive duration and fps', () => {
    const dims = { imgW: 64, imgH: 48, outW: 64, outH: 48 };
    expect(() => planFrames(PATH, { ...dims, duration: 0, fps: 30 })).toThrow(
      /duration must be/,
    );
    expect(() => planFrames(PATH, { ...dims, duration: 1, fps: 0 })).toThrow(
      /fps must be/,
    );
  });
});

describe('isWebCodecsSupported', () => {
  it('is false under Node (no VideoEncoder)', () => {
    expect(isWebCodecsSupported()).toBe(false);
  });
});
