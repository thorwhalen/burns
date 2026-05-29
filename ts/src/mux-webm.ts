/**
 * Optional WebM muxing for the WebCodecs exporter (browser only).
 *
 * {@link exportWebCodecsVideo} deliberately emits raw `EncodedVideoChunk`s and
 * takes no muxer dependency, so the pure core stays dependency-light. This
 * module is the thin, *optional* layer that turns that chunk stream into a
 * playable `.webm` `Blob` by wrapping the [`webm-muxer`](https://www.npmjs.com/package/webm-muxer)
 * package — which is declared as an **optional peer dependency**. It is loaded
 * via dynamic `import()` so a consumer who never mux (e.g. uploads chunks to a
 * server, or muxes with a different library) pays nothing and need not install
 * it.
 *
 * Two entry points:
 * - {@link createWebmMuxer} — low-level: returns an `onChunk` to feed straight
 *   into {@link WebCodecsExportOptions.onChunk}, plus a `finalize()` that
 *   returns the `Blob`. Use when you want to drive the encoder yourself.
 * - {@link exportWebmBlob} — convenience: encode `image` along `path` and
 *   resolve to a ready-to-download `.webm` `Blob` in one call.
 *
 * VP9 (the exporter's default codec) maps to the Matroska/WebM codec id
 * `V_VP9`; VP8 → `V_VP8`, AV1 → `V_AV01`. H.264/HEVC are **not** WebM codecs —
 * for those, mux to MP4 instead (a future `mux-mp4.ts` wrapping `mp4-muxer`).
 */

import type { BurnsPath } from './path.js';
import { outputSizeFor } from './frame.js';
import {
  exportWebCodecsVideo,
  type WebCodecsExportOptions,
  type WebCodecsExportResult,
} from './render-webcodecs.js';

/** Minimal structural view of the bits of `webm-muxer` we use. */
interface WebmMuxerModule {
  Muxer: new (options: {
    target: unknown;
    video: { codec: string; width: number; height: number; frameRate?: number };
    firstTimestampBehavior?: 'strict' | 'offset' | 'permissive';
  }) => {
    addVideoChunk: (
      chunk: EncodedVideoChunk,
      meta?: EncodedVideoChunkMetadata,
    ) => void;
    finalize: () => void;
  };
  ArrayBufferTarget: new () => { buffer: ArrayBuffer };
}

/** A live muxing session: feed chunks via {@link onChunk}, then {@link finalize}. */
export interface WebmMuxer {
  /** Pass this straight to {@link WebCodecsExportOptions.onChunk}. */
  onChunk: (chunk: EncodedVideoChunk, meta?: EncodedVideoChunkMetadata) => void;
  /** Finish the container and return the `.webm` as a `Blob`. Call once. */
  finalize: () => Blob;
}

/** Map a WebCodecs codec string to its WebM (Matroska) codec id. */
function _webmCodecId(webCodecsCodec: string): string {
  if (webCodecsCodec.startsWith('vp09') || webCodecsCodec === 'vp9') {
    return 'V_VP9';
  }
  if (webCodecsCodec.startsWith('vp8') || webCodecsCodec === 'vp8') {
    return 'V_VP8';
  }
  if (webCodecsCodec.startsWith('av01')) {
    return 'V_AV01';
  }
  throw new Error(
    `createWebmMuxer: codec "${webCodecsCodec}" is not a WebM video codec. ` +
      'WebM carries VP8/VP9/AV1; for H.264/HEVC mux to MP4 instead.',
  );
}

async function _loadWebmMuxer(): Promise<WebmMuxerModule> {
  try {
    // Optional peer dependency — resolved only when muxing is actually used.
    return (await import('webm-muxer')) as unknown as WebmMuxerModule;
  } catch {
    throw new Error(
      "createWebmMuxer: the optional peer dependency 'webm-muxer' is not " +
        "installed. Run `npm install webm-muxer` (or pnpm/yarn) to enable " +
        'WebM muxing, or feed exportWebCodecsVideo.onChunk to your own muxer.',
    );
  }
}

/**
 * Start a WebM muxing session for an export of the given size.
 *
 * `codec` must match the {@link WebCodecsExportOptions.codec} you encode with
 * (default VP9). Returns an {@link WebmMuxer} whose `onChunk` is wired to the
 * encoder output and whose `finalize()` yields the playable `Blob`.
 */
export async function createWebmMuxer({
  width,
  height,
  fps,
  codec = 'vp09.00.10.08',
}: {
  width: number;
  height: number;
  fps?: number;
  codec?: string;
}): Promise<WebmMuxer> {
  const { Muxer, ArrayBufferTarget } = await _loadWebmMuxer();
  const target = new ArrayBufferTarget();
  const muxer = new Muxer({
    target,
    video: { codec: _webmCodecId(codec), width, height, frameRate: fps },
    // The encoder's first chunk may carry a non-zero timestamp; offset it so
    // playback starts at 0 rather than the muxer rejecting it.
    firstTimestampBehavior: 'offset',
  });
  let finalized = false;
  return {
    onChunk: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
    finalize: () => {
      if (!finalized) {
        muxer.finalize();
        finalized = true;
      }
      return new Blob([target.buffer], { type: 'video/webm' });
    },
  };
}

/** {@link exportWebmBlob} options — like {@link WebCodecsExportOptions} minus `onChunk`. */
export type WebmExportOptions = Omit<WebCodecsExportOptions, 'onChunk'>;

/** The resolved value of {@link exportWebmBlob}: the file plus its metadata. */
export interface WebmExportResult extends WebCodecsExportResult {
  /** The playable `.webm` file. */
  blob: Blob;
}

/**
 * Encode `image` along `path` and resolve to a playable `.webm` `Blob`.
 *
 * The one-call path: creates a {@link createWebmMuxer}, runs
 * {@link exportWebCodecsVideo} feeding every chunk into it, finalizes, and
 * returns the `Blob` alongside the frame/size/codec metadata. Requires the
 * optional `webm-muxer` peer dependency and a WebCodecs-capable browser.
 */
export async function exportWebmBlob(
  image: CanvasImageSource & { width: number; height: number },
  path: BurnsPath,
  options: WebmExportOptions,
): Promise<WebmExportResult> {
  const fps = options.fps ?? 30;
  const codec = options.codec ?? 'vp09.00.10.08';

  // Resolve the output size the encoder will use so the muxer header matches.
  const [outW, outH] = outputSizeFor(image.width, image.height, {
    outputAspect: options.outputAspect ?? path.outputAspect ?? null,
    outputSize: options.outputSize ?? null,
  });

  const muxer = await createWebmMuxer({ width: outW, height: outH, fps, codec });
  const result = await exportWebCodecsVideo(image, path, {
    ...options,
    onChunk: muxer.onChunk,
  });
  return { ...result, blob: muxer.finalize() };
}
