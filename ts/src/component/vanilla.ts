/**
 * The default **vanilla DOM** renderer for the path-entry component.
 *
 * This is the shipping default renderer (spec §7): a framework-free adapter
 * that maps pointer/keyboard interaction to the core's {@link Event}s, draws
 * the resulting {@link State}, and reads everything it shows from the core —
 * never from hard-coded values. It is a *registered example, not a privileged
 * one*: it uses only the public core API (`./index`), so its source doubles as
 * the canonical "how to write a renderer" reference. Hosts are expected to
 * replace it for production look-and-feel; see `ts/README.md`.
 *
 * Styling is entirely CSS custom properties (injected once) — override them on
 * the mount target (or any ancestor) to theme. No framework, no build step.
 *
 * The interaction (drag-resize an aspect-ratio-locked window over an image with
 * a dim-outside matte) is the well-precedented cropper convention.
 */

import {
  initState,
  reduce,
  resolveCatalog,
  resolveStartEnd,
  editTargets,
  contextFor,
  toValue,
  rectReadout,
  rectFromDrag,
  translateRect,
  toRectData,
  simplifyRatio,
  type Catalog,
  type ConfigInput,
  type State,
  type Value,
  type RectData,
  type Preset,
} from './index.js';

/** Options for {@link mountPathEntry}. */
export interface MountOptions {
  /** A bespoke preset catalog; defaults to the config-resolved default set. */
  catalog?: Catalog;
  /** Pre-open an existing emitted value for further editing. */
  initialValue?: Value;
  /** Fires on every state change (live preview). */
  onChange?: (value: Value, state: State) => void;
  /** Fires when the user clicks Submit / Done. */
  onSubmit?: (value: Value, state: State) => void;
}

/** Handle returned by {@link mountPathEntry}. */
export interface PathEntryHandle {
  /** The current emitted wire value. */
  getValue(): Value;
  /** The current internal state (read-only snapshot). */
  getState(): State;
  /** Tear down listeners and remove the DOM. */
  destroy(): void;
}

const STYLE_ID = 'kb-path-entry-styles';

/**
 * Mount the path-entry component into `target`. Returns a {@link PathEntryHandle}.
 *
 * ```ts
 * const handle = mountPathEntry(el, {
 *   image: { src, width: 1920, height: 1080 },
 *   targetAspect: { num: 16, den: 9, locked: true },
 * }, { onSubmit: (value) => submit(value) });
 * ```
 */
