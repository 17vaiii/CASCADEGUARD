"""Storage helpers with local-first paths and fsspec-compatible cloud URIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def is_uri(location: str | Path) -> bool:
    return bool(urlparse(str(location)).scheme)


def write_parquet(frame: Any, location: str | Path) -> str:
    """Write a dataframe to a local path or an fsspec URI (s3://, gs://, ...)."""
    target = str(location)
    if not is_uri(target) or target.startswith("file://"):
        path = Path(target.removeprefix("file://"))
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        return str(path)
    try:
        import fsspec
    except ImportError as exc:
        raise RuntimeError("Cloud storage requires fsspec and the matching s3fs/gcsfs extra") from exc
    fs, fs_path = fsspec.core.url_to_fs(target)
    parent = fs_path.rsplit("/", 1)[0] if "/" in fs_path else ""
    if parent:
        fs.makedirs(parent, exist_ok=True)
    with fs.open(fs_path, "wb") as stream:
        frame.to_parquet(stream, index=False)
    return target


def write_json(value: Any, location: str | Path) -> str:
    """Write JSON to a local path or fsspec URI."""
    payload = json.dumps(value, indent=2, sort_keys=True, default=str).encode("utf-8")
    target = str(location)
    if not is_uri(target) or target.startswith("file://"):
        path = Path(target.removeprefix("file://"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return str(path)
    try:
        import fsspec
    except ImportError as exc:
        raise RuntimeError("Cloud storage requires fsspec and the matching s3fs/gcsfs extra") from exc
    fs, fs_path = fsspec.core.url_to_fs(target)
    parent = fs_path.rsplit("/", 1)[0] if "/" in fs_path else ""
    if parent:
        fs.makedirs(parent, exist_ok=True)
    with fs.open(fs_path, "wb") as stream:
        stream.write(payload)
    return target
