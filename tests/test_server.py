import json

import pytest
from mcp import types
from mcp.client import Client

from mcp.server.elicitation import AcceptedElicitation, DeclinedElicitation

from bambu_mcp import server
from bambu_mcp.config import Settings
from bambu_mcp.safety import PrintGate, SlicedRegistry
from conftest import make_job

AMS = {
    "ams": [{"id": "0", "tray": [
        {"id": "0", "tray_type": "PLA", "tray_color": "FF6A13FF"},
        {"id": "1", "tray_type": "PETG", "tray_color": "000000FF"},
        {"id": "2"},
        {"id": "3"},
    ]}]
}


class FakePrinter:
    def __init__(self, state="IDLE"):
        self.state = state
        self.calls = []

    def refresh(self):
        return {"print": {"gcode_state": self.state, "ams": AMS}}

    def upload(self, path, remote):
        self.calls.append(("upload", remote))
        return remote

    def start_project(self, *args):
        self.calls.append(("start", *args))

    def pause(self):
        self.calls.append(("pause",))

    def stop(self):
        self.calls.append(("stop",))

    def resume(self):
        self.calls.append(("resume",))

    def started(self):
        return [c for c in self.calls if c[0] == "start"]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def make(read_only=False, state="IDLE", plates=(1,)):
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        s = Settings("1.2.3.4", "SN", "code", None, work, read_only)
        fake = FakePrinter(state)
        reg = SlicedRegistry(work)
        job = make_job(work / "part-1.gcode.3mf", plates=plates)
        reg.add(job)
        monkeypatch.setattr(server, "_settings", s)
        monkeypatch.setattr(server, "_printer", fake)
        monkeypatch.setattr(server, "_gate", PrintGate())
        monkeypatch.setattr(server, "_sliced", reg)
        return fake, job
    return make


def typed(code):
    return AcceptedElicitation(data=server.PrintApproval(code=code))


def prompt_code():
    return server._ask_human().message.rsplit(":", 1)[1].strip()


def test_human_approval_starts_print(setup):
    fake, job = setup()
    prep = server.prepare_print(str(job), ams_mapping=[0])
    assert prep["print_minutes"] == 62 and prep["filament_g"] == 21.5
    assert not fake.started()
    result = server._start_print(typed(prompt_code().lower()))
    assert result["started"] is True
    assert fake.started()[0][2:] == (1, True, [0])


def test_nothing_model_visible_can_approve(setup):
    fake, job = setup()
    prep = server.prepare_print(str(job))
    assert prompt_code() not in json.dumps(prep)
    # A guessed code is refused, and the pending job is used up.
    assert server._start_print(typed("AAAA"))["started"] is False
    assert not fake.started()
    with pytest.raises(PermissionError, match="prepare_print"):
        server._start_print(typed("AAAA"))


def test_decline_does_not_start(setup):
    fake, job = setup()
    server.prepare_print(str(job))
    assert server._start_print(DeclinedElicitation())["started"] is False
    assert not fake.started()


def test_start_without_prepare_fails(setup):
    fake, _ = setup()
    with pytest.raises(PermissionError):
        server._ask_human()
    with pytest.raises(PermissionError):
        server._start_print(typed("AAAA"))
    assert fake.calls == []


def test_rejects_file_outside_work_dir(setup, tmp_path):
    fake, _ = setup()
    outside = make_job(tmp_path / "evil.gcode.3mf")
    with pytest.raises(PermissionError, match="inside"):
        server.prepare_print(str(outside))
    assert fake.calls == []


def test_rejects_file_not_made_by_slicer(setup):
    fake, job = setup()
    handmade = make_job(job.parent / "handmade.gcode.3mf")
    with pytest.raises(PermissionError, match="slice_model"):
        server.prepare_print(str(handmade))
    assert fake.calls == []


@pytest.mark.parametrize("plate", [-5, 0, 2])
def test_rejects_bad_plate(setup, plate):
    fake, job = setup()
    with pytest.raises(ValueError, match="Plate"):
        server.prepare_print(str(job), plate=plate)
    assert fake.calls == []


@pytest.mark.parametrize("mapping", [[99], [-3], [2], [0, 1]])
def test_rejects_bad_ams_mapping(setup, mapping):
    fake, job = setup()
    with pytest.raises(ValueError):
        server.prepare_print(str(job), ams_mapping=mapping)
    assert fake.calls == []


def test_unmapped_slot_allowed(setup):
    fake, job = setup()
    server.prepare_print(str(job), ams_mapping=[-1])
    assert fake.calls[0][0] == "upload"


@pytest.mark.parametrize("state", ["RUNNING", "PAUSE", None, "SOMETHING_NEW"])
def test_busy_or_unknown_state_refuses(setup, state):
    fake, job = setup(state=state)
    with pytest.raises(RuntimeError, match="busy"):
        server.prepare_print(str(job))
    assert fake.calls == []


def test_read_only_mode(setup):
    fake, job = setup(read_only=True)
    with pytest.raises(PermissionError):
        server.prepare_print(str(job))
    with pytest.raises(PermissionError):
        server.resume_print()
    server.pause_print()
    server.stop_print()
    assert fake.calls == [("pause",), ("stop",)]


def test_reprepare_uses_new_remote_name(setup, monkeypatch):
    fake, job = setup()
    times = iter(["100000", "100001"])
    monkeypatch.setattr(server.time, "strftime", lambda fmt: next(times))
    server.prepare_print(str(job))
    server.prepare_print(str(job))
    names = [c[1] for c in fake.calls if c[0] == "upload"]
    assert len(set(names)) == 2


# ---- through a real MCP client, to prove the prompt goes to the human ----

MODES = ["auto", "legacy"]  # new input_required flow and older mid-call requests


async def _call_start(setup, elicitation_callback, mode):
    fake, job = setup()
    server.prepare_print(str(job))
    async with Client(server.mcp, elicitation_callback=elicitation_callback, mode=mode) as client:
        result = await client.call_tool("start_print", {})
    return fake, result


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
async def test_real_client_elicitation_accept(setup, mode):
    seen = {}

    async def human(context, params):
        seen["message"] = params.message
        code = params.message.rsplit(":", 1)[1].strip()
        return types.ElicitResult(action="accept", content={"code": code})

    fake, result = await _call_start(setup, human, mode)
    assert not result.is_error, result
    assert fake.started()
    # The code lives only in the prompt, not in what the model gets back.
    code = seen["message"].rsplit(":", 1)[1].strip()
    assert code not in json.dumps(result.model_dump())


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
async def test_real_client_elicitation_decline(setup, mode):
    async def human(context, params):
        return types.ElicitResult(action="decline")

    fake, result = await _call_start(setup, human, mode)
    assert not fake.started()


@pytest.mark.anyio
@pytest.mark.parametrize("mode", MODES)
async def test_client_without_prompts_fails_closed(setup, mode):
    import traceback

    try:
        _, result = await _call_start(setup, None, mode)
        assert result.is_error
    except Exception as exc:  # MCPError, possibly wrapped in an ExceptionGroup
        assert "elicitation capability" in "".join(traceback.format_exception(exc))
    assert not server._printer.started()
