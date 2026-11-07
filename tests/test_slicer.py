import io
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from bambu_mcp import presets, server, slicer
from bambu_mcp.config import Settings
from bambu_mcp.geometry import private_copy, strip_3mf
from bambu_mcp.presets import PresetError, SystemPresets, build_settings
from bambu_mcp.safety import PrintGate, SlicedRegistry
from conftest import make_job

STOCK_START = "M104 S220\nG28\n"
EVIL = "M104 S300 ; evil"


@pytest.fixture
def profiles_dir(tmp_path):
    d = tmp_path / "profiles" / "BBL"
    for sub in ("machine", "process", "filament"):
        (d / sub).mkdir(parents=True)

    def put(sub, name, **data):
        (d / sub / f"{name}.json").write_text(json.dumps({"name": name, **data}))

    p2s = ["Bambu Lab P2S 0.4 nozzle"]
    put("machine", "fdm_common", type="machine", machine_start_gcode=STOCK_START)
    put("machine", "Bambu Lab P2S 0.4 nozzle", type="machine", inherits="fdm_common",
        printer_model="Bambu Lab P2S", machine_end_gcode="M84")
    put("machine", "Bambu Lab A1 mini 0.4 nozzle", type="machine", machine_start_gcode="A1",
        printer_model="Bambu Lab A1 mini")
    put("process", "0.20mm Standard @BBL P2S", type="process", layer_height="0.2",
        post_process=["should be removed"], compatible_printers=p2s)
    put("process", "0.20mm Standard @BBL A1M", type="process",
        compatible_printers=["Bambu Lab A1 mini 0.4 nozzle"])
    put("filament", "Bambu PLA Basic @BBL P2S", type="filament", filament_type=["PLA"],
        compatible_printers=p2s)
    put("filament", "Bambu PETG HF @BBL P2S", type="filament", filament_type=["PETG"],
        compatible_printers=p2s)
    put("filament", "Wrong Type @BBL P2S", type="filament", filament_type=["ABS"],
        compatible_printers=p2s)
    put("filament", "No Type @BBL P2S", type="filament", compatible_printers=p2s)
    put("filament", "Bambu PLA Basic @BBL A1M", type="filament", filament_type=["PLA"],
        compatible_printers=["Bambu Lab A1 mini 0.4 nozzle"])
    return d


def evil_3mf(path: Path) -> Path:
    """A project stuffed with every kind of embedded setting, in sneaky spellings."""
    bad_settings = json.dumps({"machine_start_gcode": EVIL, "post_process": ["calc.exe"]})
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("_rels/.rels", "<Relationships/>")
        zf.writestr("3D/3dmodel.model", '<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"/>')
        zf.writestr("3D/Objects/object_1.model", "<model/>")
        zf.writestr("3D/_rels/3dmodel.model.rels", "<Relationships/>")
        zf.writestr("Metadata/project_settings.config", bad_settings)
        zf.writestr("metadata/Custom_Gcode_Per_Layer.xml",
                    '<c xmlns="x"><layer extra="' + EVIL + '"/></c>')
        zf.writestr("Metadata/model_settings.config", "<config/>")
        zf.writestr("Metadata/Slic3r_PE.config", "; post_process = evil")
        zf.writestr("Auxiliaries/readme.txt", "hi")
    return path


# ---- presets ----

def test_build_settings_resolves_inheritance(profiles_dir):
    machine, process, fils = build_settings(SystemPresets([profiles_dir]), ["pla", "PETG"], env={})
    assert machine["machine_start_gcode"] == STOCK_START and machine["machine_end_gcode"] == "M84"
    assert "inherits" not in machine and machine["name"] == "Bambu Lab P2S 0.4 nozzle"
    assert process["post_process"] == []
    assert [f["name"] for f in fils] == ["Bambu PLA Basic @BBL P2S", "Bambu PETG HF @BBL P2S"]


@pytest.mark.parametrize("types", [["ABS"], ["ASA"], ["TPU"]])
def test_only_pla_and_petg(profiles_dir, types):
    with pytest.raises(PresetError, match="isn't allowed"):
        build_settings(SystemPresets([profiles_dir]), types, env={})


def test_preset_must_be_right_kind_and_type(profiles_dir):
    p = SystemPresets([profiles_dir])
    with pytest.raises(PresetError, match="not machine"):
        build_settings(p, ["PLA"], env={"BAMBU_MACHINE_PRESET": "0.20mm Standard @BBL P2S"})
    with pytest.raises(PresetError, match="not PLA"):
        build_settings(p, ["PLA"], env={"BAMBU_FILAMENT_PRESET_PLA": "Wrong Type @BBL P2S"})


def test_machine_must_be_p2s(profiles_dir):
    with pytest.raises(PresetError, match="isn't a P2S"):
        build_settings(SystemPresets([profiles_dir]), ["PLA"],
                       env={"BAMBU_MACHINE_PRESET": "Bambu Lab A1 mini 0.4 nozzle"})


