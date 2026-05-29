/**
 * Unit tests for the optional WebM muxer wiring (`src/mux-webm.ts`).
 *
 * The *encode* path needs a browser; these cover only what runs in Node: the
 * codec-id mapping and the muxing-session shape. `webm-muxer` is a
 * devDependency, so `createWebmMuxer` resolves it and constructs a real `Muxer`
 * (pure buffer work — no DOM needed). The browser encode + a real `.webm` are
 * exercised by the headed Playwright parity test instead.
 */

import { describe, expect, it } from 'vitest';
import { createWebmMuxer } from '../src/mux-webm.js';

describe('createWebmMuxer', () => {
  it('builds a session with onChunk + finalize for VP9 (the default)', async () => {
    const muxer = await createWebmMuxer({ width: 64, height: 48, fps: 30 });
    expect(typeof muxer.onChunk).toBe('function');
    expect(typeof muxer.finalize).toBe('function');
    // No chunks added — finalize still yields a (header-only) WebM Blob.
    const blob = muxer.finalize();
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('video/webm');
  });

  it('finalize is idempotent (safe to call twice)', async () => {
    const muxer = await createWebmMuxer({ width: 32, height: 32 });
    const a = muxer.finalize();
    const b = muxer.finalize();
    expect(a).toBeInstanceOf(Blob);
    expect(b).toBeInstanceOf(Blob);
  });

  it('maps vp8 and av1 codec strings without throwing', async () => {
    await expect(
      createWebmMuxer({ width: 16, height: 16, codec: 'vp8' }),
    ).resolves.toBeDefined();
    await expect(
      createWebmMuxer({ width: 16, height: 16, codec: 'av01.0.04M.08' }),
    ).resolves.toBeDefined();
  });

  it('rejects a non-WebM codec (H.264 belongs in MP4)', async () => {
    await expect(
      createWebmMuxer({ width: 64, height: 48, codec: 'avc1.42001f' }),
    ).rejects.toThrow(/not a WebM video codec/);
  });
});
