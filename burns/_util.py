"""Internal helpers for :mod:`burns` — output-path resolution and
collision-safe naming.

These are deliberately self-contained so ``burns`` carries no dependency
beyond ``numpy`` / ``moviepy`` / ``pillow``.
"""

from pathlib import Path
from typing import Container


def _auto_video_path(src_path: str, suffix: str, *, ext: str | None = None) -> Path:
    """Generate an output video path by appending ``suffix`` to the stem.

    Args:
        src_path: Source file path (image or video).
        suffix: Suffix to add to the stem (e.g. ``"_kenburns"``).
        ext: Optional extension override (e.g. ``".mp4"``).

    Returns:
        Path with format ``{stem}{suffix}{ext}``.

    Examples:
        >>> str(_auto_video_path("photo.jpg", "_kenburns", ext=".mp4"))
        'photo_kenburns.mp4'
    """
    src = Path(src_path)
    output = src.with_stem(f"{src.stem}{suffix}")
    if ext:
        output = output.with_suffix(ext)
    return output


def _ensure_output_path(path: str | Path) -> Path:
    """Convert to :class:`~pathlib.Path` and ensure the parent directory exists.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> tmp = Path(tempfile.mkdtemp())
        >>> out = _ensure_output_path(tmp / "sub" / "film.mp4")
        >>> out.parent.exists()
        True
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _non_colliding_key(
    key: str, exclude: Container[str], *, max_attempts: int = 10000
) -> str:
    """Return a filename not present in ``exclude``.

    If ``key`` is already unique it is returned as-is; otherwise a
    ``" (N)"`` suffix is inserted before the extension until a free name is
    found. Mirrors ``dol.non_colliding_key``'s default string behavior so
    auto-named renders never silently overwrite an existing file.

    Examples:
        >>> _non_colliding_key("film.mp4", set())
        'film.mp4'
        >>> _non_colliding_key("film.mp4", {"film.mp4"})
        'film (1).mp4'
        >>> _non_colliding_key("film.mp4", {"film.mp4", "film (1).mp4"})
        'film (2).mp4'
    """
    if key not in exclude:
        return key
    p = Path(key)
    stem, suffix = p.stem, p.suffix
    for attempt in range(1, max_attempts + 1):
        candidate = f"{stem} ({attempt}){suffix}"
        if candidate not in exclude:
            return candidate
    raise ValueError(
        f"_non_colliding_key: no free name for {key!r} within {max_attempts} attempts"
    )