@pytest.mark.parametrize("env", [
    {"BAMBU_PROCESS_PRESET": "0.20mm Standard @BBL A1M"},
    {"BAMBU_FILAMENT_PRESET_PLA": "Bambu PLA Basic @BBL A1M"},
])
def test_presets_must_be_made_for_p2s(profiles_dir, env):
    with pytest.raises(PresetError, match="isn't made for"):
        build_settings(SystemPresets([profiles_dir]), ["PLA"], env=env)


def test_filament_without_type_refused(profiles_dir):
    with pytest.raises(PresetError, match="unknown type"):
        build_settings(SystemPresets([profiles_dir]), ["PLA"],
                       env={"BAMBU_FILAMENT_PRESET_PLA": "No Type @BBL P2S"})


def test_missing_preset_lists_close_matches(profiles_dir):
    with pytest.raises(PresetError, match="Similar: Bambu Lab P2S 0.4 nozzle"):
        build_settings(SystemPresets([profiles_dir]), ["PLA"],
                       env={"BAMBU_MACHINE_PRESET": "Bambu Lab P2S 0.6 nozzle"})


def test_linux_preset_path_is_searched(tmp_path, monkeypatch):
    linux = tmp_path / ".config" / "BambuStudio" / "system" / "BBL"
    linux.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("BAMBU_PROFILES_DIRS", raising=False)
    assert linux in presets.default_profile_dirs(None)


# ---- geometry-only copy ----

def test_strip_3mf_keeps_only_geometry(tmp_path):
    stripped = zipfile.ZipFile(io.BytesIO(strip_3mf(evil_3mf(tmp_path / "e.3mf").read_bytes())))
    assert sorted(stripped.namelist()) == [
        "3D/3dmodel.model", "3D/Objects/object_1.model", "3D/_rels/3dmodel.model.rels",
        "[Content_Types].xml", "_rels/.rels",
    ]
    assert EVIL.encode() not in b"".join(stripped.read(n) for n in stripped.namelist())


def test_duplicate_or_case_variant_entries_refused(tmp_path):
    p = tmp_path / "dup.3mf"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
        zf.writestr("3d/3DModel.model", "<model/>")
    with pytest.raises(ValueError, match="duplicate"):
        strip_3mf(p.read_bytes())


@pytest.mark.parametrize("name", [
    "3D/../../evil.model", "/3D/abs.model", "3D\\win.model", "C:/3D/x.model",
])
def test_unsafe_entry_names_refused(tmp_path, name):
    p = tmp_path / "t.3mf"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
        zf.writestr(name, "<model/>")
    with pytest.raises(ValueError, match="unsafe"):
        strip_3mf(p.read_bytes())


def test_zip_bomb_refused(tmp_path, monkeypatch):
    from bambu_mcp import geometry
    monkeypatch.setattr(geometry, "MAX_BYTES", 1000)
    p = tmp_path / "bomb.3mf"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("3D/3dmodel.model", b"0" * 100_000)  # tiny on disk, big unpacked
    assert p.stat().st_size < 1000
    with pytest.raises(ValueError, match="size limit"):
        strip_3mf(p.read_bytes())


def test_3mf_without_mesh_refused(tmp_path):
    p = tmp_path / "empty.3mf"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("Metadata/project_settings.config", "{}")
    with pytest.raises(ValueError, match="no 3D model"):
        strip_3mf(p.read_bytes())


def test_unsupported_format_refused(tmp_path):
    p = tmp_path / "x.gcode"
    p.write_text("G28")
    with pytest.raises(ValueError):
        private_copy(p, tmp_path)


# ---- slice_model end to end with a mocked slicer ----

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
    for k in [k for k in __import__("os").environ if k.startswith("BAMBU_")]:
        monkeypatch.delenv(k)
    monkeypatch.setattr(server, "_settings", s)
    monkeypatch.setattr(server, "_printer", FakePrinter())
    monkeypatch.setattr(server, "_gate", PrintGate())
    monkeypatch.setattr(server, "_sliced", SlicedRegistry(work))
    monkeypatch.setattr(slicer, "find_studio", lambda configured: "studio")
    monkeypatch.setattr(presets, "default_profile_dirs", lambda studio: [profiles_dir])
    runs = []

    def fake_run(cmd, **kwargs):
        # Snapshot everything the slicer would read, at the moment it runs.
        arg = lambda flag: cmd[cmd.index(flag) + 1]
        runs.append({
            "cmd": cmd,
            "model": Path(cmd[-1]).read_bytes(),
            "settings": [json.loads(Path(p).read_text()) for p in arg("--load-settings").split(";")],
            "filaments": [json.loads(Path(p).read_text()) for p in arg("--load-filaments").split(";")],
        })
        make_job(Path(arg("--outputdir")) / arg("--export-3mf"))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(slicer.subprocess, "run", fake_run)
    return tmp_path, work, runs


