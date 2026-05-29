"""Generate browser-verification reference renders for the ``kenburnz`` TS port.

The TS package ships two browser-only surfaces the Node test suite cannot
exercise — the CSS preview (``ts/src/css-preview.ts``) and the WebCodecs
exporter (``ts/src/render-webcodecs.ts``). To verify them you need an eye in a
real browser *and* a ground truth to compare against. This script produces that
ground truth from the **same** Python spec math the golden vectors pin:

For each scenario (a labelled ``BurnsPath`` + image/output sizes) it renders
the Python frame at a handful of clock times via :func:`burns._frame.sample_frame`
and writes them as PNGs, alongside a ``manifest.json`` that carries, per frame,
the exact integer :func:`burns._frame.sample_box` crop and — crucially — the
path's :meth:`BurnsPath.to_dict` wire form so the TS side can rebuild the
**identical** path with ``BurnsPath.fromDict``.

The demo page (``ts/demo/``) shows each scenario's CSS preview next to the
matching Python PNG; the headed Playwright test (``ts/test-e2e/``) pixel-diffs
the WebCodecs output against these PNGs. Both read the manifest, so the contract
lives in one place.

Run from the repo root::

    python -m misc.gen_preview_reference
    #  or:  python misc/gen_preview_reference.py
    #  custom out dir:  python misc/gen_preview_reference.py --out-dir /tmp/ref

Output (default ``ts/demo/public/reference/``, gitignored — regenerated, never
committed, mirroring reelee-web's "e2e needs the Python package importable"
model):

    reference/
      manifest.json
      source.png                 # the synthetic source image
      <scenario>/t0.0000.png ...  # one PNG per sampled clock time
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image as PIL_Image
from PIL import ImageDraw

from burns import BurnsPath, Rect, ken_burns_path
from burns._frame import output_size_for, sample_box, sample_frame

# Clock times sampled per scenario — endpoints plus interior quarters, matching
# the golden-vector cadence so a framing divergence shows at the same t's.
T_SAMPLES = (0.0, 0.25, 0.5, 0.75, 1.0)

# A 4:3 source at a resolution big enough to see resampling, even-snapped.
IMG_W, IMG_H = 800, 600


def _synthetic_source(w: int, h: int) -> PIL_Image.Image:
    """A deterministic, framing-legible test image.

    A coordinate grid + labelled quadrants + a center crosshair + distinct
    corner blocks, so a mis-framed pan / zoom / cover-crop is *obvious* at a
    glance (the wrong quadrant colour or a clipped grid line jumps out).
    """
    img = PIL_Image.new("RGB", (w, h), (24, 24, 28))
    draw = ImageDraw.Draw(img)

    # Quadrant tints (TL, TR, BL, BR) — asymmetric so orientation is unambiguous.
    quad = {
        (0, 0): (60, 30, 30),
        (1, 0): (30, 60, 30),
        (0, 1): (30, 30, 70),
        (1, 1): (60, 55, 25),
    }
    for (qx, qy), color in quad.items():
        x0 = qx * w // 2
        y0 = qy * h // 2
        draw.rectangle([x0, y0, x0 + w // 2, y0 + h // 2], fill=color)

    # Grid every 10% so scale changes are readable.
    grid = (90, 90, 100)
    for i in range(1, 10):
        gx = round(i * w / 10)
        gy = round(i * h / 10)
        draw.line([(gx, 0), (gx, h)], fill=grid, width=1)
        draw.line([(0, gy), (w, gy)], fill=grid, width=1)

    # Distinct corner blocks (pure primaries) — clipped if framing overshoots.
    block = max(8, w // 25)
    corners = {
        (0, 0): (255, 80, 80),
        (1, 0): (80, 255, 80),
        (0, 1): (80, 160, 255),
        (1, 1): (255, 220, 60),
    }
    for (cx, cy), color in corners.items():
        x0 = cx * (w - block)
        y0 = cy * (h - block)
        draw.rectangle([x0, y0, x0 + block, y0 + block], fill=color)

    # Center crosshair + dot — the push-in target.
    cx, cy = w // 2, h // 2
    draw.line([(cx, cy - 30), (cx, cy + 30)], fill=(255, 255, 255), width=2)
    draw.line([(cx - 30, cy), (cx + 30, cy)], fill=(255, 255, 255), width=2)
    draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(255, 255, 255))
    return img


def _scenarios() -> dict[str, dict]:
    """The labelled catalog: each maps to a ``BurnsPath`` + an output-size rule.

    Chosen to bracket the cover-crop behaviour, which is where the float CSS
    preview and the integer ``sample_box`` are most likely to *look* wrong:

    - ``push_in``      — output AR == image AR, no cover-crop (the baseline).
    - ``push_in_square`` — square output over a 4:3 image: trims left/right.
    - ``pan_widescreen`` — 16:9 output over a 4:3 image: trims top/bottom.
    """
    return {
        # Center push-in to 1.3x, no reframing (output AR follows the image).
        "push_in": {
            "path": BurnsPath.push_in(1.3, easing="ease-in-out"),
            "output_aspect": None,
        },
        # Off-center push-in into a SQUARE output — the wide source is
        # cover-cropped left/right at every frame.
        "push_in_square": {
            "path": ken_burns_path(1, zoom=1.6, pan=0.25, output_aspect=1.0),
            "output_aspect": 1.0,
        },
        # Pan across the image with a 16:9 output — the 4:3 source is
        # cover-cropped top/bottom.
        "pan_widescreen": {
            "path": BurnsPath(
                keyframes=(
                    (0.0, Rect(0.0, 0.05, 0.7, 0.7)),
                    (1.0, Rect(0.3, 0.05, 0.7, 0.7)),
                ),
                easing="ease-in-out",
                output_aspect=16 / 9,
            ),
            "output_aspect": 16 / 9,
        },
    }


def generate(out_dir: Path) -> Path:
    """Render every scenario's reference frames + manifest into ``out_dir``."""
    out_dir.mkdir(parents=True, exist_ok=True)

    source = _synthetic_source(IMG_W, IMG_H)
    source.save(out_dir / "source.png")
    img_np = np.asarray(source)

    manifest: dict = {
        "image": "source.png",
        "imgW": IMG_W,
        "imgH": IMG_H,
        "tSamples": list(T_SAMPLES),
        "scenarios": [],
    }

    for name, spec in _scenarios().items():
        path: BurnsPath = spec["path"]
        out_w, out_h = output_size_for(
            IMG_W, IMG_H, output_aspect=spec["output_aspect"]
        )
        scene_dir = out_dir / name
        scene_dir.mkdir(parents=True, exist_ok=True)

        frames = []
        for t in T_SAMPLES:
            box = sample_box(path, t, IMG_W, IMG_H, out_w, out_h)
            frame = sample_frame(path, t, img_np, IMG_W, IMG_H, out_w, out_h)
            fname = f"t{t:.4f}.png"
            PIL_Image.fromarray(frame).save(scene_dir / fname)
            frames.append(
                {"t": t, "file": f"{name}/{fname}", "box": list(box)}
            )

        manifest["scenarios"].append(
            {
                "id": name,
                "outW": out_w,
                "outH": out_h,
                "outputAspect": spec["output_aspect"],
                "imageAspect": IMG_W / IMG_H,
                "path": path.to_dict(),
                "frames": frames,
            }
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_out = (
        Path(__file__).resolve().parent.parent
        / "ts"
        / "demo"
        / "public"
        / "reference"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=default_out,
        help=f"where to write reference renders (default: {default_out})",
    )
    args = parser.parse_args()
    manifest_path = generate(args.out_dir)
    scenarios = json.loads(manifest_path.read_text())["scenarios"]
    print(
        f"Wrote {manifest_path} "
        f"({len(scenarios)} scenarios x {len(T_SAMPLES)} frames)"
    )


if __name__ == "__main__":
    main()
