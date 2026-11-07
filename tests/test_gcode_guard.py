import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from bambu_mcp import gcode_guard, server, slicer
from bambu_mcp.config import Settings
from bambu_mcp.gcode_guard import SystemProfiles, UnsafeProject, check_project
from bambu_mcp.safety import PrintGate, SlicedRegistry
from conftest import make_job

STOCK_START = "M104 S220\nG28\n"
STOCK_FIL = "; filament start\n"


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles" / "BBL"
    (d / "machine").mkdir(parents=True)
    (d / "filament").mkdir()
    (d / "machine" / "common.json").write_text(json.dumps(
        {"name": "fdm_common", "machine_start_gcode": STOCK_START, "layer_change_gcode": ""}))
    (d / "machine" / "p2s.json").write_text(json.dumps(
        {"name": "Bambu Lab P2S 0.4 nozzle", "inherits": "fdm_common", "machine_end_gcode": "M84"}))
    (d / "filament" / "pla.json").write_text(json.dumps(
        {"name": "Bambu PLA Basic @BBL P2S", "filament_start_gcode": [STOCK_FIL]}))
    return d


def project(path: Path, layers: str | None = None, **overrides) -> Path:
    settings = {
        "printer_settings_id": "Bambu Lab P2S 0.4 nozzle",
        "inherits_group": ["", "Bambu PLA Basic @BBL P2S", "Bambu Lab P2S 0.4 nozzle"],
        "filament_settings_id": ["Bambu PLA Basic @BBL P2S"],
        "machine_start_gcode": STOCK_START.replace("\n", "\r\n"),  # line endings don't matter
        "machine_end_gcode": "M84",
        "layer_change_gcode": "",
        "filament_start_gcode": [STOCK_FIL],
        "post_process": [],
    }
    settings.update(overrides)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
        zf.writestr("Metadata/project_settings.config", json.dumps(settings))
        if layers is not None:
            zf.writestr("Metadata/custom_gcode_per_layer.xml", layers)
    return path


def test_stock_project_passes(tmp_path, profiles_dir):
    check_project(project(tmp_path / "ok.3mf"), SystemProfiles([profiles_dir]))


@pytest.mark.parametrize("override", [
    {"machine_start_gcode": STOCK_START + "M106 S255\n"},
    {"change_filament_gcode": "G1 X999"},  # key not in stock preset at all
    {"layer_change_gcode": "M104 S300"},
    {"filament_start_gcode": ["M104 S300"]},
    {"printer_settings_id": "My Printer", "inherits_group": ["", "", "My Printer"]},
])
def test_custom_gcode_refused(tmp_path, profiles_dir, override):
    with pytest.raises(UnsafeProject):
        check_project(project(tmp_path / "bad.3mf", **override), SystemProfiles([profiles_dir]))


def test_post_process_always_refused(tmp_path, profiles_dir):
    p = project(tmp_path / "pp.3mf", post_process=["calc.exe"])
    with pytest.raises(UnsafeProject, match="post-processing"):
        check_project(p, SystemProfiles([profiles_dir]), allow_custom_gcode=True)


def test_per_layer_gcode_refused(tmp_path, profiles_dir):
    p = project(tmp_path / "l.3mf", layers='<custom_gcodes_per_layer><plate><layer top_z="2" type="4" extra="M104 S300"/></plate></custom_gcodes_per_layer>')
    with pytest.raises(UnsafeProject, match="per-layer"):
        check_project(p, SystemProfiles([profiles_dir]))


def test_no_profiles_found_refuses(tmp_path):
    with pytest.raises(UnsafeProject, match="system presets"):
        check_project(project(tmp_path / "ok.3mf"), SystemProfiles([]))


def test_opt_out_allows_custom_gcode(tmp_path):
    p = project(tmp_path / "c.3mf", machine_start_gcode="G28\nM106")
    check_project(p, SystemProfiles([]), allow_custom_gcode=True)


# ---- slice_model -> prepare_print round trip with a mocked slicer ----

class FakePrinter:
    def refresh(self):
        return {"print": {"gcode_state": "IDLE", "ams": {"ams": []}}}

    def upload(self, data, remote):
        self.uploaded = data
        return remote


@pytest.fixture
def env(tmp_path, monkeypatch, profiles_dir):
    work = tmp_path / "work"
    s = Settings("1.2.3.4", "SN", "code", "studio", work, False)
    monkeypatch.setattr(server, "_settings", s)
    monkeypatch.setattr(server, "_printer", FakePrinter())
    monkeypatch.setattr(server, "_gate", PrintGate())
    monkeypatch.setattr(server, "_sliced", SlicedRegistry(work))
    monkeypatch.setattr(slicer, "find_studio", lambda configured: "studio")
    monkeypatch.setattr(gcode_guard, "default_profile_dirs", lambda studio: [profiles_dir])
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        out_dir = Path(cmd[cmd.index("--outputdir") + 1])
        make_job(out_dir / cmd[cmd.index("--export-3mf") + 1])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(slicer.subprocess, "run", fake_run)
    return tmp_path, runs


def test_round_trip_stock_project(env):
    tmp_path, runs = env
    result = server.slice_model(str(project(tmp_path / "part.3mf")))
    prep = server.prepare_print(result["sliced_file"])
    assert len(runs) == 1 and prep["plate"] == 1
    assert server._printer.uploaded == Path(result["sliced_file"]).read_bytes()


def test_round_trip_custom_gcode_never_sliced(env):
    tmp_path, runs = env
    bad = project(tmp_path / "evil.3mf", machine_start_gcode="M104 S300\nG28")
    with pytest.raises(UnsafeProject):
        server.slice_model(str(bad))
    assert runs == []  # slicer never ran


def test_round_trip_post_process_never_sliced(env):
    tmp_path, runs = env
    with pytest.raises(UnsafeProject):
        server.slice_model(str(project(tmp_path / "pp.3mf", post_process="cmd /c evil")))
    assert runs == []
