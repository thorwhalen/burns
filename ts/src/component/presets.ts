/**
 * The preset catalog — data-driven motion templates (spec §5).
 *
 * A {@link Preset} is a parameterised template that takes 0, 1, or 2
 * user-drawn rects plus named parameters and yields the full `(start, end)`
 * pair. The catalog is **data**: adding a preset is adding an entry, never
 * editing the core or the state machine. Hosts override the set via
 * `Config.presets` (a subset of ids, or their own {@link Preset} objects).
 *
 * `derive` is pure and clamps its results to the containment constraint (it
 * builds rects through `geometry.ts`, which clamps). Icons are referenced by
 * `lucide`-style *name* so any renderer can pick a matching icon family — the
 * preset never ships an SVG.
 */

import type { Rect } from '../rect.js';
import {
  maxContainedRect,
  scaledContainedRect,
  toRect,
} from './geometry.js';
import type { RectData } from './schema.js';

/** A tunable numeric parameter a preset exposes to the UI. */
export interface ParamSpec {
  name: string;
  label: string;
  default: number;
  min?: number;
  max?: number;
  step?: number;
}

/** Context every `derive` receives: the resolved aspect lock + image AR. */
export interface PresetContext {
  /** Normalized `w / h` lock ratio (`outputAspect / imageAspect`). */
  lockRatio: number;
  /** The image's pixel aspect ratio (`width / height`). */
  imageAspect: number;
}

/** The `(start, end)` pair a preset derives. */
export interface StartEnd {
  start: Rect;
  end: Rect;
}

export interface Preset {
  id: string;
  label: string;
  description: string;
  /** A `lucide`-style icon name; renderers map it to their icon family. */
  icon: string;
  /** How many rects the user draws (0, 1, or 2). */
  arity: 0 | 1 | 2;
  /** Tunable parameters, surfaced in the UI with these defaults. */
  params?: ParamSpec[];
  /** Pure: user rects + params + context → the `(start, end)` pair. */
  derive: (rects: RectData[], params: Record<string, number>, ctx: PresetContext) => StartEnd;
}

const ZOOM_PARAM = (def: number): ParamSpec => ({
  name: 'zoomFactor',
  label: 'Zoom',
  default: def,
  min: 1.05,
  max: 4,
  step: 0.05,
});

/** Default param value lookup with a fallback. */
function p(params: Record<string, number>, name: string, fallback: number): number {
  const v = params[name];
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback;
}

/** The first user rect, or a sensible centered default if none drawn yet. */
function userRect(rects: RectData[], ctx: PresetContext, zoom = 1.8): Rect {
  const r = rects[0];
  return r ? toRect(r) : scaledContainedRect(ctx.lockRatio, zoom);
}

/**
 * The default catalog (spec §5). Opinionated but fully overridable: a host
 * passing `presets: ["push-in-to", "pull-out-from"]` gets only those two.
 */
