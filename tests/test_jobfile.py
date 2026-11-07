import pytest

from bambu_mcp.jobfile import inspect_job
from conftest import make_job


def test_reads_plates_and_summary(tmp_path):
    plates = inspect_job(make_job(tmp_path / "j.gcode.3mf", plates=(1, 2)))
    assert sorted(plates) == [1, 2]
    assert plates[1]["print_minutes"] == 62
    assert plates[1]["filament_g"] == 21.5
    assert plates[1]["filaments"][0]["type"] == "PLA"
    assert plates[2]["filaments"] == []


def test_rejects_non_zip(tmp_path):
    bad = tmp_path / "x.gcode.3mf"
    bad.write_text("G1 X0")
    with pytest.raises(ValueError):
        inspect_job(bad)


def test_rejects_zip_without_plates(tmp_path):
    with pytest.raises(ValueError):
        inspect_job(make_job(tmp_path / "e.gcode.3mf", plates=()))