def test_embedded_gcode_and_post_process_have_no_effect(env):
    tmp_path, work, runs = env
    src = evil_3mf(tmp_path / "evil.3mf")
    result = server.slice_model(str(src))
    run = runs[0]
    job_dir = Path(result["sliced_file"]).parent
    # The slicer only ever sees files inside our private job folder...
    assert Path(run["cmd"][-1]).parent == job_dir and job_dir.is_relative_to(work.resolve())
    for flag in ("--load-settings", "--load-filaments"):
        for p in run["cmd"][run["cmd"].index(flag) + 1].split(";"):
            assert Path(p).parent == job_dir
    # ...the model copy has no settings in it...
    names = zipfile.ZipFile(io.BytesIO(run["model"])).namelist()
    assert not [n for n in names if n.lower().startswith("metadata/")]
    # ...and the settings it gets are the stock P2S presets.
    machine, process = run["settings"]
    assert machine["machine_start_gcode"] == STOCK_START
    assert process["post_process"] == []
    assert EVIL not in json.dumps(run["settings"] + run["filaments"])
    assert result["presets"]["machine"] == "Bambu Lab P2S 0.4 nozzle"
    # Only the sliced result is left in the job folder.
    assert [p.name for p in job_dir.iterdir()] == [Path(result["sliced_file"]).name]


def test_source_swapped_after_copy_has_no_effect(env, monkeypatch):
    tmp_path, work, runs = env
    src = tmp_path / "part.stl"
    src.write_bytes(b"solid good\nendsolid\n")
    real_copy = slicer.private_copy

    def copy_then_swap(source, dest):
        out = real_copy(source, dest)
        source.write_bytes(b"solid EVIL\n")
        return out

    monkeypatch.setattr(slicer, "private_copy", copy_then_swap)
    server.slice_model(str(src))
    assert runs[0]["model"] == b"solid good\nendsolid\n"


def test_stl_round_trip_to_prepare(env):
    tmp_path, work, runs = env
    src = tmp_path / "part.stl"
    src.write_bytes(b"solid x\nendsolid\n")
    result = server.slice_model(str(src), filaments=["PETG"])
    assert [f["name"] for f in runs[0]["filaments"]] == ["Bambu PETG HF @BBL P2S"]
    prep = server.prepare_print(result["sliced_file"])
    assert prep["plate"] == 1
    assert server._printer.uploaded == Path(result["sliced_file"]).read_bytes()


def test_failed_slice_removes_job_folder(env, monkeypatch):
    tmp_path, work, runs = env
    src = tmp_path / "part.stl"
    src.write_bytes(b"solid x\n")
    monkeypatch.setattr(slicer.subprocess, "run",
                        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        server.slice_model(str(src))
    assert list((work / "jobs").iterdir()) == []


@pytest.mark.skipif(not __import__("os").environ.get("BAMBU_SMOKE_STUDIO"),
                    reason="set BAMBU_SMOKE_STUDIO=path/to/bambu-studio to run against the real CLI")
def test_smoke_real_bambu_studio(tmp_path):
    import os
    studio = os.environ["BAMBU_SMOKE_STUDIO"]
    machine, process, fils = build_settings(
        SystemPresets(presets.default_profile_dirs(studio)), ["PLA"], env={})
    stl = tmp_path / "cube.stl"
    stl.write_text(CUBE_STL)
    out = slicer.slice_file(studio, stl, tmp_path / "work", machine, process, fils)
    assert "Metadata/plate_1.gcode" in zipfile.ZipFile(out).namelist()


CUBE_STL = "solid c\n" + "".join(
    f"facet normal 0 0 0\nouter loop\nvertex {a}\nvertex {b}\nvertex {c}\nendloop\nendfacet\n"
    for a, b, c in [
        ("0 0 0", "10 0 0", "10 10 0"), ("0 0 0", "10 10 0", "0 10 0"),
        ("0 0 10", "10 10 10", "10 0 10"), ("0 0 10", "0 10 10", "10 10 10"),
        ("0 0 0", "10 0 10", "10 0 0"), ("0 0 0", "0 0 10", "10 0 10"),
        ("0 10 0", "10 10 0", "10 10 10"), ("0 10 0", "10 10 10", "0 10 10"),
        ("0 0 0", "0 10 0", "0 10 10"), ("0 0 0", "0 10 10", "0 0 10"),
        ("10 0 0", "10 0 10", "10 10 10"), ("10 0 0", "10 10 10", "10 10 0"),
    ]) + "endsolid c\n"


def test_disallowed_filament_never_slices(env):
    tmp_path, work, runs = env
    src = tmp_path / "part.stl"
    src.write_bytes(b"solid x\n")
    with pytest.raises(PresetError):
        server.slice_model(str(src), filaments=["ABS"])
    assert runs == []
