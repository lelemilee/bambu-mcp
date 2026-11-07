import zipfile
from pathlib import Path

import pytest

SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="3720"/>
    <metadata key="weight" value="21.5"/>
    <filament id="1" type="PLA" color="#FF6A13" used_g="21.5"/>
  </plate>
</config>"""


def make_job(path: Path, plates=(1,), slice_info: str | None = SLICE_INFO) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for p in plates:
            zf.writestr(f"Metadata/plate_{p}.gcode", "G28\n")
        if slice_info is not None:
            zf.writestr("Metadata/slice_info.config", slice_info)
    return path


@pytest.fixture
def anyio_backend():
    return "asyncio"
