from pathlib import Path

import pytest

from bambu_mcp import server
from bambu_mcp.config import Settings
from bambu_mcp.safety import PrintGate


class FakePrinter:
    def __init__(self, state="IDLE"):
        self.state = state
        self.calls = []

    def refresh(self):
        return {"print": {"gcode_state": self.state, "ams": {"ams": []}}}

    def upload(self, path):
        self.calls.append(("upload", path.name))
        return path.name

    def start_project(self, *args):
        self.calls.append(("start", *args))

    def pause(self):
        self.calls.append(("pause",))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def make(read_only=False, state="IDLE"):
        s = Settings("1.2.3.4", "SN", "code", None, tmp_path, read_only)
        fake = FakePrinter(state)
        monkeypatch.setattr(server, "_settings", s)
        monkeypatch.setattr(server, "_printer", fake)
        monkeypatch.setattr(server, "_gate", PrintGate())
        sliced = tmp_path / "part.gcode.3mf"
        sliced.write_bytes(b"x")
        return fake, sliced
    return make


def test_two_step_print(setup):
    fake, sliced = setup()
    prep = server.prepare_print(str(sliced))
    assert ("upload", "part.gcode.3mf") in fake.calls
    assert not any(c[0] == "start" for c in fake.calls)
    server.start_print(prep["confirm_code"])
    assert ("start", "part.gcode.3mf", 1, True, None) in fake.calls


def test_start_without_prepare_fails(setup):
    fake, _ = setup()
    with pytest.raises(PermissionError):
        server.start_print("ABC123")
    assert fake.calls == []


def test_read_only_blocks_printing_but_not_pause(setup):
    fake, sliced = setup(read_only=True)
    with pytest.raises(PermissionError):
        server.prepare_print(str(sliced))
    server.pause_print()
    assert fake.calls == [("pause",)]


def test_busy_printer_refuses(setup):
    fake, sliced = setup(state="RUNNING")
    with pytest.raises(RuntimeError, match="busy"):
        server.prepare_print(str(sliced))
    assert fake.calls == []


def test_rejects_unsliced_file(setup, tmp_path):
    setup()
    stl = tmp_path / "part.stl"
    stl.write_bytes(b"x")
    with pytest.raises(ValueError):
        server.prepare_print(str(stl))