export function mountPathEntry(
  target: HTMLElement,
  config: ConfigInput,
  options: MountOptions = {},
): PathEntryHandle {
  ensureStyles(target.ownerDocument ?? document);
  const catalog = options.catalog ?? resolveCatalog(config);
  let state = initState(config, {
    catalog,
    ...(options.initialValue ? { initialValue: options.initialValue } : {}),
  });

  const dualView = config.dualView ?? 'side-by-side';
  const imageAspect = config.image.width / config.image.height;

  const cleanups: Array<() => void> = [];
  const root = el('div', 'kb-pe');
  target.appendChild(root);

  // --- structure (built once) -------------------------------------------
  const presetRow = el('div', 'kb-pe-presets');
  const paramsBox = el('div', 'kb-pe-params');
  const stageArea = el('div', 'kb-pe-stage-area');
  const controls = el('div', 'kb-pe-controls');
  const footer = el('div', 'kb-pe-footer');
  root.append(presetRow, paramsBox, stageArea, controls, footer);

  // Preset selector row (static set of buttons; active toggled in applyState).
  const presetButtons = new Map<string, HTMLButtonElement>();
  for (const preset of catalog) {
    const btn = el('button', 'kb-pe-preset') as HTMLButtonElement;
    btn.type = 'button';
    btn.dataset['icon'] = preset.icon;
    btn.title = preset.description;
    btn.innerHTML = `<span class="kb-pe-preset-icon" aria-hidden="true">${iconGlyph(preset.icon)}</span><span class="kb-pe-preset-label">${esc(preset.label)}</span>`;
    on(btn, 'click', () => dispatch({ type: 'selectPreset', presetId: preset.id }), cleanups);
    presetRow.appendChild(btn);
    presetButtons.set(preset.id, btn);
  }

  // Controls: duration, easing, swap.
  const durationWrap = el('label', 'kb-pe-field');
  durationWrap.innerHTML = `<span class="kb-pe-field-label">Duration</span>`;
  const durationInput = el('input', 'kb-pe-duration') as HTMLInputElement;
  durationInput.type = 'range';
  durationInput.min = String(config.duration?.minMs ?? 1000);
  durationInput.max = String(config.duration?.maxMs ?? 12000);
  durationInput.step = '250';
  const durationOut = el('span', 'kb-pe-duration-out');
  durationWrap.append(durationInput, durationOut);
  on(durationInput, 'input', () =>
    dispatch({ type: 'setDuration', ms: durationInput.valueAsNumber }), cleanups);

  const easingWrap = el('label', 'kb-pe-field');
  easingWrap.innerHTML = `<span class="kb-pe-field-label">Motion speed</span>`;
  const easingSelect = el('select', 'kb-pe-easing') as HTMLSelectElement;
  for (const opt of config.easing?.options ?? EASING_OPTIONS) {
    const o = document.createElement('option');
    o.value = String(opt);
    o.textContent = String(opt);
    easingSelect.appendChild(o);
  }
  easingWrap.appendChild(easingSelect);
  on(easingSelect, 'change', () =>
    dispatch({ type: 'setEasing', easing: easingSelect.value }), cleanups);

  const swapBtn = el('button', 'kb-pe-swap') as HTMLButtonElement;
  swapBtn.type = 'button';
  swapBtn.textContent = 'Swap Start / End';
  swapBtn.title = 'Swap the Start and End windows';
  on(swapBtn, 'click', () => dispatch({ type: 'swap' }), cleanups);

  controls.append(durationWrap, easingWrap, swapBtn);

  // Aspect-ratio control (only when editable).
  const arWrap = el('div', 'kb-pe-aspect');
  controls.appendChild(arWrap);

  // Footer: readout + submit.
  const readout = el('div', 'kb-pe-readout');
  const submitBtn = el('button', 'kb-pe-submit') as HTMLButtonElement;
  submitBtn.type = 'button';
  submitBtn.textContent = 'Use this path';
  on(submitBtn, 'click', () =>
    options.onSubmit?.(toValue(state, catalog), state), cleanups);
  footer.append(readout, submitBtn);

  // --- dynamic stage panes (rebuilt when preset/layout changes) ---------
  let stages: StageHandle[] = [];
  let builtPresetId: string | null = null;

  function rebuildStages(): void {
    for (const s of stages) s.destroy();
    stages = [];
    stageArea.innerHTML = '';
    stageArea.dataset['layout'] = dualView;

    if (dualView === 'overlay') {
      const stage = makeStage(['start', 'end']);
      stageArea.appendChild(stage.root);
      stages.push(stage);
    } else if (dualView === 'tabbed') {
      const tabs = el('div', 'kb-pe-tabs');
      const startTab = tabButton('Start', 'start');
      const endTab = tabButton('End', 'end');
      tabs.append(startTab.btn, endTab.btn);
      stageArea.appendChild(tabs);
      const stage = makeStage([activeTab]);
      stageArea.appendChild(stage.root);
      stages.push(stage);
    } else {
      // side-by-side (default): Start pane | End pane
      const startStage = makeStage(['start']);
      const endStage = makeStage(['end']);
      startStage.root.classList.add('kb-pe-stage--start');
      endStage.root.classList.add('kb-pe-stage--end');
      stageArea.append(startStage.root, endStage.root);
      stages.push(startStage, endStage);
    }
    builtPresetId = state.presetId;
  }

  // Tabbed-layout active slot.
  let activeTab: 'start' | 'end' = 'start';
  function tabButton(label: string, slot: 'start' | 'end') {
    const btn = el('button', 'kb-pe-tab') as HTMLButtonElement;
    btn.type = 'button';
    btn.textContent = label;
    on(btn, 'click', () => {
      activeTab = slot;
      builtPresetId = null; // force stage rebuild
      applyState();
    }, cleanups);
    return { btn };
  }

  /**
   * Build a stage: an image with one or two overlaid crop rects. `slots` lists
   * which derived endpoints this stage shows.
   */
  function makeStage(slots: Array<'start' | 'end'>): StageHandle {
    const root = el('div', 'kb-pe-stage');
    const frame = el('div', 'kb-pe-frame');
    frame.style.aspectRatio = String(imageAspect);
    const img = el('img', 'kb-pe-image') as HTMLImageElement;
    img.src = config.image.src;
    img.alt = '';
    img.draggable = false;
    frame.appendChild(img);

    const caption = el('div', 'kb-pe-caption');
    root.append(caption, frame);

    const rectEls = new Map<'start' | 'end', RectEl>();
    for (const slot of slots) {
      const rectEl = makeRectEl(slot, frame, img);
      rectEls.set(slot, rectEl);
    }

    return {
      root,
      update(start, end, targets) {
        const labelParts = slots.map((s) => (s === 'start' ? 'Start' : 'End'));
        caption.textContent = labelParts.join(' / ');
        for (const slot of slots) {
          const rectEl = rectEls.get(slot)!;
          const rd = slot === 'start' ? start : end;
          const editIndex = targets[slot];
          rectEl.apply(rd, editIndex);
        }
      },
      destroy() {
        for (const r of rectEls.values()) r.destroy();
      },
    };
  }

  /** One overlaid crop rect with a matte, handles, thirds grid, interaction. */
  function makeRectEl(
    slot: 'start' | 'end',
    frame: HTMLElement,
    img: HTMLImageElement,
  ): RectEl {
    const box = el('div', `kb-pe-rect kb-pe-rect--${slot}`);
    box.tabIndex = 0;
    box.innerHTML =
      `<div class="kb-pe-thirds" aria-hidden="true"></div>` +
      ['nw', 'ne', 'sw', 'se']
        .map((c) => `<div class="kb-pe-handle kb-pe-handle--${c}" data-corner="${c}"></div>`)
        .join('');
    frame.appendChild(box);

    let editIndex: number | undefined;
    let current: RectData = { x: 0, y: 0, w: 1, h: 1 };

    const norm = (ev: PointerEvent): { x: number; y: number } => {
      const r = img.getBoundingClientRect();
      return {
        x: clamp01((ev.clientX - r.left) / r.width),
        y: clamp01((ev.clientY - r.top) / r.height),
      };
    };

    let drag: null | { mode: 'pan' | 'create' | 'resize'; anchor: { x: number; y: number }; grabDx: number; grabDy: number } = null;

    const onDown = (ev: PointerEvent): void => {
      if (editIndex === undefined) return; // ghost: not interactive
      const target = ev.target as HTMLElement;
      const corner = target.dataset['corner'];
      const p = norm(ev);
      box.setPointerCapture(ev.pointerId);
      ev.preventDefault();
      if (corner) {
        // Resize: anchor = the opposite corner.
        const ax = corner.includes('w') ? current.x + current.w : current.x;
        const ay = corner.includes('n') ? current.y + current.h : current.y;
        drag = { mode: 'resize', anchor: { x: ax, y: ay }, grabDx: 0, grabDy: 0 };
      } else if (insideRect(p, current)) {
        drag = { mode: 'pan', anchor: p, grabDx: p.x - current.x, grabDy: p.y - current.y };
      } else {
        drag = { mode: 'create', anchor: p, grabDx: 0, grabDy: 0 };
      }
    };

    const onMove = (ev: PointerEvent): void => {
      const idx = editIndex;
      if (!drag || idx === undefined) return;
      const p = norm(ev);
      const ratio = contextFor(state).lockRatio;
      let next: RectData;
      if (drag.mode === 'pan') {
        next = toRectData(translateRect(current, p.x - drag.grabDx - current.x, p.y - drag.grabDy - current.y));
      } else {
        next = toRectData(rectFromDrag(drag.anchor, p, ratio));
      }
      dispatch({ type: 'setRect', index: idx, rect: next });
    };

    const onUp = (ev: PointerEvent): void => {
      if (box.hasPointerCapture(ev.pointerId)) box.releasePointerCapture(ev.pointerId);
      drag = null;
    };

    const onKey = (ev: KeyboardEvent): void => {
      const idx = editIndex;
      if (idx === undefined) return;
      const stepX = (ev.shiftKey ? 10 : 1) / config.image.width;
      const stepY = (ev.shiftKey ? 10 : 1) / config.image.height;
      let dx = 0;
      let dy = 0;
      if (ev.key === 'ArrowLeft') dx = -stepX;
      else if (ev.key === 'ArrowRight') dx = stepX;
      else if (ev.key === 'ArrowUp') dy = -stepY;
      else if (ev.key === 'ArrowDown') dy = stepY;
      else return;
      ev.preventDefault();
      dispatch({ type: 'nudgeRect', index: idx, dx, dy });
    };

    on(box, 'pointerdown', onDown as EventListener, cleanups);
    on(box, 'pointermove', onMove as EventListener, cleanups);
    on(box, 'pointerup', onUp as EventListener, cleanups);
    on(box, 'pointercancel', onUp as EventListener, cleanups);
    on(box, 'keydown', onKey as EventListener, cleanups);

    return {
      apply(rd, idx) {
        current = rd;
        editIndex = idx;
        box.classList.toggle('kb-pe-rect--ghost', idx === undefined);
        box.style.left = `${rd.x * 100}%`;
        box.style.top = `${rd.y * 100}%`;
        box.style.width = `${rd.w * 100}%`;
        box.style.height = `${rd.h * 100}%`;
      },
      destroy() {
        box.remove();
      },
    };
  }

  // --- the render loop ---------------------------------------------------
  function applyState(): void {
    // Preset row active state.
    for (const [id, btn] of presetButtons) {
      btn.classList.toggle('kb-pe-preset--active', id === state.presetId);
    }

    // Param controls (rebuild when preset changes).
    if (builtPresetId !== state.presetId) {
      buildParams();
    }

    // Stages (rebuild when preset/layout changes).
    if (builtPresetId !== state.presetId) {
      rebuildStages();
    }

    const { start, end } = resolveStartEnd(state, catalog);
    const targets = editTargets(state, catalog);
    const startData = toRectData(start);
    const endData = toRectData(end);
    for (const s of stages) s.update(startData, endData, targets);

    // Controls.
    durationInput.value = String(state.durationMs);
    durationInput.disabled = !state.durationEditable;
    durationOut.textContent = `${(state.durationMs / 1000).toFixed(2)} s`;
    durationWrap.style.display = state.durationEditable ? '' : 'none';
    easingSelect.value = String(state.easing);
    ensureEasingOption(easingSelect, String(state.easing));
    easingWrap.style.display = state.easingEditable ? '' : 'none';

    // Aspect control.
    buildAspect();

    // Readout (the interactive rect, or the End rect).
    const which = targets.end ?? targets.start;
    const r = which === undefined ? endData : (which === targets.start ? startData : endData);
    const ro = rectReadout(r);
    readout.textContent =
      `x ${ro.xPercent.toFixed(0)}%  ·  y ${ro.yPercent.toFixed(0)}%  ·  zoom ${ro.zoom.toFixed(2)}×` +
      `  ·  ${simplifyRatio(state.outputAspect.num, state.outputAspect.den).num}:${simplifyRatio(state.outputAspect.num, state.outputAspect.den).den}`;
  }

  function buildParams(): void {
    paramsBox.innerHTML = '';
    const preset = catalog.find((p) => p.id === state.presetId) as Preset | undefined;
    if (!preset?.params?.length) {
      paramsBox.style.display = 'none';
      return;
    }
    paramsBox.style.display = '';
    for (const spec of preset.params) {
      const wrap = el('label', 'kb-pe-field');
      wrap.innerHTML = `<span class="kb-pe-field-label">${esc(spec.label)}</span>`;
      const input = el('input', 'kb-pe-param') as HTMLInputElement;
      input.type = 'range';
      input.min = String(spec.min ?? 0);
      input.max = String(spec.max ?? 1);
      input.step = String(spec.step ?? 0.01);
      input.value = String(state.presetParams[spec.name] ?? spec.default);
      const out = el('span', 'kb-pe-param-out');
      out.textContent = input.value;
      on(input, 'input', () => {
        out.textContent = input.value;
        dispatch({ type: 'setParam', name: spec.name, value: input.valueAsNumber });
      }, cleanups);
      wrap.append(input, out);
      paramsBox.appendChild(wrap);
    }
  }

  let arInputs: { num: HTMLInputElement; den: HTMLInputElement } | null = null;
  function buildAspect(): void {
    if (!state.aspectEditable) {
      arWrap.style.display = 'none';
      return;
    }
    arWrap.style.display = '';
    if (arInputs) {
      arInputs.num.value = String(state.outputAspect.num);
      arInputs.den.value = String(state.outputAspect.den);
      return;
    }
    arWrap.innerHTML = `<span class="kb-pe-field-label">Aspect</span>`;
    const num = el('input', 'kb-pe-ar-num') as HTMLInputElement;
    const den = el('input', 'kb-pe-ar-den') as HTMLInputElement;
    num.type = den.type = 'number';
    num.min = den.min = '1';
    num.value = String(state.outputAspect.num);
    den.value = String(state.outputAspect.den);
    const sep = el('span', 'kb-pe-ar-sep');
    sep.textContent = ':';
    const useImg = el('button', 'kb-pe-ar-useimg') as HTMLButtonElement;
    useImg.type = 'button';
    useImg.textContent = 'Use image';
    const commit = (): void => {
      const n = Number(num.value);
      const d = Number(den.value);
      if (n > 0 && d > 0) dispatch({ type: 'setAspect', aspect: { num: n, den: d } });
    };
    on(num, 'change', commit, cleanups);
    on(den, 'change', commit, cleanups);
    on(useImg, 'click', () => {
      const ar = simplifyRatio(config.image.width, config.image.height);
      num.value = String(ar.num);
      den.value = String(ar.den);
      commit();
    }, cleanups);
    arWrap.append(num, sep, den, useImg);
    arInputs = { num, den };
  }

  function dispatch(event: Parameters<typeof reduce>[1]): void {
    state = reduce(state, event, catalog);
    applyState();
    options.onChange?.(toValue(state, catalog), state);
  }

  // Initial paint.
  applyState();

  return {
    getValue: () => toValue(state, catalog),
    getState: () => state,
    destroy: () => {
      for (const fn of cleanups) fn();
      for (const s of stages) s.destroy();
      root.remove();
    },
  };
}

