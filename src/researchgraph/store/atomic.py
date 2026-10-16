"""Atomic file write helper."""
from __future__ import annotations

import os
from pathlib import Path


def write_atomic(target_path: Path | str, content: str, encoding: str = "utf-8") -> None:
    """Write content to target_path atomically using a temporary file and rename."""
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.parent / f".tmp.{target.name}.{os.getpid()}"
    try:
        temp_path.write_text(content, encoding=encoding)
        temp_path.replace(target)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
