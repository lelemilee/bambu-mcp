"""Read what's inside a sliced .gcode.3mf (it's a zip)."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

_PLATE_RE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def inspect_job(path: Path) -> dict[int, dict[str, Any]]:
    """Return {plate_number: {print_minutes, filament_g, filaments: [...]}}."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a valid sliced .gcode.3mf file.") from exc
    with zf:
        names = zf.namelist()
        plates: dict[int, dict[str, Any]] = {
            int(m.group(1)): {"print_minutes": None, "filament_g": None, "filaments": []}
            for n in names
            if (m := _PLATE_RE.match(n))
        }
        if "Metadata/slice_info.config" in names:
            try:
                root = ElementTree.fromstring(zf.read("Metadata/slice_info.config"))
            except ElementTree.ParseError:
                root = None
            for plate in root.iter("plate") if root is not None else []:
                meta = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
                idx = _num(meta.get("index"))
                if idx is None or int(idx) not in plates:
                    continue
                seconds = _num(meta.get("prediction"))
                plates[int(idx)].update(
                    print_minutes=round(seconds / 60) if seconds is not None else None,
                    filament_g=_num(meta.get("weight")),
                    filaments=[
                        {
                            "id": f.get("id"),
                            "type": f.get("type"),
                            "color": f.get("color"),
                            "used_g": _num(f.get("used_g")),
                        }
                        for f in plate.findall("filament")
                    ],
                )
    if not plates:
        raise ValueError("No sliced plates found in this file.")
    return plates
