"""Generate the README demo assets: a still image + two Ken Burns GIFs.

Run from the repo root:

    python misc/generate_demo.py

Produces (committed under ``assets/``):
    - ``demo_landscape.jpg`` — a synthetic sunset landscape (the input still)
    - ``demo_push.gif``      — ``ken_burns_path(..., style="push", ease=True)``
    - ``demo_drift.gif``     — ``ken_burns_path(..., style="drift")``

The image is generated procedurally (no external assets), so the demo is fully
reproducible. GIF conversion uses the system ``ffmpeg`` palette pipeline for a
small, crisp result.
"""

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from burns import ken_burns_video, ken_burns_path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
GIF_WIDTH = 480
GIF_FPS = 12


def make_landscape(width: int = 1280, height: int = 720) -> Image.Image:
    """A procedurally drawn sunset landscape with enough detail across the
    frame that pan and zoom both read clearly."""
    horizon = int(height * 0.62)

    # Sky: vertical gradient (deep indigo at top → warm orange at the horizon),
    # built with numpy for speed, then drawn on with PIL features.
    top = np.array([32, 28, 78], dtype=float)
    bottom = np.array([250, 160, 70], dtype=float)
    ground = np.array([46, 30, 36], dtype=float)  # warm dark, blends at the seam
    arr = np.empty((height, width, 3), dtype=np.uint8)
    for y in range(height):
        if y < horizon:
            t = y / horizon
            arr[y, :, :] = (top + (bottom - top) * t).astype(np.uint8)
        else:
            arr[y, :, :] = ground.astype(np.uint8)
    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)

    # Stars in the upper sky.
    rng = np.random.default_rng(7)
    for _ in range(160):
        sx = int(rng.integers(0, width))
        sy = int(rng.integers(0, int(horizon * 0.55)))
        b = int(rng.integers(150, 256))
        draw.point((sx, sy), fill=(b, b, b))

    # Sun with a soft glow (concentric translucent rings).
    sun_cx, sun_cy, sun_r = int(width * 0.70), int(horizon * 0.74), 64
    for ring in range(8, 0, -1):
        rr = sun_r + ring * 14
        alpha = int(18 * ring / 8)
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        gdraw.ellipse(
            [sun_cx - rr, sun_cy - rr, sun_cx + rr, sun_cy + rr],
            fill=(255, 220, 150, alpha),
        )
        img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
        draw = ImageDraw.Draw(img)
    draw.ellipse(
        [sun_cx - sun_r, sun_cy - sun_r, sun_cx + sun_r, sun_cy + sun_r],
        fill=(255, 236, 190),
    )

    # Layered hill silhouettes — darker as they come forward.
    def hill_layer(base_y, amp, color, freq, phase):
        pts = [(0, height)]
        for x in range(0, width + 1, 6):
            y = (
                base_y
                + int(amp * math.sin(x * freq + phase))
                + int(amp * 0.4 * math.sin(x * freq * 2.3 + phase))
            )
            pts.append((x, y))
        pts += [(width, height)]
        draw.polygon(pts, fill=color)

    hill_layer(horizon - 4, 22, (66, 50, 78), 0.006, 0.0)
    hill_layer(horizon + 56, 32, (44, 32, 56), 0.008, 1.3)
    hill_layer(horizon + 118, 44, (24, 17, 34), 0.010, 2.7)

    # A few distant birds (simple V strokes).
    for bx, by in [(220, 150), (300, 120), (380, 165), (900, 110), (980, 140)]:
        draw.line([(bx, by), (bx + 12, by - 8)], fill=(28, 20, 30), width=2)
        draw.line([(bx + 12, by - 8), (bx + 24, by)], fill=(28, 20, 30), width=2)

    return img


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
    )


def mp4_to_gif(mp4: Path, gif: Path, *, width: int = GIF_WIDTH, fps: int = GIF_FPS):
    """High-quality mp4 → gif via the ffmpeg palettegen/paletteuse pipeline."""
    with tempfile.TemporaryDirectory() as tmp:
        palette = Path(tmp) / "palette.png"
        vf = f"fps={fps},scale={width}:-1:flags=lanczos"
        _ffmpeg(["-i", str(mp4), "-vf", f"{vf},palettegen=stats_mode=diff", str(palette)])
        _ffmpeg(
            [
                "-i", str(mp4),
                "-i", str(palette),
                "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
                str(gif),
            ]
        )


def main():
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found on PATH — install it to build the demo GIFs.")
    ASSETS.mkdir(exist_ok=True)

    still = ASSETS / "demo_landscape.jpg"
    img = make_landscape()
    img.save(still, quality=88)
    print(f"wrote {still}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        push_mp4 = ken_burns_video(
            still,
            phases=ken_burns_path(1, 4.0, zoom=1.4, pan=0.06, ease=True),
            fps=24,
            saveas=str(tmp / "push.mp4"),
        )
        mp4_to_gif(Path(push_mp4), ASSETS / "demo_push.gif")
        print(f"wrote {ASSETS / 'demo_push.gif'}")

        drift_mp4 = ken_burns_video(
            still,
            phases=ken_burns_path(2, 4.0, style="drift", pan=0.14),
            fps=24,
            saveas=str(tmp / "drift.mp4"),
        )
        mp4_to_gif(Path(drift_mp4), ASSETS / "demo_drift.gif")
        print(f"wrote {ASSETS / 'demo_drift.gif'}")


if __name__ == "__main__":
    main()
