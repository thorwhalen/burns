/**
 * The headless state machine — a pure reducer over {@link State}.
 *
 * Events in, new state out; no DOM, no listeners, no side effects. This is the
 * entire behaviour of the path-entry component. A renderer is a thin shell that
 * (1) maps user interaction to {@link Event}s, (2) dispatches them through
 * {@link reduce}, and (3) draws the resulting state plus the derived
 * `(start, end)` rects from {@link resolveStartEnd}. The emitted
 * {@link Value} comes from {@link toValue} / {@link buildPath}.
 *
 * State holds only raw authoring inputs. The derived rects and the wire value
 * are computed by the selectors below, never stored — so there is exactly one
 * source of truth and no cache to invalidate.
 */

import { BurnsPath } from '../path.js';
import type { Rect } from '../rect.js';
import {
  aspectValue,
  lockRatio as lockRatioOf,
  maxContainedRect,
  scaledContainedRect,
  simplifyRatio,
  translateRect,
  scaleRect,
  toRect,
  toRectData,
  imageAspectOf,
} from './geometry.js';
import {
  DEFAULT_PRESETS,
  type Preset,
  type PresetContext,
  type StartEnd,
} from './presets.js';
import type {
  AspectRatio,
  ConfigInput,
  EasingId,
  RectData,
  State,
  Value,
  ValueMeta,
} from './schema.js';

export { DEFAULT_PRESETS } from './presets.js';
export type { Preset } from './presets.js';

const DFLT_DURATION_MS = 5000;
const DFLT_EASING: EasingId = 'ease-in-out';

/** Events the reducer understands. Renderers map interaction to these. */
export type Event =
  | { type: 'selectPreset'; presetId: string }
  | { type: 'setParam'; name: string; value: number }
  | { type: 'setRect'; index: number; rect: RectData }
  | { type: 'nudgeRect'; index: number; dx: number; dy: number }
  | { type: 'scaleRect'; index: number; factor: number }
  | { type: 'setDuration'; ms: number }
  | { type: 'setEasing'; easing: EasingId }
  | { type: 'setAspect'; aspect: AspectRatio }
  | { type: 'swap' };

/** A resolved catalog: the host's chosen presets, defaults filled in. */
export type Catalog = Preset[];

/**
 * Resolve `Config.presets` to a concrete {@link Catalog}.
 *
 * `"default"` / omitted ⇒ the full {@link DEFAULT_PRESETS}. An array of ids
 * selects that subset (order preserved). `allowCustom: false` drops `custom`.
 * Hosts wanting bespoke presets pass {@link Preset} objects directly to
 * {@link initState} via its `catalog` option instead.
 */
export function resolveCatalog(config: ConfigInput): Catalog {
  const all = DEFAULT_PRESETS;
  let catalog: Preset[];
  if (!config.presets || config.presets === 'default') {
    catalog = [...all];
  } else {
    const byId = new Map(all.map((p) => [p.id, p]));
    catalog = config.presets
      .map((id) => byId.get(id))
      .filter((p): p is Preset => p !== undefined);
  }
  if (config.allowCustom === false) {
    catalog = catalog.filter((p) => p.id !== 'custom');
  }
  return catalog.length > 0 ? catalog : [...all];
}

function presetById(catalog: Catalog, id: string): Preset {
  const found = catalog.find((p) => p.id === id);
  if (!found) {
    throw new Error(
      `Unknown preset ${JSON.stringify(id)}; catalog has [${catalog
        .map((p) => p.id)
        .join(', ')}]`,
    );
  }
  return found;
}

/** Default parameter values for a preset (from its {@link ParamSpec}s). */
function defaultParams(preset: Preset): Record<string, number> {
  const out: Record<string, number> = {};
  for (const spec of preset.params ?? []) out[spec.name] = spec.default;
  return out;
}

/** Default user rects when a preset of the given arity is first selected. */
function defaultRects(preset: Preset, ctx: PresetContext): RectData[] {
  switch (preset.arity) {
    case 0:
      return [];
    case 1:
      return [toRectData(scaledContainedRect(ctx.lockRatio, 1.8))];
    case 2:
      return [
        toRectData(maxContainedRect(ctx.lockRatio)),
        toRectData(scaledContainedRect(ctx.lockRatio, 1.3)),
      ];
  }
}