export const DEFAULT_PRESETS: Preset[] = [
  // --- arity 0 -----------------------------------------------------------
  {
    id: 'zoom-in',
    label: 'Zoom in',
    description: 'Push in toward the centre.',
    icon: 'zoom-in',
    arity: 0,
    params: [ZOOM_PARAM(1.3)],
    derive: (_r, params, ctx) => ({
      start: maxContainedRect(ctx.lockRatio),
      end: scaledContainedRect(ctx.lockRatio, p(params, 'zoomFactor', 1.3)),
    }),
  },
  {
    id: 'zoom-out',
    label: 'Zoom out',
    description: 'Pull out from the centre.',
    icon: 'zoom-out',
    arity: 0,
    params: [ZOOM_PARAM(1.3)],
    derive: (_r, params, ctx) => ({
      start: scaledContainedRect(ctx.lockRatio, p(params, 'zoomFactor', 1.3)),
      end: maxContainedRect(ctx.lockRatio),
    }),
  },
  {
    id: 'pan-left-to-right',
    label: 'Pan →',
    description: 'Slow pan across the image, left to right.',
    icon: 'arrow-right',
    arity: 0,
    params: [ZOOM_PARAM(1.2)],
    derive: (_r, params, ctx) => panEndpoints(ctx, p(params, 'zoomFactor', 1.2), 'h', 1),
  },
  {
    id: 'pan-right-to-left',
    label: 'Pan ←',
    description: 'Slow pan across the image, right to left.',
    icon: 'arrow-left',
    arity: 0,
    params: [ZOOM_PARAM(1.2)],
    derive: (_r, params, ctx) => panEndpoints(ctx, p(params, 'zoomFactor', 1.2), 'h', -1),
  },
  {
    id: 'pan-top-to-bottom',
    label: 'Pan ↓',
    description: 'Slow pan down the image.',
    icon: 'arrow-down',
    arity: 0,
    params: [ZOOM_PARAM(1.2)],
    derive: (_r, params, ctx) => panEndpoints(ctx, p(params, 'zoomFactor', 1.2), 'v', 1),
  },
  {
    id: 'pan-bottom-to-top',
    label: 'Pan ↑',
    description: 'Slow pan up the image.',
    icon: 'arrow-up',
    arity: 0,
    params: [ZOOM_PARAM(1.2)],
    derive: (_r, params, ctx) => panEndpoints(ctx, p(params, 'zoomFactor', 1.2), 'v', -1),
  },
  {
    id: 'drift',
    label: 'Drift',
    description: 'A subtle drift — small pan plus a tiny zoom.',
    icon: 'move',
    arity: 0,
    params: [
      { name: 'intensity', label: 'Intensity', default: 0.05, min: 0.01, max: 0.2, step: 0.01 },
    ],
    derive: (_r, params, ctx) => {
      const i = p(params, 'intensity', 0.05);
      const zoom = 1 + i;
      return {
        start: scaledContainedRect(ctx.lockRatio, zoom, 0.5 - i, 0.5),
        end: scaledContainedRect(ctx.lockRatio, zoom, 0.5 + i, 0.5),
      };
    },
  },
  // --- arity 1 -----------------------------------------------------------
  {
    id: 'push-in-to',
    label: 'Push in to…',
    description: 'Start on the full image, push in to your selection.',
    icon: 'crosshair-zoom-in',
    arity: 1,
    derive: (rects, _params, ctx) => ({
      start: maxContainedRect(ctx.lockRatio),
      end: userRect(rects, ctx),
    }),
  },
  {
    id: 'pull-out-from',
    label: 'Pull out from…',
    description: 'Start on your selection, pull out to the full image.',
    icon: 'crosshair-zoom-out',
    arity: 1,
    derive: (rects, _params, ctx) => ({
      start: userRect(rects, ctx),
      end: maxContainedRect(ctx.lockRatio),
    }),
  },
  {
    id: 'enter-from-left',
    label: 'Enter from left',
    description: 'Slide your selection in from the left edge.',
    icon: 'arrow-right-circle',
    arity: 1,
    derive: (rects, _params, ctx) => enterExit(rects, ctx, 'left', 'enter'),
  },
  {
    id: 'enter-from-right',
    label: 'Enter from right',
    description: 'Slide your selection in from the right edge.',
    icon: 'arrow-left-circle',
    arity: 1,
    derive: (rects, _params, ctx) => enterExit(rects, ctx, 'right', 'enter'),
  },
  {
    id: 'enter-from-top',
    label: 'Enter from top',
    description: 'Slide your selection in from the top edge.',
    icon: 'arrow-down-circle',
    arity: 1,
    derive: (rects, _params, ctx) => enterExit(rects, ctx, 'top', 'enter'),
  },
  {
    id: 'enter-from-bottom',
    label: 'Enter from bottom',
    description: 'Slide your selection in from the bottom edge.',
    icon: 'arrow-up-circle',
    arity: 1,
    derive: (rects, _params, ctx) => enterExit(rects, ctx, 'bottom', 'enter'),
  },
  {
    id: 'exit-to-left',
    label: 'Exit to left',
    description: 'Slide your selection out toward the left edge.',
    icon: 'arrow-left-circle',
    arity: 1,
    derive: (rects, _params, ctx) => enterExit(rects, ctx, 'left', 'exit'),
  },
  {
    id: 'exit-to-right',
    label: 'Exit to right',
    description: 'Slide your selection out toward the right edge.',
    icon: 'arrow-right-circle',
    arity: 1,
    derive: (rects, _params, ctx) => enterExit(rects, ctx, 'right', 'exit'),
  },
  {
    id: 'reveal-around',
    label: 'Reveal around',
    description: 'Start on your selection, reveal the surrounding context.',
    icon: 'expand',
    arity: 1,
    derive: (rects, _params, ctx) => ({
      start: userRect(rects, ctx),
      end: maxContainedRect(ctx.lockRatio),
    }),
  },
  // --- arity 2 -----------------------------------------------------------
  {
    id: 'custom',
    label: 'Custom',
    description: 'Draw both the Start and End windows yourself.',
    icon: 'pencil',
    arity: 2,
    derive: (rects, _params, ctx) => ({
      start: rects[0] ? toRect(rects[0]) : maxContainedRect(ctx.lockRatio),
      end: rects[1]
        ? toRect(rects[1])
        : scaledContainedRect(ctx.lockRatio, 1.3),
    }),
  },
];

/** Endpoints for the four pan presets. `axis`: `"h"` or `"v"`; `dir`: ±1. */
function panEndpoints(
  ctx: PresetContext,
  zoom: number,
  axis: 'h' | 'v',
  dir: 1 | -1,
): StartEnd {
  const lo = axis === 'h'
    ? scaledContainedRect(ctx.lockRatio, zoom, 0, 0.5)
    : scaledContainedRect(ctx.lockRatio, zoom, 0.5, 0);
  const hi = axis === 'h'
    ? scaledContainedRect(ctx.lockRatio, zoom, 1, 0.5)
    : scaledContainedRect(ctx.lockRatio, zoom, 0.5, 1);
  return dir === 1 ? { start: lo, end: hi } : { start: hi, end: lo };
}

/** Endpoints for the enter-/exit-from-edge presets. */
function enterExit(
  rects: RectData[],
  ctx: PresetContext,
  edge: 'left' | 'right' | 'top' | 'bottom',
  kind: 'enter' | 'exit',
): StartEnd {
  const placed = userRect(rects, ctx);
  const offFrame = slideToEdge(placed, edge);
  // Enter: come from the edge to the drawn position. Exit: the reverse.
  return kind === 'enter'
    ? { start: offFrame, end: placed }
    : { start: placed, end: offFrame };
}

/** The drawn rect translated until it rides the named image edge. */
function slideToEdge(
  r: Rect,
  edge: 'left' | 'right' | 'top' | 'bottom',
): Rect {
  switch (edge) {
    case 'left':
      return toRect({ x: 0, y: r.y, w: r.w, h: r.h }).clamped();
    case 'right':
      return toRect({ x: 1 - r.w, y: r.y, w: r.w, h: r.h }).clamped();
    case 'top':
      return toRect({ x: r.x, y: 0, w: r.w, h: r.h }).clamped();
    case 'bottom':
      return toRect({ x: r.x, y: 1 - r.h, w: r.w, h: r.h }).clamped();
  }
}