// --- small DOM + helpers ---------------------------------------------------

interface StageHandle {
  root: HTMLElement;
  update(start: RectData, end: RectData, targets: { start?: number; end?: number }): void;
  destroy(): void;
}

interface RectEl {
  apply(rect: RectData, editIndex: number | undefined): void;
  destroy(): void;
}

const EASING_OPTIONS = ['linear', 'ease-in', 'ease-out', 'ease-in-out', 'ease'];

function ensureEasingOption(select: HTMLSelectElement, value: string): void {
  if (![...select.options].some((o) => o.value === value)) {
    const o = document.createElement('option');
    o.value = value;
    o.textContent = value;
    select.appendChild(o);
    select.value = value;
  }
}

function insideRect(p: { x: number; y: number }, r: RectData): boolean {
  return p.x >= r.x && p.x <= r.x + r.w && p.y >= r.y && p.y <= r.y + r.h;
}

function clamp01(v: number): number {
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

function el(tag: string, className: string): HTMLElement {
  const e = document.createElement(tag);
  e.className = className;
  return e;
}

function on(
  node: EventTarget,
  type: string,
  handler: EventListener,
  cleanups: Array<() => void>,
): void {
  node.addEventListener(type, handler);
  cleanups.push(() => node.removeEventListener(type, handler));
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) =>
    c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&quot;');
}