/** Resolve the output aspect ratio + whether the AR control is offered. */
function resolveAspect(config: ConfigInput): {
  outputAspect: AspectRatio;
  editable: boolean;
} {
  const { image, targetAspect } = config;
  if (targetAspect === 'match-image') {
    return { outputAspect: simplifyRatio(image.width, image.height), editable: false };
  }
  if (targetAspect && typeof targetAspect === 'object') {
    return {
      outputAspect: { num: targetAspect.num, den: targetAspect.den },
      editable: !targetAspect.locked,
    };
  }
  // Undefined: user picks. Seed from the image's dimensions.
  return { outputAspect: simplifyRatio(image.width, image.height), editable: true };
}

export interface InitOptions {
  /** Override the resolved catalog (for fully bespoke preset sets). */
  catalog?: Catalog;
  /** Pre-open an existing emitted value for further editing (round-trip). */
  initialValue?: Value;
}

/** Build the initial {@link State} from host {@link ConfigInput}. */
export function initState(config: ConfigInput, options: InitOptions = {}): State {
  const catalog = options.catalog ?? resolveCatalog(config);
  const { outputAspect, editable: aspectEditable } = resolveAspect(config);
  const imageAspect = imageAspectOf(config.image.width, config.image.height);
  const ctx: PresetContext = {
    lockRatio: lockRatioOf(outputAspect, imageAspect),
    imageAspect,
  };

  if (options.initialValue) {
    return stateFromValue(config, catalog, outputAspect, aspectEditable, options.initialValue);
  }

  const firstPreset = catalog[0]!;
  return {
    image: config.image,
    outputAspect,
    aspectEditable,
    presetId: firstPreset.id,
    presetParams: defaultParams(firstPreset),
    rects: defaultRects(firstPreset, ctx),
    durationMs: config.duration?.defaultMs ?? DFLT_DURATION_MS,
    durationEditable: config.duration?.editable ?? true,
    easing: config.easing?.default ?? DFLT_EASING,
    easingEditable: config.easing?.editable ?? true,
    reversed: false,
  };
}

/** Re-open an emitted {@link Value} as `custom` state (lossless for editing). */
function stateFromValue(
  config: ConfigInput,
  catalog: Catalog,
  outputAspect: AspectRatio,
  aspectEditable: boolean,
  value: Value,
): State {
  const ar = value.meta?.output_aspect_ratio ?? outputAspect;
  const presetId = value.meta?.preset_id ?? 'custom';
  const known = catalog.some((p) => p.id === presetId) ? presetId : 'custom';
  const start = value.keyframes[0]!.rect;
  const end = value.keyframes[value.keyframes.length - 1]!.rect;
  return {
    image: config.image,
    outputAspect: ar,
    aspectEditable,
    presetId: known,
    presetParams: value.meta?.preset_params ?? {},
    // Re-opening always lands in an editable two-rect form.
    rects: known === 'custom' ? [start, end] : [end],
    durationMs: value.duration_ms ?? config.duration?.defaultMs ?? DFLT_DURATION_MS,
    durationEditable: config.duration?.editable ?? true,
    easing: value.easing,
    easingEditable: config.easing?.editable ?? true,
    reversed: false,
  };
}

/** The pure reducer: `(state, event) → state`. Never mutates its input. */
export function reduce(state: State, event: Event, catalog: Catalog): State {
  const ctx = contextFor(state);
  switch (event.type) {
    case 'selectPreset': {
      const preset = presetById(catalog, event.presetId);
      return {
        ...state,
        presetId: preset.id,
        presetParams: defaultParams(preset),
        rects: defaultRects(preset, ctx),
        reversed: false,
      };
    }
    case 'setParam':
      return {
        ...state,
        presetParams: { ...state.presetParams, [event.name]: event.value },
      };
    case 'setRect': {
      const rects = state.rects.slice();
      if (event.index < 0 || event.index >= Math.max(rects.length, 1)) return state;
      rects[event.index] = clampToImage(event.rect);
      return { ...state, rects };
    }
    case 'nudgeRect': {
      const rects = state.rects.slice();
      const cur = rects[event.index];
      if (!cur) return state;
      rects[event.index] = toRectData(translateRect(cur, event.dx, event.dy));
      return { ...state, rects };
    }
    case 'scaleRect': {
      const rects = state.rects.slice();
      const cur = rects[event.index];
      if (!cur) return state;
      rects[event.index] = toRectData(scaleRect(cur, event.factor));
      return { ...state, rects };
    }
    case 'setDuration':
      if (!state.durationEditable) return state;
      return { ...state, durationMs: event.ms };
    case 'setEasing':
      if (!state.easingEditable) return state;
      return { ...state, easing: event.easing };
    case 'setAspect': {
      if (!state.aspectEditable) return state;
      const outputAspect = event.aspect;
      const nextCtx: PresetContext = {
        lockRatio: lockRatioOf(outputAspect, ctx.imageAspect),
        imageAspect: ctx.imageAspect,
      };
      // Re-derive default rects at the new lock ratio (old rects no longer fit).
      const preset = presetById(catalog, state.presetId);
      return { ...state, outputAspect, rects: defaultRects(preset, nextCtx) };
    }
    case 'swap':
      return { ...state, reversed: !state.reversed };
  }
}

