"""Make a private, geometry-only copy of a model file.

The input is read exactly once. STL/STEP are copied as they are (they can't
carry slicer settings). A 3MF is rebuilt with only its mesh parts, so any
settings, custom G-code or scripts stored in it are simply not there.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

MAX_BYTES = 300 * 1024 * 1024
PLAIN_FORMATS = {".stl", ".step", ".stp"}


def _keep_3mf_member(name: str) -> bool:
    n = name.lower()
    if n in ("[content_types].xml", "_rels/.rels"):
        return True
    if n.startswith("3d/_rels/") and n.endswith(".rels"):
        return True
    return n.startswith("3d/") and n.endswith(".model")


def strip_3mf(data: bytes) -> bytes:
    try:
        src = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a valid 3MF file.") from exc
    with src:
        names = [i.filename for i in src.infolist()]
        lowered = [n.lower() for n in names]
        if len(set(lowered)) != len(lowered):
            raise ValueError("3MF has duplicate entries. Refusing it.")
        kept = [n for n in names if _keep_3mf_member(n)]
        if not any(n.lower().endswith(".model") for n in kept):
            raise ValueError("3MF has no 3D model inside.")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
            for n in kept:
                dst.writestr(n, src.read(n))
    return out.getvalue()


def private_copy(source: Path, dest_dir: Path) -> Path:
    suffix = source.suffix.lower()
    if suffix not in PLAIN_FORMATS | {".3mf"}:
        raise ValueError("Give an .stl, .step or .3mf model file.")
    with source.open("rb") as fh:
        data = fh.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Model file is too big.")
    if suffix == ".3mf":
        data = strip_3mf(data)
    dest = dest_dir / f"model{suffix}"
    dest.write_bytes(data)
    return dest
