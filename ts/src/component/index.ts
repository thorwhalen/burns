/**
 * The headless Ken Burns path-entry component — core (no DOM).
 *
 * This barrel re-exports the schema-first contract, the pure geometry, the
 * preset catalog, and the state machine. It imports **no** DOM, so it is safe
 * in any environment (Node, a worker, a non-vanilla renderer). The default
 * vanilla DOM renderer lives in the sibling `./vanilla` entry and is the only
 * piece that touches the document.
 *
 * See `misc/docs/ken_burns_path_entry_component_spec.md` for the spec this
 * implements, and `ts/README.md` (Path-entry component) for usage + the
 * "bring your own renderer" guide.
 */

// Schemas + inferred types (the contract).
export {
  EPS,
  rectSchema,
  aspectRatioSchema,
  easingSchema,
  keyframeSchema,
  valueMetaSchema,
  valueSchema,
  imageConfigSchema,
  targetAspectConfigSchema,
  durationConfigSchema,
  easingConfigSchema,
  dualViewSchema,
  configSchema,
  stateSchema,
  type RectData,
  type AspectRatio,
  type EasingId,
  type KeyframeData,
  type ValueMeta,
  type Value,
  type ImageConfig,
  type TargetAspectConfig,
  type DurationConfig,
  type EasingConfig,
  type DualView,
  type ConfigInput,
  type State,
} from './schema.js';

// Pure geometry.
export {
  imageAspectOf,
  aspectValue,
  lockRatio,
  simplifyRatio,
  toRect,
  toRectData,
  maxContainedRect,
  scaledContainedRect,
  rectFromDrag,
  translateRect,
  scaleRect,
  rectReadout,
  type RectReadout,
} from './geometry.js';

// Preset catalog.
export {
  DEFAULT_PRESETS,
  type Preset,
  type ParamSpec,
  type PresetContext,
  type StartEnd,
} from './presets.js';

// State machine + selectors.
export {
  initState,
  reduce,
  resolveCatalog,
  resolveStartEnd,
  interactiveRects,
  editTargets,
  contextFor,
  buildPath,
  toValue,
  type Event,
  type Catalog,
  type InitOptions,
} from './machine.js';
