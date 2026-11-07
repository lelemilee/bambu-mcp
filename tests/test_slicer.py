from pathlib import Path

import pytest

from bambu_mcp.slicer import build_command, slice_file


def test_build_command():
    cmd = build_command("studio", Path("in.3mf"), Path("out"), "in.gcode.3mf", 0, ["m.json", "p.json"])
    assert cmd == [
        "studio", "--slice", "0", "--outputdir", "out", "--export-3mf", "in.gcode.3mf",
        "--load-settings", "m.json;p.json", "in.3mf",
    ]


def test_stl_needs_settings(tmp_path):
    stl = tmp_path / "a.stl"
    stl.write_bytes(b"x")
    with pytest.raises(ValueError):
        slice_file("studio", stl, tmp_path)
