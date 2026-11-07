"""Slice with the Bambu Studio command-line tool, using trusted presets only.

Run `bambu-studio --help` on your PC to see every flag your version supports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .geometry import private_copy

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
    raise FileNotFoundError("Bambu Studio not found. Set BAMBU_STUDIO_PATH to bambu-studio.exe.")


def build_command(
    studio: str, model: Path, job_dir: Path, output_name: str, plate: int,
    settings: list[Path], filaments: list[Path],
) -> list[str]:
    return [
        studio,
        "--slice", str(plate),  # 0 = all plates
        "--arrange", "1",
        "--load-settings", ";".join(str(p) for p in settings),
        "--load-filaments", ";".join(str(p) for p in filaments),
        "--outputdir", str(job_dir),
        "--export-3mf", output_name,
        str(model),
    ]


def slice_file(
    studio: str,
    source: Path,
    work_dir: Path,
    machine: dict[str, Any],
    process: dict[str, Any],
    filaments: list[dict[str, Any]],
    plate: int = 0,
    timeout: int = 900,
) -> Path:
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"No such file: {source}")
    jobs = work_dir.resolve() / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    job_dir = Path(tempfile.mkdtemp(prefix="slice-", dir=jobs))  # private (0700)

    # From here on the slicer only sees files we wrote into job_dir.
    model = private_copy(source, job_dir)
    settings = [job_dir / "machine.json", job_dir / "process.json"]
    settings[0].write_text(json.dumps(machine), encoding="utf-8")
    settings[1].write_text(json.dumps(process), encoding="utf-8")
    filament_files = []
    for i, f in enumerate(filaments, 1):
        p = job_dir / f"filament{i}.json"
        p.write_text(json.dumps(f), encoding="utf-8")
        filament_files.append(p)

    output_name = f"{source.stem}-{time.strftime('%Y%m%d-%H%M%S')}.gcode.3mf"
    cmd = build_command(studio, model, job_dir, output_name, plate, settings, filament_files)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=job_dir)
    out = job_dir / output_name
    if result.returncode != 0 or not out.is_file():
        tail = (result.stderr or result.stdout or "").strip()[-1500:]
        raise RuntimeError(f"Slicing failed (exit {result.returncode}).\n{tail}")
    return out
