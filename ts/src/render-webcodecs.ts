/**
 * Browser-side video export of a {@link BurnsPath} via the WebCodecs API.
 *
 * Each output frame is the source image cropped to {@link sampleBox} and
 * resized onto an `OffscreenCanvas`, then handed to a `VideoEncoder`. The
 * frame schedule mirrors the Python renderer exactly: frame `i` is sampled at
 * `t = (i / fps) / duration` for `i` in `0 .. n-1` (so it is *not* endpoint-
 * inclusive — the last frame's `t` is just under 1), making a WebCodecs export
 * and a Python export sample the identical sequence of windows.
 *
 * WebCodecs produces raw **encoded chunks**, not a container. Muxing those into
 * a playable `.mp4` / `.webm` is the caller's job (e.g. `mp4-muxer` /
 * `webm-muxer`); this module deliberately takes no muxer dependency and instead
 * streams every {@link VideoEncoderOutput} to an `onChunk` callback.
 *
 * NOTE: the per-frame *plan* ({@link planFrames}) is pure and unit-tested in
 * Node. The encode path needs a browser (WebCodecs + OffscreenCanvas) and is
 * **not** exercised by the Node test suite — guard with
 * {@link isWebCodecsSupported} and verify in a real browser.
 */

import type { BurnsPath } from './path.js';
import { outputSizeFor, sampleBox } from './frame.js';

/** One planned frame: when to sample and which source box to draw. */
export interface FramePlan {
  /** Frame index, `0 .. n-1`. */
  index: number;
  /** Normalized clock time fed to `path.evaluate`. */
  t: number;
  /** Presentation timestamp in microseconds (`VideoFrame.timestamp`). */
  timestampMicros: number;
  /** Source crop box `[x0, y0, x1, y1]` (half-open) — from {@link sampleBox}. */
  sourceBox: readonly [number, number, number, number];
}

/** True only where the WebCodecs encode path can actually run. */
export function isWebCodecsSupported(): boolean {
  return (
    typeof globalThis !== 'undefined' &&
    typeof (globalThis as { VideoEncoder?: unknown }).VideoEncoder !==
      'undefined' &&
    typeof (globalThis as { VideoFrame?: unknown }).VideoFrame !== 'undefined' &&
    typeof (globalThis as { OffscreenCanvas?: unknown }).OffscreenCanvas !==
      'undefined'
  );
}

/**
 * The pure frame schedule for an export — no image, no canvas, no encoder.
 *
 * Returns one {@link FramePlan} per output frame, each carrying the
 * {@link sampleBox} crop for its `t`. This is the deterministic core the encode
 * loop consumes, isolated so it can be tested without a browser.
 */
export function planFrames(
  path: BurnsPath,
  {
    imgW,
    imgH,
    outW,
    outH,
    duration,
    fps,
  }: {
    imgW: number;
    imgH: number;
    outW: number;
    outH: number;
    duration: number;
    fps: number;
  },
): FramePlan[] {
  if (duration <= 0) {
    throw new Error(`planFrames: duration must be > 0, got ${duration}`);
  }
  if (fps <= 0) {
    throw new Error(`planFrames: fps must be > 0, got ${fps}`);
  }
  const n = Math.max(1, Math.round(duration * fps));
  const plans: FramePlan[] = [];
  for (let i = 0; i < n; i++) {
    const tSeconds = i / fps;
    const t = Math.min(1, tSeconds / duration);
    plans.push({
      index: i,
      t,
      timestampMicros: Math.round(tSeconds * 1e6),
      sourceBox: sampleBox(path, t, imgW, imgH, outW, outH),
    });
  }
  return plans;
}

export interface WebCodecsExportOptions {
  /** Clip length in seconds. */
  duration: number;
  /** Frames per second (default 30). */
  fps?: number;
  /** Explicit output size; else derived from `outputAspect` / the image. */
  outputSize?: readonly [number, number];
  /** Output aspect ratio when `outputSize` is omitted (default: the path's). */
  outputAspect?: number | null;
  /** WebCodecs codec string (default VP9 — broad browser support). */
  codec?: string;
  /** Target bitrate in bits/sec (default 5_000_000). */
  bitrate?: number;
  /** Called for every encoded chunk; receives the chunk + its metadata. */
  onChunk: (chunk: EncodedVideoChunk, meta?: EncodedVideoChunkMetadata) => void;
}

/** Result metadata once every frame has been encoded and flushed. */
export interface WebCodecsExportResult {
  frameCount: number;
  width: number;
  height: number;
  codec: string;
}

/**
 * Encode `image` along `path` into WebCodecs video chunks (browser only).
 *
 * Draws each {@link FramePlan}'s `sourceBox` onto an `OffscreenCanvas` of the
 * output size and encodes it. Resolves once the encoder has flushed. Throws if
 * WebCodecs is unavailable — gate calls with {@link isWebCodecsSupported}.
 */
export async function exportWebCodecsVideo(
  image: CanvasImageSource & { width: number; height: number },
  path: BurnsPath,
  options: WebCodecsExportOptions,
): Promise<WebCodecsExportResult> {
  if (!isWebCodecsSupported()) {
    throw new Error(
      'exportWebCodecsVideo: WebCodecs is unavailable in this environment. ' +
        'Guard with isWebCodecsSupported(); WebCodecs needs a modern browser.',
    );
  }

  const {
    duration,
    fps = 30,
    outputSize,
    outputAspect = path.outputAspect,
    codec = 'vp09.00.10.08',
    bitrate = 5_000_000,
    onChunk,
  } = options;

  const imgW = image.width;
  const imgH = image.height;
  const [outW, outH] = outputSizeFor(imgW, imgH, {
    outputAspect: outputAspect ?? null,
    outputSize: outputSize ?? null,
  });

  const plans = planFrames(path, { imgW, imgH, outW, outH, duration, fps });

  const canvas = new OffscreenCanvas(outW, outH);
  const ctx = canvas.getContext('2d');
  if (ctx === null) {
    throw new Error('exportWebCodecsVideo: could not get a 2D canvas context');
  }
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';

  let encodeError: unknown = null;
  const encoder = new VideoEncoder({
    output: (chunk, meta) => onChunk(chunk, meta),
    error: (e) => {
      encodeError = e;
    },
  });
  encoder.configure({
    codec,
    width: outW,
    height: outH,
    bitrate,
    framerate: fps,
  });

  for (const plan of plans) {
    if (encodeError !== null) break;
    const [sx0, sy0, sx1, sy1] = plan.sourceBox;
    ctx.clearRect(0, 0, outW, outH);
    ctx.drawImage(image, sx0, sy0, sx1 - sx0, sy1 - sy0, 0, 0, outW, outH);
    const frame = new VideoFrame(canvas, { timestamp: plan.timestampMicros });
    // Key every ~1s so the stream is seekable.
    encoder.encode(frame, { keyFrame: plan.index % fps === 0 });
    frame.close();
  }

  await encoder.flush();
  encoder.close();
  if (encodeError !== null) throw encodeError;

  return { frameCount: plans.length, width: outW, height: outH, codec };
}
