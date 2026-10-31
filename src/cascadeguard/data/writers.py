"""P2 dataset writers. Local files are the default; cloud URIs use fsspec."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascadeguard.common.io import write_json, write_parquet


def write_dataset(frame: Any, destination: str | Path) -> str:
    return write_parquet(frame, destination)


__all__ = ["write_dataset", "write_json", "write_parquet"]
