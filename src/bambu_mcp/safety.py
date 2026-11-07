"""Two-step confirm for anything that makes the printer move.

`prepare_print` returns a one-time code with a summary. `start_print` only
works with that code, within a few minutes, once. That gives you a moment to
read the summary (and check the camera) before Claude can start a job.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

TOKEN_TTL_SECONDS = 300


@dataclass
class PendingPrint:
    details: dict[str, Any]
    created: float = field(default_factory=time.monotonic)


class PrintGate:
    def __init__(self, ttl: float = TOKEN_TTL_SECONDS, clock=time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._pending: dict[str, PendingPrint] = {}

    def prepare(self, details: dict[str, Any]) -> str:
        self._pending.clear()  # only one pending print at a time
        token = secrets.token_hex(3).upper()
        self._pending[token] = PendingPrint(details, created=self._clock())
        return token

    def consume(self, token: str) -> dict[str, Any]:
        pending = self._pending.pop((token or "").strip().upper(), None)
        if pending is None:
            raise PermissionError("Unknown or already used confirm code. Run prepare_print again.")
        if self._clock() - pending.created > self._ttl:
            raise PermissionError("Confirm code expired. Run prepare_print again.")
        return pending.details
