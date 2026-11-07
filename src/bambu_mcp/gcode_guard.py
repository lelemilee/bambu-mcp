"""Refuse 3MF projects that carry custom G-code or post-processing scripts.

A Bambu Studio project stores its printer and filament settings in
`Metadata/project_settings.config`, including G-code templates such as
`machine_start_gcode` and `change_filament_gcode`, and `post_process`
scripts that the slicer RUNS ON THIS PC. A downloaded project could use these
to send arbitrary G-code to the printer or run commands here.

So before slicing we:
- always refuse a non-empty `post_process`,
- refuse per-layer custom G-code,
- compare every G-code template with Bambu's own installed system preset of
  the same name and refuse any difference (unless BAMBU_ALLOW_CUSTOM_GCODE=true).
"""

from __future__ import annotations

import json
import os
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

PER_FILAMENT_KEYS = {"filament_start_gcode", "filament_end_gcode"}


class UnsafeProject(PermissionError):
    pass


def default_profile_dirs(studio_path: str | None) -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("BAMBU_PROFILES_DIRS")
    if env:
        dirs += [Path(p) for p in env.split(os.pathsep) if p]
    if studio_path:
        exe = Path(studio_path)
        dirs += [exe.parent / "resources" / "profiles" / "BBL",
                 exe.parent.parent / "Resources" / "profiles" / "BBL"]  # macOS bundle
    if os.environ.get("APPDATA"):
        dirs.append(Path(os.environ["APPDATA"]) / "BambuStudio" / "system" / "BBL")
    dirs.append(Path.home() / "Library" / "Application Support" / "BambuStudio" / "system" / "BBL")
    return [d for d in dirs if d.is_dir()]


class SystemProfiles:
    """Bambu's own presets from the installed app, looked up by name."""

    def __init__(self, dirs: list[Path]) -> None:
        self._by_name: dict[str, Path] = {}
        for d in dirs:
            for path in sorted(d.rglob("*.json")):
                try:
                    name = json.loads(path.read_text(encoding="utf-8")).get("name")
                except (OSError, ValueError, AttributeError):
                    continue
                if isinstance(name, str):
                    self._by_name.setdefault(name, path)

    def __bool__(self) -> bool:
        return bool(self._by_name)

    def has(self, name: str) -> bool:
        return name in self._by_name

    @lru_cache(maxsize=None)
    def _load(self, name: str) -> dict[str, Any] | None:
        path = self._by_name.get(name)
        if path is None:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def value(self, name: str, key: str, _depth: int = 0) -> Any:
        data = self._load(name)
        if data is None or _depth > 20:
            return None
        if key in data:
            return data[key]
        parent = data.get("inherits")
        return self.value(parent, key, _depth + 1) if parent else None


def _norm(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else "\n".join(map(str, value))
    text = str(value or "").replace("\r\n", "\n").replace("\\n", "\n")
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def read_project(path: Path) -> tuple[dict[str, Any], bytes | None]:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            settings = (
                json.loads(zf.read("Metadata/project_settings.config"))
                if "Metadata/project_settings.config" in names
                else {}
            )
            layers = (
                zf.read("Metadata/custom_gcode_per_layer.xml")
                if "Metadata/custom_gcode_per_layer.xml" in names
                else None
            )
    except (zipfile.BadZipFile, ValueError) as exc:
        raise UnsafeProject("Couldn't read this 3MF project's settings.") from exc
    return settings, layers


def check_project(path: Path, profiles: SystemProfiles, allow_custom_gcode: bool = False) -> None:
    settings, layers = read_project(path)

    if any(str(v).strip() for v in _as_list(settings.get("post_process", ""))):
        raise UnsafeProject("Project has post-processing scripts (they'd run on this PC). Refusing.")

    if layers:
        try:
            root = ElementTree.fromstring(layers)
            has_layer_codes = any(True for _ in root.iter("layer"))
        except ElementTree.ParseError:
            has_layer_codes = True
        if has_layer_codes:
            raise UnsafeProject(
                "Project has per-layer custom G-code or pauses. Remove them in Bambu Studio first."
            )

    if allow_custom_gcode:
        return
    if not profiles:
        raise UnsafeProject(
            "Couldn't find Bambu Studio's system presets to check G-code against. "
            "Set BAMBU_STUDIO_PATH or BAMBU_PROFILES_DIRS."
        )

    groups = _as_list(settings.get("inherits_group") or [])
    printer_names = [n for n in [settings.get("printer_settings_id"), groups[-1] if groups else None]
                     if isinstance(n, str) and profiles.has(n)]
    if not printer_names:
        raise UnsafeProject("Project doesn't use a Bambu system printer preset. Refusing to slice.")

    for key, value in settings.items():
        if not key.endswith("_gcode") or key in PER_FILAMENT_KEYS:
            continue
        if not any(_norm(profiles.value(n, key)) == _norm(value) for n in printer_names):
            raise UnsafeProject(f"Project changes '{key}' from Bambu's stock preset. Refusing.")

    filament_ids = _as_list(settings.get("filament_settings_id") or [])
    filament_parents = groups[1:-1] if len(groups) > 2 else []
    for key in PER_FILAMENT_KEYS:
        if key not in settings:
            continue
        for i, value in enumerate(_as_list(settings[key])):
            names = [n for n in (
                filament_ids[i] if i < len(filament_ids) else None,
                filament_parents[i] if i < len(filament_parents) else None,
            ) if isinstance(n, str) and profiles.has(n)]
            if not any(_norm(profiles.value(n, key)) == _norm(value) for n in names):
                raise UnsafeProject(
                    f"Filament {i + 1} changes '{key}' from Bambu's stock preset. Refusing."
                )
