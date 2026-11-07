"""Slice with the Bambu Studio command-line tool.

Run `bambu-studio --help` on your PC to see every flag your version supports.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_PATHS = [
    r"C:\Program Files\Bambu Studio\bambu-studio.exe",
    "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio",
    "/usr/bin/bambu-studio",
]


def find_studio(configured: str | None) -> str:
    candidates = [configured] if configured else []
    candidates += [shutil.which("bambu-studio") or ""] + DEFAULT_PATHS
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "Bambu Studio not found. Set BAMBU_STUDIO_PATH to bambu-studio.exe."
    )


def build_command(
    studio: str,
    input_file: Path,
    output_dir: Path,
    output_name: str,
    plate: int = 0,
    settings: list[str] | None = None,
    filaments: list[str] | None = None,
) -> list[str]:
    cmd = [
        studio,
        "--slice", str(plate),  # 0 = all plates
        "--outputdir", str(output_dir),
        "--export-3mf", output_name,
    ]
    if settings:
        cmd += ["--load-settings", ";".join(settings)]
    if filaments:
        cmd += ["--load-filaments", ";".join(filaments)]
    cmd.append(str(input_file))
    return cmd


def slice_file(
    studio: str,
    input_file: Path,
    output_dir: Path,
    plate: int = 0,
    settings: list[str] | None = None,
    filaments: list[str] | None = None,
    timeout: int = 900,
) -> Path:
    if not input_file.is_file():
        raise FileNotFoundError(f"No such file: {input_file}")
    if input_file.suffix.lower() != ".3mf" and not settings:
        raise ValueError(
            "STL files need printer/process settings. Save the model as a 3MF "
            "project in Bambu Studio first, or pass settings JSON files."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_name = f"{input_file.stem}.gcode.3mf"
    cmd = build_command(studio, input_file, output_dir, output_name, plate, settings, filaments)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = output_dir / output_name
    if result.returncode != 0 or not out.is_file():
        tail = (result.stderr or result.stdout or "").strip()[-1500:]
        raise RuntimeError(f"Slicing failed (exit {result.returncode}).\n{tail}")
    return out
