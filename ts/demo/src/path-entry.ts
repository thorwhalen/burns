/**
 * Interactive demo of the headless path-entry component + its vanilla renderer.
 *
 * Mounts {@link mountPathEntry} over the shared reference image, mirrors the
 * live emitted `BurnsPath` value, and drives a zero-cost CSS ghost-preview from
 * `BurnsPath.evaluate(t)` — so the whole loop (author → emit → preview) is
 * visible without any rendering backend. Layout + aspect switchers re-mount the
 * component with a fresh config. Pure verification harness; not shipped.
 */

import { mountPathEntry, type PathEntryHandle } from 'kenburnz/vanilla';
import { type ConfigInput, type Value } from 'kenburnz/component';
import { BurnsPath, cssPreviewAt } from 'kenburnz';

const SOURCE_SRC = '/reference/source.png';

const componentEl = document.getElementById('component')!;
const valueEl = document.getElementById('value')!;
const previewImg = document.getElementById('preview-img') as HTMLImageElement;
const previewBox = previewImg.parentElement as HTMLElement;
const scrub = document.getElementById('scrub') as HTMLInputElement;
const tOut = document.getElementById('t')!;
const layoutSel = document.getElementById('layout') as HTMLSelectElement;
const aspectSel = document.getElementById('aspect') as HTMLSelectElement;

let handle: PathEntryHandle | null = null;
let imageDims = { width: 1920, height: 1080 };
let currentValue: Value | null = null;

function aspectConfig(): ConfigInput['targetAspect'] {
  switch (aspectSel.value) {
    case '16:9': return { num: 16, den: 9, locked: true };
    case '1:1': return { num: 1, den: 1, locked: true };
    case '9:16': return { num: 9, den: 16, locked: true };
    case 'match': return 'match-image';
    default: return undefined; // free
  }
}

function applyPreview(): void {
  if (!currentValue) return;
  const path = BurnsPath.fromDict({
    version: currentValue.version,
    keyframes: currentValue.keyframes,
    interp: currentValue.interp,
    easing: currentValue.easing,
    output_aspect: currentValue.output_aspect,
  });
  const imageAspect = imageDims.width / imageDims.height;
  const outputAspect = currentValue.output_aspect ?? imageAspect;
  previewBox.style.aspectRatio = String(outputAspect);
  const t = scrub.valueAsNumber;
  tOut.textContent = t.toFixed(3);
  const css = cssPreviewAt(path, t, { imageAspect, outputAspect });
  previewImg.style.width = css.width;
  previewImg.style.height = css.height;
  previewImg.style.transform = css.transform;
  previewImg.style.transformOrigin = css.transformOrigin;
}

function onValue(value: Value): void {
  currentValue = value;
  valueEl.textContent = JSON.stringify(value, null, 2);
  applyPreview();
}

function remount(): void {
  handle?.destroy();
  const config: ConfigInput = {
    image: { src: SOURCE_SRC, width: imageDims.width, height: imageDims.height },
    dualView: layoutSel.value as ConfigInput['dualView'],
    duration: { defaultMs: 5000, minMs: 1000, maxMs: 12000, editable: true },
    easing: { default: 'ease-in-out', editable: true },
  };
  const ta = aspectConfig();
  if (ta !== undefined) config.targetAspect = ta;
  handle = mountPathEntry(componentEl, config, {
    onChange: onValue,
    onSubmit: (value) => {
      // In a real host this would submit to a render backend.
      // eslint-disable-next-line no-console
      console.log('submit', value);
      valueEl.textContent = 'SUBMITTED\n\n' + JSON.stringify(value, null, 2);
    },
  });
  currentValue = handle.getValue();
  onValue(currentValue);
}

previewImg.src = SOURCE_SRC;
scrub.addEventListener('input', applyPreview);
layoutSel.addEventListener('change', remount);
aspectSel.addEventListener('change', remount);

const probe = new Image();
probe.onload = () => {
  imageDims = { width: probe.naturalWidth, height: probe.naturalHeight };
  remount();
};
probe.onerror = () => remount();
probe.src = SOURCE_SRC;
