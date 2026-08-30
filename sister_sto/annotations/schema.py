"""Deterministic serialization and coordinate helpers for annotation corpora."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
BBox = Tuple[int, int, int, int]


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON-compatible value in a stable form."""
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fingerprint(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def pixel_sha256(image: Any) -> str:
    """Hash decoded pixel content together with its shape and dtype."""
    descriptor = canonical_json_bytes(
        {"dtype": str(image.dtype), "shape": list(image.shape)}
    )
    return sha256_bytes(descriptor + image.tobytes(order="C"))


def clamp_bbox(bbox: Sequence[float], width: int, height: int) -> BBox:
    """Clamp an xyxy box to image bounds and normalize reversed edges."""
    x1, y1, x2, y2 = (int(round(value)) for value in bbox)
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    return (
        min(max(x1, 0), width),
        min(max(y1, 0), height),
        min(max(x2, 0), width),
        min(max(y2, 0), height),
    )


def map_bbox_to_source(
    bbox: Sequence[float],
    processed_width: int,
    processed_height: int,
    source_width: int,
    source_height: int,
) -> BBox:
    """Map a processed-image box back into source-image coordinates."""
    if processed_width <= 0 or processed_height <= 0:
        raise ValueError("Processed image dimensions must be positive")
    scale_x = source_width / processed_width
    scale_y = source_height / processed_height
    x1, y1, x2, y2 = bbox
    return clamp_bbox(
        (x1 * scale_x, y1 * scale_y, x2 * scale_x, y2 * scale_y),
        source_width,
        source_height,
    )


def atomic_write_bytes(path: Path, value: bytes) -> None:
    """Atomically replace a file with bytes written in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def package_version() -> str:
    try:
        return metadata.version("sister_sto")
    except metadata.PackageNotFoundError:
        return "unknown"


def git_revision(repository: Optional[Path] = None) -> Optional[str]:
    """Return the current revision when run from a Git checkout."""
    cwd = repository or Path(__file__).resolve().parents[2]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision or None