/** Clamp a raw rect into the image (containment), preserving size. */
function clampToImage(r: RectData): RectData {
  return toRectData(toRect(r).clamped());
}

/** The {@link PresetContext} implied by a state. */
export function contextFor(state: State): PresetContext {
  const imageAspect = imageAspectOf(state.image.width, state.image.height);
  return { lockRatio: lockRatioOf(state.outputAspect, imageAspect), imageAspect };
}

/**
 * The derived `(start, end)` rects for the current state — runs the active
 * preset's `derive`, then applies the swap toggle. This is what a renderer
 * draws (both rects, one interactive, the other a ghost).
 */
export function resolveStartEnd(state: State, catalog: Catalog): StartEnd {
  const preset = presetById(catalog, state.presetId);
  const { start, end } = preset.derive(state.rects, state.presetParams, contextFor(state));
  return state.reversed ? { start: end, end: start } : { start, end };
}

/**
 * Which user rect(s) are interactive for the active preset, and their roles.
 * Arity 0 ⇒ none; arity 1 ⇒ the single drawn rect; arity 2 ⇒ start + end.
 * A convenience for renderers; pure.
 */
export function interactiveRects(
  state: State,
  catalog: Catalog,
): { index: number; rect: RectData }[] {
  const preset = presetById(catalog, state.presetId);
  return state.rects
    .slice(0, preset.arity)
    .map((rect, index) => ({ index, rect }));
}

/**
 * Map each *displayed* slot (`start` / `end`) to the user-rect index a renderer
 * should edit when the user drags that rect — or omit the slot if it is a
 * non-interactive derived ghost (arity-0 presets, or the derived endpoint of an
 * arity-1 preset). Accounts for the swap toggle.
 *
 * The displayed start/end come from {@link resolveStartEnd} (post-swap); this
 * tells the renderer which `setRect` index a manipulation of each maps back to.
 */
export function editTargets(
  state: State,
  catalog: Catalog,
): { start?: number; end?: number } {
  const preset = presetById(catalog, state.presetId);
  if (preset.arity === 0) return {};
  const pre = preset.derive(state.rects, state.presetParams, contextFor(state));
  const out: { start?: number; end?: number } = {};
  state.rects.slice(0, preset.arity).forEach((rd, i) => {
    const r = toRect(rd);
    let preSlot: 'start' | 'end';
    if (rectsClose(pre.start, r)) preSlot = 'start';
    else if (rectsClose(pre.end, r)) preSlot = 'end';
    // Fallback for non-pass-through presets: index 0 ⇒ start, else end.
    else preSlot = i === 0 ? 'start' : 'end';
    const displayed: 'start' | 'end' = state.reversed
      ? preSlot === 'start'
        ? 'end'
        : 'start'
      : preSlot;
    out[displayed] = i;
  });
  return out;
}

function rectsClose(a: Rect, b: Rect): boolean {
  return (
    Math.abs(a.x - b.x) < 1e-9 &&
    Math.abs(a.y - b.y) < 1e-9 &&
    Math.abs(a.w - b.w) < 1e-9 &&
    Math.abs(a.h - b.h) < 1e-9
  );
}

/** Build the core {@link BurnsPath} for the current state (no duration/meta). */
export function buildPath(state: State, catalog: Catalog): BurnsPath {
  const { start, end } = resolveStartEnd(state, catalog);
  return BurnsPath.fromStartEnd(start, end, {
    easing: state.easing,
    outputAspect: aspectValue(state.outputAspect),
  });
}

/**
 * The emitted wire {@link Value}: the {@link BurnsPath} dict (Python-parity
 * core fields) extended with the additive `duration_ms` + `meta`.
 */
export function toValue(state: State, catalog: Catalog): Value {
  const path = buildPath(state, catalog);
  const dict = path.toDict();
  const meta: ValueMeta = {
    preset_id: state.presetId,
    output_aspect_ratio: state.outputAspect,
  };
  if (Object.keys(state.presetParams).length > 0) {
    meta.preset_params = state.presetParams;
  }
  return {
    version: dict.version as 1,
    keyframes: dict.keyframes,
    interp: dict.interp as 'linear',
    easing: state.easing,
    output_aspect: dict.output_aspect,
    duration_ms: state.durationMs,
    meta,
  };
}
