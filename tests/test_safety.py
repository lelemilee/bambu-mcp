import pytest

from bambu_mcp.safety import PrintGate


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_code_is_single_use():
    gate = PrintGate()
    code = gate.prepare({"f": 1})
    assert gate.consume(code.lower()) == {"f": 1}
    with pytest.raises(PermissionError):
        gate.consume(code)


def test_code_expires():
    clock = Clock()
    gate = PrintGate(ttl=300, clock=clock)
    code = gate.prepare({})
    clock.t = 301
    with pytest.raises(PermissionError, match="expired"):
        gate.consume(code)


def test_new_prepare_cancels_old_code():
    gate = PrintGate()
    old = gate.prepare({"n": 1})
    gate.prepare({"n": 2})
    with pytest.raises(PermissionError):
        gate.consume(old)


def test_wrong_code():
    gate = PrintGate()
    gate.prepare({})
    with pytest.raises(PermissionError):
        gate.consume("NOPE")
