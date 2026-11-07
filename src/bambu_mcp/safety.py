"""Guards for anything that makes the printer move.

The model never sees anything it could use to approve a print. `prepare_print`
only stores a pending job; `start_print` asks the human directly through MCP
elicitation (a prompt in the client UI) and the human must type a short code
that is shown only in that prompt.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PENDING_TTL_SECONDS = 300
# No 0/O or 1/I so the code is easy to read and type.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def human_code(length: int = 4) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class PendingPrint:
    details: dict[str, Any]
    created: float = field(default_factory=time.monotonic)
    # Shown only inside the human's confirmation prompt, never in a tool result.
    code: str = field(default_factory=human_code)


class PrintGate:
    """Holds at most one prepared job, which expires and can be taken once."""

    def __init__(self, ttl: float = PENDING_TTL_SECONDS, clock=time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._pending: PendingPrint | None = None

    def prepare(self, details: dict[str, Any]) -> None:
        self._pending = PendingPrint(details, created=self._clock())

    def _valid(self, pending: PendingPrint | None) -> PendingPrint:
        if pending is None:
            raise PermissionError("No prepared print. Run prepare_print first.")
        if self._clock() - pending.created > self._ttl:
            raise PermissionError("The prepared print expired. Run prepare_print again.")
        return pending

    def peek(self) -> PendingPrint:
        """Look at the pending job without using it up (to build the prompt)."""
        return self._valid(self._pending)

    def take(self) -> PendingPrint:
        """Use up the pending job. Called once per start attempt, pass or fail."""
        pending, self._pending = self._pending, None
        return self._valid(pending)

    def cancel(self) -> None:
        self._pending = None


class SlicedRegistry:
    """Files this server sliced itself, with their hashes.

    Only these can be printed, so a hand-made .gcode.3mf (or one edited after
    slicing) is refused. Kept in memory on purpose: after a restart you re-slice.
    """

    def __init__(self, work_dir: Path) -> None:
        self._work_dir = work_dir.resolve()
        self._files: dict[Path, str] = {}

    def add(self, path: Path) -> None:
        resolved = path.resolve()
        self._check_inside(resolved)
        self._files[resolved] = sha256_file(resolved)

    def verify(self, path: Path) -> Path:
        resolved = path.expanduser().resolve()
        self._check_inside(resolved)
        expected = self._files.get(resolved)
        if expected is None:
            raise PermissionError("Only files made by slice_model in this session can be printed.")
        if not resolved.is_file() or sha256_file(resolved) != expected:
            raise PermissionError("Sliced file changed since slice_model made it. Slice again.")
        return resolved

    def _check_inside(self, resolved: Path) -> None:
        if not resolved.is_relative_to(self._work_dir):
            raise PermissionError(f"File must be inside the work folder {self._work_dir}.")
