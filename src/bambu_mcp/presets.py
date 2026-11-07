"""Trusted slicing settings: Bambu's own system presets for the P2S.

Slicing never uses settings stored inside a model file. We take Bambu
Studio's installed system presets (machine, process, filament), resolve their
`inherits` chains into complete configs, and pass only those to the slicer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_MACHINE = "Bambu Lab P2S 0.4 nozzle"
DEFAULT_PROCESS = "0.20mm Standard @BBL P2S"
DEFAULT_FILAMENTS = {
    "PLA": "Bambu PLA Basic @BBL P2S",
    "PETG": "Bambu PETG HF @BBL P2S",
}
ALLOWED_FILAMENT_TYPES = tuple(DEFAULT_FILAMENTS)  # PLA/PETG only, on purpose


class PresetError(LookupError):
    pass


def default_profile_dirs(studio_path: str | None) -> list[Path]:
    """Same order Bambu Studio uses: the system presets it keeps up to date in
    its data folder first, then the copies shipped in the install folder."""
    dirs: list[Path] = []
    env = os.environ.get("BAMBU_PROFILES_DIRS")
    if env:
        dirs += [Path(p) for p in env.split(os.pathsep) if p]
    if os.environ.get("APPDATA"):
        dirs.append(Path(os.environ["APPDATA"]) / "BambuStudio" / "system" / "BBL")
    home = Path.home()
    dirs += [
        home / "Library" / "Application Support" / "BambuStudio" / "system" / "BBL",
        home / ".config" / "BambuStudio" / "system" / "BBL",
    ]
    if studio_path:
        exe = Path(studio_path)
        dirs += [
            exe.parent / "resources" / "profiles" / "BBL",
            exe.parent.parent / "Resources" / "profiles" / "BBL",  # macOS bundle
        ]
    return [d for d in dirs if d.is_dir()]


class SystemPresets:
    def __init__(self, dirs: list[Path]) -> None:
        self._by_name: dict[str, dict[str, Any]] = {}
        for d in dirs:
            for path in sorted(d.rglob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if isinstance(data, dict) and isinstance(data.get("name"), str):
                    self._by_name.setdefault(data["name"], data)

    def resolve(self, name: str, kind: str) -> dict[str, Any]:
        """Full config for a system preset of `kind` (machine/process/filament)."""
        chain: list[dict[str, Any]] = []
        current: str | None = name
        while current:
            data = self._by_name.get(current)
            if data is None or len(chain) > 20:
                if not chain:
                    raise PresetError(self._missing(name, kind))
                raise PresetError(f"Preset '{name}' inherits from missing '{current}'.")
            chain.append(data)
            current = data.get("inherits") or None
        if chain[0].get("type") != kind:
            raise PresetError(f"'{name}' is a {chain[0].get('type')} preset, not {kind}.")
        merged: dict[str, Any] = {}
        for data in reversed(chain):
            merged.update(data)
        merged.pop("inherits", None)
        merged["name"] = name
        merged["from"] = "system"
        return merged

    def _missing(self, name: str, kind: str) -> str:
        similar = sorted(n for n, d in self._by_name.items()
                         if d.get("type") == kind and "P2S" in n)[:8]
        hint = f" Similar: {', '.join(similar)}." if similar else ""
        return (f"Bambu Studio {kind} preset '{name}' not found.{hint} "
                "Set the matching BAMBU_*_PRESET setting.")


def _require_compatible(preset: dict[str, Any], machine_name: str) -> None:
    compatible = preset.get("compatible_printers")
    if not isinstance(compatible, list) or machine_name not in compatible:
        raise PresetError(f"Preset '{preset['name']}' isn't made for '{machine_name}'.")


def build_settings(
    presets: SystemPresets, filament_types: list[str], env: dict[str, str] | None = None
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    env = os.environ if env is None else env
    machine = presets.resolve(env.get("BAMBU_MACHINE_PRESET") or DEFAULT_MACHINE, "machine")
    model = str(machine.get("printer_model") or machine["name"])
    if "P2S" not in machine["name"] or "P2S" not in model:
        raise PresetError(f"Machine preset '{machine['name']}' isn't a P2S preset.")
    process = presets.resolve(env.get("BAMBU_PROCESS_PRESET") or DEFAULT_PROCESS, "process")
    _require_compatible(process, machine["name"])
    process["post_process"] = []  # never run scripts, even if a preset had one
    filaments = []
    for ftype in filament_types:
        ftype = ftype.strip().upper()
        if ftype not in ALLOWED_FILAMENT_TYPES:
            raise PresetError(f"Filament '{ftype}' isn't allowed. Use one of {ALLOWED_FILAMENT_TYPES}.")
        name = env.get(f"BAMBU_FILAMENT_PRESET_{ftype}") or DEFAULT_FILAMENTS[ftype]
        preset = presets.resolve(name, "filament")
        declared = preset.get("filament_type")
        declared = declared[0] if isinstance(declared, list) and declared else declared
        if not declared or str(declared).upper() != ftype:
            raise PresetError(f"Preset '{name}' is {declared or 'an unknown type'}, not {ftype}.")
        _require_compatible(preset, machine["name"])
        filaments.append(preset)
    return machine, process, filaments
