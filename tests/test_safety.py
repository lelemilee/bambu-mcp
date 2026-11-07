import pytest

from bambu_mcp.safety import PrintGate, SlicedRegistry, human_code


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_pending_job_is_single_use():
    gate = PrintGate()
    gate.prepare({"f": 1})
    assert gate.take().details == {"f": 1}
    with pytest.raises(PermissionError):
        gate.take()


def test_pending_job_expires():
    clock = Clock()
    gate = PrintGate(ttl=300, clock=clock)
    gate.prepare({})
    clock.t = 301
    with pytest.raises(PermissionError, match="expired"):
        gate.take()


def test_cancel_clears_job():
    gate = PrintGate()
    gate.prepare({})
    gate.cancel()
    with pytest.raises(PermissionError):
        gate.take()


def test_human_code_is_readable():
    code = human_code()
    assert len(code) == 4 and not set(code) & set("01OI")


def test_registry_only_accepts_own_unchanged_files(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    reg = SlicedRegistry(work)
    good = work / "a.gcode.3mf"
    good.write_bytes(b"one")
    reg.add(good)
    assert reg.verify(good) == good.resolve()

    stranger = work / "b.gcode.3mf"
    stranger.write_bytes(b"x")
    with pytest.raises(PermissionError, match="slice_model"):
        reg.verify(stranger)

    good.write_bytes(b"tampered")
    with pytest.raises(PermissionError, match="changed"):
        reg.verify(good)


def test_registry_rejects_outside_work_dir(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "evil.gcode.3mf"
    outside.write_bytes(b"x")
    reg = SlicedRegistry(work)
    with pytest.raises(PermissionError, match="inside"):
        reg.add(outside)
    with pytest.raises(PermissionError, match="inside"):
        reg.verify(work / ".." / "evil.gcode.3mf")
