/**
 * kenburnz browser-verification demo.
 *
 * Loads the Python-generated reference manifest (`/reference/manifest.json`,
 * produced by `misc/gen_preview_reference.py`) and, for every scenario, renders
 * the live CSS preview beside the matching Python reference frame so the
 * framing can be eyeballed, plus a WebCodecs→WebM export button so the encode +
 * mux path can be played and compared. Pure verification harness — not shipped.
 */

import {
  BurnsPath,
  cssPreviewAt,
  exportWebmBlob,
  isWebCodecsSupported,
  type BurnsPathDict,
} from 'kenburnz';

interface FrameRef {
  t: number;
  file: string;
  box: [number, number, number, number];
}

interface Scenario {
  id: string;
  outW: number;
  outH: number;
  outputAspect: number | null;
  imageAspect: number;
  path: BurnsPathDict;
  frames: FrameRef[];
}

interface Manifest {
  image: string;
  imgW: number;
  imgH: number;
  tSamples: number[];
  scenarios: Scenario[];
}

const REF_BASE = '/reference';
const SOURCE_SRC = `${REF_BASE}/source.png`;

function setStatus(msg: string, isError = false): void {
  const el = document.getElementById('status')!;
  el.textContent = msg;
  el.classList.toggle('error', isError);
}

/** The reference frame whose sampled `t` is closest to the scrubbed `t`. */
function nearestFrame(frames: FrameRef[], t: number): FrameRef {
  return frames.reduce((best, f) =>
    Math.abs(f.t - t) < Math.abs(best.t - t) ? f : best,
  );
}

function buildScenarioPanel(
  scene: Scenario,
  manifest: Manifest,
  sourceBitmap: ImageBitmap,
): HTMLElement {
  const path = BurnsPath.fromDict(scene.path);
  const outputAspect = scene.outputAspect ?? scene.imageAspect;

  const panel = document.createElement('section');
  panel.className = 'panel';
  panel.innerHTML = `
    <h2>${scene.id}</h2>
    <p class="meta">
      image ${manifest.imgW}×${manifest.imgH} (AR ${scene.imageAspect.toFixed(3)})
      → output ${scene.outW}×${scene.outH} (AR ${outputAspect.toFixed(3)})
      ${scene.outputAspect === null ? '· no cover-crop' : '· cover-cropped'}
    </p>
    <div class="compare">
      <figure>
        <figcaption>CSS preview (live)</figcaption>
        <div class="kb-viewport"><img class="kb-img" alt="css preview" /></div>
      </figure>
      <figure>
        <figcaption>Python reference (<span class="ref-t"></span>)</figcaption>
        <div class="kb-viewport"><img class="ref-img" alt="python reference" /></div>
      </figure>
    </div>
    <label class="scrub">
      t = <span class="t-val">0.000</span>
      <input type="range" min="0" max="1" step="0.001" value="0" />
    </label>
    <div class="export">
      <button class="export-btn">Export WebM (WebCodecs)</button>
      <span class="export-status"></span>
      <video class="export-video" controls loop></video>
      <a class="export-dl" download>download .webm</a>
    </div>
  `;

  const viewports = panel.querySelectorAll<HTMLElement>('.kb-viewport');
  viewports.forEach((vp) => {
    vp.style.aspectRatio = String(outputAspect);
  });

  const cssImg = panel.querySelector<HTMLImageElement>('.kb-img')!;
  cssImg.src = SOURCE_SRC;
  const refImg = panel.querySelector<HTMLImageElement>('.ref-img')!;
  const refT = panel.querySelector<HTMLElement>('.ref-t')!;
  const tVal = panel.querySelector<HTMLElement>('.t-val')!;
  const slider = panel.querySelector<HTMLInputElement>('input[type=range]')!;

  function applyT(t: number): void {
    tVal.textContent = t.toFixed(3);
    const css = cssPreviewAt(path, t, {
      imageAspect: scene.imageAspect,
      outputAspect,
    });
    cssImg.style.width = css.width;
    cssImg.style.height = css.height;
    cssImg.style.transform = css.transform;
    cssImg.style.transformOrigin = css.transformOrigin;

    const frame = nearestFrame(scene.frames, t);
    refImg.src = `${REF_BASE}/${frame.file}`;
    refT.textContent = `t=${frame.t.toFixed(2)}`;
  }

  slider.addEventListener('input', () => applyT(slider.valueAsNumber));
  applyT(0);

  // --- WebCodecs export ---------------------------------------------------
  const exportBtn = panel.querySelector<HTMLButtonElement>('.export-btn')!;
  const exportStatus = panel.querySelector<HTMLElement>('.export-status')!;
  const video = panel.querySelector<HTMLVideoElement>('.export-video')!;
  const dl = panel.querySelector<HTMLAnchorElement>('.export-dl')!;

  if (!isWebCodecsSupported()) {
    exportBtn.disabled = true;
    exportStatus.textContent = 'WebCodecs unavailable in this browser.';
  } else {
    exportBtn.addEventListener('click', async () => {
      exportBtn.disabled = true;
      exportStatus.textContent = 'encoding…';
      try {
        const t0 = performance.now();
        const { blob, frameCount, width, height, codec } = await exportWebmBlob(
          sourceBitmap,
          path,
          { duration: 3, fps: 30, outputAspect: scene.outputAspect },
        );
        const url = URL.createObjectURL(blob);
        video.src = url;
        dl.href = url;
        dl.download = `${scene.id}.webm`;
        const ms = Math.round(performance.now() - t0);
        exportStatus.textContent = `${frameCount} frames · ${width}×${height} · ${codec} · ${(
          blob.size / 1024
        ).toFixed(0)} KB · ${ms} ms`;
      } catch (err) {
        exportStatus.textContent = `export failed: ${String(err)}`;
        exportStatus.classList.add('error');
      } finally {
        exportBtn.disabled = false;
      }
    });
  }

  return panel;
}

async function main(): Promise<void> {
  setStatus('loading reference manifest…');
  let manifest: Manifest;
  try {
    const res = await fetch(`${REF_BASE}/manifest.json`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    manifest = (await res.json()) as Manifest;
  } catch (err) {
    setStatus(
      `Could not load ${REF_BASE}/manifest.json (${String(err)}). ` +
        'Run `pnpm reference` (or `python3 ../../misc/gen_preview_reference.py`) first.',
      true,
    );
    return;
  }

  const sourceBitmap = await createImageBitmap(
    await (await fetch(SOURCE_SRC)).blob(),
  );

  const app = document.getElementById('app')!;
  for (const scene of manifest.scenarios) {
    app.appendChild(buildScenarioPanel(scene, manifest, sourceBitmap));
  }
  setStatus(
    isWebCodecsSupported()
      ? `${manifest.scenarios.length} scenarios loaded. WebCodecs available.`
      : `${manifest.scenarios.length} scenarios loaded. WebCodecs NOT available — export disabled.`,
  );
}

void main();