/** A tiny unicode glyph fallback for a `lucide`-style icon name. */
function iconGlyph(icon: string): string {
  const map: Record<string, string> = {
    'zoom-in': '⊕',
    'zoom-out': '⊖',
    'arrow-right': '→',
    'arrow-left': '←',
    'arrow-up': '↑',
    'arrow-down': '↓',
    move: '✥',
    'crosshair-zoom-in': '⊕',
    'crosshair-zoom-out': '⊖',
    'arrow-right-circle': '⊳',
    'arrow-left-circle': '⊲',
    'arrow-up-circle': '⊼',
    'arrow-down-circle': '⊻',
    expand: '⤢',
    pencil: '✎',
  };
  return map[icon] ?? '◻';
}

/** Inject the renderer's CSS once per document. Theme via custom properties. */
function ensureStyles(doc: Document): void {
  if (doc.getElementById(STYLE_ID)) return;
  const style = doc.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CSS;
  doc.head.appendChild(style);
}

const CSS = `
.kb-pe {
  --kb-bg: #14151a;
  --kb-fg: #e7e9ee;
  --kb-muted: #9aa0ad;
  --kb-accent: #6ea8fe;
  --kb-start: #46d39a;
  --kb-end: #ff6b6b;
  --kb-matte: rgba(0,0,0,0.62);
  --kb-handle: #ffffff;
  --kb-radius: 8px;
  --kb-gap: 12px;
  font: 13px/1.4 system-ui, sans-serif;
  color: var(--kb-fg);
  background: var(--kb-bg);
  padding: var(--kb-gap);
  border-radius: var(--kb-radius);
  display: flex;
  flex-direction: column;
  gap: var(--kb-gap);
}
.kb-pe-presets { display: flex; flex-wrap: wrap; gap: 6px; }
.kb-pe-preset {
  display: inline-flex; align-items: center; gap: 5px;
  background: #20222b; color: var(--kb-fg); border: 1px solid #2c2f3a;
  border-radius: 6px; padding: 5px 9px; cursor: pointer; font-size: 12px;
}
.kb-pe-preset:hover { border-color: var(--kb-accent); }
.kb-pe-preset--active { background: var(--kb-accent); color: #0b0c10; border-color: var(--kb-accent); }
.kb-pe-preset-icon { font-size: 14px; }
.kb-pe-stage-area { display: flex; gap: var(--kb-gap); flex-wrap: wrap; }
.kb-pe-stage-area[data-layout="side-by-side"] .kb-pe-stage { flex: 1 1 320px; }
.kb-pe-stage { display: flex; flex-direction: column; gap: 6px; min-width: 240px; }
.kb-pe-caption { color: var(--kb-muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.kb-pe-frame { position: relative; overflow: hidden; background: #000; border-radius: 6px; user-select: none; }
.kb-pe-image { display: block; width: 100%; height: 100%; object-fit: contain; pointer-events: none; }
.kb-pe-rect {
  position: absolute; box-sizing: border-box;
  border: 2px solid var(--kb-accent);
  box-shadow: 0 0 0 9999px var(--kb-matte);
  cursor: move; touch-action: none;
}
.kb-pe-rect--start { border-color: var(--kb-start); }
.kb-pe-rect--end { border-color: var(--kb-end); }
.kb-pe-rect--ghost { box-shadow: none; cursor: default; border-style: dashed; opacity: 0.7; }
.kb-pe-rect:focus { outline: 2px solid var(--kb-accent); outline-offset: 1px; }
.kb-pe-thirds {
  position: absolute; inset: 0; pointer-events: none;
  background:
    linear-gradient(to right, transparent 33.33%, rgba(255,255,255,0.25) 33.33%, rgba(255,255,255,0.25) calc(33.33% + 1px), transparent calc(33.33% + 1px)),
    linear-gradient(to right, transparent 66.66%, rgba(255,255,255,0.25) 66.66%, rgba(255,255,255,0.25) calc(66.66% + 1px), transparent calc(66.66% + 1px)),
    linear-gradient(to bottom, transparent 33.33%, rgba(255,255,255,0.25) 33.33%, rgba(255,255,255,0.25) calc(33.33% + 1px), transparent calc(33.33% + 1px)),
    linear-gradient(to bottom, transparent 66.66%, rgba(255,255,255,0.25) 66.66%, rgba(255,255,255,0.25) calc(66.66% + 1px), transparent calc(66.66% + 1px));
}
.kb-pe-rect--ghost .kb-pe-thirds, .kb-pe-rect--ghost .kb-pe-handle { display: none; }
.kb-pe-handle {
  position: absolute; width: 12px; height: 12px; background: var(--kb-handle);
  border: 1px solid #00000055; border-radius: 2px;
}
.kb-pe-handle--nw { left: -6px; top: -6px; cursor: nwse-resize; }
.kb-pe-handle--ne { right: -6px; top: -6px; cursor: nesw-resize; }
.kb-pe-handle--sw { left: -6px; bottom: -6px; cursor: nesw-resize; }
.kb-pe-handle--se { right: -6px; bottom: -6px; cursor: nwse-resize; }
.kb-pe-tabs { display: flex; gap: 4px; }
.kb-pe-tab { background: #20222b; color: var(--kb-fg); border: 1px solid #2c2f3a; border-radius: 6px; padding: 4px 12px; cursor: pointer; }
.kb-pe-params, .kb-pe-controls, .kb-pe-aspect { display: flex; flex-wrap: wrap; gap: var(--kb-gap); align-items: center; }
.kb-pe-field { display: inline-flex; align-items: center; gap: 6px; }
.kb-pe-field-label { color: var(--kb-muted); font-size: 11px; }
.kb-pe-aspect { gap: 4px; }
.kb-pe-ar-num, .kb-pe-ar-den { width: 56px; background: #20222b; color: var(--kb-fg); border: 1px solid #2c2f3a; border-radius: 4px; padding: 3px 6px; }
.kb-pe-ar-useimg, .kb-pe-swap { background: #20222b; color: var(--kb-fg); border: 1px solid #2c2f3a; border-radius: 6px; padding: 5px 10px; cursor: pointer; }
.kb-pe-footer { display: flex; justify-content: space-between; align-items: center; gap: var(--kb-gap); }
.kb-pe-readout { color: var(--kb-muted); font-variant-numeric: tabular-nums; }
.kb-pe-submit { background: var(--kb-accent); color: #0b0c10; border: 0; border-radius: 6px; padding: 8px 16px; font-weight: 600; cursor: pointer; }
`;
